from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.runtime import build_web_app


def settings(**overrides):
    values = {
        "validate_web_auth": Mock(),
        "web_auth_secret": "x" * 32,
        "web_auth_challenge_ttl_seconds": 600,
        "web_auth_session_ttl_seconds": 2592000,
        "web_auth_attempt_limit": 5,
        "web_auth_rate_window_seconds": 60,
        "web_auth_rate_limit_per_requester": 5,
        "web_auth_global_rate_limit": 100,
        "web_auth_active_challenge_limit": 3,
        "web_auth_challenge_retention_seconds": 86400,
        "web_auth_session_retention_seconds": 604800,
        "web_login_channels": ("telegram", "wechat"),
        "web_origin": "https://kb.example.test",
        "web_cookie_secure": True,
        "web_publish_budget_seconds": 1.5,
        "agent_save_enabled": True,
        "web_static_dir": "web/dist",
        "ingest_max_active_per_user": 10,
        "ingest_daily_new_item_limit": 50,
        "ingest_max_items_per_user": 1000,
        "ingest_max_active_global": 100,
        "ingest_daily_new_item_limit_global": 300,
        "ingest_daily_dispatch_limit_per_user": 100,
        "ingest_daily_dispatch_limit_global": 1000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runtime_composes_auth_library_submission_and_transcript_without_io():
    config = settings()

    app = build_web_app(
        config,
        session_factory=lambda: None,
        publisher=lambda _dispatch_id: "task",
        object_store=object(),
        mount_static=False,
    )

    paths = app.openapi()["paths"]
    assert "/api/v1/auth/challenges" in paths
    assert "/api/v1/library/items" in paths
    assert "/api/v1/library/items/{item_public_id}/transcript" in paths
    config.validate_web_auth.assert_called_once_with()


def test_runtime_exposes_only_the_enabled_login_channels():
    app = build_web_app(
        settings(web_login_channels=("wechat",)),
        session_factory=lambda: None,
        publisher=lambda _dispatch_id: "task",
        object_store=object(),
        mount_static=False,
    )

    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["web_login_channels"] == ["wechat"]


def test_runtime_applies_the_global_save_switch_to_web_capabilities():
    app = build_web_app(
        settings(agent_save_enabled=False),
        session_factory=lambda: None,
        publisher=lambda _dispatch_id: "task",
        object_store=object(),
        mount_static=False,
    )

    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["save_enabled"] is False


@pytest.mark.parametrize(
    "override",
    [
        {"web_origin": None},
        {"web_cookie_secure": False},
    ],
)
def test_runtime_rejects_an_origin_or_cookie_mode_that_breaks_host_cookie_security(override):
    with pytest.raises(ValueError):
        build_web_app(
            settings(**override),
            session_factory=lambda: None,
            publisher=lambda _dispatch_id: "task",
            object_store=object(),
            mount_static=False,
        )
