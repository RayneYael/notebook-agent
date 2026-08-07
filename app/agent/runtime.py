"""PydanticAI runtime with fixed tenant dependencies and evidence enforcement."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Callable, Literal

from pydantic_ai import Agent, PromptedOutput, RunContext, UsageLimits
from pydantic_ai.exceptions import (
    ModelHTTPError,
    ModelRetry,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from app.agent.actions import (
    ActionInputMismatch,
    AgentActionRuntime,
    AgentActionServices,
)
from app.agent.services import (
    EmbeddingUnavailable,
    KnowledgeNotFound,
    KnowledgeServices,
    RetrievalUnavailable,
)
from app.agent.types import (
    AgentAnswer,
    AgentRequest,
    AnswerDraft,
    Citation,
    RetrievalToolPayload,
)
from app.config import Settings
from app.diagnostics import RequestDiagnostics, classify_usage_limit


INSTRUCTIONS = """
你是私有知识库检索助手。你只能根据本次会话中的知识库工具结果回答。

规则：
1. 回答知识库事实前必须调用 search_segments；可以改写查询并再次搜索。
2. 需要上下文时调用 get_neighbors，需要元数据时调用 get_item，最终引用位置可调用 open_at。
3. 不得依据模型记忆补写。没有结果或证据不足时，明确说“知识库中未找到足够证据”。
4. 你的本阶段职责是收集可信证据；收集充分后停止调用工具。最终总结、引用编号和来源由服务器的独立回答阶段生成。
5. 工具没有 user_id 参数；不要询问、猜测或尝试改变当前用户。
6. 明确要求保存且消息中有视频 URL 时调用 save_videos；只有裸 URL
   时调用 request_save_confirmation。
7. 用户确认或取消待保存视频时分别调用 confirm_video_save 或
   cancel_video_save；不要从历史文本重建 URL。
8. 询问链接内容不代表保存意图，仍按知识检索规则处理。
9. 多来源问题先比较 search_segments 返回的 excerpt、标题和来源；不要为每一个候选机械展开。
   同一视频的不同时间证据可保留，但不要编造章节标题。
