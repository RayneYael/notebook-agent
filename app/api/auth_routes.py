"""Narrow FastAPI router for same-origin Web authentication."""

from __future__ import annotations

import hmac
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Header, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.api.auth_schemas import (
    AuthErrorResponse,
    ChallengeCreateRequest,
    ChallengeCreateResponse,
    ChallengeReferenceRequest,
    ChallengeStatusResponse,
    SessionResponse,
)
from app.web.auth import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    LoginChallengeCredentials,
    LoginChallengeStatus,
    ResolvedWebSession,
    WebAuthError,
    WebSessionCredentials,
)


class WebAuthBoundary(Protocol):
    def create_challenge(
        self, target_channel: str, *, requester_key: str
    ) -> LoginChallengeCredentials: ...

    def status(
        self, public_id: str, browser_secret: str
    ) -> LoginChallengeStatus: ...

    def exchange(
        self, public_id: str, browser_secret: str
    ) -> WebSessionCredentials: ...

    def resolve_session(self, session_token: str) -> ResolvedWebSession: ...

    def validate_csrf(self, session_token: str, csrf_token: str) -> None: ...

    def revoke_session(self, session_token: str) -> None: ...


_session_cookie_schema = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    scheme_name="SessionCookie",
    auto_error=False,
)
_browser_secret_schema = HTTPBearer(
    scheme_name="BrowserSecret",
    auto_error=False,
)
SessionCookieDocument = Annotated[
    str | None,
    Security(_session_cookie_schema),
]
BrowserSecretDocument = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(_browser_secret_schema),
]
CsrfHeader = Annotated[
    str | None,
    Header(alias="X-CSRF-Token", max_length=200),
]


class _SafeValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={
                        "code": "validation_error",
                        "message": "请求参数无效。",
                    },
                )

        return safe_handler


def build_auth_router(
    web_auth: WebAuthBoundary,
    *,
    expected_origin: str,
    cookie_secure: bool,
) -> APIRouter:
    """Build an injectable router without owning the application lifecycle."""

    origin = str(expected_origin).strip()
    if not origin or origin.endswith("/"):
        raise ValueError("expected_origin must be an exact origin without a slash")

    router = APIRouter(
        prefix="/api/v1/auth",
        tags=["authentication"],
        route_class=_SafeValidationRoute,
        responses={422: {"model": AuthErrorResponse}},
    )

    @router.post(
        "/challenges",
        response_model=ChallengeCreateResponse,
        status_code=201,
        responses={
            400: {"model": AuthErrorResponse},
            429: {"model": AuthErrorResponse},
        },
    )
    def create_challenge(
        payload: ChallengeCreateRequest, request: Request
    ) -> Response:
        if error := _same_origin_error(request, origin):
            return error
        try:
            requester_key = request.client.host if request.client else "unknown"
            challenge = web_auth.create_challenge(
                payload.target_channel,
                requester_key=requester_key,
            )
        except WebAuthError as exc:
            return _auth_error(exc)
        response = ChallengeCreateResponse(
            public_id=challenge.public_id,
            command=f"/web-login {challenge.code}",
            browser_secret=challenge.browser_secret,
            target_channel=cast(
                "Literal['telegram', 'wechat']", challenge.target_channel
            ),
            expires_at=challenge.expires_at,
        )
        return _json(response, status_code=201)

    @router.post(
        "/challenges/status",
        response_model=ChallengeStatusResponse,
        responses={
            202: {"model": ChallengeStatusResponse},
            401: {"model": AuthErrorResponse},
            410: {"model": AuthErrorResponse},
        },
    )
    def challenge_status(
        payload: ChallengeReferenceRequest,
        request: Request,
        _browser_secret_document: BrowserSecretDocument,
    ) -> Response:
        if error := _same_origin_error(request, origin):
            return error
        try:
            secret = _bearer_secret(request)
            result = web_auth.status(payload.public_id, secret)
        except WebAuthError as exc:
            return _auth_error(exc)
        if result.status == "expired":
            return _auth_error(WebAuthError("challenge_expired"))
        if result.status == "consumed":
            return _auth_error(WebAuthError("challenge_used"))
        if result.status == "cancelled":
            return _auth_error(WebAuthError("challenge_invalid"), status_code=410)
        status = cast("Literal['pending', 'approved']", result.status)
        response = ChallengeStatusResponse(
            status=status, expires_at=result.expires_at
        )
        return _json(response, status_code=202 if status == "pending" else 200)

    @router.post(
        "/sessions",
        response_model=SessionResponse,
        status_code=201,
        responses={
            202: {"model": AuthErrorResponse},
            401: {"model": AuthErrorResponse},
            410: {"model": AuthErrorResponse},
        },
    )
    def exchange_session(
        payload: ChallengeReferenceRequest,
        request: Request,
        _browser_secret_document: BrowserSecretDocument,
    ) -> Response:
        if error := _same_origin_error(request, origin):
            return error
        try:
            browser_secret = _bearer_secret(request)
            credentials = web_auth.exchange(payload.public_id, browser_secret)
            resolved = web_auth.resolve_session(credentials.session_token)
        except WebAuthError as exc:
            return _auth_error(exc)
        response = _json(
            _session_response(resolved),
            status_code=201,
        )
        _set_session_cookies(response, credentials, secure=cookie_secure)
        return response

    @router.get(
        "/session",
        response_model=SessionResponse,
        responses={401: {"model": AuthErrorResponse}},
    )
    def current_session(
        request: Request,
        _session_cookie_document: SessionCookieDocument,
    ) -> Response:
        try:
            token = _session_cookie(request)
            resolved = web_auth.resolve_session(token)
        except WebAuthError as exc:
            return _auth_error(exc)
        return _json(_session_response(resolved), status_code=200)

    @router.delete(
        "/session",
        status_code=204,
        responses={
            401: {"model": AuthErrorResponse},
            403: {"model": AuthErrorResponse},
        },
    )
    def logout(
        request: Request,
        _session_cookie_document: SessionCookieDocument,
        _csrf_token: CsrfHeader = None,
    ) -> Response:
        if error := _same_origin_error(request, origin):
            return error
        try:
            session_token = _session_cookie(request)
            web_auth.resolve_session(session_token)
            cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME, "")
            header_csrf = request.headers.get("x-csrf-token", "")
            if (
                not cookie_csrf
                or not header_csrf
                or not hmac.compare_digest(cookie_csrf, header_csrf)
            ):
                raise WebAuthError("csrf_invalid")
            web_auth.validate_csrf(session_token, header_csrf)
            web_auth.revoke_session(session_token)
        except WebAuthError as exc:
            return _auth_error(exc)
        response = Response(status_code=204)
        _delete_session_cookies(response, secure=cookie_secure)
        return response

    return router


