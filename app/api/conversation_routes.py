"""Compatibility conversation and channel-link routes for the canonical app.

The browser application owns authentication and CSRF enforcement in
``app.api.app``.  This module only adapts the existing channel/link services
to that application; it does not define a second cookie, session, or origin
boundary.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Callable, Protocol
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, Security
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.agent.types import AgentAnswer
from app.channels.errors import IdentityError
from app.channels.identity import consume_link_token, create_link_token
from app.channels.service import _link_failure
from app.api.library_schemas import ErrorResponse
from app.channels.types import ChannelEnvelope, TenantContext
from app.models import AppUser, ChannelIdentity
from app.web.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.web_auth import AuthenticatedWebSession


_MAX_CONVERSATION_ID = 128
_MAX_MESSAGE_ID = 128
_MAX_MESSAGE_TEXT = 16_000
_PRIVATE_RESULT_KEYS = frozenset(
    {
        "id",
        "item_id",
        "segment_id",
        "app_user_id",
        "channel_identity_id",
        "session_id",
        "tenant_id",
    }
)

_SESSION_COOKIE_SCHEMA = APIKeyCookie(
    name="__Host-kb_session",
    scheme_name="SessionCookie",
    auto_error=False,
)
CsrfHeader = Annotated[
    str,
    Header(alias="X-CSRF-Token", min_length=1, max_length=200),
]


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=_MAX_MESSAGE_ID)
    text: str = Field(min_length=1, max_length=_MAX_MESSAGE_TEXT)


class LinkTokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_channel: str = Field(min_length=1, max_length=32)


class ConsumeLinkTokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=128)


class LinkTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str


class LinkedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linked: bool = True


class ConversationCitationResponse(BaseModel):
    """Browser-safe citation projection without internal row identifiers."""

    model_config = ConfigDict(extra="forbid")

    title: str
    excerpt: str
    url: str
    start_sec: float | None = None


class ConversationResponse(BaseModel):
    """Stable compatibility response for the retained conversation surface."""

    model_config = ConfigDict(extra="forbid")

    status: str
    text: str
    citations: list[ConversationCitationResponse] = Field(default_factory=list)
    action_results: list[dict] = Field(default_factory=list)
    thread_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class BrowserSessionIdentity:
    """Public identity projection used by retained browser channel routes.

    The email session implementation exposes a :class:`TenantContext`, while
    the migration-era channel session exposes only ``app_user_id`` and
    ``login_channel``.  Keeping the identity projection explicit prevents the
    route from accidentally treating an internal numeric id as an external
    channel principal.
    """

    app_user_id: int
    external_user_id: str
    tenant: TenantContext


class BrowserSessionIdentityResolver(Protocol):
    def __call__(self, session: object) -> BrowserSessionIdentity: ...


def resolve_browser_session_identity(
    session: object,
    session_factory: Callable | None,
) -> BrowserSessionIdentity:
    """Adapt either canonical email or legacy channel sessions.

    Email sessions carry their already-validated tenant directly.  Legacy
    sessions deliberately do not, so resolve the channel identity server-side
    using the session's app user and login channel.  The query is deterministic
    and rejects disabled/missing identities rather than falling back to an
    internal id.
    """

    tenant = getattr(session, "tenant", None)
    if isinstance(tenant, TenantContext):
        return BrowserSessionIdentity(
            app_user_id=tenant.app_user_id,
            external_user_id=tenant.external_user_id,
            tenant=tenant,
        )

    app_user_id = getattr(session, "app_user_id", None)
    login_channel = str(getattr(session, "login_channel", "")).strip().lower()
    if (
        isinstance(app_user_id, bool)
        or not isinstance(app_user_id, int)
        or app_user_id <= 0
        or not login_channel
        or session_factory is None
    ):
        raise ValueError("browser session identity is unavailable")

    with session_factory() as db:
        user = db.get(AppUser, app_user_id)
        identity = db.scalar(
            select(ChannelIdentity)
            .where(
                ChannelIdentity.app_user_id == app_user_id,
                ChannelIdentity.channel == login_channel,
                ChannelIdentity.disabled_at.is_(None),
            )
            .order_by(ChannelIdentity.id)
        )
        if (
            user is None
            or user.disabled_at is not None
            or identity is None
            or identity.app_user_id != user.id
        ):
            raise ValueError("browser session identity is unavailable")
        resolved_tenant = TenantContext(
            app_user_id=user.id,
            channel_identity_id=identity.id,
            channel=identity.channel,
            account_id=identity.account_id,
            external_user_id=identity.external_user_id,
        )
    return BrowserSessionIdentity(
        app_user_id=resolved_tenant.app_user_id,
        external_user_id=resolved_tenant.external_user_id,
        tenant=resolved_tenant,
    )


def build_conversation_router(
    *,
    channel_service,
    session_dependency: Callable,
    session_factory,
    settings,
    session_identity_resolver: BrowserSessionIdentityResolver | None = None,
) -> APIRouter:
    """Build retained conversation/link routes behind canonical auth.

    ``channel_service`` may be ``None`` for API-only compositions such as the
    OpenAPI exporter.  The routes remain documented but fail closed with a
    bounded ``request_failed`` response until a service is configured.
    """

    router = APIRouter(prefix="/api/v1", tags=["conversation"])

    def authenticated_session(
        request: Request,
        _session_cookie: str | None = Security(_SESSION_COOKIE_SCHEMA),
    ) -> AuthenticatedWebSession:
        # The canonical application owns cookie parsing and session
        # resolution.  The wrapper exists only to document the shared cookie
        # security scheme on these compatibility operations.
        return session_dependency(request)

    def service_or_unavailable():
        if channel_service is None or session_factory is None:
            raise HTTPException(status_code=503, detail="request_failed")
        return channel_service

    def browser_identity(session: object) -> BrowserSessionIdentity:
        if session_identity_resolver is not None:
            resolved = session_identity_resolver(session)
            if isinstance(resolved, BrowserSessionIdentity):
                return resolved
            # A resolver supplied by a small embedding may return the
            # canonical tenant directly; normalize it at this boundary.
            if isinstance(resolved, TenantContext):
                return BrowserSessionIdentity(
                    app_user_id=resolved.app_user_id,
                    external_user_id=resolved.external_user_id,
                    tenant=resolved,
                )
            raise ValueError("browser session identity resolver returned an invalid value")
        return resolve_browser_session_identity(session, session_factory)

    def project_answer(answer: AgentAnswer) -> ConversationResponse:
        return ConversationResponse(
            status=answer.status,
            text=answer.text,
            citations=[
                ConversationCitationResponse(
                    title=citation.title,
                    excerpt=citation.excerpt,
                    url=citation.url,
                    start_sec=citation.start_sec,
                )
                for citation in answer.citations
            ],
            action_results=[_safe_result(value) for value in answer.action_results],
            thread_id=answer.thread_id,
            error_code=answer.error_code,
        )

    def _safe_result(value):
        if isinstance(value, dict):
            return {
                key: _safe_result(item)
                for key, item in value.items()
                if key not in _PRIVATE_RESULT_KEYS
            }
        if isinstance(value, list):
            return [_safe_result(item) for item in value]
        return value

    def web_envelope(
        session: object,
        conversation_id: str,
        message_id: str,
        text: str,
    ) -> ChannelEnvelope:
        identity = browser_identity(session)
        tenant = identity.tenant
        return ChannelEnvelope(
            tenant.channel,
            tenant.account_id,
            tenant.external_user_id,
            conversation_id,
            message_id,
            text,
            request_id=uuid4().hex,
        )

    @router.post(
        "/conversations/{conversation_id}/messages",
        response_model=ConversationResponse,
        responses={
            401: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    async def send_message(
        conversation_id: str,
        payload: MessageInput,
        _csrf_token: CsrfHeader,
        session: object = Depends(authenticated_session),
    ) -> ConversationResponse:
        channel = service_or_unavailable()
        if not 1 <= len(conversation_id.strip()) <= _MAX_CONVERSATION_ID:
            raise HTTPException(status_code=422, detail="validation_error")
        try:
            answer = await asyncio.wait_for(
                channel.handle(
                    web_envelope(
                        session,
                        conversation_id,
                        payload.message_id,
                        payload.text,
                    )
                ),
                timeout=float(getattr(settings, "agent_timeout_seconds", 30.0)),
            )
        except TimeoutError:
            raise HTTPException(status_code=504, detail="request_failed") from None
        return project_answer(answer)

    @router.post(
        "/conversations/{conversation_id}/reset",
        response_model=ConversationResponse,
        responses={
            401: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    async def reset_conversation(
        conversation_id: str,
        _csrf_token: CsrfHeader,
        session: object = Depends(authenticated_session),
    ) -> ConversationResponse:
        channel = service_or_unavailable()
        if not 1 <= len(conversation_id.strip()) <= _MAX_CONVERSATION_ID:
            raise HTTPException(status_code=422, detail="validation_error")
        answer = await channel.handle(
            web_envelope(
                session,
                conversation_id,
                f"web-reset-{uuid4().hex}",
                "/new",
            )
        )
        return project_answer(answer)

    @router.post(
        "/link-tokens",
        response_model=LinkTokenResponse,
        responses={
            401: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    def create_token(
        payload: LinkTokenInput,
        _csrf_token: CsrfHeader,
        session: object = Depends(authenticated_session),
    ) -> LinkTokenResponse:
        service_or_unavailable()
        target = payload.target_channel.strip().lower()
        if target not in {"telegram", "wechat"}:
            raise HTTPException(status_code=422, detail="validation_error")
        try:
            with session_factory() as db:
                token = create_link_token(
                    db,
                    browser_identity(session).tenant,
                    target_channel=target,
                    ttl=timedelta(
                        seconds=float(
                            getattr(settings, "channel_link_ttl_seconds", 600)
                        )
                    ),
                )
                db.commit()
        except IdentityError as exc:
            raise HTTPException(
                status_code=409, detail=_link_failure(exc).error_code
            ) from None
        return LinkTokenResponse(token=token)

    @router.post(
        "/link-tokens/consume",
        response_model=LinkedResponse,
        responses={
            401: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    def consume_token(
        payload: ConsumeLinkTokenInput,
        _csrf_token: CsrfHeader,
        response: Response,
        session: object = Depends(authenticated_session),
    ) -> LinkedResponse:
        service_or_unavailable()
        envelope = web_envelope(session, "web-link", f"web-link-{uuid4().hex}", "")
        try:
            with session_factory() as db:
                consume_link_token(db, envelope, payload.token)
                db.commit()
        except IdentityError as exc:
            raise HTTPException(
                status_code=409, detail=_link_failure(exc).error_code
            ) from None
        # Linking may absorb the presenting tenant; do not retain its session.
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie(
            CSRF_COOKIE_NAME,
            path="/",
            secure=True,
            httponly=False,
            samesite="lax",
        )
        return LinkedResponse()

    return router


__all__ = [
    "ConsumeLinkTokenInput",
    "ConversationCitationResponse",
    "ConversationResponse",
    "LinkTokenInput",
    "LinkTokenResponse",
    "LinkedResponse",
    "MessageInput",
    "BrowserSessionIdentity",
    "BrowserSessionIdentityResolver",
    "build_conversation_router",
    "resolve_browser_session_identity",
]
