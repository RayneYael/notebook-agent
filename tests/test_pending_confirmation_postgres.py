from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.channels.pending_actions import (
    PendingConfirmationService,
    PendingSaveSnapshot,
)
from app.channels.conversations import reset_thread
from app.channels.types import ChannelEnvelope, TenantContext
from app.db import get_engine
from app.models import (
    AppUser,
    Base,
    ChannelIdentity,
    ConversationThread,
    PendingChannelAction,
)


@pytest.fixture
def pending_factory():
    try:
        engine = get_engine()
    except Exception as exc:
        pytest.skip(
            "PostgreSQL configuration unavailable: "
            f"{type(exc).__name__}"
        )
    schema = f"test_pending_{uuid4().hex}"
    tables = [
        AppUser.__table__,
        ChannelIdentity.__table__,
        ConversationThread.__table__,
        PendingChannelAction.__table__,
    ]
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(
                text(f'SET LOCAL search_path TO "{schema}", public')
            )
            Base.metadata.create_all(
                connection,
                tables=tables,
                checkfirst=False,
            )
    except Exception as exc:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
        except Exception:
            pass
        pytest.skip(
            "isolated PostgreSQL schema unavailable: "
            f"{type(exc).__name__}"
        )

    def factory():
        db = Session(bind=engine, expire_on_commit=False)
        db.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        return db

    try:
        yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            )


def _conversation(factory, number):
    suffix = uuid4().hex
    with factory() as db:
        user = AppUser()
        db.add(user)
        db.flush()
        identity = ChannelIdentity(
            app_user_id=user.id,
            channel="telegram",
            account_id=f"account-{suffix}",
            external_user_id=f"user-{suffix}",
        )
        db.add(identity)
        db.flush()
        thread = ConversationThread(
            public_id=uuid4().hex,
            app_user_id=user.id,
            channel_identity_id=identity.id,
            channel="telegram",
            account_id=identity.account_id,
            external_conversation_id=f"chat-{suffix}",
        )
        db.add(thread)
        db.commit()
        return (
            TenantContext(
                user.id,
                identity.id,
                identity.channel,
                identity.account_id,
                identity.external_user_id,
            ),
            thread.id,
        )


def test_request_replaces_batch_and_confirm_is_single_consume_with_replay(
    pending_factory,
):
    tenant, thread_id = _conversation(pending_factory, 1)
    service = PendingConfirmationService(pending_factory)
    old_urls = [
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/9bZkp7q19f0",
    ]
    new_url = "https://youtu.be/M7lc1UVf-VE"

    first = service.request_save(tenant, thread_id, old_urls)
    replacement = service.request_save(tenant, thread_id, [new_url])
    confirmed = service.confirm_save(
        tenant, thread_id, message_id="confirm-one"
    )
    replay = service.confirm_save(
        tenant, thread_id, message_id="confirm-one"
    )
    late = service.confirm_save(
        tenant, thread_id, message_id="confirm-two"
    )

    assert first.status == "confirmation_required"
    assert len(first.urls) == 2
    assert replacement.status == "confirmation_required"
    assert confirmed.status == "confirmed"
    assert confirmed.urls == (
        "https://www.youtube.com/watch?v=M7lc1UVf-VE",
    )
    assert replay.status == "confirmed"
    assert replay.urls == confirmed.urls
    assert replay.replayed
    assert late.status == "confirmation_missing"
    assert late.urls == ()

    with pending_factory() as db:
        rows = list(
            db.scalars(
                select(PendingChannelAction).order_by(
                    PendingChannelAction.id
                )
            )
        )
    assert len(rows) == 2
    assert rows[0].cancelled_at is not None
    assert rows[1].consumed_message_id == "confirm-one"
    assert rows[1].payload == {
        "version": 1,
        "urls": [
            "https://www.youtube.com/watch?v=M7lc1UVf-VE"
        ],
    }
    assert timedelta(seconds=599) <= (
        rows[1].expires_at - rows[1].created_at
    ) <= timedelta(seconds=601)


def test_old_confirmation_replay_does_not_consume_a_new_pending_batch(
    pending_factory,
):
    tenant, thread_id = _conversation(pending_factory, 2)
    service = PendingConfirmationService(pending_factory)

    service.request_save(
        tenant, thread_id, ["https://youtu.be/dQw4w9WgXcQ"]
    )
    old = service.confirm_save(
        tenant, thread_id, message_id="old-confirm"
    )
    service.request_save(
        tenant, thread_id, ["https://youtu.be/9bZkp7q19f0"]
    )
    old_replay = service.confirm_save(
        tenant, thread_id, message_id="old-confirm"
    )
    current = service.confirm_save(
        tenant, thread_id, message_id="new-confirm"
    )

    assert old_replay.replayed
    assert old_replay.urls == old.urls
    assert current.urls == (
        "https://www.youtube.com/watch?v=9bZkp7q19f0",
    )


def test_expired_and_cancelled_confirmation_never_returns_urls(
    pending_factory,
):
    tenant, thread_id = _conversation(pending_factory, 3)
    service = PendingConfirmationService(pending_factory)

    service.request_save(
        tenant, thread_id, ["https://youtu.be/dQw4w9WgXcQ"]
    )
    with pending_factory() as db:
        action = db.scalar(select(PendingChannelAction))
        action.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    expired = service.confirm_save(
        tenant, thread_id, message_id="expired-confirm"
    )
    missing = service.confirm_save(
        tenant, thread_id, message_id="late-confirm"
    )

    assert expired.status == "confirmation_expired"
    assert expired.urls == ()
    assert missing.status == "confirmation_missing"

    service.request_save(
        tenant, thread_id, ["https://youtu.be/M7lc1UVf-VE"]
    )
    cancelled = service.cancel_save(tenant, thread_id)
    cancelled_again = service.cancel_save(tenant, thread_id)

    assert cancelled.status == "cancelled"
    assert cancelled.urls == ()
    assert cancelled_again.status == "confirmation_missing"


