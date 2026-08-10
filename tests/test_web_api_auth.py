from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.channels.types import UserScope
from app.api.auth_routes import build_auth_router
from app.web.auth import (
    LoginChallengeCredentials,
    LoginChallengeStatus,
    ResolvedWebSession,
    WebAuthError,
    WebSessionCredentials,
)


NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
ORIGIN = "https://kb.example.test"


class FakeWebAuth:
    def __init__(self):
        self.challenge_status = "pending"
        self.error_by_method = {}
        self.calls = []

    def _raise(self, method):
        code = self.error_by_method.get(method)
        if code:
            raise WebAuthError(code)

    def create_challenge(self, target_channel, *, requester_key):
        self.calls.append(("create", target_channel, requester_key))
        self._raise("create")
        return LoginChallengeCredentials(
            "challenge-public",
            "ABCD-EFGH",
            "browser-secret",
            target_channel,
            NOW + timedelta(minutes=10),
        )

    def status(self, public_id, browser_secret):
        self.calls.append(("status", public_id, browser_secret))
        self._raise("status")
        return LoginChallengeStatus(
            self.challenge_status, NOW + timedelta(minutes=10)
        )

    def exchange(self, public_id, browser_secret):
        self.calls.append(("exchange", public_id, browser_secret))
        self._raise("exchange")
        return WebSessionCredentials(
            "session-secret",
            "csrf-secret",
            NOW + timedelta(hours=12),
            UserScope(7),
        )

    def resolve_session(self, session_token):
        self.calls.append(("resolve", session_token))
        self._raise("resolve")
        return ResolvedWebSession(
            7,
            "session-public",
            "telegram",
            NOW + timedelta(hours=12),
        )

    def validate_csrf(self, session_token, csrf_token):
        self.calls.append(("csrf", session_token, csrf_token))
        self._raise("csrf")

    def revoke_session(self, session_token):
        self.calls.append(("revoke", session_token))
        self._raise("revoke")


def _client(auth):
    app = FastAPI()
    app.include_router(
        build_auth_router(
            auth,
            expected_origin=ORIGIN,
            cookie_secure=True,
        )
    )
    return TestClient(app, base_url=ORIGIN)


def _bearer(secret="browser-secret"):
    return {
        "Authorization": f"Bearer {secret}",
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
    }


def _same_origin():
    return {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


def test_public_auth_posts_require_exact_same_origin_metadata():
    auth = FakeWebAuth()
    with _client(auth) as client:
        missing = client.post(
            "/api/v1/auth/challenges",
            json={"target_channel": "telegram"},
        )
        lookalike = client.post(
            "/api/v1/auth/challenges",
            json={"target_channel": "telegram"},
            headers={
                "Origin": f"{ORIGIN}.evil",
                "Sec-Fetch-Site": "same-origin",
            },
        )

    for response in (missing, lookalike):
        assert response.status_code == 403
        assert response.json()["code"] == "csrf_invalid"


def test_create_and_status_use_bearer_secret_and_safe_status_codes():
    auth = FakeWebAuth()
    with _client(auth) as client:
        created = client.post(
            "/api/v1/auth/challenges",
            json={"target_channel": "telegram"},
            headers=_same_origin(),
        )
        missing_bearer = client.post(
            "/api/v1/auth/challenges/status",
            json={"public_id": "challenge-public"},
            headers=_same_origin(),
        )
        pending = client.post(
            "/api/v1/auth/challenges/status",
            json={"public_id": "challenge-public"},
            headers=_bearer(),
        )
        auth.challenge_status = "approved"
        approved = client.post(
            "/api/v1/auth/challenges/status",
            json={"public_id": "challenge-public"},
            headers=_bearer(),
        )
        auth.challenge_status = "expired"
        expired = client.post(
            "/api/v1/auth/challenges/status",
            json={"public_id": "challenge-public"},
            headers=_bearer(),
        )

    assert created.status_code == 201
    assert created.json() == {
        "public_id": "challenge-public",
        "command": "/web-login ABCD-EFGH",
        "browser_secret": "browser-secret",
        "target_channel": "telegram",
        "expires_at": "2026-08-07T12:10:00Z",
    }
    assert missing_bearer.status_code == 401
    assert missing_bearer.json() == {
        "code": "challenge_invalid",
        "message": "登录请求无效，请重新开始。",
    }
    assert missing_bearer.headers["www-authenticate"] == "Bearer"
    assert pending.status_code == 202
    assert pending.json()["status"] == "pending"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert expired.status_code == 410
    assert expired.json()["code"] == "challenge_expired"
    assert ("status", "challenge-public", "browser-secret") in auth.calls
    assert ("create", "telegram", "testclient") in auth.calls


def test_challenge_rate_limit_is_a_stable_429_without_private_details():
    auth = FakeWebAuth()
    auth.error_by_method["create"] = "rate_limited"

    with _client(auth) as client:
        response = client.post(
            "/api/v1/auth/challenges",
            json={"target_channel": "telegram"},
            headers=_same_origin(),
        )

    assert response.status_code == 429
    assert response.json() == {
        "code": "rate_limited",
        "message": "登录请求过于频繁，请稍后重试。",
    }
    assert response.headers["retry-after"] == "60"


def test_exchange_sets_host_cookies_without_returning_tokens():
    auth = FakeWebAuth()
    with _client(auth) as client:
        response = client.post(
            "/api/v1/auth/sessions",
            json={"public_id": "challenge-public"},
            headers=_bearer(),
        )

    assert response.status_code == 201
    assert response.json() == {
        "authenticated": True,
        "login_channel": "telegram",
        "expires_at": "2026-08-08T00:00:00Z",
    }
    assert "session-secret" not in response.text
    assert "csrf-secret" not in response.text
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if "__Host-kb_session=" in value)
    csrf_cookie = next(value for value in cookies if "__Host-kb_csrf=" in value)
    for value in cookies:
        assert "Secure" in value
        assert "SameSite=strict" in value
        assert "Path=/" in value
    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie


