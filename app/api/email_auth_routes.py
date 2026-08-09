"""Email-code authentication routes for the same-origin Web API.

The upstream Web application keeps its library routes and session-cookie
boundary.  This router replaces only its channel-assisted login entry point;
it deliberately does not expose Telegram/WeChat login challenges.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.web.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, WebAuthError
from app.web_auth import (
    EmailDeliveryUnavailable,
    InvalidEmail,
    InvalidSession,
    InvalidVerification,
    LoginRateLimited,
)


class _StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailChallengeRequest(_StrictSchema):
    email: str = Field(min_length=3, max_length=254)


class EmailVerifyRequest(EmailChallengeRequest):
    code: str = Field(min_length=6, max_length=6)


class EmailSessionResponse(_StrictSchema):
    authenticated: bool = True
    expires_at: str
    tenant: dict[str, int]


CsrfHeader = Annotated[str | None, Header(alias="X-CSRF-Token", max_length=200)]


@dataclass(frozen=True)
class EmailResolvedSession:
    """Upstream library routes only require the authenticated tenant id."""

    app_user_id: int
    session_public_id: str
    login_channel: str
    expires_at: object


class EmailWebAuthAdapter:
    """Present email sessions through the Web API's established boundary."""

    def __init__(self, service) -> None:
        self._service = service

    def resolve_session(self, raw_token: str) -> EmailResolvedSession:
        try:
            session = self._service.resolve_session(raw_token)
        except InvalidSession:
            raise WebAuthError("session_invalid") from None
        return EmailResolvedSession(
            app_user_id=session.tenant.app_user_id,
            session_public_id=session.public_id,
            login_channel="email",
            expires_at=session.expires_at,
        )

    def validate_csrf(self, raw_token: str, raw_csrf_token: str) -> None:
        try:
            self._service.validate_csrf(raw_token, raw_csrf_token)
        except InvalidSession:
            raise WebAuthError("csrf_invalid") from None

    def revoke_session(self, raw_token: str) -> None:
        self._service.revoke_session(raw_token)


def build_email_auth_router(
    email_auth,
    *,
    expected_origin: str,
    cookie_secure: bool,
    trusted_proxy_hosts: str = "",
) -> APIRouter:
    """Build the email login API without registering a second ASGI app."""

    origin = str(expected_origin).strip()
    if not origin or origin.endswith("/"):
        raise ValueError("expected_origin must be an exact origin without a slash")
    router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
    trusted_proxies = {
        value.strip()
        for value in trusted_proxy_hosts.split(",")
        if value.strip()
    }

    def same_origin(request: Request) -> JSONResponse | None:
        if request.headers.get("origin") != origin:
            return _error("origin_forbidden", 403)
        return None

    def client_ip(request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        if peer in trusted_proxies:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0]
            if forwarded.strip():
                return forwarded.strip()[:128]
        return peer[:128]

    @router.post("/challenges", status_code=200)
    def request_challenge(payload: EmailChallengeRequest, request: Request) -> Response:
        if error := same_origin(request):
            return error
        try:
            email_auth.request_challenge(payload.email, client_ip(request))
        except InvalidEmail:
            return _error("invalid_email", 422)
        except LoginRateLimited:
            # The public projection intentionally stays indistinguishable.
            pass
        except EmailDeliveryUnavailable:
            return _error("email_delivery_unavailable", 503)
        return JSONResponse({"status": "accepted"}, status_code=200)

    @router.post("/verify", status_code=200)
    def verify(payload: EmailVerifyRequest, request: Request) -> Response:
        if error := same_origin(request):
            return error
        try:
            verified = email_auth.verify(payload.email, payload.code)
        except (InvalidEmail, InvalidVerification):
            return _error("verification_failed", 401)
        response = JSONResponse(
            EmailSessionResponse(
                expires_at=verified.session.expires_at.isoformat(),
                tenant={"id": verified.session.tenant.app_user_id},
            ).model_dump(),
            status_code=200,
        )
        _set_session_cookies(response, verified, secure=cookie_secure)
        return response

    @router.get("/session", status_code=200)
    def current_session(request: Request) -> Response:
        try:
            session = email_auth.resolve_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
        except InvalidSession:
            return _error("authentication_required", 401)
        return JSONResponse(
            EmailSessionResponse(
                expires_at=session.expires_at.isoformat(),
                tenant={"id": session.tenant.app_user_id},
            ).model_dump(),
            status_code=200,
        )

    @router.delete("/session", status_code=204)
    def logout(request: Request, _csrf: CsrfHeader = None) -> Response:
        if error := same_origin(request):
            return error
        raw_session = request.cookies.get(SESSION_COOKIE_NAME, "")
        cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_csrf = request.headers.get("x-csrf-token", "")
        if not cookie_csrf or not header_csrf or not hmac.compare_digest(
            cookie_csrf, header_csrf
        ):
            return _error("csrf_invalid", 403)
        try:
            email_auth.validate_csrf(raw_session, header_csrf)
            email_auth.revoke_session(raw_session)
        except InvalidSession:
            return _error("authentication_required", 401)
        response = Response(status_code=204)
        _delete_session_cookies(response, secure=cookie_secure)
        return response

    return router


def _set_session_cookies(response: Response, verified, *, secure: bool) -> None:
    expires = verified.session.expires_at
    response.set_cookie(
        SESSION_COOKIE_NAME,
        verified.raw_session_token,
        expires=expires,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        verified.raw_csrf_token,
        expires=expires,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def _delete_session_cookies(response: Response, *, secure: bool) -> None:
    for name, httponly in ((SESSION_COOKIE_NAME, True), (CSRF_COOKIE_NAME, False)):
        response.delete_cookie(
            name,
            path="/",
            secure=secure,
            httponly=httponly,
            samesite="lax",
        )


def _error(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status_code)