""".strip()


NORMAL_RETRIEVAL_CALLS_LIMIT = 5
NORMAL_SEARCH_CALLS_LIMIT = 2
NORMAL_EXPANSION_CALLS_LIMIT = 3
MAX_SOURCE_ITEMS = 5
SEARCH_RESULT_LIMIT = 10
ANSWER_REQUEST_LIMIT = 2
FALLBACK_INTRO = "自动总结未完成，以下是知识库中最相关的证据："


class RetrievalKind(str, Enum):
    SEARCH = "search"
    EXPANSION = "expansion"


class ReservationResult(str, Enum):
    EXECUTE = "execute"
    SAME_STEP_SKIPPED = "same_step_skipped"
    STAGE_BUDGET_EXHAUSTED = "stage_budget_exhausted"


@dataclass
class AgentDeps:
    services: KnowledgeServices
    actions: AgentActionRuntime
    search_calls: int = 0
    retrieval_calls: int = 0
    expansion_calls: int = 0
    tool_calls: int = 0
    citations: dict[int, Citation] = field(default_factory=dict)
    last_retrieval_run_step: int | None = None
    diagnostics: RequestDiagnostics | None = None
    _tool_lock: threading.Lock = field(default_factory=threading.Lock)

    def reserve_retrieval(
        self, *, run_step: int, kind: RetrievalKind
    ) -> ReservationResult:
        """Atomically reserve the only backend retrieval allowed in a step."""

        with self._tool_lock:
            if self.last_retrieval_run_step == run_step:
                return ReservationResult.SAME_STEP_SKIPPED
            if self.retrieval_calls >= NORMAL_RETRIEVAL_CALLS_LIMIT:
                return ReservationResult.STAGE_BUDGET_EXHAUSTED
            if kind is RetrievalKind.SEARCH:
                if self.search_calls >= NORMAL_SEARCH_CALLS_LIMIT:
                    return ReservationResult.STAGE_BUDGET_EXHAUSTED
                self.search_calls += 1
            else:
                if self.expansion_calls >= NORMAL_EXPANSION_CALLS_LIMIT:
                    return ReservationResult.STAGE_BUDGET_EXHAUSTED
                self.expansion_calls += 1
            self.retrieval_calls += 1
            self.last_retrieval_run_step = run_step
            return ReservationResult.EXECUTE

    def record(self, values: list[Citation] | Citation) -> None:
        rows = values if isinstance(values, list) else [values]
        for citation in rows:
            self.citations[citation.segment_id] = citation

    def tool_event(self, name: str, outcome: str, call_index: int, result_count: int | None = None,
                   exception: BaseException | None = None) -> None:
        if self.diagnostics is not None:
            self.diagnostics.event(
                "tool_call", tool_name=name, tool_outcome=outcome,
                call_index=call_index, result_count=result_count, exception=exception,
                agent_phase="retrieval",
            )


@dataclass
class ComposerDeps:
    """Trusted allow-list passed to the tool-free answer composer only."""

    citations: dict[int, Citation]
    diagnostics: RequestDiagnostics | None = None
    invalid_draft_count: int = 0


@dataclass(frozen=True)
class AgentExecution:
    answer: AgentAnswer
    new_messages: list[ModelMessage]


def build_agent(
    model: Model | str,
    *,
    tool_timeout: float = 15.0,
) -> Agent[AgentDeps, str]:
    def normal_retrieval_available(deps: AgentDeps) -> bool:
        if deps.retrieval_calls >= NORMAL_RETRIEVAL_CALLS_LIMIT:
            return False
        return (
            deps.search_calls < NORMAL_SEARCH_CALLS_LIMIT
            or (bool(deps.citations) and deps.expansion_calls < NORMAL_EXPANSION_CALLS_LIMIT)
        )

    def prepare_search(ctx: RunContext[AgentDeps], tool_def):
        deps = ctx.deps
        if (
            normal_retrieval_available(deps)
            and deps.search_calls < NORMAL_SEARCH_CALLS_LIMIT
        ):
            return tool_def
        return None

    def prepare_expansion(ctx: RunContext[AgentDeps], tool_def):
        deps = ctx.deps
        if (
            deps.citations
            and normal_retrieval_available(deps)
            and deps.expansion_calls < NORMAL_EXPANSION_CALLS_LIMIT
        ):
            return tool_def
        return None

    def execute_tool(deps: AgentDeps, name: str, operation):
        """Record only the tool boundary, never its arguments or output."""
        with deps._tool_lock:
            deps.tool_calls += 1
            call_index = deps.tool_calls
        deps.tool_event(name, "started", call_index)
        try:
            return operation(), call_index
        except Exception as exc:
            deps.tool_event(name, "failed", call_index, exception=exc)
            raise

    def skipped_payload(
        ctx: RunContext[AgentDeps], name: str, kind: RetrievalKind
    ) -> RetrievalToolPayload | None:
        """Reserve a retrieval or provide a truthful no-side-effect result."""

        reservation = ctx.deps.reserve_retrieval(
            run_step=ctx.run_step,
            kind=kind,
        )
        if reservation is ReservationResult.EXECUTE:
            return None
        with ctx.deps._tool_lock:
            ctx.deps.tool_calls += 1
            call_index = ctx.deps.tool_calls
        reason: Literal["same_model_step", "budget_exhausted"]
        reason = (
            "same_model_step"
            if reservation is ReservationResult.SAME_STEP_SKIPPED
            else "budget_exhausted"
        )
        ctx.deps.tool_event(name, "skipped", call_index, 0)
        return {"status": "skipped", "evidence": [], "reason": reason}

    agent = Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        instructions=INSTRUCTIONS,
        retries={"tools": 1},
        tool_timeout=tool_timeout,
    )

    @agent.instructions
    def retrieval_convergence_instruction(ctx: RunContext[AgentDeps]) -> str:
        """State the server-enforced retrieval phase without exposing internals."""

        deps = ctx.deps
        if not normal_retrieval_available(deps):
            return (
                "检索轮次已经结束。只能根据已返回的工具证据作答；"
                "若证据不足，明确说明证据不足，不要继续检索或依据模型记忆补写。"
            )
        return (
            "优先基于已有证据作答。搜索结果是待比较的候选，不要为每个候选机械展开；"
            "仅在上下文确实不足时选择最有希望的代表片段扩展。"
        )

    @agent.instructions
    def pending_save_instruction(ctx: RunContext[AgentDeps]) -> str:
        """Inject only the current run's server-verified confirmation state."""

        snapshot = ctx.deps.actions.pending_save_snapshot()
        if not snapshot.active:
            return ""
        return (
            "可信服务器状态：当前 conversation 有 "
            f"{snapshot.count} 个视频等待保存确认。\n"
            "把本条短回复作为确认语义判断：明确肯定（包括“需要”）调用 "
            "confirm_video_save；明确否定调用 cancel_video_save；含糊则调用 "
            "clarify_save_confirmation；"
            "明显无关的新问题按正常知识流程处理并保留待确认状态。"
            "不要为确认回复调用知识检索。"
        )

    @agent.tool(prepare=prepare_search)
    def search_segments(
        ctx: RunContext[AgentDeps], query: str, limit: int = SEARCH_RESULT_LIMIT
    ) -> RetrievalToolPayload:
        """Search the current user's knowledge segments for evidence."""

        if skipped := skipped_payload(ctx, "search_segments", RetrievalKind.SEARCH):
            return skipped
        (citations, call_index) = execute_tool(
            ctx.deps, "search_segments", lambda: ctx.deps.services.search_segments(query, limit=limit)
        )
        ctx.deps.record(citations)
        ctx.deps.tool_event("search_segments", "succeeded", call_index, len(citations))
        ctx.deps.diagnostics and ctx.deps.diagnostics.retrieval_detail(tool_name="search_segments", call_index=call_index, query=query, limit=limit)
        for citation in citations:
            ctx.deps.diagnostics and ctx.deps.diagnostics.retrieval_detail(tool_name="search_segments", call_index=call_index, query=query, limit=limit, item_id=citation.item_id, segment_id=citation.segment_id, title=citation.title, url=citation.url, excerpt=citation.excerpt, score=getattr(citation, "_retrieval_score", None), start=citation.start_sec)
        return {
            "status": "ok",
            "evidence": [value.model_dump() for value in citations],
            "reason": None,
        }

    @agent.tool(prepare=prepare_expansion)
    def get_neighbors(
        ctx: RunContext[AgentDeps], segment_id: int, radius: int = 1
    ) -> RetrievalToolPayload:
        """Read nearby segments around a search result."""

        if skipped := skipped_payload(ctx, "get_neighbors", RetrievalKind.EXPANSION):
            return skipped
        (citations, call_index) = execute_tool(
            ctx.deps, "get_neighbors", lambda: ctx.deps.services.get_neighbors(segment_id, radius=radius)
        )
        ctx.deps.record(citations)
        ctx.deps.tool_event("get_neighbors", "succeeded", call_index, len(citations))
        for citation in citations:
            ctx.deps.diagnostics and ctx.deps.diagnostics.retrieval_detail(tool_name="get_neighbors", call_index=call_index, segment_id=citation.segment_id, radius=radius, item_id=citation.item_id, title=citation.title, url=citation.url, excerpt=citation.excerpt, start=citation.start_sec)
        return {
            "status": "ok",
            "evidence": [value.model_dump() for value in citations],
            "reason": None,
        }

    @agent.tool(prepare=prepare_expansion)
    def get_item(ctx: RunContext[AgentDeps], item_id: int) -> RetrievalToolPayload:
        """Read metadata for a knowledge item returned by search."""

        if skipped := skipped_payload(ctx, "get_item", RetrievalKind.EXPANSION):
            return skipped
        (result, call_index) = execute_tool(ctx.deps, "get_item", lambda: asdict(ctx.deps.services.get_item(item_id)))
        ctx.deps.tool_event("get_item", "succeeded", call_index, 1)
        ctx.deps.diagnostics and ctx.deps.diagnostics.retrieval_detail(tool_name="get_item", call_index=call_index, item_id=item_id, title=result.get("title"), author=result.get("author"), description=result.get("description"), url=result.get("url"))
        return {"status": "ok", "evidence": [result], "reason": None}

    @agent.tool(prepare=prepare_expansion)
    def open_at(ctx: RunContext[AgentDeps], segment_id: int) -> RetrievalToolPayload:
        """Resolve a segment to a clickable timestamp or article anchor."""

        if skipped := skipped_payload(ctx, "open_at", RetrievalKind.EXPANSION):
            return skipped
        (citation, call_index) = execute_tool(ctx.deps, "open_at", lambda: ctx.deps.services.open_at(segment_id))
        ctx.deps.record(citation)
        ctx.deps.tool_event("open_at", "succeeded", call_index, 1)
        ctx.deps.diagnostics and ctx.deps.diagnostics.retrieval_detail(tool_name="open_at", call_index=call_index, segment_id=segment_id, item_id=citation.item_id, title=citation.title, url=citation.url, excerpt=citation.excerpt, start=citation.start_sec)
        return {"status": "ok", "evidence": [citation.model_dump()], "reason": None}

    @agent.tool
    def request_save_confirmation(
        ctx: RunContext[AgentDeps], urls: list[str]
    ) -> dict:
        """Persist a bounded bare-URL batch for explicit confirmation."""

        try:
            outcome, call_index = execute_tool(ctx.deps, "request_save_confirmation", lambda: ctx.deps.actions.request_confirmation(urls))
        except ActionInputMismatch:
            raise ModelRetry(
                "Include every URL from the current user message exactly once "
                "per occurrence and in the original order; do not add URLs."
            ) from None
        ctx.deps.tool_event("request_save_confirmation", "succeeded", call_index, len(outcome.results))
        return outcome.tool_payload()

    @agent.tool
    def save_videos(
        ctx: RunContext[AgentDeps],
        urls: list[str],
        why_saved: str | None = None,
    ) -> dict:
        """Queue current-message video URLs for the private tenant."""

        try:
            outcome, call_index = execute_tool(ctx.deps, "save_videos", lambda: ctx.deps.actions.save_videos(urls, why_saved=why_saved))
        except ActionInputMismatch:
            raise ModelRetry(
                "Include every URL from the current user message exactly once "
                "per occurrence and in the original order; do not add URLs."
            ) from None
        ctx.deps.tool_event("save_videos", "succeeded", call_index, len(outcome.results))
        return outcome.tool_payload()

    @agent.tool
    def confirm_video_save(ctx: RunContext[AgentDeps]) -> dict:
        """Consume the current conversation's persisted pending batch."""

        outcome, call_index = execute_tool(ctx.deps, "confirm_video_save", ctx.deps.actions.confirm)
        ctx.deps.tool_event("confirm_video_save", "succeeded", call_index, len(outcome.results))
        return outcome.tool_payload()

    @agent.tool
    def clarify_save_confirmation(ctx: RunContext[AgentDeps]) -> dict:
        """Ask for a clear decision without consuming the pending batch."""

        outcome, call_index = execute_tool(ctx.deps, "clarify_save_confirmation", ctx.deps.actions.clarify_confirmation)
        ctx.deps.tool_event("clarify_save_confirmation", "succeeded", call_index, len(outcome.results))
        return outcome.tool_payload()

    @agent.tool
    def cancel_video_save(ctx: RunContext[AgentDeps]) -> dict:
        """Cancel the current conversation's persisted pending batch."""

        outcome, call_index = execute_tool(ctx.deps, "cancel_video_save", ctx.deps.actions.cancel)
        ctx.deps.tool_event("cancel_video_save", "succeeded", call_index, len(outcome.results))
        return outcome.tool_payload()

    return agent


