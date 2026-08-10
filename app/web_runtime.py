"""ASGI composition that keeps Web cookie and MCP bearer boundaries separate."""

from __future__ import annotations

from app.api.runtime import build_web_app
from app.config import Settings, get_settings
from app.mcp_grants import McpGrantService
from app.mcp_server import create_streamable_http_app


def create_combined_asgi_app(*, settings: Settings | None = None, session_factory=None, channel_service=None, auth_service=None, mcp_server=None, grant_service=None):
    settings = settings or get_settings()
    if session_factory is None:
        from app.db import get_session_factory
        session_factory = get_session_factory()
    grant_service = grant_service or McpGrantService(session_factory)
    mcp_app = create_streamable_http_app(server=mcp_server, grant_service=grant_service, settings=settings)
    # The Web product has one FastAPI app.  It owns the email-login cookies
    # and upstream library routes; MCP remains an independently authenticated
    # ASGI target below.
    web_app = build_web_app(
        settings=settings,
        session_factory=session_factory,
        email_auth=auth_service,
        channel_service=channel_service,
    )

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            await mcp_app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == settings.mcp_path or path.startswith(settings.mcp_path + "/"):
            await mcp_app(scope, receive, send)
        else:
            await web_app(scope, receive, send)

    return app
