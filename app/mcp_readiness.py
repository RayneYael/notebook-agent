"""Bounded production readiness checks for the full MCP profile.

The read profile is intentionally lazy and can answer questions from an
already-running application with only the database/model path.  Mutating MCP
tools additionally depend on the database, broker/Redis, object store, and
maintenance configuration.  This module performs a short, redacted startup
assessment; callers may inject probes in tests or deployments with an
existing health system.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Thread
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import text

from app.config import Settings


READINESS_CHECKS: tuple[str, ...] = (
    "database",
    "broker",
    "object_store",
    "maintenance",
    "worker",
)

# Celery's inspect timeout bounds the reply wait, while the daemon-thread
# wrapper below also bounds connection/setup failures in Kombu transports that
# do not consistently honour that value.  A timed-out daemon is never joined
# indefinitely and cannot keep the MCP process alive during startup.
_WORKER_INSPECT_TIMEOUT_SECONDS = 0.35
_WORKER_TOTAL_TIMEOUT_SECONDS = 0.75
_REQUIRED_WORKER_QUEUES = frozenset({"ingest", "maintenance"})


@dataclass(frozen=True)
class McpMutationReadiness:
    """Safe readiness result; no provider exception or credential is stored."""

    ready: bool
    checks: Mapping[str, bool]
    failure_codes: tuple[str, ...] = ()

    @property
    def error_code(self) -> str:
        return self.failure_codes[0] if self.failure_codes else "mutation_unavailable"


def _call_probe(probe: Callable[..., Any], settings: Settings) -> bool:
    try:
        try:
            value = probe(settings)
        except TypeError:
            value = probe()
        return bool(value)
    except Exception:
        return False


def _probe_database(session_factory: Callable[[], Any] | None) -> bool:
    if session_factory is None:
        return False
    try:
        with session_factory() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _probe_redis(settings: Settings) -> bool:
    value = (settings.redis_url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        return False
    try:
        import redis

        client = redis.Redis.from_url(
            value,
            socket_connect_timeout=0.35,
            socket_timeout=0.35,
            health_check_interval=0,
        )
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:
        return False


def _probe_object_store(settings: Settings) -> bool:
    endpoint = (settings.minio_endpoint_url or "").strip()
    bucket = (settings.minio_bucket or "").strip()
    access_key = settings.minio_access_key
    secret_key = settings.minio_secret_key
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or not bucket
        or not access_key
        or not secret_key
    ):
        return False
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(
                connect_timeout=0.35,
                read_timeout=0.35,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )
        client.head_bucket(Bucket=bucket)
        return True
    except Exception:
        return False


def _probe_maintenance(settings: Settings) -> bool:
    values = (
        settings.trash_retention_days,
        settings.trash_purge_interval_seconds,
        settings.trash_purge_batch_size,
        settings.trash_purge_claim_timeout_seconds,
        settings.trash_purge_max_duration_seconds,
        settings.trash_purge_object_timeout_seconds,
    )
    return all(value > 0 for value in values)


def _inspect_worker(settings: Settings) -> bool:
    """Check for a live Celery worker serving both mutation queues.

    The task app is the same app used by ingestion submission and the
    deployment runbook's ``celery inspect ping/active_queues`` commands.  We
    intentionally reduce all broker/worker responses to booleans and never
    include worker names, broker URLs, or exception text in readiness output.
    """

    del settings  # Celery is composed from the same REDIS_URL environment.
    from app.ingest.tasks import celery_app

    inspector = celery_app.control.inspect(
        timeout=_WORKER_INSPECT_TIMEOUT_SECONDS
    )
    pongs = inspector.ping()
    queues = inspector.active_queues()
    if not isinstance(pongs, Mapping) or not isinstance(queues, Mapping):
        return False
    for worker_name, response in pongs.items():
        if not isinstance(response, Mapping) or response.get("ok") != "pong":
            continue
        worker_queues = queues.get(worker_name)
        if not isinstance(worker_queues, list):
            continue
        queue_names = {
            row.get("name")
            for row in worker_queues
            if isinstance(row, Mapping) and isinstance(row.get("name"), str)
        }
        if _REQUIRED_WORKER_QUEUES.issubset(queue_names):
            return True
    return False


def probe_mcp_worker(
    settings: Settings,
    *,
    inspector: Callable[[Settings], Any] | None = None,
    timeout_seconds: float = _WORKER_TOTAL_TIMEOUT_SECONDS,
) -> bool:
    """Run the production worker inspection under a hard bounded deadline.

    ``inspector`` exists for deterministic tests and deployment health
    adapters.  A probe exception, malformed response, or timeout fails closed;
    the daemon thread prevents an unresponsive broker client from hanging MCP
    startup or test teardown.
    """

    callback = inspector or _inspect_worker
    try:
        budget = max(0.01, min(float(timeout_seconds), 5.0))
    except (TypeError, ValueError):
        return False
    result: dict[str, bool] = {}

    def run() -> None:
        try:
            try:
                value = callback(settings)
            except TypeError:
                value = callback()  # type: ignore[call-arg]
            result["ready"] = bool(value)
        except Exception:
            result["ready"] = False

    thread = Thread(target=run, name="mcp-worker-readiness", daemon=True)
    thread.start()
    thread.join(budget)
    return thread.is_alive() is False and result.get("ready", False)


def assess_mcp_mutation_readiness(
    settings: Settings,
    *,
    session_factory: Callable[[], Any] | None = None,
    database_probe: Callable[..., Any] | None = None,
    broker_probe: Callable[..., Any] | None = None,
    object_store_probe: Callable[..., Any] | None = None,
    maintenance_probe: Callable[..., Any] | None = None,
    worker_probe: Callable[..., Any] | None = None,
) -> McpMutationReadiness:
    """Run bounded checks and return a safe full-profile decision.

    Probe callbacks are deliberately tiny and receive ``settings`` when they
    accept an argument.  Their return values are reduced to booleans and all
    exceptions fail closed with stable categories.
    """

    checks = {
        "database": (
            _call_probe(database_probe, settings)
            if database_probe is not None
            else _probe_database(session_factory)
        ),
        "broker": (
            _call_probe(broker_probe, settings)
            if broker_probe is not None
            else _probe_redis(settings)
        ),
        "object_store": (
            _call_probe(object_store_probe, settings)
            if object_store_probe is not None
            else _probe_object_store(settings)
        ),
        "maintenance": (
            _call_probe(maintenance_probe, settings)
            if maintenance_probe is not None
            else _probe_maintenance(settings)
        ),
        "worker": (
            _call_probe(worker_probe, settings)
            if worker_probe is not None
            else probe_mcp_worker(settings)
        ),
    }
    failures = tuple(f"{name}_unavailable" for name in READINESS_CHECKS if not checks[name])
    return McpMutationReadiness(
        ready=not failures,
        checks=checks,
        failure_codes=failures,
    )


__all__ = [
    "McpMutationReadiness",
    "READINESS_CHECKS",
    "assess_mcp_mutation_readiness",
    "probe_mcp_worker",
]
