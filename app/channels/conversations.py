"""Durable bounded conversation history independent of any Agent framework."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Sequence

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from app.channels.types import ChannelEnvelope, TenantContext
from app.models import (
    ConversationThread,
    ConversationTurn,
    PendingChannelAction,
)


def get_or_create_thread(
    db: Session, tenant: TenantContext, envelope: ChannelEnvelope
) -> ConversationThread:
    thread = db.scalar(
        select(ConversationThread).where(
            ConversationThread.channel_identity_id == tenant.channel_identity_id,
            ConversationThread.external_conversation_id == envelope.conversation_id,
            ConversationThread.closed_at.is_(None),
        )
    )
    if thread is not None:
        return thread
    thread = ConversationThread(
        public_id=str(uuid.uuid4()),
        app_user_id=tenant.app_user_id,
        channel_identity_id=tenant.channel_identity_id,
        channel=envelope.channel,
        account_id=envelope.account_id,
        external_conversation_id=envelope.conversation_id,
    )
    db.add(thread)
    db.flush()
    return thread


def reset_thread(
    db: Session, tenant: TenantContext, envelope: ChannelEnvelope
) -> ConversationThread:
    current = db.scalar(
        select(ConversationThread)
        .where(
            ConversationThread.channel_identity_id == tenant.channel_identity_id,
            ConversationThread.external_conversation_id == envelope.conversation_id,
            ConversationThread.closed_at.is_(None),
        )
        .with_for_update()
    )
    if current is not None:
        now = datetime.now(UTC)
        db.execute(
            update(PendingChannelAction)
            .where(
                PendingChannelAction.thread_id == current.id,
                PendingChannelAction.consumed_at.is_(None),
                PendingChannelAction.cancelled_at.is_(None),
            )
            .values(cancelled_at=now)
        )
        current.closed_at = now
        current.updated_at = current.closed_at
        db.flush()
    return get_or_create_thread(db, tenant, envelope)


def find_turn(
    db: Session, thread_id: int, message_id: str
) -> ConversationTurn | None:
    return db.scalar(
        select(ConversationTurn).where(
            ConversationTurn.thread_id == thread_id,
            ConversationTurn.message_id == message_id,
            ConversationTurn.status == "completed",
        )
    )


def load_message_history(
    db: Session,
    thread_id: int,
    *,
    max_turns: int,
    max_tokens: int,
) -> list[ModelMessage]:
    turns = list(
        db.scalars(
            select(ConversationTurn)
            .where(
                ConversationTurn.thread_id == thread_id,
                ConversationTurn.status == "completed",
            )
            .order_by(desc(ConversationTurn.created_at), desc(ConversationTurn.id))
            .limit(max_turns)
        )
    )
    selected: list[ConversationTurn] = []
    used = 0
    for turn in turns:
        cost = _estimate_tokens(turn.model_messages)
        if selected and used + cost > max_tokens:
            break
        if cost > max_tokens and not selected:
            continue
        selected.append(turn)
        used += cost

    messages: list[ModelMessage] = []
    for turn in reversed(selected):
        messages.extend(ModelMessagesTypeAdapter.validate_python(turn.model_messages))
    return messages


def save_completed_turn(
    db: Session,
    *,
    thread: ConversationThread,
    envelope: ChannelEnvelope,
    assistant_text: str,
    sources: Sequence[dict[str, Any]],
    model_messages: Sequence[ModelMessage],
    answer_status: str = "legacy",
    error_code: str | None = None,
    action_results: Sequence[dict[str, Any]] = (),
) -> ConversationTurn:
    existing = find_turn(db, thread.id, envelope.message_id)
    if existing is not None:
        return existing
    serialized = ModelMessagesTypeAdapter.dump_python(
        list(model_messages), mode="json"
    )
    turn = ConversationTurn(
        thread_id=thread.id,
        message_id=envelope.message_id,
        user_text=envelope.text,
        assistant_text=assistant_text,
        sources=list(sources),
        model_messages=serialized,
        answer_status=answer_status,
        error_code=error_code,
        action_results=list(action_results),
        status="completed",
    )
    db.add(turn)
    thread.updated_at = datetime.now(UTC)
    db.flush()
    return turn


def _estimate_tokens(payload: list | dict) -> int:
    # Provider-neutral conservative approximation used only for a hard cap.
    return max(1, len(json.dumps(payload, ensure_ascii=False)) // 3)