def _bearer_secret(request: Request) -> str:
    value = request.headers.get("authorization", "")
    parts = value.split()
    if (
        len(parts) != 2
        or parts[0].lower() != "bearer"
        or not parts[1]
        or len(parts[1]) > 200
    ):
        raise WebAuthError("challenge_invalid")
    return parts[1]


def _same_origin_error(
    request: Request, expected_origin: str
) -> JSONResponse | None:
    if (
        request.headers.get("origin") != expected_origin
        or request.headers.get("sec-fetch-site") != "same-origin"
    ):
        return _auth_error(WebAuthError("csrf_invalid"))
    return None


def _session_cookie(request: Request) -> str:
    value = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not value or len(value) > 200:
        raise WebAuthError("session_invalid")
    return value


def _session_response(session: ResolvedWebSession) -> SessionResponse:
    return SessionResponse(
        login_channel=cast(
            "Literal['telegram', 'wechat']", session.login_channel
        ),
        expires_at=session.expires_at,
    )


def _set_session_cookies(
    response: Response,
    credentials: WebSessionCredentials,
    *,
    secure: bool,
) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        credentials.session_token,
        expires=credentials.expires_at,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        credentials.csrf_token,
        expires=credentials.expires_at,
        path="/",
        secure=secure,
        httponly=False,
        samesite="strict",
    )


def _delete_session_cookies(
    response: Response, *, secure: bool
) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        path="/",
        secure=secure,
        httponly=False,
        samesite="strict",
    )


def _auth_error(
    error: WebAuthError, *, status_code: int | None = None
) -> JSONResponse:
    status_by_code = {
        "challenge_pending": 202,
        "challenge_expired": 410,
        "challenge_used": 410,
        "challenge_invalid": 401,
        "session_invalid": 401,
        "account_disabled": 401,
        "csrf_invalid": 403,
        "channel_unavailable": 400,
        "rate_limited": 429,
    }
    safe_code = error.code if error.code in status_by_code else "request_failed"
    resolved_status = status_code or status_by_code.get(safe_code, 400)
    headers = None
    if resolved_status == 401:
        headers = {"WWW-Authenticate": "Bearer"}
    elif resolved_status == 429:
        headers = {"Retry-After": "60"}
    return JSONResponse(
        status_code=resolved_status,
        content=AuthErrorResponse(
            code=safe_code,
            message=str(error) if safe_code == error.code else "请求无法完成。",
        ).model_dump(),
        headers=headers,
    )


def _json(model: BaseModel, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=model.model_dump(mode="json"),
    )