COMPOSER_INSTRUCTIONS = """
你是私有知识库的回答编辑器。只能依据服务器提供的证据写回答，不能使用模型记忆补充事实。
输出结构化 sections；每个 section 写简洁中文文本，并列出支持该 section 的 segment ID。
不要输出 URL、视频标题、[S…] 标记、章节标题或服务器未提供的事实。最多引用五个不同视频。
""".strip()


def build_composer(model: Model | str, *, tool_timeout: float = 15.0) -> Agent[ComposerDeps, AnswerDraft]:
    """Build the answer-only stage with no retrieval or action tools."""

    composer = Agent(
        model,
        deps_type=ComposerDeps,
        output_type=PromptedOutput(AnswerDraft),
        instructions=COMPOSER_INSTRUCTIONS,
        retries={"output": 1},
        tool_timeout=tool_timeout,
    )

    @composer.instructions
    def bounded_evidence_instruction(ctx: RunContext[ComposerDeps]) -> str:
        rows: list[str] = []
        for citation in ctx.deps.citations.values():
            excerpt = " ".join(citation.excerpt.split())[:360]
            timestamp = (
                f"，时间 {int(citation.start_sec)} 秒"
                if citation.start_sec is not None
                else ""
            )
            rows.append(
                f"ID {citation.segment_id}，视频《{citation.title}》{timestamp}：{excerpt}"
            )
        return "可用证据（仅可引用以下 ID）：\n" + "\n".join(rows)

    @composer.output_validator
    def validate_draft(ctx: RunContext[ComposerDeps], draft: AnswerDraft) -> AnswerDraft:
        cited_ids = {
            segment_id
            for section in draft.sections
            for segment_id in section.citation_ids
        }
        allowed = set(ctx.deps.citations)
        item_ids = {
            ctx.deps.citations[segment_id].item_id
            for segment_id in cited_ids
            if segment_id in ctx.deps.citations
        }
        if cited_ids and cited_ids.issubset(allowed) and len(item_ids) <= MAX_SOURCE_ITEMS:
            return draft
        ctx.deps.invalid_draft_count += 1
        if ctx.deps.diagnostics is not None:
            ctx.deps.diagnostics.event(
                "citation_validated",
                error_code="answer_unavailable",
                retry_count=ctx.deps.invalid_draft_count,
                agent_phase="answer",
            )
        raise ModelRetry(
            "Every section must cite only an allowed segment ID, and all sections together may cite no more than five videos."
        )

    return composer


