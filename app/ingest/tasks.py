"""Synchronous ingestion core plus isolated Celery retry wrapper."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError
from celery import Celery, Task
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.connectors.base import NeedsASR, NeedsExtension, TextResult, TransientFetchError
from app.connectors.youtube import YouTubeConnector
from app.db import get_session_factory
from app.ingest.chunker import chunk
from app.ingest.embed import ZhipuEmbedder
from app.ingest.validate import guard_transcript
from app.models import AppUser, ContentItem, Segment


celery_app = Celery("kb", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"), backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
celery_app.conf.task_routes = {"app.ingest.tasks.fetch_text_task": {"queue": "ingest"}}


class RawObjectStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.minio_bucket
        self.client = boto3.client("s3", endpoint_url=settings.minio_endpoint_url, aws_access_key_id=settings.minio_access_key, aws_secret_access_key=settings.minio_secret_key)

    def put(self, key: str, body: bytes, content_type: str) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)


def _connector(url: str) -> YouTubeConnector:
    connector = YouTubeConnector()
    if connector.match(url):
        return connector
    raise ValueError(f"unsupported URL: {url}")


def create_item(url: str, *, user_id: int = 1, why_saved: str | None = None, connector: Any | None = None, session_factory=None) -> int:
    connector = connector or _connector(url)
    platform_id = connector.match(url)
    if not platform_id:
        raise ValueError(f"connector does not match URL: {url}")
    meta = connector.fetch_meta(platform_id)
    factory = session_factory or get_session_factory()
    with factory() as db:
        if db.get(AppUser, user_id) is None:
            db.add(AppUser(id=user_id))
            db.flush()
        existing = db.scalar(select(ContentItem).where(ContentItem.user_id == user_id, ContentItem.platform == connector.platform, ContentItem.platform_id == platform_id))
        if existing:
            return existing.id
        item = ContentItem(user_id=user_id, platform=connector.platform, platform_id=platform_id, kind="video", url=meta.url, title=meta.title, author=meta.author, published_at=meta.published_at, duration_sec=meta.duration_sec, lang=meta.lang, description=meta.description, tags=meta.tags, chapters=meta.chapters, cover_url=meta.cover_url, why_saved=why_saved, state="fetching")
        db.add(item)
        db.commit()
        return item.id


def process_item(item_id: int, *, connector: Any | None = None, embedder: Any | None = None, object_store: Any | None = None, session_factory=None) -> str:
    factory = session_factory or get_session_factory()
    with factory() as db:
        item = db.get(ContentItem, item_id)
        if item is None:
            raise LookupError(f"content item {item_id} not found")
        connector = connector or _connector(item.url)
        connector.fetch_meta(item.platform_id)
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
        (object_store or RawObjectStore()).put(key, result.raw_body, "application/json")
        item.raw_object_key = key
        item.content_hash = hashlib.sha256("\n".join(c.text.strip() for c in result.cues).encode()).hexdigest()
        item.text_source = result.source
        item.lang = result.lang
        item.state = "chunking"
        db.flush()
        if embedder is None:
            settings = get_settings()
            embedder = ZhipuEmbedder(
                settings.zhipu_api_key or "",
                model=settings.embedding_model,
                endpoint=settings.embedding_endpoint,
                dimensions=settings.embedding_dimensions,
                batch_size=settings.embedding_batch_size,
            )
        semantic = lambda texts: embedder.embed(texts)
        chunks = chunk(result.cues, lang=result.lang, chapters=item.chapters, semantic_embedder=semantic)
        vectors = embedder.embed([part.text for part in chunks])
        if len(vectors) != len(chunks):
            raise ValueError(
                f"embedding count mismatch: expected {len(chunks)}, got {len(vectors)}"
            )
        db.execute(delete(Segment).where(Segment.item_id == item.id))
        item.state = "embedding"
        for seq, (part, vector) in enumerate(zip(chunks, vectors, strict=True)):
            fts = func.to_tsvector("english", part.text) if not result.lang.startswith("zh") else None
            db.add(Segment(item_id=item.id, seq=seq, start_sec=part.start_sec, end_sec=part.end_sec, text=part.text, embedding=vector, fts=fts, boundary_kind=part.boundary_kind))
        item.state = "ready"
        item.fail_reason = None
        db.commit()
        return item.state


class IngestTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        if args:
            _mark_failed(args[0], exc)


@celery_app.task(bind=True, base=IngestTask, autoretry_for=(TransientFetchError,), max_retries=5, retry_backoff=8, retry_backoff_max=600, retry_jitter=True)
def fetch_text_task(self, item_id: int) -> str:
    return process_item(item_id)


def ingest_url(url: str, *, user_id: int = 1, why_saved: str | None = None, connector=None, embedder=None, object_store=None, session_factory=None) -> tuple[int, str]:
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
            item.fail_reason = str(exc)
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
