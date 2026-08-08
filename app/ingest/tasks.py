"""Synchronous ingestion core plus isolated Celery retry wrapper."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from celery import Celery, Task
from kombu import Producer
from sqlalchemy import delete, func, select

from app.config import Settings, get_settings
from app.connectors.base import NeedsASR, NeedsExtension, TextResult, TransientFetchError
from app.connectors.youtube import YouTubeConnector
from app.db import get_session_factory
from app.ingest.chunker import chunk
from app.ingest.embed import EmbeddingProvider, ZhipuEmbedder
from app.ingest.validate import guard_transcript
from app.models import AppUser, ContentItem, IngestDispatch, Segment
from app.agent.management import RecycleBinPurgeService
from app.object_store import RawObjectStore
from app.tls import configure_trusted_ca


celery_app = Celery("kb", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"), backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
celery_app.conf.task_routes = {
    "app.ingest.tasks.fetch_text_task": {"queue": "ingest"},
    "app.ingest.tasks.purge_expired_items_task": {"queue": "maintenance"},
}


def _bounded_publish_options(
    settings: Settings,
    *,
    budget_seconds: float | None = None,
) -> dict[str, Any]:
    """Build native Celery/Kombu publish bounds below the Agent deadline.

    Kombu applies ``max_retries`` both while publishing and while re-opening a
    lost connection.  We therefore reserve a small, fixed retry interval and
    divide the remaining budget across a conservative upper bound for those
    operations.  No thread or watchdog is needed (or left running) when the
    broker is unavailable.
    """

    budget = float(settings.broker_publish_timeout_seconds)
    agent_timeout = min(
        float(settings.agent_timeout_seconds),
        float(settings.agent_tool_timeout_seconds),
    )
    retries = int(settings.broker_publish_max_retries)
    if budget <= 0 or agent_timeout <= 0:
        raise ValueError("broker and Agent tool timeouts must be positive")
    if retries < 0:
        raise ValueError("BROKER_PUBLISH_MAX_RETRIES must be non-negative")

    # Reserve time for the surrounding Agent/channel request.  A
    # misconfigured larger value is clamped rather than allowing a broker call
    # to consume the whole model deadline, including for very small test
    # deadlines.
    agent_margin = min(1.0, agent_timeout / 2)
    budget = min(budget, agent_timeout - agent_margin)
    if budget_seconds is not None:
        budget = min(budget, float(budget_seconds))
    if budget <= 0:
        raise TimeoutError("broker_publish_timeout")
    attempts = retries + 1
    # One initial connection plus Kombu's bounded reconnect attempts for each
    # failed publish.  The multiplier leaves room for queue/exchange declare
    # and the Redis/AMQP socket operation on each attempt.
    operation_count = max(1, (attempts * (retries + 4)) // 2)
    sleep_count = retries * (retries + 3) // 2
    interval = min(0.1, budget / (4 * max(sleep_count, 1)))
    operation_budget = (budget - interval * sleep_count) / (4 * operation_count)

    return {
        "retry": True,
        "retry_policy": {
            "max_retries": retries,
            "interval_start": interval,
            "interval_step": 0,
            "interval_max": interval,
        },
        # Supported by Kombu Producer.publish (and by AMQP transports).
        "timeout": operation_budget,
        "_connect_timeout": operation_budget,
        "_socket_timeout": operation_budget,
        "_total_timeout": budget,
    }


def _connector(url: str) -> YouTubeConnector:
    connector = YouTubeConnector()
    if connector.match(url):
        return connector
    raise ValueError(f"unsupported URL: {url}")


def create_item(url: str, *, user_id: int, why_saved: str | None = None, connector: Any | None = None, session_factory=None) -> int:
    connector = connector or _connector(url)
    platform_id = connector.match(url)
    if not platform_id:
        raise ValueError(f"connector does not match URL: {url}")
    factory = session_factory or get_session_factory()
    with factory() as db:
        if db.get(AppUser, user_id) is None:
            raise LookupError(f"app user {user_id} not found")
        existing = db.scalar(select(ContentItem).where(ContentItem.user_id == user_id, ContentItem.platform == connector.platform, ContentItem.platform_id == platform_id).with_for_update())
        if existing:
            if getattr(existing, "deleted_at", None) is not None:
                retention_days = get_settings().trash_retention_days
                now = db.scalar(select(func.now()))
                if getattr(existing, "purge_claimed_at", None) is not None or existing.deleted_at + timedelta(days=retention_days) <= now:
                    return existing.id
                existing.deleted_at = None
                existing.delete_claim_token = uuid4().hex
                existing.purge_claimed_at = None
                existing.purge_attempts = 0
                existing.purge_error_code = None
                if why_saved is not None:
                    existing.why_saved = " ".join(why_saved.split())[:500] or None
                db.commit()
            return existing.id
        item = ContentItem(
            public_id=uuid4().hex,
            user_id=user_id,
            platform=connector.platform,
            platform_id=platform_id,
            kind="video",
            url=url,
            why_saved=why_saved,
            state="pending",
        )
        db.add(item)
        db.commit()
        return item.id


def process_item(item_id: int, *, connector: Any | None = None, embedder: EmbeddingProvider | None = None, object_store: Any | None = None, session_factory=None) -> str:
    factory = session_factory or get_session_factory()
    with factory() as db:
        item = db.get(ContentItem, item_id)
        if item is None:
            raise LookupError(f"content item {item_id} not found")
        if getattr(item, "deleted_at", None) is not None or getattr(item, "purge_claimed_at", None) is not None:
            # A late worker may finish remote fetching, but must not publish
            # new visible segments for an item that is in the recycle bin.
            _mark_item_deleted(db, item)
            return "deleted"
        connector = connector or _connector(item.url)
        meta = connector.fetch_meta(item.platform_id)
        if meta is not None:
            item.url = meta.url
            item.title = meta.title
            item.author = meta.author
            item.published_at = meta.published_at
            item.duration_sec = meta.duration_sec
            item.lang = meta.lang
            item.description = meta.description
            item.tags = meta.tags
            item.chapters = meta.chapters
            item.cover_url = meta.cover_url
        item.state = "fetching"
        db.commit()
        result = connector.fetch_text(item.platform_id)
        if isinstance(result, NeedsExtension):
            item.state = "needs_extension"
            db.commit()
            return item.state
        if isinstance(result, NeedsASR):
            item.state = "needs_asr"
            db.commit()
            return item.state
        if not isinstance(result, TextResult):
            raise TypeError(f"connector returned unsupported text result: {type(result)!r}")
        guard_transcript(result.raw_body, result.cues, platform=item.platform)
        key = f"{item.user_id}/{item.platform}/{item.platform_id}/{hashlib.sha256(result.raw_body).hexdigest()}.json3"
        db.refresh(item)
        if getattr(item, "deleted_at", None) is not None or getattr(item, "purge_claimed_at", None) is not None:
            _mark_item_deleted(db, item)
            return "deleted"
        store = object_store or RawObjectStore()
        # Persist a deterministic cleanup intent before crossing the external
        # object-store boundary.  If the process dies during/after ``put``,
        # purge and a later worker both have the key needed for idempotent
        # cleanup; no uncommitted ORM attribute can hide an orphan object.
        item.raw_object_key = key
        item.content_hash = hashlib.sha256("\n".join(c.text.strip() for c in result.cues).encode()).hexdigest()
        item.text_source = result.source
        item.lang = result.lang
        item.state = "chunking"
        db.commit()
        store.put(key, result.raw_body, "application/json")
        # A soft delete may have committed while the object was being put.
        # Remove the object immediately and leave the row/dispatch available
        # for restore or retry; the final check below protects the embedding
        # interleaving as well.
        db.refresh(item)
        if getattr(item, "deleted_at", None) is not None or getattr(item, "purge_claimed_at", None) is not None:
            _delete_object_best_effort(store, key)
            _mark_item_deleted(db, item)
            return "deleted"
        if embedder is None:
            embedder = build_worker_embedder()
        semantic = lambda texts: embedder.embed(texts)
        chunks = chunk(result.cues, lang=result.lang, chapters=item.chapters, semantic_embedder=semantic)
        vectors = embedder.embed([part.text for part in chunks])
        if len(vectors) != len(chunks):
            raise ValueError(
                f"embedding count mismatch: expected {len(chunks)}, got {len(vectors)}"
            )
        db.refresh(item)
        if getattr(item, "deleted_at", None) is not None or getattr(item, "purge_claimed_at", None) is not None:
            _delete_object_best_effort(store, key)
            _mark_item_deleted(db, item)
            return "deleted"
        db.execute(delete(Segment).where(Segment.item_id == item.id))
        item.state = "embedding"
        for seq, (part, vector) in enumerate(zip(chunks, vectors, strict=True)):
            fts = func.to_tsvector("english", part.text) if not result.lang.startswith("zh") else None
            db.add(Segment(item_id=item.id, seq=seq, start_sec=part.start_sec, end_sec=part.end_sec, text=part.text, embedding=vector, fts=fts, boundary_kind=part.boundary_kind))
        item.state = "ready"
        item.fail_reason = None
        db.commit()
        return item.state


def _delete_object_best_effort(store: Any, key: str) -> None:
    """Delete a late worker object without exposing key/provider details."""

    delete = getattr(store, "delete_object", None) or getattr(store, "delete", None)
    if delete is None:
        return
    try:
        delete(key)
    except TypeError:
        try:
            delete(getattr(store, "bucket", None), key)
        except Exception:
            return
    except Exception:
        return


def _mark_item_deleted(db: Any, item: Any) -> None:
    """Converge a worker abort into a durable retryable item state."""

    # A worker that returns ``deleted`` may have already persisted cleanup
    # intent/raw_object_key and then observed a soft-delete race.  Keep the
    # row visibly failed (rather than chunking/embedding forever) so restore
    # plus a later save/retry can create a fresh dispatch.
    item.state = "failed"
    item.fail_reason = "item_deleted"
    db.commit()


class IngestTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        if args:
            _mark_dispatch_failed(args[0], exc, task_id=task_id)


@celery_app.task(bind=True, base=IngestTask, autoretry_for=(TransientFetchError,), max_retries=5, retry_backoff=8, retry_backoff_max=600, retry_jitter=True)
def fetch_text_task(self, dispatch_id: int) -> str:
    return process_dispatch(
        dispatch_id,
        task_id=self.request.id,
    )


def publish_ingest_dispatch(
    dispatch_id: int,
    *,
    remaining_budget_seconds: float | None = None,
) -> str:
    """Publish only the durable internal dispatch identifier."""

    settings = get_settings()
    options = _bounded_publish_options(
        settings,
        budget_seconds=remaining_budget_seconds,
    )
    # These are read by Celery when it acquires the producer connection.  Keep
    # transport options scoped to the broker publish path; worker task retry /
    # backoff settings above remain unchanged.
    connect_timeout = options.pop("_connect_timeout")
    socket_timeout = options.pop("_socket_timeout")
    celery_app.conf.broker_connection_timeout = connect_timeout
    transport_options = dict(celery_app.conf.broker_transport_options or {})
    transport_options.update(
        socket_timeout=socket_timeout,
        socket_connect_timeout=connect_timeout,
    )
    celery_app.conf.broker_transport_options = transport_options
    options.pop("_total_timeout")
    # Celery's shared ProducerPool has a bounded outer acquire but performs a
    # nested ConnectionPool.acquire(block=True) without forwarding that
    # timeout. Use a request-local bounded connection instead, so neither pool
    # can make an Agent tool thread wait indefinitely.
    with celery_app.connection_for_write(
        connect_timeout=connect_timeout,
        transport_options=transport_options,
    ) as connection:
        producer = Producer(connection)
        result = fetch_text_task.apply_async(
            args=[dispatch_id],
            producer=producer,
            **options,
        )
        return str(result.id)


@celery_app.task(name="app.ingest.tasks.purge_expired_items_task")
def purge_expired_items_task() -> dict[str, int]:
    """Run one bounded recycle-bin sweep and emit only safe counters."""

    settings = get_settings()
    service = RecycleBinPurgeService(
        get_session_factory(),
        RawObjectStore(),
        retention_days=settings.trash_retention_days,
        batch_size=settings.trash_purge_batch_size,
        claim_timeout_seconds=settings.trash_purge_claim_timeout_seconds,
        max_duration_seconds=settings.trash_purge_max_duration_seconds,
    )
    result = service.purge_once()
    return {
        "claimed": result.claimed,
        "completed": result.completed,
        "failed": result.failed,
        "deferred": result.deferred,
    }


try:
    _purge_interval = max(1, int(os.getenv("TRASH_PURGE_INTERVAL_SECONDS", "3600")))
except (TypeError, ValueError):
    _purge_interval = 3600

celery_app.conf.beat_schedule = {
    "purge-expired-items": {
        "task": "app.ingest.tasks.purge_expired_items_task",
        "schedule": float(_purge_interval),
        "options": {"queue": "maintenance"},
    }
}


def build_worker_embedder(
    settings: Settings | None = None,
) -> EmbeddingProvider:
    """Build worker HTTPS embedding with the verified shared CA contract."""

    settings = settings or get_settings()
    trusted_ca = configure_trusted_ca(settings.tls_ca_bundle)
    return ZhipuEmbedder(
        settings.zhipu_api_key or "",
        model=settings.embedding_model,
        endpoint=settings.embedding_endpoint,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        ssl_context=trusted_ca.ssl_context,
    )


def process_dispatch(
    dispatch_id: int,
    *,
    task_id: str | None,
    processor: Callable[[int], str] | None = None,
    session_factory=None,
) -> str:
    """Claim one dispatch; duplicate deliveries never rerun ingestion."""

    factory = session_factory or get_session_factory()
    item_id = _claim_dispatch(
        dispatch_id, task_id, session_factory=factory
    )
    if item_id is None:
        return "duplicate"
    try:
        state = (processor or process_item)(item_id)
    except TransientFetchError:
        _release_dispatch_for_retry(
            dispatch_id, task_id, session_factory=factory
        )
        # Celery may log task exceptions; preserve retry type but never copy
        # connector/provider details into the task failure surface.
        raise TransientFetchError("transient_fetch_failed") from None
    except Exception as exc:
        _mark_dispatch_failed(
            dispatch_id, exc, task_id=task_id, session_factory=factory
        )
        raise RuntimeError("ingestion_failed") from None
    _complete_dispatch(
        dispatch_id, task_id, process_state=state, session_factory=factory
    )
    return state


def _claim_dispatch(
    dispatch_id: int,
    task_id: str | None,
    *,
    session_factory=None,
) -> int | None:
    factory = session_factory or get_session_factory()
    with factory() as db:
        dispatch = db.scalar(
            select(IngestDispatch)
            .where(IngestDispatch.id == dispatch_id)
            .with_for_update()
        )
        if dispatch is None or dispatch.state not in {
            "pending",
            "enqueued",
        }:
            return None
        if (
            dispatch.task_id is not None
            and task_id is not None
            and dispatch.task_id != task_id
        ):
            return None
        item = db.get(ContentItem, dispatch.item_id)
        if item is None:
            # A tenant merge may retire a queued duplicate and cascade its
            # dispatch before this delivery is claimed. Treat that as the same
            # no-op duplicate outcome as a missing dispatch.
            return None
        if getattr(item, "deleted_at", None) is not None or getattr(item, "purge_claimed_at", None) is not None:
            dispatch.state = "failed"
            dispatch.error_code = "item_deleted"
            item.state = "failed"
            item.fail_reason = "item_deleted"
            dispatch.updated_at = datetime.now(UTC)
            db.commit()
            return None
        dispatch.state = "running"
        if task_id is not None:
            dispatch.task_id = task_id
        dispatch.updated_at = datetime.now(UTC)
        db.commit()
        return item.id


def _release_dispatch_for_retry(
    dispatch_id: int,
    task_id: str | None,
    *,
    session_factory=None,
) -> None:
    factory = session_factory or get_session_factory()
    with factory() as db:
        dispatch = db.scalar(
            select(IngestDispatch)
            .where(IngestDispatch.id == dispatch_id)
            .with_for_update()
        )
        if (
            dispatch is None
            or dispatch.state != "running"
            or (
                task_id is not None
                and dispatch.task_id not in {None, task_id}
            )
        ):
            return
        dispatch.state = "enqueued"
        dispatch.updated_at = datetime.now(UTC)
        db.commit()


def _complete_dispatch(
    dispatch_id: int,
    task_id: str | None,
    *,
    process_state: str | None = None,
    session_factory=None,
) -> None:
    factory = session_factory or get_session_factory()
    with factory() as db:
        dispatch = db.scalar(
            select(IngestDispatch)
            .where(IngestDispatch.id == dispatch_id)
            .with_for_update()
        )
        if (
            dispatch is None
            or dispatch.state != "running"
            or (
                task_id is not None
                and dispatch.task_id not in {None, task_id}
            )
        ):
            return
        item = db.get(ContentItem, dispatch.item_id)
        if (
            item is None
            or process_state == "deleted"
            or getattr(item, "deleted_at", None) is not None
            or getattr(item, "purge_claimed_at", None) is not None
        ):
            dispatch.state = "failed"
            dispatch.error_code = "item_deleted"
            if item is not None:
                item.state = "failed"
                item.fail_reason = "item_deleted"
            dispatch.updated_at = datetime.now(UTC)
            db.commit()
            return
        dispatch.state = "completed"
        dispatch.error_code = None
        dispatch.updated_at = datetime.now(UTC)
        db.commit()


def _mark_dispatch_failed(
    dispatch_id: int,
    exc: BaseException,
    *,
    task_id: str | None = None,
    session_factory=None,
) -> None:
    factory = session_factory or get_session_factory()
    error_code = (
        "transient_fetch_failed"
        if isinstance(exc, TransientFetchError)
        else "ingestion_failed"
    )
    with factory() as db:
        dispatch = db.scalar(
            select(IngestDispatch)
            .where(IngestDispatch.id == dispatch_id)
            .with_for_update()
        )
        if (
            dispatch is None
            or dispatch.state == "completed"
            or (
                task_id is not None
                and dispatch.task_id not in {None, task_id}
            )
        ):
            return
        dispatch.state = "failed"
        dispatch.error_code = error_code
        dispatch.updated_at = datetime.now(UTC)
        item = db.get(ContentItem, dispatch.item_id)
        if item is not None and item.state != "ready":
            item.state = "failed"
            item.fail_reason = error_code
        db.commit()


def ingest_url(url: str, *, user_id: int, why_saved: str | None = None, connector=None, embedder=None, object_store=None, session_factory=None) -> tuple[int, str]:
    connector = connector or _connector(url)
    item_id = create_item(url, user_id=user_id, why_saved=why_saved, connector=connector, session_factory=session_factory)
    try:
        state = process_item(item_id, connector=connector, embedder=embedder, object_store=object_store, session_factory=session_factory)
    except Exception as exc:
        _mark_failed(item_id, exc, session_factory=session_factory)
        raise
    return item_id, state


def _mark_failed(item_id: int, exc: BaseException, *, session_factory=None) -> None:
    factory = session_factory or get_session_factory()
    with factory() as db:
        item = db.get(ContentItem, item_id)
        if item is not None:
            item.state = "failed"
            item.fail_reason = (
                "transient_fetch_failed"
                if isinstance(exc, TransientFetchError)
                else "ingestion_failed"
            )
            db.commit()


def run_isolated_batch(items: list[Any], worker: Callable[[Any], Any], *, max_retries: int = 5, sleep: Callable[[float], None] = time.sleep) -> list[Any]:
    """Run independent items; a throttled item never pauses or cancels peers."""
    results: list[Any] = [None] * len(items)
    pending = list(enumerate(items))
    for attempt in range(max_retries + 1):
        retry: list[tuple[int, Any]] = []
        for index, item in pending:
            try:
                results[index] = worker(item)
            except TransientFetchError:
                retry.append((index, item))
        if not retry or attempt == max_retries:
            break
        sleep(min(8 * 2**attempt, 600))
        pending = retry
    return results