def test_session_resolution_has_no_user_identifier_and_invalid_is_401():
    auth = FakeWebAuth()
    with _client(auth) as client:
        client.cookies.set("__Host-kb_session", "session-secret")
        current = client.get("/api/v1/auth/session")
        auth.error_by_method["resolve"] = "session_invalid"
        invalid = client.get("/api/v1/auth/session")

    assert current.status_code == 200
    assert current.json() == {
        "authenticated": True,
        "login_channel": "telegram",
        "expires_at": "2026-08-08T00:00:00Z",
    }
    assert "user_id" not in current.text
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "session_invalid"


def test_logout_requires_exact_origin_fetch_site_and_bound_csrf():
    auth = FakeWebAuth()
    with _client(auth) as client:
        client.cookies.set("__Host-kb_session", "session-secret")
        client.cookies.set("__Host-kb_csrf", "csrf-secret")
        missing_origin = client.delete("/api/v1/auth/session")
        cross_site = client.delete(
            "/api/v1/auth/session",
            headers={"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
        )
        wrong_header = client.delete(
            "/api/v1/auth/session",
            headers={
                "Origin": ORIGIN,
                "Sec-Fetch-Site": "same-origin",
                "X-CSRF-Token": "wrong",
            },
        )
        valid = client.delete(
            "/api/v1/auth/session",
            headers={
                "Origin": ORIGIN,
                "Sec-Fetch-Site": "same-origin",
                "X-CSRF-Token": "csrf-secret",
            },
        )

    for rejected in (missing_origin, cross_site, wrong_header):
        assert rejected.status_code == 403
        assert rejected.json()["code"] == "csrf_invalid"
    assert valid.status_code == 204
    assert ("resolve", "session-secret") in auth.calls
    assert ("csrf", "session-secret", "csrf-secret") in auth.calls
    assert ("revoke", "session-secret") in auth.calls
    deleted = valid.headers.get_list("set-cookie")
    assert any("__Host-kb_session=" in value and "Max-Age=0" in value for value in deleted)
    assert any("__Host-kb_csrf=" in value and "Max-Age=0" in value for value in deleted)


def test_auth_errors_are_fixed_and_openapi_never_accepts_user_id():
    auth = FakeWebAuth()
    auth.error_by_method["exchange"] = "challenge_pending"
    with _client(auth) as client:
        pending = client.post(
            "/api/v1/auth/sessions",
            json={"public_id": "challenge-public"},
            headers=_bearer(),
        )
        unknown_field = client.post(
            "/api/v1/auth/challenges",
            json={"target_channel": "telegram", "user_id": 999},
            headers=_same_origin(),
        )
        openapi = client.get("/openapi.json")

    assert pending.status_code == 202
    assert pending.json() == {
        "code": "challenge_pending",
        "message": "请先在所选渠道批准登录。",
    }
    assert unknown_field.status_code == 422
    assert unknown_field.json() == {
        "code": "validation_error",
        "message": "请求参数无效。",
    }
    for forbidden in ("user_id", "app_user_id", "channel_identity_id"):
        assert forbidden not in str(openapi.json())


def test_unknown_service_error_code_is_collapsed_without_secret_leakage():
    auth = FakeWebAuth()
    auth.error_by_method["create"] = "private-provider-secret-detail"
    with _client(auth) as client:
        response = client.post(
            "/api/v1/auth/challenges",
            json={"target_channel": "telegram"},
            headers=_same_origin(),
        )

    assert response.status_code == 400
    assert response.json() == {
        "code": "request_failed",
        "message": "请求无法完成。",
    }
    assert "private-provider" not in response.text


def test_auth_rejects_oversized_public_id_and_bearer_without_echoing_them():
    auth = FakeWebAuth()
    oversized = "PRIVATE" * 100
    with _client(auth) as client:
        public_id = client.post(
            "/api/v1/auth/challenges/status",
            json={"public_id": oversized},
            headers=_bearer(),
        )
        bearer = client.post(
            "/api/v1/auth/challenges/status",
            json={"public_id": "challenge-public"},
            headers={**_same_origin(), "Authorization": f"Bearer {oversized}"},
        )

    assert public_id.status_code == 422
    assert public_id.json()["code"] == "validation_error"
    assert bearer.status_code == 401
    assert bearer.json()["code"] == "challenge_invalid"
    assert "PRIVATE" not in public_id.text + bearer.text
