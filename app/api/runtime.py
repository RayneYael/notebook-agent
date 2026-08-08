"""Production composition for the same-origin Web API and static SPA."""

from __future__ import annotations

from datetime import timedelta

from app.api.app import WebApiServices, create_app
from app.config import Settings, get_settings
from app.db import get_session_factory
from app.ingest.submission import IngestSubmissionService
from app.object_store import RawObjectStore
from app.web.auth import WebAuthService
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
    settings.validate_web_auth()
    if not settings.web_origin:
        raise ValueError("WEB_ORIGIN is required for the Web server")
    if not settings.web_cookie_secure:
        raise ValueError("WEB_COOKIE_SECURE must stay enabled for __Host- cookies")
    factory = session_factory or get_session_factory()
    if publisher is None:
        from app.ingest.tasks import publish_ingest_dispatch

        publisher = publish_ingest_dispatch
    store = object_store or RawObjectStore()
    web_auth = WebAuthService(
        factory,
        secret=settings.web_auth_secret,
        challenge_ttl=timedelta(
            seconds=settings.web_auth_challenge_ttl_seconds
        ),
        session_ttl=timedelta(seconds=settings.web_auth_session_ttl_seconds),
        attempt_limit=settings.web_auth_attempt_limit,
        enabled_channels=settings.web_login_channels,
        challenge_rate_window=timedelta(
            seconds=settings.web_auth_rate_window_seconds
        ),
        challenge_rate_limit_per_requester=(
            settings.web_auth_rate_limit_per_requester
        ),
        challenge_global_rate_limit=settings.web_auth_global_rate_limit,
        challenge_active_limit_per_requester=(
            settings.web_auth_active_challenge_limit
        ),
        challenge_retention=timedelta(
            seconds=settings.web_auth_challenge_retention_seconds
        ),
        session_retention=timedelta(
            seconds=settings.web_auth_session_retention_seconds
        ),
    )
    submission = IngestSubmissionService(
        factory,
        publisher,
        max_active_per_tenant=settings.ingest_max_active_per_user,
        daily_new_item_limit=settings.ingest_daily_new_item_limit,
        max_items_per_tenant=settings.ingest_max_items_per_user,
        max_active_global=settings.ingest_max_active_global,
        daily_new_item_limit_global=(
            settings.ingest_daily_new_item_limit_global
        ),
        daily_dispatch_limit_per_tenant=(
            settings.ingest_daily_dispatch_limit_per_user
        ),
        daily_dispatch_limit_global=(
            settings.ingest_daily_dispatch_limit_global
        ),
    )
    services = WebApiServices(
        web_auth=web_auth,
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
        expected_origin=settings.web_origin,
        cookie_secure=True,
        publish_budget_seconds=settings.web_publish_budget_seconds,
        save_enabled=settings.agent_save_enabled,
        web_login_channels=settings.web_login_channels,
        static_dir=settings.web_static_dir if serve_static else None,
    )
