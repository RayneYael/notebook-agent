"""Deterministic channel commands and the trusted Agent boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session
from pydantic_ai.messages import ModelMessagesTypeAdapter

from app.agent.runtime import AgentExecution, KnowledgeAgent
from app.agent.types import AgentAnswer, AgentRequest, Citation
from app.channels.conversations import (
    find_turn,
    get_or_create_thread,
    load_message_history,
    reset_thread,
    save_completed_turn,
)
from app.channels.errors import IdentityError, UnboundIdentity
from app.channels.identity import (
    consume_link_token,
    create_link_token,
    resolve_identity,
    resolve_or_register,
)
from app.channels.types import ChannelEnvelope
from app.config import Settings
from app.diagnostics import RequestDiagnostics
from app.models import ConversationThread


class ChannelService:
    """Handle one normalized message without importing any platform SDK."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        agent: KnowledgeAgent,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._agent = agent
        self._settings = settings
        self._locks: dict[tuple[str, str, str, str], asyncio.Lock] = {}

    async def handle(self, envelope: ChannelEnvelope) -> AgentAnswer:
        # Every in-process entry point gets an internal correlation ID. The
        # HTTP gateway overwrites its untrusted envelope field before this
        # point; other adapters and CLI receive a locally generated one.
        if envelope.request_id is None:
            envelope = replace(envelope, request_id=uuid4().hex)
        key = (
            envelope.channel,
            envelope.account_id,
            envelope.external_user_id,
            envelope.conversation_id,
        )
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                return await self._handle_locked(envelope)
            except IdentityError as exc:
                return AgentAnswer(
                    status="failed",
                    text=f"身份验证失败：{exc}",
                    error_code="identity_error",
                )

    async def _handle_locked(self, envelope: ChannelEnvelope) -> AgentAnswer:
        command, argument = _command(envelope.text)
        if command == "link":
            return self._handle_link(envelope, argument)

        with self._session_factory() as db:
            tenant = resolve_or_register(db, envelope)
            diagnostics = RequestDiagnostics.start(
                envelope.request_id, tenant.app_user_id, envelope.trace_id,
                allow_retrieval_content=self._settings.notebook_agent_log_retrieval_content,
                environment=self._settings.notebook_agent_env,
            )
            diagnostics.event("accepted")
            if command == "start":
                diagnostics.event("route", route="command")
                db.commit()
                return self._response_ready(
                    diagnostics,
                    AgentAnswer(
                        status="ok",
                        text=(
                            "账户已就绪。你的知识库与其他用户完全隔离。\n"
                            f"内部用户编号：{tenant.app_user_id}"
                        ),
                    ),
                )
            if command == "whoami":
                diagnostics.event("route", route="command")
                db.commit()
                return self._response_ready(
                    diagnostics,
                    AgentAnswer(
                        status="ok", text=f"内部用户编号：{tenant.app_user_id}"
                    ),
                )
            if command == "new":
                diagnostics.event("route", route="command")
                thread = reset_thread(db, tenant, envelope)
                db.commit()
                return self._response_ready(
                    diagnostics,
                    AgentAnswer(
                        status="ok",
                        text="已开启新会话，旧上下文不会继续带入。",
                        thread_id=thread.public_id,
                    ),
                )

            thread = get_or_create_thread(db, tenant, envelope)
            duplicate = find_turn(db, thread.id, envelope.message_id)
            if duplicate is not None:
                diagnostics.event("duplicate", route="duplicate")
                answer = _answer_from_turn(duplicate, thread.public_id)
                db.commit()
                return self._response_ready(diagnostics, answer)
            history = load_message_history(
                db,
                thread.id,
                max_turns=self._settings.context_max_turns,
                max_tokens=self._settings.context_token_budget,
            )
            request = AgentRequest(
                question=envelope.text,
                tenant=tenant,
                thread_db_id=thread.id,
                thread_public_id=thread.public_id,
                message_id=envelope.message_id,
                request_id=envelope.request_id,
                history=tuple(
                    ModelMessagesTypeAdapter.dump_python(history, mode="json")
                ),
            )
            db.commit()

        diagnostics.event("route", route="agent")
        execution = await self._agent.run(request, diagnostics=diagnostics)
        # A terminal action outcome must be durable even when its public status
        # is failed; plain transient knowledge failures remain retryable.
        if (
            execution.answer.status == "failed"
            and not execution.answer.action_results
        ):
            return self._response_ready(diagnostics, execution.answer)

        with self._session_factory() as db:
            thread = db.get(ConversationThread, request.thread_db_id)
            if thread is None or thread.app_user_id != request.tenant.app_user_id:
                return self._response_ready(
                    diagnostics,
                    AgentAnswer(
                        status="failed",
                        text="会话已失效，请重新发送消息。",
                        error_code="thread_missing",
                    ),
                )
            duplicate = find_turn(db, thread.id, envelope.message_id)
            if duplicate is not None:
                return self._response_ready(
                    diagnostics, _answer_from_turn(duplicate, thread.public_id)
                )
            save_completed_turn(
                db,
                thread=thread,
                envelope=envelope,
                assistant_text=execution.answer.text,
                sources=[value.model_dump() for value in execution.answer.citations],
                model_messages=execution.new_messages,
                answer_status=execution.answer.status,
                error_code=execution.answer.error_code,
                action_results=execution.answer.action_results,
            )
            db.commit()
        return self._response_ready(diagnostics, execution.answer)

    @staticmethod
    def _response_ready(
        diagnostics: RequestDiagnostics, answer: AgentAnswer
    ) -> AgentAnswer:
        diagnostics.event("gateway_response_ready", error_code=answer.error_code)
        return answer

    def _handle_link(self, envelope: ChannelEnvelope, argument: str | None) -> AgentAnswer:
        if not argument:
            return AgentAnswer(
                status="failed",
                text="用法：已登录渠道发送 /link telegram；新渠道发送 /link <绑定码>。",
                error_code="link_usage",
            )
        with self._session_factory() as db:
            try:
                tenant = resolve_identity(db, envelope)
            except UnboundIdentity:
                tenant = consume_link_token(db, envelope, argument)
                db.commit()
                return AgentAnswer(
                    status="ok",
                    text="渠道绑定成功，现在可访问同一个私有知识库。",
                )

            token = create_link_token(
                db,
                tenant,
                target_channel=argument.lower(),
                ttl=timedelta(seconds=self._settings.channel_link_ttl_seconds),
            )
            db.commit()
            return AgentAnswer(
                status="ok",
                text=(
                    f"绑定码：{token}\n"
                    f"请在 {argument.lower()} 中发送 /link {token}。"
                    "该绑定码短期有效且只能使用一次。"
                ),
            )


def _command(text: str) -> tuple[str | None, str | None]:
    parts = text.strip().split(maxsplit=1)
    if not parts or not parts[0].startswith("/"):
        return None, None
    command = parts[0].split("@", 1)[0].lower().removeprefix("/")
    if command not in {"start", "new", "link", "whoami"}:
        return None, None
    return command, parts[1].strip() if len(parts) == 2 else None


def _answer_from_turn(turn, public_id: str) -> AgentAnswer:
    citations = [Citation.model_validate(value) for value in turn.sources]
    answer_status = turn.answer_status
    error_code = turn.error_code
    if answer_status == "legacy":
        answer_status = "ok" if citations else "not_found"
        error_code = None if citations else "no_evidence"
    return AgentAnswer(
        status=answer_status,
        text=turn.assistant_text,
        citations=citations,
        action_results=list(turn.action_results or []),
        thread_id=public_id,
        error_code=error_code,
    )
