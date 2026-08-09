"""Same-origin HTTP adapter for Web email login and conversations.

MCP is deliberately not mounted into FastAPI: it retains its bearer middleware
and official SDK app behind a tiny path dispatcher in ``create_combined_asgi_app``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.agent.types import AgentAnswer
from app.bootstrap import build_channel_service
from app.channels.errors import IdentityError
from app.channels.identity import consume_link_token, create_link_token
from app.channels.service import _link_failure
from app.channels.types import ChannelEnvelope
from app.config import Settings, get_settings
from app.db import get_session_factory
from app.web_auth import (
    AuthenticatedWebSession,
    EmailDeliveryUnavailable,
    InMemoryEmailSender,
    InMemoryLoginRateLimiter,
    InvalidEmail,
    InvalidSession,
    InvalidVerification,
    LoginRateLimited,
    RedisLoginRateLimiter,
    ResendEmailSender,
    SmtpEmailSender,
    WEB_ACCOUNT_ID,
    WEB_CHANNEL,
    WebAuthService,
    build_email_auth_service,
)


SESSION_COOKIE_NAME = "__Host-notebook-agent-session"
_MAX_CONVERSATION_ID = 128
_MAX_MESSAGE_ID = 128
_MAX_MESSAGE_TEXT = 16_000


class ChallengeInput(BaseModel):
    email: str = Field(max_length=254)


class VerifyInput(ChallengeInput):
    code: str = Field(min_length=6, max_length=6)


class MessageInput(BaseModel):
    message_id: str = Field(min_length=1, max_length=_MAX_MESSAGE_ID)
    text: str = Field(min_length=1, max_length=_MAX_MESSAGE_TEXT)


class LinkTokenInput(BaseModel):
    target_channel: str = Field(min_length=1, max_length=32)


class ConsumeLinkTokenInput(BaseModel):
    token: str = Field(min_length=1, max_length=128)


def build_web_auth_service(settings: Settings, session_factory=None) -> WebAuthService:
    return build_email_auth_service(settings, session_factory)


def create_web_api(
    *,
    settings: Settings | None = None,
    auth_service: WebAuthService | None = None,
    channel_service=None,
) -> FastAPI:
    settings = settings or get_settings()
    auth_service = auth_service or build_web_auth_service(settings)
    channel_service = channel_service or build_channel_service(settings)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def require_origin(request: Request) -> None:
        if request.headers.get("origin") != settings.web_public_origin:
            raise HTTPException(status_code=403, detail="origin_forbidden")
        content_type = request.headers.get("content-type", "")
        # DELETE intentionally has no request payload, while every POST must
        # carry JSON so browsers cannot issue state changes via form submits.
        if request.method == "POST" and not content_type.lower().startswith("application/json"):
            raise HTTPException(status_code=415, detail="json_required")

    def client_ip(request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        trusted = {value.strip() for value in settings.web_trusted_proxy_hosts.split(",") if value.strip()}
        if peer in trusted:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                return forwarded[:128]
        return peer[:128]

    async def current_session(request: Request) -> AuthenticatedWebSession:
        raw = request.cookies.get(SESSION_COOKIE_NAME)
        if not raw:
            raise HTTPException(status_code=401, detail="authentication_required")
        try:
            return auth_service.resolve_session(raw)
        except InvalidSession:
            raise HTTPException(status_code=401, detail="authentication_required") from None

    def session_projection(session: AuthenticatedWebSession) -> dict:
        return {"authenticated": True, "session_id": session.session_id, "expires_at": session.expires_at, "tenant": {"id": session.tenant.app_user_id}}

    def set_session_cookie(response: Response, raw_token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE_NAME, raw_token, max_age=settings.web_session_ttl_seconds,
            path="/", secure=True, httponly=True, samesite="lax",
        )

    @app.post(f"{settings.web_api_prefix}/auth/challenges")
    async def request_challenge(payload: ChallengeInput, request: Request) -> dict:
        require_origin(request)
        try:
            auth_service.request_challenge(payload.email, client_ip(request))
        except InvalidEmail:
            raise HTTPException(status_code=422, detail="invalid_email") from None
        except LoginRateLimited:
            # Identical accepted projection avoids turning the send endpoint
            # into an account or rate-limit oracle.
            pass
        except EmailDeliveryUnavailable:
            raise HTTPException(status_code=503, detail="email_delivery_unavailable") from None
        return {"status": "accepted"}

    @app.post(f"{settings.web_api_prefix}/auth/verify")
    async def verify(payload: VerifyInput, request: Request, response: Response) -> dict:
        require_origin(request)
        try:
            verified = auth_service.verify(payload.email, payload.code)
        except (InvalidEmail, InvalidVerification):
            raise HTTPException(status_code=401, detail="verification_failed") from None
        set_session_cookie(response, verified.raw_session_token)
        return session_projection(verified.session)

    @app.get(f"{settings.web_api_prefix}/session")
    async def get_session(session: AuthenticatedWebSession = Depends(current_session)) -> dict:
        return session_projection(session)

    @app.delete(f"{settings.web_api_prefix}/session", status_code=204)
    async def delete_session(request: Request, session: AuthenticatedWebSession = Depends(current_session)) -> Response:
        require_origin(request)
        raw = request.cookies.get(SESSION_COOKIE_NAME)
        if raw:
            auth_service.revoke_session(raw)
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
        return response

    def web_envelope(session: AuthenticatedWebSession, conversation_id: str, message_id: str, text: str) -> ChannelEnvelope:
        return ChannelEnvelope(WEB_CHANNEL, "web", session.tenant.external_user_id, conversation_id, message_id, text, request_id=uuid4().hex)

    @app.post(f"{settings.web_api_prefix}/conversations/{{conversation_id}}/messages")
    async def send_message(conversation_id: str, payload: MessageInput, request: Request, session: AuthenticatedWebSession = Depends(current_session)) -> dict:
        require_origin(request)
        if not 1 <= len(conversation_id.strip()) <= _MAX_CONVERSATION_ID:
            raise HTTPException(status_code=422, detail="invalid_conversation_id")
        try:
            answer: AgentAnswer = await asyncio.wait_for(
                channel_service.handle(web_envelope(session, conversation_id, payload.message_id, payload.text)),
                timeout=settings.agent_timeout_seconds,
            )
        except TimeoutError:
            raise HTTPException(status_code=504, detail="agent_timeout") from None
        return answer.model_dump(mode="json")

    @app.post(f"{settings.web_api_prefix}/conversations/{{conversation_id}}/reset")
    async def reset_conversation(conversation_id: str, request: Request, session: AuthenticatedWebSession = Depends(current_session)) -> dict:
        require_origin(request)
        if not 1 <= len(conversation_id.strip()) <= _MAX_CONVERSATION_ID:
            raise HTTPException(status_code=422, detail="invalid_conversation_id")
        answer: AgentAnswer = await channel_service.handle(web_envelope(session, conversation_id, f"web-reset-{uuid4().hex}", "/new"))
        return answer.model_dump(mode="json")

    @app.post(f"{settings.web_api_prefix}/link-tokens")
    async def create_token(payload: LinkTokenInput, request: Request, session: AuthenticatedWebSession = Depends(current_session)) -> dict:
        require_origin(request)
        if payload.target_channel.strip().lower() not in {"telegram", "wechat"}:
            raise HTTPException(status_code=422, detail="link_channel_unsupported")
        try:
            with auth_service._session_factory() as db:  # same transaction owner as identity linking
                token = create_link_token(
                    db, session.tenant, target_channel=payload.target_channel,
                    ttl=timedelta(seconds=settings.channel_link_ttl_seconds),
                )
                db.commit()
        except IdentityError as exc:
            raise HTTPException(status_code=409, detail=_link_failure(exc).error_code) from None
        return {"token": token}

    @app.post(f"{settings.web_api_prefix}/link-tokens/consume")
    async def consume_token(payload: ConsumeLinkTokenInput, request: Request, response: Response, session: AuthenticatedWebSession = Depends(current_session)) -> dict:
        require_origin(request)
        envelope = web_envelope(session, "web-link", f"web-link-{uuid4().hex}", "")
        try:
            with auth_service._session_factory() as db:
                consume_link_token(db, envelope, payload.token)
                db.commit()
        except IdentityError as exc:
            raise HTTPException(status_code=409, detail=_link_failure(exc).error_code) from None
        # The presenting tenant was absorbed, so this credential must not be
        # retained in the browser even before its next authenticated request.
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
        return {"linked": True}

    return app


class CombinedASGIApp:
    def __init__(self, web_app, mcp_app, mcp_path: str) -> None:
        self.web_app, self.mcp_app, self.mcp_path = web_app, mcp_app, mcp_path

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self.mcp_app(scope, receive, send)
            return
        path = scope.get("path", "")
        target = self.mcp_app if path == self.mcp_path or path.startswith(self.mcp_path + "/") else self.web_app
        await target(scope, receive, send)


def create_combined_asgi_app(*, mcp_app, settings: Settings | None = None, web_app=None):
    settings = settings or get_settings()
    return CombinedASGIApp(web_app or create_web_api(settings=settings), mcp_app, settings.mcp_path)


# Kept as the composition-root spelling used by ``app.web_runtime`` and
# embedding tests.  The session factory is injectable so ASGI tests can use
# isolated SQLite fixtures without changing global application configuration.
def create_web_app(*, settings: Settings | None = None, session_factory=None, channel_service=None, auth_service: WebAuthService | None = None) -> FastAPI:
    settings = settings or get_settings()
    auth_service = auth_service or build_web_auth_service(settings, session_factory)
    return create_web_api(settings=settings, auth_service=auth_service, channel_service=channel_service)
