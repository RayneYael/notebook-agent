"""Deterministic self-registration and cross-channel identity linking."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.channels.errors import (
    DisabledIdentity,
    ExpiredLinkToken,
    IdentityConflict,
    InvalidLinkToken,
    UnboundIdentity,
    UsedLinkToken,
)
from app.channels.types import ChannelEnvelope, TenantContext
from app.models import AppUser, ChannelIdentity, ChannelLinkToken


def _identity_query(envelope: ChannelEnvelope):
    return select(ChannelIdentity).where(
        ChannelIdentity.channel == envelope.channel,
        ChannelIdentity.account_id == envelope.account_id,
        ChannelIdentity.external_user_id == envelope.external_user_id,
    )


def _tenant(db: Session, identity: ChannelIdentity) -> TenantContext:
    user = db.get(AppUser, identity.app_user_id)
    if user is None or user.disabled_at is not None or identity.disabled_at is not None:
        raise DisabledIdentity("account is disabled")
    return TenantContext(
        app_user_id=user.id,
        channel_identity_id=identity.id,
        channel=identity.channel,
        account_id=identity.account_id,
        external_user_id=identity.external_user_id,
    )


def resolve_identity(db: Session, envelope: ChannelEnvelope) -> TenantContext:
    identity = db.scalar(_identity_query(envelope))
    if identity is None:
        raise UnboundIdentity("channel identity is not registered")
    return _tenant(db, identity)


def resolve_or_register(db: Session, envelope: ChannelEnvelope) -> TenantContext:
    """Atomically return the existing identity or create one private tenant."""

    identity = db.scalar(_identity_query(envelope))
    if identity is not None:
        return _tenant(db, identity)

    user = AppUser()
    db.add(user)
    db.flush()
    identity_id = db.scalar(
        insert(ChannelIdentity)
        .values(
            app_user_id=user.id,
            channel=envelope.channel,
            account_id=envelope.account_id,
            external_user_id=envelope.external_user_id,
        )
        .on_conflict_do_nothing(
            index_elements=["channel", "account_id", "external_user_id"]
        )
        .returning(ChannelIdentity.id)
    )
    if identity_id is None:
        db.delete(user)
        db.flush()
        identity = db.scalar(_identity_query(envelope))
        if identity is None:
            raise IdentityConflict("identity registration raced but no owner exists")
    else:
        identity = db.get(ChannelIdentity, identity_id)
    return _tenant(db, identity)


def create_link_token(
    db: Session,
    tenant: TenantContext,
    *,
    target_channel: str | None = None,
    ttl: timedelta = timedelta(minutes=10),
    now: datetime | None = None,
) -> str:
    if db.get(AppUser, tenant.app_user_id) is None:
        raise UnboundIdentity("internal user does not exist")
    raw = secrets.token_urlsafe(32)
    token = ChannelLinkToken(
        token_hash=_token_hash(raw),
        app_user_id=tenant.app_user_id,
        target_channel=target_channel.strip() if target_channel else None,
        expires_at=(now or datetime.now(UTC)) + ttl,
    )
    db.add(token)
    db.flush()
    return raw


def consume_link_token(
    db: Session,
    envelope: ChannelEnvelope,
    raw_token: str,
    *,
    now: datetime | None = None,
) -> TenantContext:
    token = db.scalar(
        select(ChannelLinkToken)
        .where(ChannelLinkToken.token_hash == _token_hash(raw_token))
        .with_for_update()
    )
    current = now or datetime.now(UTC)
    if token is None:
        raise InvalidLinkToken("link token is invalid")
    if token.consumed_at is not None:
        raise UsedLinkToken("link token has already been used")
    if token.expires_at <= current:
        raise ExpiredLinkToken("link token has expired")
    if token.target_channel and token.target_channel != envelope.channel:
        raise InvalidLinkToken("link token is for a different channel")
    if db.scalar(_identity_query(envelope)) is not None:
        raise IdentityConflict("channel identity is already bound")

    identity = ChannelIdentity(
        app_user_id=token.app_user_id,
        channel=envelope.channel,
        account_id=envelope.account_id,
        external_user_id=envelope.external_user_id,
    )
    db.add(identity)
    token.consumed_at = current
    db.flush()
    return _tenant(db, identity)


def _token_hash(raw_token: str) -> str:
    normalized = str(raw_token).strip()
    if not normalized:
        raise InvalidLinkToken("link token is required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
