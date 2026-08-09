"""Production composition for the same-origin Web API and static SPA."""

from __future__ import annotations

from datetime import timedelta

from app.api.app import WebApiServices, create_app
from app.api.email_auth_routes import EmailWebAuthAdapter
from app.config import Settings, get_settings
from app.db import get_session_factory
from app.ingest.submission import build_ingest_submission_service
from app.object_store import RawObjectStore
from app.web.auth import WebAuthService
from app.web_auth import build_email_auth_service
from app.web.library import ContentLibraryService
from app.web.transcript import TranscriptService


def build_web_app(
    settings: Settings | None = None,
    *,
    session_factory=None,
    publisher=None,
    object_store=None,
    mount_static: bool | None = None,
):
    """Wire concrete services while keeping test doubles explicit and local."""

    settings = settings or get_settings()
    if not settings.web_cookie_secure:
        raise ValueError("WEB_COOKIE_SECURE must stay enabled for __Host- cookies")
    factory = session_factory or get_session_factory()
    if publisher is None:
        from app.ingest.tasks import publish_ingest_dispatch

        publisher = publish_ingest_dispatch
    store = object_store or RawObjectStore()
    submission = build_ingest_submission_service(factory, publisher, settings)
    email_enabled = bool(getattr(settings, "web_auth_enabled", False))
    if email_enabled:
        email_auth = build_email_auth_service(settings, factory)
        web_auth = EmailWebAuthAdapter(email_auth)
        expected_origin = settings.web_public_origin or ""
        public_login_channels = ("email",)
    else:
        # The old channel-approved service remains injectable for existing
        # embedders and migration-era tests, but the deployed runtime enables
        # email OTP and never registers this as its public login flow.
        if getattr(settings, "notebook_agent_env", "development") == "production":
            raise ValueError(
                "WEB_AUTH_ENABLED must stay enabled for the production Web server"
            )
        settings.validate_web_auth()
        if not settings.web_origin:
            raise ValueError("WEB_ORIGIN is required for the Web server")
        email_auth = None
        web_auth = WebAuthService(
            factory,
            secret=settings.web_auth_secret,
            challenge_ttl=timedelta(seconds=settings.web_auth_challenge_ttl_seconds),
            session_ttl=timedelta(seconds=settings.web_auth_session_ttl_seconds),
            attempt_limit=settings.web_auth_attempt_limit,
            enabled_channels=settings.web_login_channels,
            challenge_rate_window=timedelta(seconds=settings.web_auth_rate_window_seconds),
            challenge_rate_limit_per_requester=settings.web_auth_rate_limit_per_requester,
            challenge_global_rate_limit=settings.web_auth_global_rate_limit,
            challenge_active_limit_per_requester=settings.web_auth_active_challenge_limit,
            challenge_retention=timedelta(seconds=settings.web_auth_challenge_retention_seconds),
            session_retention=timedelta(seconds=settings.web_auth_session_retention_seconds),
        )
        expected_origin = settings.web_origin
        public_login_channels = settings.web_login_channels
    services = WebApiServices(
        web_auth=web_auth,
        email_auth=email_auth,
        trusted_proxy_hosts=getattr(settings, "web_trusted_proxy_hosts", ""),
        library=ContentLibraryService(
            factory,
            publisher,
            quota_policy=submission.quota_policy,
            save_enabled=settings.agent_save_enabled,
        ),
        submission=submission,
        transcript=TranscriptService(factory, store),
    )
    serve_static = (
        settings.web_serve_static
        if mount_static is None
        else mount_static
    )
    return create_app(
        services=services,
        expected_origin=expected_origin,
        cookie_secure=True,
        publish_budget_seconds=settings.web_publish_budget_seconds,
        save_enabled=settings.agent_save_enabled,
        web_login_channels=public_login_channels,
        static_dir=settings.web_static_dir if serve_static else None,
    )
