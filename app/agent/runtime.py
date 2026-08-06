"""PydanticAI runtime with fixed tenant dependencies and evidence enforcement."""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.models import Model

from app.agent.services import (
    EmbeddingUnavailable,
    KnowledgeNotFound,
    KnowledgeServices,
    RetrievalUnavailable,
)
from app.agent.types import AgentAnswer, AgentRequest, Citation
from app.config import Settings


INSTRUCTIONS = """
你是私有知识库检索助手。你只能根据本次会话中的知识库工具结果回答。

规则：
1. 回答知识库事实前必须调用 search_segments；可以改写查询并再次搜索。
2. 需要上下文时调用 get_neighbors，需要元数据时调用 get_item，最终引用位置可调用 open_at。
3. 不得依据模型记忆补写。没有结果或证据不足时，明确说“知识库中未找到足够证据”。
4. 回答中的结论应标注对应的 [S片段编号]。不要编造片段编号、标题、原文或链接。
5. 工具没有 user_id 参数；不要询问、猜测或尝试改变当前用户。
""".strip()


@dataclass
class AgentDeps:
    services: KnowledgeServices
    search_calls: int = 0
    tool_calls: int = 0
    citations: dict[int, Citation] = field(default_factory=dict)
    last_search_citation_ids: set[int] = field(default_factory=set)
    final_citation_ids: set[int] = field(default_factory=set)
    citation_repair_search_calls: int | None = None
    discarded_draft_count: int = 0

    def record(self, values: list[Citation] | Citation) -> None:
        rows = values if isinstance(values, list) else [values]
        for citation in rows:
            if len(self.citations) >= 12:
                break
            self.citations[citation.segment_id] = citation


@dataclass(frozen=True)
class AgentExecution:
    answer: AgentAnswer
    new_messages: list[ModelMessage]


def build_agent(model: Model | str) -> Agent[AgentDeps, str]:
    agent = Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        instructions=INSTRUCTIONS,
        retries={"tools": 1, "output": 1},
        tool_timeout=15.0,
    )

    @agent.tool
    def search_segments(
        ctx: RunContext[AgentDeps], query: str, limit: int = 6
    ) -> list[dict]:
        """Search the current user's knowledge segments for evidence."""

        ctx.deps.search_calls += 1
        ctx.deps.tool_calls += 1
        citations = ctx.deps.services.search_segments(query, limit=limit)
        ctx.deps.record(citations)
        ctx.deps.last_search_citation_ids = {
            citation.segment_id for citation in citations
        }
        return [value.model_dump() for value in citations]

    @agent.tool
    def get_neighbors(
        ctx: RunContext[AgentDeps], segment_id: int, radius: int = 1
    ) -> list[dict]:
        """Read nearby segments around a search result."""

        ctx.deps.tool_calls += 1
        citations = ctx.deps.services.get_neighbors(segment_id, radius=radius)
        ctx.deps.record(citations)
        return [value.model_dump() for value in citations]

    @agent.tool
    def get_item(ctx: RunContext[AgentDeps], item_id: int) -> dict:
        """Read metadata for a knowledge item returned by search."""

        ctx.deps.tool_calls += 1
        return asdict(ctx.deps.services.get_item(item_id))

    @agent.tool
    def open_at(ctx: RunContext[AgentDeps], segment_id: int) -> dict:
        """Resolve a segment to a clickable timestamp or article anchor."""

        ctx.deps.tool_calls += 1
        citation = ctx.deps.services.open_at(segment_id)
        ctx.deps.record(citation)
        return citation.model_dump()

    @agent.output_validator
    def validate_evidence(ctx: RunContext[AgentDeps], output: str) -> str:
        """Reject fabricated markers before the draft becomes an Agent result."""

        citations = ctx.deps.citations
        if not citations:
            return output
        cited_ids = {int(value) for value in re.findall(r"\[S(\d+)\]", output)}
        allowed_ids = (
            ctx.deps.last_search_citation_ids
            if ctx.deps.citation_repair_search_calls is not None
            else set(citations)
        )
        if cited_ids and cited_ids.issubset(allowed_ids):
            if (
                ctx.deps.citation_repair_search_calls is None
                or ctx.deps.search_calls > ctx.deps.citation_repair_search_calls
            ):
                ctx.deps.final_citation_ids = cited_ids
                return output
        ctx.deps.discarded_draft_count += 1
        if ctx.deps.citation_repair_search_calls is None:
            ctx.deps.citation_repair_search_calls = ctx.deps.search_calls
        raise ModelRetry(
            "The draft did not cite only evidence returned by the tools. "
            "Call search_segments again, then answer using only citation IDs from "
            "the fresh tool result."
        )

    return agent


