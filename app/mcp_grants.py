"""Operator-managed MCP bearer grants.

The MCP transport is intentionally stateless.  Every request presents a raw
bearer token, which is immediately reduced to a SHA-256 digest and resolved to
one durable principal, tenant, and capability scope.  No caller-controlled
application-user id crosses this boundary.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels.identity import ensure_explicit_identity
from app.channels.types import TenantContext
from app.models import AppUser, ChannelIdentity, McpAccessGrant


McpScope = Literal["read", "full"]
MCP_SCOPES: frozenset[str] = frozenset({"read", "full"})
MCP_CHANNEL = "mcp"
MCP_ACCOUNT = "mcp"
_MAX_TOKEN_CHARS = 512
_MAX_LABEL_CHARS = 200
_MAX_CREATED_BY_CHARS = 128
_MAX_LIST_LIMIT = 100
_MAX_LIST_OFFSET = 1_000_000


class McpGrantError(ValueError):
    """Safe operator/authentication error with a stable public code."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class InvalidMcpScope(McpGrantError):
    def __init__(self) -> None:
        super().__init__("invalid_scope")


class McpGrantNotFound(McpGrantError):
    def __init__(self) -> None:
        # Listing/rotating by a random id intentionally gives no tenant or
        # existence detail to a transport caller.
        super().__init__("grant_not_found")


class InvalidMcpGrant(McpGrantError):
    def __init__(self) -> None:
        super().__init__("invalid_grant")


class InsufficientMcpScope(McpGrantError):
    def __init__(self) -> None:
        super().__init__("insufficient_scope")


@dataclass(frozen=True)
class McpGrantMetadata:
    grant_id: str
    app_user_id: int
    scope: McpScope
    expires_at: datetime | None
    revoked_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None
    rotated_at: datetime | None
    last_used_at: datetime | None
    label: str | None
    created_by: str | None

    @property
    def principal_id(self) -> str:
        return self.grant_id

    @classmethod
    def from_model(cls, grant: McpAccessGrant) -> "McpGrantMetadata":
        # The database check constraint guarantees this cast in PostgreSQL;
        # the explicit guard also makes SQLite/unit test fixtures fail closed.
        scope = grant.scope if grant.scope in MCP_SCOPES else "read"
        return cls(
            grant_id=grant.grant_id,
            app_user_id=grant.app_user_id,
            scope=scope,  # type: ignore[arg-type]
            expires_at=grant.expires_at,
            revoked_at=grant.revoked_at,
            disabled_at=grant.disabled_at,
            created_at=grant.created_at,
            updated_at=grant.updated_at,
            rotated_at=grant.rotated_at,
            last_used_at=grant.last_used_at,
            label=grant.label,
            created_by=grant.created_by,
        )

    def model_dump(self) -> dict:
        return {
            "grant_id": self.grant_id,
            "app_user_id": self.app_user_id,
            "scope": self.scope,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "disabled_at": self.disabled_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rotated_at": self.rotated_at,
            "last_used_at": self.last_used_at,
            "label": self.label,
            "created_by": self.created_by,
        }


@dataclass(frozen=True)
class IssuedMcpGrant:
    metadata: McpGrantMetadata
    raw_token: str

    @property
    def grant_id(self) -> str:
        return self.metadata.grant_id

    @property
    def token(self) -> str:
        """One-time bearer material (never included in metadata/list output)."""

        return self.raw_token


@dataclass(frozen=True)
class ResolvedMcpGrant:
    metadata: McpGrantMetadata
    tenant: TenantContext

    @property
    def grant_id(self) -> str:
        return self.metadata.grant_id

    @property
    def scope(self) -> McpScope:
        return self.metadata.scope


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _token_hash(raw_token: str) -> str:
    normalized = raw_token.strip()
    if not normalized or len(normalized) > _MAX_TOKEN_CHARS:
        raise InvalidMcpGrant()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _new_token() -> str:
    # token_urlsafe(32) carries 256 bits of entropy before encoding/prefixing.
    return "mcp_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _validate_scope(scope: str) -> McpScope:
    if scope not in MCP_SCOPES:
        raise InvalidMcpScope()
    return scope  # type: ignore[return-value]