class KnowledgeAgent:
    """Run the model and convert every outcome to a fail-closed answer."""

    def __init__(
        self,
        model: Model | str,
        settings: Settings,
        service_factory: Callable[[AgentRequest], KnowledgeServices],
        action_factory: (
            Callable[[AgentRequest], AgentActionServices] | None
        ) = None,
        *,
        composer_model: Model | str | None = None,
    ) -> None:
        self._agent = build_agent(
            model,
            tool_timeout=settings.agent_tool_timeout_seconds,
        )
        self._composer = build_composer(
            composer_model or model,
            tool_timeout=settings.agent_tool_timeout_seconds,
        )
        self._settings = settings
        self._service_factory = service_factory
        self._action_factory = action_factory

    async def run(
        self,
        request: AgentRequest,
        *,
        diagnostics: RequestDiagnostics | None = None,
    ) -> AgentExecution:
        diagnostics = diagnostics or RequestDiagnostics.start(
            request.request_id, request.tenant.app_user_id,
            allow_retrieval_content=self._settings.notebook_agent_log_retrieval_content,
            environment=self._settings.notebook_agent_env,
        )
        services = self._service_factory(request)
        if isinstance(services, KnowledgeServices):
            services.set_diagnostics(diagnostics)
        action_services = (
            self._action_factory(request)
            if self._settings.agent_save_enabled
            and self._action_factory is not None
            else None
        )
        actions = AgentActionRuntime(
            request,
            action_services,
            enabled=self._settings.agent_save_enabled,
        )
        deps = AgentDeps(services, actions, diagnostics=diagnostics)
        diagnostics.event("agent_started", agent_phase="retrieval")
        usage = RunUsage()
        model_attempts = 0

        def record_model_attempt(_context):
            nonlocal model_attempts
            model_attempts += 1
            diagnostics.event(
                "model_attempt",
                call_index=model_attempts,
                agent_phase="retrieval",
            )
            return {"parallel_tool_calls": False}
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(
                list(request.history)
            )
            async with asyncio.timeout(self._settings.agent_timeout_seconds):
                with self._agent.parallel_tool_call_execution_mode("sequential"):
                    await self._agent.run(
                        request.question,
                        deps=deps,
                        message_history=message_history,
                        usage_limits=UsageLimits(
                            request_limit=self._settings.agent_request_limit,
                            tool_calls_limit=self._settings.agent_tool_calls_limit,
                            output_tokens_limit=self._settings.agent_output_token_limit,
                        ),
                        usage=usage,
                        model_settings=record_model_attempt,
                    )
        except TimeoutError:
            diagnostics.event(
                "agent_failed", error_code="timeout", agent_phase="retrieval"
            )
            if deps.citations:
                return await self._compose_or_fallback(request, deps, diagnostics)
            return self._failure(
                request, "模型响应超时，请稍后重试。", "timeout", diagnostics,
                log_event=False,
            )
        except UsageLimitExceeded as exc:
            kind, limit, used = classify_usage_limit(exc)
            diagnostics.event(
                "agent_failed", error_code="limit", exception=exc,
                limit_kind=kind, limit_value=limit,
                used_value=deps.tool_calls if kind == "tool_calls" else used,
                projected_value=used if kind == "tool_calls" else None,
                agent_phase="retrieval",
            )
            if deps.citations:
                return await self._compose_or_fallback(request, deps, diagnostics)
            return self._failure(
                request, self._limit_text(kind, phase="retrieval"), "limit", diagnostics,
                log_event=False,
            )
        except EmbeddingUnavailable:
            return self._failure(
                request,
                "查询能力暂时不可用，请稍后重试。",
                "embedding_unavailable",
                diagnostics,
            )
        except RetrievalUnavailable:
            return self._failure(
                request,
                "查询能力暂时不可用，请稍后重试。",
                "retrieval_unavailable",
                diagnostics,
            )
        except ModelHTTPError as exc:
            diagnostics.event(
                "agent_failed",
                error_code="runtime_error",
                exception=exc,
                http_status=exc.status_code,
                agent_phase="retrieval",
            )
            return self._failure(
                request,
                "知识库暂时无法完成检索，请稍后重试。",
                "runtime_error",
                diagnostics,
                log_event=False,
            )
        except UnexpectedModelBehavior:
            if deps.actions.input_mismatch:
                outcome = deps.actions.finalize_input_mismatch()
                diagnostics.event(
                    "action_validated", error_code=outcome.error_code
                )
                return AgentExecution(
                    AgentAnswer(
                        status=outcome.status,
                        text=outcome.text,
                        action_results=list(outcome.results),
                        thread_id=request.thread_public_id,
                        error_code=outcome.error_code,
                    ),
                    [],
                )
            return self._failure(
                request, "知识库暂时无法完成检索，请稍后重试。", "runtime_error", diagnostics
            )
        except KnowledgeNotFound:
            return self._failure(request, "请求的知识片段不存在。", "not_found", diagnostics)
        except Exception as exc:
            diagnostics.event(
                "agent_failed",
                error_code="runtime_error",
                exception=exc,
                agent_phase="retrieval",
            )
            return self._failure(
                request, "知识库暂时无法完成检索，请稍后重试。", "runtime_error", diagnostics,
                log_event=False,
            )

        if deps.actions.outcome is not None:
            outcome = deps.actions.outcome
            diagnostics.event(
                "action_validated", error_code=outcome.error_code
            )
            return AgentExecution(
                AgentAnswer(
                    status=outcome.status,
                    text=outcome.text,
                    action_results=list(outcome.results),
                    thread_id=request.thread_public_id,
                    error_code=outcome.error_code,
                ),
                # The model's action prose is not trusted or needed for
                # recovery. Persist only the canonical ActionOutcome on the
                # conversation turn; pending confirmation is separately
                # durable and tenant/thread-bound.
                [],
            )

        if deps.search_calls < 1:
            return self._failure(
                request,
                "未完成必要的知识库检索，因此不返回无来源答案。",
                "search_required",
                diagnostics,
            )
        if not deps.citations:
            diagnostics.event(
                "citation_validated",
                error_code="no_evidence",
                agent_phase="retrieval",
            )
            return AgentExecution(
                AgentAnswer(
                    status="not_found",
                    text="知识库中未找到足够证据。",
                    thread_id=request.thread_public_id,
                    error_code="no_evidence",
                ),
                [],
            )
        return await self._compose_or_fallback(request, deps, diagnostics)

    async def _compose_or_fallback(
        self,
        request: AgentRequest,
        deps: AgentDeps,
        diagnostics: RequestDiagnostics,
    ) -> AgentExecution:
        """Run a fresh-budget answer-only stage, preserving trusted evidence."""

        citations = _limit_citations_by_item(list(deps.citations.values()))
        composer_deps = ComposerDeps(
            {citation.segment_id: citation for citation in citations},
            diagnostics=diagnostics,
        )
        attempts = 0

        def record_answer_attempt(_context):
            nonlocal attempts
            attempts += 1
            diagnostics.event(
                "model_attempt", call_index=attempts, agent_phase="answer"
            )
            return {"parallel_tool_calls": False}

        try:
            async with asyncio.timeout(self._settings.agent_timeout_seconds):
                result = await self._composer.run(
                    request.question.strip(),
                    deps=composer_deps,
                    usage_limits=UsageLimits(
                        request_limit=ANSWER_REQUEST_LIMIT,
                        output_tokens_limit=self._settings.agent_output_token_limit,
                    ),
                    usage=RunUsage(),
                    model_settings=record_answer_attempt,
                )
        except TimeoutError:
            diagnostics.event(
                "agent_failed", error_code="timeout", agent_phase="answer"
            )
            return self._evidence_fallback(request, citations)
        except UsageLimitExceeded as exc:
            kind, limit, used = classify_usage_limit(exc)
            diagnostics.event(
                "agent_failed",
                error_code="limit",
                exception=exc,
                limit_kind=kind,
                limit_value=limit,
                used_value=used,
                agent_phase="answer",
            )
            return self._evidence_fallback(request, citations)
        except ModelHTTPError as exc:
            diagnostics.event(
                "agent_failed",
                error_code="answer_unavailable",
                exception=exc,
                http_status=exc.status_code,
                agent_phase="answer",
            )
            return self._evidence_fallback(request, citations)
        except (UnexpectedModelBehavior, ModelRetry) as exc:
            diagnostics.event(
                "agent_failed",
                error_code="answer_unavailable",
                exception=exc,
                agent_phase="answer",
            )
            return self._evidence_fallback(request, citations)
        except Exception as exc:
            diagnostics.event(
                "agent_failed",
                error_code="answer_unavailable",
                exception=exc,
                agent_phase="answer",
            )
            return self._evidence_fallback(request, citations)

        cited_ids = {
            segment_id
            for section in result.output.sections
            for segment_id in section.citation_ids
        }
        selected = [
            citation for citation in citations if citation.segment_id in cited_ids
        ]
        answer_text = _render_sections(result.output, selected)
        diagnostics.event(
            "citation_validated",
            result_count=len(selected),
            retry_count=composer_deps.invalid_draft_count,
            agent_phase="answer",
        )
        return AgentExecution(
            AgentAnswer(
                status="ok",
                text=answer_text,
                citations=selected,
                thread_id=request.thread_public_id,
            ),
            _canonical_history(request.question, answer_text),
        )

    @staticmethod
    def _evidence_fallback(
        request: AgentRequest, citations: list[Citation]
    ) -> AgentExecution:
        answer_text = _append_sources(FALLBACK_INTRO, citations)
        return AgentExecution(
            AgentAnswer(
                status="ok",
                text=answer_text,
                citations=citations,
                thread_id=request.thread_public_id,
            ),
            _canonical_history(request.question, answer_text),
        )

    @staticmethod
    def _limit_text(kind: str, *, phase: Literal["retrieval", "answer"]) -> str:
        prefix = "检索阶段" if phase == "retrieval" else "回答阶段"
        if kind == "output_tokens":
            return f"{prefix}的模型输出超过安全上限，请稍后重试。"
        if kind == "request":
            return f"{prefix}的模型请求次数超过安全上限，请稍后重试。"
        if kind == "tool_calls":
            return "检索工具调用超过安全上限，请稍后重试。"
        return f"{prefix}达到安全上限，请稍后重试。"

    @staticmethod
    def _failure(
        request: AgentRequest,
        text: str,
        code: str,
        diagnostics: RequestDiagnostics,
        *,
        log_event: bool = True,
    ) -> AgentExecution:
        if log_event:
            diagnostics.event(
                "agent_failed", error_code=code, agent_phase="retrieval"
            )
        return AgentExecution(
            AgentAnswer(
                status="failed",
                text=text,
                thread_id=request.thread_public_id,
                error_code=code,
            ),
            [],
        )


