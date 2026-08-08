"""Compatibility exports for MCP transport authentication."""

from app.mcp_server import (  # noqa: F401
    AuthenticatedPath,
    McpAuthMiddleware,
    McpAuthenticationError,
    extract_authentication,
    redact_request_uri,
)

__all__ = [
    "AuthenticatedPath",
    "McpAuthMiddleware",
    "McpAuthenticationError",
    "extract_authentication",
    "redact_request_uri",
]
