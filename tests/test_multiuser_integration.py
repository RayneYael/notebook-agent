from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.agent.runtime import AgentExecution
from app.agent.services import KnowledgeNotFound, KnowledgeServices
from app.agent.types import AgentAnswer, Citation
from app.channels.conversations import (
    get_or_create_thread,
    load_message_history,
    save_completed_turn,
)
from app.channels.errors import (
    DisabledIdentity,
    ExpiredLinkToken,
    InvalidLinkToken,
    UsedLinkToken,
)
from app.channels.identity import (
    consume_link_token,
    create_link_token,
    resolve_identity,
    resolve_or_register,
)
from app.channels.service import ChannelService
from app.channels.types import ChannelEnvelope
from app.config import Settings
from app.db import get_engine, get_session_factory
from app.models import AppUser, ChannelIdentity, ContentItem, Segment
from app.retrieval.search import vector_search


class FakeEmbeddingProvider:
    dimensions = 1536

    def __init__(self):
        self.queries = []

    def embed(self, texts):
        self.queries.extend(texts)
        return [[0.01] * self.dimensions for _ in texts]


@pytest.fixture
def db_factory():
    try:
        connection = get_engine().connect()
        connection.execute(text("SELECT 1 FROM channel_identity LIMIT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL integration database unavailable: {type(exc).__name__}")
    transaction = connection.begin_nested() if connection.in_transaction() else connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield factory
    finally:
        transaction.rollback()
        connection.close()


def envelope(channel="telegram", user=None, message=None, conversation="chat"):
    suffix = user or uuid4().hex
    return ChannelEnvelope(
        channel=channel,
        account_id=f"account-{channel}",
        external_user_id=suffix,
        conversation_id=conversation,
        message_id=message or uuid4().hex,
        text="question",
    )


def test_registration_linking_expiry_replay_and_disable_fail_closed(db_factory):
    first = envelope(user=uuid4().hex)
    with db_factory() as db:
        tenant = resolve_or_register(db, first)
        db.commit()
    with db_factory() as db:
        repeated = resolve_or_register(db, first)
        assert repeated == tenant

        token = create_link_token(db, tenant, target_channel="wechat")
        db.commit()
    second = envelope(channel="wechat", user=uuid4().hex)
    with db_factory() as db:
        linked = consume_link_token(db, second, token)
        db.commit()
        assert linked.app_user_id == tenant.app_user_id
    with db_factory() as db:
        with pytest.raises(UsedLinkToken):
            consume_link_token(db, envelope(channel="wechat"), token)

        expired = create_link_token(
            db, tenant, target_channel="wechat", ttl=timedelta(seconds=-1)
        )
        db.commit()
    with db_factory() as db:
        with pytest.raises(ExpiredLinkToken):
            consume_link_token(db, envelope(channel="wechat"), expired)

        wrong = create_link_token(db, tenant, target_channel="slack")
        db.commit()
    with db_factory() as db:
        with pytest.raises(InvalidLinkToken):
            consume_link_token(db, envelope(channel="wechat"), wrong)

        user = db.get(AppUser, tenant.app_user_id)
        user.disabled_at = datetime.now(UTC)
        db.commit()
    with db_factory() as db:
        with pytest.raises(DisabledIdentity):
            resolve_identity(db, first)


def test_concurrent_registration_creates_one_user_and_identity():
    try:
        get_engine().connect().close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL integration database unavailable: {type(exc).__name__}")
    factory = get_session_factory()
    shared = envelope(user=f"concurrent-{uuid4().hex}")
    barrier = Barrier(2)

    def register():
        with factory() as db:
            barrier.wait(timeout=5)
            tenant = resolve_or_register(db, shared)
            db.commit()
            return tenant.app_user_id, tenant.channel_identity_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register(), range(2)))

    assert results[0] == results[1]
    with factory() as db:
        identities = list(
            db.scalars(
                select(ChannelIdentity).where(
                    ChannelIdentity.external_user_id == shared.external_user_id
                )
            )
        )
        assert len(identities) == 1
        db.delete(db.get(AppUser, results[0][0]))
        db.commit()


def _add_item(db, user_id, unique_text):
    item = ContentItem(
        user_id=user_id,
        platform="youtube",
        platform_id=uuid4().hex[:11],
        kind="video",
        url="https://youtu.be/example",
        title=f"title-{unique_text}",
        lang="zh",
        state="ready",
    )
    db.add(item)
    db.flush()
    segment = Segment(
        item_id=item.id,
        seq=0,
        start_sec=42,
        end_sec=52,
        text=unique_text,
        embedding=[0.01] * 1536,
        boundary_kind="hard_cut",
    )
    db.add(segment)
    db.flush()
    return item, segment


def test_every_read_service_is_tenant_scoped(db_factory):
    with db_factory() as db:
        tenant_a = resolve_or_register(db, envelope(user=uuid4().hex))
        tenant_b = resolve_or_register(db, envelope(user=uuid4().hex))
        item_a, segment_a = _add_item(db, tenant_a.app_user_id, "甲方专属量子菠萝")
        item_b, segment_b = _add_item(db, tenant_b.app_user_id, "乙方专属月球草莓")
        db.commit()

    embedder = FakeEmbeddingProvider()
    service_a = KnowledgeServices(tenant_a, db_factory, embedder=embedder)
    # Vector ranking may return tenant A's nearest candidate for a query that
    # names tenant B. The security contract is that it can never hydrate B.
    assert {
        value.segment_id for value in service_a.search_segments("乙方专属月球草莓")
    } == {segment_a.id}
    assert service_a.search_segments("甲方专属量子菠萝")[0].segment_id == segment_a.id
    for action in (
        lambda: service_a.get_neighbors(segment_b.id),
        lambda: service_a.get_item(item_b.id),
        lambda: service_a.open_at(segment_b.id),
    ):
        with pytest.raises(KnowledgeNotFound):
            action()
    assert service_a.get_item(item_a.id).item_id == item_a.id
    assert service_a.open_at(segment_a.id).url.endswith("?t=42")
    assert embedder.queries == ["乙方专属月球草莓", "甲方专属量子菠萝"]
    with db_factory() as db:
        vector_hits = vector_search(
            db, [0.01] * 1536, user_id=tenant_a.app_user_id, k=10
        )
    assert {value.segment_id for value in vector_hits} == {segment_a.id}


