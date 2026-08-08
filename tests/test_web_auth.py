from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from app.channels.types import TenantContext, UserScope
from app.config import Settings
from app.web.auth import (
    SESSION_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    WebAuthError,
    WebAuthService,
    hash_browser_secret,
    hash_csrf_token,
    hash_login_code,
    hash_session_token,
)


def test_user_scope_is_frozen_and_tenant_context_keeps_positional_contract():
    scope = UserScope(7)
    tenant = TenantContext(7, 11, "telegram", "bot", "external")

    assert tenant.app_user_id == scope.app_user_id
    assert isinstance(tenant, UserScope)
    with pytest.raises(FrozenInstanceError):
        scope.app_user_id = 8
    with pytest.raises(ValueError, match="positive"):
        UserScope(0)


def test_web_auth_hashes_use_hmac_for_codes_and_sha256_for_browser_values():
    code = "ABCD-EFGH"
    assert hash_login_code(code, "a" * 32) != hash_login_code(code, "b" * 32)
    assert hash_login_code(" abcd-efgh ", "a" * 32) == hash_login_code(
        code, "a" * 32
    )

    raw = "browser-or-session-secret"
    assert hash_browser_secret(raw) == hash_session_token(raw)
    assert hash_session_token(raw) == hash_csrf_token(raw)
    assert raw not in hash_browser_secret(raw)

    with pytest.raises(WebAuthError) as missing_csrf:
        hash_csrf_token("")
    assert missing_csrf.value.code == "csrf_invalid"


def test_web_auth_configuration_is_safe_and_framework_neutral():
    assert SESSION_COOKIE_NAME == "__Host-kb_session"
    assert CSRF_COOKIE_NAME == "__Host-kb_csrf"

    with pytest.raises(ValueError, match="WEB_AUTH_SECRET"):
        WebAuthService(lambda: None, secret="short")
    with pytest.raises(ValueError, match="attempt"):
        WebAuthService(lambda: None, secret="x" * 32, attempt_limit=0)
    with pytest.raises(ValueError, match="TTL"):
        WebAuthService(
            lambda: None,
            secret="x" * 32,
            challenge_ttl=timedelta(0),
        )


def test_web_auth_configuration_rejects_retention_shorter_than_rate_window():
    with pytest.raises(ValueError, match="retention.*rate window"):
        WebAuthService(
            lambda: None,
            secret="x" * 32,
            challenge_rate_window=timedelta(minutes=2),
            challenge_retention=timedelta(minutes=1),
        )


@pytest.mark.parametrize("forwarded_allow_ips", ["", "*"])
def test_web_auth_settings_require_explicit_trusted_proxy_sources(
    forwarded_allow_ips,
):
    settings = Settings(
        database_url="postgresql+psycopg://unused/unused",
        redis_url="redis://unused/0",
        web_auth_secret="x" * 32,
        web_forwarded_allow_ips=forwarded_allow_ips,
    )

    with pytest.raises(ValueError, match="WEB_FORWARDED_ALLOW_IPS"):
        settings.validate_web_auth()


def test_web_auth_settings_reject_retention_shorter_than_rate_window():
    settings = Settings(
        database_url="postgresql+psycopg://unused/unused",
        redis_url="redis://unused/0",
        web_auth_secret="x" * 32,
        web_auth_rate_window_seconds=120,
        web_auth_challenge_retention_seconds=60,
    )

    with pytest.raises(ValueError, match="RETENTION.*rate window"):
        settings.validate_web_auth()


def test_web_static_serving_defaults_on_and_accepts_explicit_disable(monkeypatch):
    monkeypatch.delenv("WEB_SERVE_STATIC", raising=False)
    base = {
        "database_url": "postgresql+psycopg://unused/unused",
        "redis_url": "redis://unused/0",
    }

    assert Settings(**base).web_serve_static is True
    monkeypatch.setenv("WEB_SERVE_STATIC", "false")
    assert Settings(**base).web_serve_static is False
    monkeypatch.setenv("WEB_SERVE_STATIC", "sometimes")
    with pytest.raises(ValueError, match="WEB_SERVE_STATIC must be a boolean"):
        Settings(**base)


def test_web_origin_rejects_lookalike_loopback_and_paths():
    base = {
        "database_url": "postgresql+psycopg://unused/unused",
        "redis_url": "redis://unused/0",
        "web_auth_secret": "x" * 32,
    }
    Settings(**base, web_origin="https://kb.example.com").validate_web_auth()
    Settings(**base, web_origin="http://localhost:5173").validate_web_auth()

    for unsafe in (
        "http://localhost.evil",
        "https://kb.example.com/path",
        "https://user@kb.example.com",
    ):
        with pytest.raises(ValueError, match="WEB_ORIGIN"):
            Settings(**base, web_origin=unsafe).validate_web_auth()