class KnowledgeAgent:
    """Run the model and convert every outcome to a fail-closed answer."""

    def __init__(
        self,
        model: Model | str,
        settings: Settings,
        service_factory: Callable[[AgentRequest], KnowledgeServices],
    ) -> None:
        self._agent = build_agent(model)
        self._settings = settings
        self._service_factory = service_factory

    async def run(self, request: AgentRequest) -> AgentExecution:
        deps = AgentDeps(self._service_factory(request))
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(
                list(request.history)
            )
            async with asyncio.timeout(self._settings.agent_timeout_seconds):
                result = await self._agent.run(
                    request.question,
                    deps=deps,
                    message_history=message_history,
                    usage_limits=UsageLimits(
                        request_limit=self._settings.agent_request_limit,
                        tool_calls_limit=self._settings.agent_tool_calls_limit,
                        output_tokens_limit=self._settings.agent_output_token_limit,
                    ),
                )
        except TimeoutError:
            return self._failure(request, "模型响应超时，请稍后重试。", "timeout")
        except UsageLimitExceeded:
            return self._failure(
                request, "检索步骤已达到上限，请缩小问题范围后重试。", "limit"
            )
        except EmbeddingUnavailable:
            return self._failure(
                request,
                "查询能力暂时不可用，请稍后重试。",
                "embedding_unavailable",
            )
        except RetrievalUnavailable:
            return self._failure(
                request,
                "查询能力暂时不可用，请稍后重试。",
                "retrieval_unavailable",
            )
        except UnexpectedModelBehavior:
            if deps.citation_repair_search_calls is not None:
                return self._failure(
                    request,
                    "暂时无法生成可靠答案，请换个问法或稍后重试。",
                    "answer_unavailable",
                )
            return self._failure(
                request, "知识库暂时无法完成检索，请稍后重试。", "runtime_error"
            )
        except KnowledgeNotFound:
            return self._failure(request, "请求的知识片段不存在。", "not_found")
        except Exception:
            return self._failure(
                request, "知识库暂时无法完成检索，请稍后重试。", "runtime_error"
            )

        if deps.search_calls < 1:
            return self._failure(
                request,
                "未完成必要的知识库检索，因此不返回无来源答案。",
                "search_required",
            )
        citations = [
            citation
            for segment_id, citation in deps.citations.items()
            if segment_id in deps.final_citation_ids
        ]
        if not citations:
            return AgentExecution(
                AgentAnswer(
                    status="not_found",
                    text="知识库中未找到足够证据。",
                    thread_id=request.thread_public_id,
                    error_code="no_evidence",
                ),
                result.new_messages(),
            )
        answer_text = result.output.strip()
        if not answer_text:
            return self._failure(
                request, "模型没有生成可验证的答案。", "empty_answer"
            )
        answer_text = _append_sources(answer_text, citations)
        return AgentExecution(
            AgentAnswer(
                status="ok",
                text=answer_text,
                citations=citations,
                thread_id=request.thread_public_id,
            ),
            # A rejected draft is never persisted. Keeping the successful answer
            # without model history preserves idempotency while avoiding replaying
            # an invalid model response in a later context window.
            [] if deps.discarded_draft_count else result.new_messages(),
        )

    @staticmethod
    def _failure(request: AgentRequest, text: str, code: str) -> AgentExecution:
        return AgentExecution(
            AgentAnswer(
                status="failed",
                text=text,
                thread_id=request.thread_public_id,
                error_code=code,
            ),
            [],
        )


def _append_sources(text: str, citations: list[Citation]) -> str:
    lines = [text.rstrip(), "", "来源："]
    for citation in citations:
        excerpt = " ".join(citation.excerpt.split())
        if len(excerpt) > 180:
            excerpt = f"{excerpt[:177]}…"
        lines.append(
            f"- [S{citation.segment_id}] {citation.title} — {excerpt} — {citation.url}"
        )
    return "\n".join(lines)