def _limit_citations_by_item(citations: list[Citation]) -> list[Citation]:
    """Project deterministic top-five item evidence in retrieval order."""

    selected: list[Citation] = []
    item_ids: set[int] = set()
    for citation in citations:
        if citation.item_id not in item_ids:
            if len(item_ids) >= MAX_SOURCE_ITEMS:
                continue
            item_ids.add(citation.item_id)
        selected.append(citation)
    return selected


def _render_sections(draft: AnswerDraft, citations: list[Citation]) -> str:
    """Render server-owned markers after structured citation validation."""

    allowed = {citation.segment_id for citation in citations}
    sections: list[str] = []
    for section in draft.sections:
        ids = [
            segment_id
            for segment_id in section.citation_ids
            if segment_id in allowed
        ]
        markers = " ".join(f"[S{segment_id}]" for segment_id in ids)
        sections.append(f"{section.text.strip()} {markers}".strip())
    return _append_sources("\n\n".join(sections), citations)


def _canonical_history(question: str, answer: str) -> list[ModelMessage]:
    """Persist only the normalized user question and visible final answer."""

    normalized_question = " ".join(question.split())
    return [
        ModelRequest(parts=[UserPromptPart(normalized_question)]),
        ModelResponse(parts=[TextPart(answer)]),
    ]


def _append_sources(text: str, citations: list[Citation]) -> str:
    """Render ranked source groups without inventing chapter metadata.

    ``citations`` arrives in the retrieval order retained by the server.  That
    order is the only trustworthy relevance signal at this boundary.  A video
    gets one top-level entry, while every distinct cited segment remains a
    nested timestamp link; exact duplicate segment ids were already collapsed
    when evidence was recorded.
    """

    groups: dict[int, list[Citation]] = {}
    for citation in citations:
        if citation.item_id not in groups:
            if len(groups) >= MAX_SOURCE_ITEMS:
                continue
            groups[citation.item_id] = []
        groups[citation.item_id].append(citation)

    lines = [text.rstrip(), "", "来源："]
    for group in groups.values():
        title = group[0].title
        lines.append(f"- {title}")
        for citation in group:
            excerpt = " ".join(citation.excerpt.split())
            if len(excerpt) > 180:
                excerpt = f"{excerpt[:177]}…"
            lines.append(
                f"  - [S{citation.segment_id}] {citation.url} — {excerpt}"
            )
    return "\n".join(lines)
