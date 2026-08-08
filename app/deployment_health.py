"""Redacted readiness probe for the public Vercel competition deployment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg


CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MILLISECONDS = 5_000


@dataclass(frozen=True)
class DatabaseProbe:
    """Internal database result; failure codes are safe for private logs only."""

    ready: bool
    revision: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class HealthResponse:
    """Public HTTP response plus an optional private diagnostic category."""

    http_status: int
    payload: dict[str, Any]
    failure_code: str | None = None


def _is_pooled_neon_url(database_url: str) -> bool:
    """Require a TLS Neon pooler URL for the request-driven runtime."""

    try:
        parsed = urlsplit(database_url)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    return (
        parsed.scheme in {"postgres", "postgresql"}
        and "-pooler." in hostname
        and hostname.endswith(".neon.tech")
        and query.get("sslmode") == ["require"]
    )


def probe_database(
    database_url: str | None,
    expected_revision: str | None,
    *,
    connect: Callable[..., Any] = psycopg.connect,
) -> DatabaseProbe:
    """Check Neon connectivity and schema without exposing provider errors."""

    if not database_url:
        return DatabaseProbe(False, failure_code="database_url_missing")
    if not _is_pooled_neon_url(database_url):
        return DatabaseProbe(False, failure_code="database_url_invalid")
    if not expected_revision or not expected_revision.strip():
        return DatabaseProbe(False, failure_code="expected_revision_missing")

    try:
        with connect(
            database_url,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{STATEMENT_TIMEOUT_MILLISECONDS}ms",),
                )
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    return DatabaseProbe(False, failure_code="database_probe_failed")
                cursor.execute("SELECT version_num FROM alembic_version")
                row = cursor.fetchone()
    except Exception:
        # Provider exceptions may include the DSN. Never return or log them.
        return DatabaseProbe(False, failure_code="database_unavailable")

    revision = str(row[0]) if row and row[0] is not None else None
    if revision != expected_revision.strip():
        return DatabaseProbe(False, failure_code="database_schema_mismatch")
    return DatabaseProbe(True, revision=revision)


def build_health_response(
    environ: Mapping[str, str],
    *,
    connect: Callable[..., Any] = psycopg.connect,
) -> HealthResponse:
    """Build the stable public health contract from process configuration."""

    environment = environ.get("DEPLOYMENT_ENV", "competition").strip()
    if environment != "competition":
        environment = "competition"
    database = probe_database(
        environ.get("DATABASE_URL"),
        environ.get("EXPECTED_DATABASE_REVISION"),
        connect=connect,
    )
    if database.ready:
        return HealthResponse(
            200,
            {
                "status": "ok",
                "environment": environment,
                "database": {
                    "status": "ok",
                    "revision": database.revision,
                },
            },
        )
    return HealthResponse(
        503,
        {
            "status": "unavailable",
            "environment": environment,
            "database": {"status": "unavailable"},
        },
        failure_code=database.failure_code,
    )