class RecordingAgent:
    def __init__(self):
        self.histories = []

    async def run(self, request):
        self.histories.append(request.history)
        citation = Citation(
            item_id=1,
            segment_id=1,
            title="source",
            excerpt="evidence",
            url="https://example.test?t=1",
            start_sec=1,
        )
        messages = [
            ModelRequest(parts=[UserPromptPart(content=request.question)]),
            ModelResponse(parts=[TextPart(content="answer")]),
        ]
        return AgentExecution(
            AgentAnswer(
                status="ok",
                text="answer",
                citations=[citation],
                thread_id=request.thread_public_id,
            ),
            messages,
        )


class NoEvidenceAgent:
    def __init__(self):
        self.calls = 0

    async def run(self, request):
        self.calls += 1
        return AgentExecution(
            AgentAnswer(
                status="not_found",
                text="知识库中未找到足够证据。",
                thread_id=request.thread_public_id,
                error_code="no_evidence",
            ),
            [],
        )


@pytest.mark.asyncio
async def test_context_recovers_after_service_restart_and_replay_is_idempotent(db_factory):
    settings = replace(Settings(), context_max_turns=4, context_token_budget=1000)
    agent = RecordingAgent()
    first_service = ChannelService(db_factory, agent, settings)
    external = uuid4().hex
    first = envelope(user=external, message="m1")
    await first_service.handle(first)

    restarted_service = ChannelService(db_factory, agent, settings)
    second = envelope(user=external, message="m2")
    await restarted_service.handle(second)
    await restarted_service.handle(second)

    assert agent.histories[0] == ()
    assert len(agent.histories[1]) == 2
    assert len(agent.histories) == 2


@pytest.mark.asyncio
async def test_no_evidence_replay_keeps_its_distinct_status_and_code(db_factory):
    settings = replace(Settings(), context_max_turns=4, context_token_budget=1000)
    agent = NoEvidenceAgent()
    service = ChannelService(db_factory, agent, settings)
    original = envelope(user=uuid4().hex, message="no-evidence-message")

    first = await service.handle(original)
    replay = await service.handle(original)

    assert first.status == replay.status == "not_found"
    assert first.error_code == replay.error_code == "no_evidence"
    assert agent.calls == 1


def test_context_window_and_channels_do_not_mix(db_factory):
    with db_factory() as db:
        tg_envelope = envelope(user=uuid4().hex, conversation="same-label")
        wx_envelope = envelope(channel="wechat", user=uuid4().hex, conversation="same-label")
        tg_tenant = resolve_or_register(db, tg_envelope)
        link = create_link_token(db, tg_tenant, target_channel="wechat")
        db.flush()
        wx_tenant = consume_link_token(db, wx_envelope, link)
        assert wx_tenant.app_user_id == tg_tenant.app_user_id
        tg_thread = get_or_create_thread(db, tg_tenant, tg_envelope)
        wx_thread = get_or_create_thread(db, wx_tenant, wx_envelope)
        for index in range(3):
            current = envelope(user=tg_envelope.external_user_id, message=f"m{index}")
            save_completed_turn(
                db,
                thread=tg_thread,
                envelope=current,
                assistant_text=f"a{index}",
                sources=[],
                model_messages=[
                    ModelRequest(parts=[UserPromptPart(content=f"q{index}")]),
                    ModelResponse(parts=[TextPart(content=f"a{index}")]),
                ],
            )
        db.commit()
    with db_factory() as db:
        history = load_message_history(db, tg_thread.id, max_turns=2, max_tokens=1000)
        token_limited = load_message_history(
            db, tg_thread.id, max_turns=10, max_tokens=1
        )
        other = load_message_history(db, wx_thread.id, max_turns=10, max_tokens=1000)
    assert len(history) == 4
    assert token_limited == []
    assert other == []


@pytest.mark.asyncio
async def test_new_command_closes_old_context_and_disabled_user_skips_agent(db_factory):
    settings = replace(Settings(), context_max_turns=4, context_token_budget=1000)
    agent = RecordingAgent()
    service = ChannelService(db_factory, agent, settings)
    external = uuid4().hex
    first = envelope(user=external, message="before")
    await service.handle(first)

    reset = envelope(user=external, message="reset")
    reset = ChannelEnvelope(
        reset.channel,
        reset.account_id,
        reset.external_user_id,
        reset.conversation_id,
        reset.message_id,
        "/new",
    )
    reset_answer = await service.handle(reset)
    assert reset_answer.status == "ok"

    after = envelope(user=external, message="after")
    await service.handle(after)
    assert agent.histories[-1] == ()

    with db_factory() as db:
        tenant = resolve_identity(db, after)
        db.get(AppUser, tenant.app_user_id).disabled_at = datetime.now(UTC)
        db.commit()
    failed = await service.handle(envelope(user=external, message="disabled"))
    assert failed.status == "failed"
    assert failed.error_code == "identity_error"
    assert len(agent.histories) == 2