def _validate_expiry(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        raise McpGrantError("invalid_expiry")
    return expires_at.astimezone(UTC)


def _validate_label(label: str | None) -> str | None:
    if label is None:
        return None
    if not isinstance(label, str):
        raise McpGrantError("invalid_label")
    value = " ".join(label.split())
    if len(value) > _MAX_LABEL_CHARS or any(ord(char) < 32 for char in value):
        raise McpGrantError("invalid_label")
    return value or None


def _validate_created_by(created_by: str | None) -> str | None:
    """Normalize the bounded operator/audit label stored on a grant.

    ``created_by`` is operator metadata, not a transport identity.  Keeping
    it bounded and rejecting non-text values prevents an unbounded CLI or
    environment value from being persisted into a text column and returned
    by the grant-management commands.
    """

    if created_by is None:
        return None
    if not isinstance(created_by, str):
        raise McpGrantError("invalid_created_by")
    value = " ".join(created_by.split())
    if len(value) > _MAX_CREATED_BY_CHARS or any(ord(char) < 32 for char in value):
        raise McpGrantError("invalid_created_by")
    return value or None


class McpGrantService:
    """Issue and resolve grants with explicit transaction ownership."""

    def __init__(
        self,
        session_factory,
        *,
        account_id: str = MCP_ACCOUNT,
        channel: str = MCP_CHANNEL,
    ) -> None:
        self._session_factory = session_factory
        self.account_id = account_id
        self.channel = channel

    def issue(
        self,
        app_user_id: int,
        *,
        scope: McpScope = "read",
        expires_at: datetime | None = None,
        label: str | None = None,
        created_by: str | None = None,
    ) -> IssuedMcpGrant:
        scope = _validate_scope(scope)
        expires_at = _validate_expiry(expires_at)
        label = _validate_label(label)
        created_by = _validate_created_by(created_by)
        raw = _new_token()
        grant_id = uuid4().hex
        with self._session_factory() as db:
            tenant = ensure_explicit_identity(
                db,
                app_user_id=app_user_id,
                channel=self.channel,
                account_id=self.account_id,
                external_user_id=grant_id,
            )
            grant = McpAccessGrant(
                grant_id=grant_id,
                app_user_id=tenant.app_user_id,
                token_hash=_token_hash(raw),
                scope=scope,
                expires_at=expires_at,
                label=label,
                created_by=created_by,
            )
            if getattr(getattr(db, "bind", None), "dialect", None) is not None and db.bind.dialect.name == "sqlite":
                grant.id = int(db.scalar(select(func.max(McpAccessGrant.id))) or 0) + 1
            db.add(grant)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # A 256-bit token or UUID collision is practically impossible;
                # expose a stable operational error rather than raw SQL.
                raise McpGrantError("grant_issue_failed") from None
            db.refresh(grant)
            return IssuedMcpGrant(McpGrantMetadata.from_model(grant), raw)

    issue_grant = issue

    def resolve(
        self,
        raw_token: str,
        *,
        required_scope: str | None = None,
        now: datetime | None = None,
    ) -> ResolvedMcpGrant:
        if required_scope is not None:
            _validate_scope(required_scope)
        try:
            digest = _token_hash(raw_token)
        except McpGrantError:
            raise InvalidMcpGrant() from None
        current = _utc(now) or datetime.now(UTC)
        with self._session_factory() as db:
            grant = db.scalar(
                select(McpAccessGrant).where(McpAccessGrant.token_hash == digest)
            )
            if grant is None or not hmac.compare_digest(grant.token_hash, digest):
                raise InvalidMcpGrant()
            if grant.revoked_at is not None or grant.disabled_at is not None:
                raise InvalidMcpGrant()
            expiry = _utc(grant.expires_at)
            if expiry is not None and expiry <= current:
                raise InvalidMcpGrant()
            if grant.scope not in MCP_SCOPES:
                raise InvalidMcpGrant()
            if required_scope == "full" and grant.scope != "full":
                raise InsufficientMcpScope()
            identity = db.scalar(
                select(ChannelIdentity).where(
                    ChannelIdentity.channel == self.channel,
                    ChannelIdentity.account_id == self.account_id,
                    ChannelIdentity.external_user_id == grant.grant_id,
                )
            )
            user = db.get(AppUser, grant.app_user_id)
            if (
                identity is None
                or identity.app_user_id != grant.app_user_id
                or identity.disabled_at is not None
                or user is None
                or user.disabled_at is not None
            ):
                raise InvalidMcpGrant()
            # last_used_at is audit metadata only; a failed audit write must
            # never turn a valid request into an application failure.
            try:
                grant.last_used_at = current
                grant.updated_at = current
                db.commit()
            except Exception:
                db.rollback()
            tenant = TenantContext(
                app_user_id=user.id,
                channel_identity_id=identity.id,
                channel=identity.channel,
                account_id=identity.account_id,
                external_user_id=identity.external_user_id,
            )
            return ResolvedMcpGrant(McpGrantMetadata.from_model(grant), tenant)

    resolve_token = resolve

    def _get(self, db: Session, grant_id: str) -> McpAccessGrant:
        grant = db.scalar(
            select(McpAccessGrant).where(McpAccessGrant.grant_id == str(grant_id))
        )
        if grant is None:
            raise McpGrantNotFound()
        return grant

    def rotate(
        self,
        grant_id: str,
        *,
        expires_at: datetime | None = None,
    ) -> IssuedMcpGrant:
        expires_at = _validate_expiry(expires_at)
        raw = _new_token()
        now = datetime.now(UTC)
        with self._session_factory() as db:
            grant = db.scalar(
                select(McpAccessGrant)
                .where(McpAccessGrant.grant_id == str(grant_id))
                .with_for_update()
            )
            if grant is None:
                raise McpGrantNotFound()
            if grant.revoked_at is not None or grant.disabled_at is not None:
                raise McpGrantError("grant_disabled")
            grant.token_hash = _token_hash(raw)
            grant.expires_at = expires_at
            grant.rotated_at = now
            grant.updated_at = now
            db.commit()
            db.refresh(grant)
            return IssuedMcpGrant(McpGrantMetadata.from_model(grant), raw)

    rotate_grant = rotate

    def revoke(self, grant_id: str) -> McpGrantMetadata:
        now = datetime.now(UTC)
        with self._session_factory() as db:
            grant = self._get(db, grant_id)
            grant.revoked_at = grant.revoked_at or now
            grant.updated_at = now
            db.commit()
            db.refresh(grant)
            return McpGrantMetadata.from_model(grant)

    revoke_grant = revoke

    def disable(self, grant_id: str) -> McpGrantMetadata:
        now = datetime.now(UTC)
        with self._session_factory() as db:
            grant = self._get(db, grant_id)
            grant.disabled_at = grant.disabled_at or now
            grant.updated_at = now
            db.commit()
            db.refresh(grant)
            return McpGrantMetadata.from_model(grant)

    disable_grant = disable

    def get(self, grant_id: str) -> McpGrantMetadata:
        with self._session_factory() as db:
            return McpGrantMetadata.from_model(self._get(db, grant_id))

    def list(
        self,
        *,
        app_user_id: int | None = None,
        limit: int = _MAX_LIST_LIMIT,
        offset: int = 0,
    ) -> list[McpGrantMetadata]:
        """Return a bounded page of grant metadata (never raw token material)."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIST_LIMIT:
            raise McpGrantError("invalid_limit")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or not 0 <= offset <= _MAX_LIST_OFFSET
        ):
            raise McpGrantError("invalid_offset")
        with self._session_factory() as db:
            statement = select(McpAccessGrant).order_by(McpAccessGrant.created_at.desc(), McpAccessGrant.id.desc())
            if app_user_id is not None:
                statement = statement.where(McpAccessGrant.app_user_id == app_user_id)
            statement = statement.offset(offset).limit(limit)
            return [McpGrantMetadata.from_model(item) for item in db.scalars(statement)]

    list_grants = list


# Alternate spelling retained for integrations/tests that use the acronym as
# a class prefix.
MCPGrantService = McpGrantService
MCPGrantError = McpGrantError