def test_confirmation_is_bound_to_trusted_tenant_and_thread(
    pending_factory,
):
    tenant_a, thread_a = _conversation(pending_factory, 4)
    tenant_b, thread_b = _conversation(pending_factory, 5)
    service = PendingConfirmationService(pending_factory)
    service.request_save(
        tenant_a, thread_a, ["https://youtu.be/aqz-KE-bpKQ"]
    )

    wrong_tenant = service.confirm_save(
        tenant_b, thread_a, message_id="wrong-tenant"
    )
    wrong_thread = service.confirm_save(
        tenant_a, thread_b, message_id="wrong-thread"
    )
    owner = service.confirm_save(
        tenant_a, thread_a, message_id="owner-confirm"
    )

    assert wrong_tenant.status == "confirmation_missing"
    assert wrong_thread.status == "confirmation_missing"
    assert wrong_tenant.urls == wrong_thread.urls == ()
    assert owner.status == "confirmed"
    assert owner.urls == (
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    )


def test_inspect_save_is_read_only_expiry_aware_and_thread_bound(
    pending_factory,
):
    tenant, thread_id = _conversation(pending_factory, 7)
    other_tenant, _ = _conversation(pending_factory, 8)
    service = PendingConfirmationService(pending_factory)
    service.request_save(
        tenant,
        thread_id,
        [
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtu.be/9bZkp7q19f0",
        ],
    )
    with pending_factory() as db:
        thread = db.get(ConversationThread, thread_id)
        assert thread is not None
        other_thread = ConversationThread(
            public_id=uuid4().hex,
            app_user_id=thread.app_user_id,
            channel_identity_id=thread.channel_identity_id,
            channel=thread.channel,
            account_id=thread.account_id,
            external_conversation_id=f"other-{uuid4().hex}",
        )
        db.add(other_thread)
        db.flush()
        action = db.scalar(select(PendingChannelAction))
        assert action is not None
        before = (action.consumed_at, action.cancelled_at, action.expires_at)
        other_thread_id = other_thread.id
        db.commit()

    restarted_service = PendingConfirmationService(pending_factory)
    snapshot = restarted_service.inspect_save(tenant, thread_id)
    wrong_tenant = service.inspect_save(other_tenant, thread_id)
    wrong_thread = service.inspect_save(tenant, other_thread_id)

    assert snapshot.active
    assert snapshot.count == 2
    assert not wrong_tenant.active
    assert wrong_tenant.count == 0
    assert not wrong_thread.active
    with pending_factory() as db:
        action = db.scalar(select(PendingChannelAction))
        assert action is not None
        assert (action.consumed_at, action.cancelled_at, action.expires_at) == before
        action.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    assert not service.inspect_save(tenant, thread_id).active
    with pending_factory() as db:
        action = db.scalar(select(PendingChannelAction))
        assert action is not None
        expired_before = (
            action.consumed_at,
            action.cancelled_at,
            action.expires_at,
        )
    assert not service.inspect_save(tenant, thread_id).active
    with pending_factory() as db:
        action = db.scalar(select(PendingChannelAction))
        assert action is not None
        assert (
            action.consumed_at,
            action.cancelled_at,
            action.expires_at,
        ) == expired_before


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 1, "urls": ["not-a-url"]},
        {"version": 1, "urls": [" https://www.youtube.com/watch?v=dQw4w9WgXcQ "]},
        {"version": 1, "urls": ["https://youtu.be/dQw4w9WgXcQ"]},
    ],
)
def test_inspect_save_rejects_invalid_or_noncanonical_payload_without_writing(
    pending_factory, payload
):
    tenant, thread_id = _conversation(pending_factory, 9)
    service = PendingConfirmationService(pending_factory)
    service.request_save(
        tenant, thread_id, ["https://youtu.be/dQw4w9WgXcQ"]
    )
    with pending_factory() as db:
        action = db.scalar(select(PendingChannelAction))
        assert action is not None
        action.payload = payload
        db.commit()
        before = (action.consumed_at, action.cancelled_at, action.expires_at)

    # An inactive snapshot is what prevents PydanticAI's dynamic instruction
    # from exposing a confirmation state to the model.
    assert service.inspect_save(tenant, thread_id) == PendingSaveSnapshot(
        active=False
    )
    with pending_factory() as db:
        action = db.scalar(select(PendingChannelAction))
        assert action is not None
        assert (action.consumed_at, action.cancelled_at, action.expires_at) == before


def test_new_thread_cancels_old_pending_action(pending_factory):
    tenant, thread_id = _conversation(pending_factory, 6)
    service = PendingConfirmationService(pending_factory)
    service.request_save(
        tenant, thread_id, ["https://youtu.be/dQw4w9WgXcQ"]
    )

    with pending_factory() as db:
        thread = db.get(ConversationThread, thread_id)
        envelope = ChannelEnvelope(
            channel=thread.channel,
            account_id=thread.account_id,
            external_user_id=tenant.external_user_id,
            conversation_id=thread.external_conversation_id,
            message_id="new-message",
            text="/new",
        )
        replacement = reset_thread(db, tenant, envelope)
        db.commit()

    with pending_factory() as db:
        old_action = db.scalar(
            select(PendingChannelAction).where(
                PendingChannelAction.thread_id == thread_id
            )
        )
    assert replacement.id != thread_id
    assert old_action.cancelled_at is not None
