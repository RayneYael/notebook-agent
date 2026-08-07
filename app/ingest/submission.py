"""Tenant-bound asynchronous ingestion submission contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels.types import TenantContext
from app.connectors.youtube import YouTubeConnector
from app.models import ContentItem, IngestDispatch


class BatchValidationError(ValueError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class EmptyBatch(BatchValidationError):
    def __init__(self) -> None:
        super().__init__("empty_batch")


class BatchTooLarge(BatchValidationError):
    def __init__(self) -> None:
        super().__init__("batch_too_large")


class InvalidURL(ValueError):
    pass


class UnsupportedURL(ValueError):
    pass


@dataclass(frozen=True)
class ItemReference:
    platform: str
    platform_id: str
    canonical_url: str


@dataclass(frozen=True)
class SaveItemResult:
    result_id: str
    input_index: int
    status: Literal[
        "queued",
        "already_exists",
        "unsupported_url",
        "invalid_url",
        "queue_unavailable",
        "create_failed",
    ]
    item_id: int | None = None
    state: str | None = None
    safe_error_code: str | None = None


@dataclass(frozen=True)
class BatchSaveResult:
    results: tuple[SaveItemResult, ...]


@dataclass(frozen=True)
class PreparedItem:
    input_index: int
    reference: ItemReference | None = None
    failure: SaveItemResult | None = None


@dataclass(frozen=True)
class PreparedBatch:
    items: tuple[PreparedItem, ...]


def normalize_item_reference(url: str) -> ItemReference:
    """Normalize one supported item URL without remote connector calls."""

    value = str(url).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidURL("invalid URL")
    hostname = (parsed.hostname or "").lower()
    if hostname not in {
        "youtu.be",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    }:
        raise UnsupportedURL("unsupported URL")
    connector = YouTubeConnector()
    platform_id = connector.match(value)
    if platform_id is None:
        raise UnsupportedURL("unsupported URL")
    return ItemReference(
        platform=connector.platform,
        platform_id=platform_id,
        canonical_url=f"https://www.youtube.com/watch?v={platform_id}",
    )


def prepare_submission(urls: list[str]) -> PreparedBatch:
    """Validate a bounded batch before any persistence or queue side effect."""

    values = list(urls)
    if not values:
        raise EmptyBatch()
    if len(values) > 10:
        raise BatchTooLarge()

    items: list[PreparedItem] = []
    for index, url in enumerate(values):
        try:
            reference = normalize_item_reference(url)
        except InvalidURL:
            items.append(
                PreparedItem(
                    input_index=index,
                    failure=SaveItemResult(
                        result_id=f"A{index + 1}",
                        input_index=index,
                        status="invalid_url",
                        safe_error_code="invalid_url",
                    ),
                )
            )
        except UnsupportedURL:
            items.append(
                PreparedItem(
                    input_index=index,
                    failure=SaveItemResult(
                        result_id=f"A{index + 1}",
                        input_index=index,
                        status="unsupported_url",
                        safe_error_code="unsupported_url",
                    ),
                )
            )
        else:
            items.append(PreparedItem(input_index=index, reference=reference))
    return PreparedBatch(tuple(items))


class IngestSubmissionService:
    """Create tenant-owned pending items and publish durable dispatch IDs."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        publisher: Callable[[int], str | None],
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher

    def submit_urls(
        self,
        tenant: TenantContext,
        urls: list[str],
        *,
        why_saved: str | None,
        request_key: str,
    ) -> BatchSaveResult:
        if not request_key.strip():
            raise ValueError("request key is required")
        prepared = prepare_submission(urls)
        results: list[SaveItemResult] = []
        for item in prepared.items:
            if item.failure is not None:
                results.append(item.failure)
                continue
            results.append(
                self._submit_reference(
                    tenant,
                    item,
                    why_saved=why_saved,
                    request_key=request_key,
                )
            )
        return BatchSaveResult(tuple(results))

    def _submit_reference(
        self,
        tenant: TenantContext,
        prepared: PreparedItem,
        *,
        why_saved: str | None,
        request_key: str,
    ) -> SaveItemResult:
        reference = prepared.reference
        if reference is None:
            raise RuntimeError("prepared item has no reference")
        result_id = f"A{prepared.input_index + 1}"
        try:
            with self._session_factory() as db:
                existing = db.scalar(
                    select(ContentItem).where(
                        ContentItem.user_id == tenant.app_user_id,
                        ContentItem.platform == reference.platform,
                        ContentItem.platform_id == reference.platform_id,
                    )
                )
                if existing is not None:
                    replay = db.scalar(
                        select(IngestDispatch).where(
                            IngestDispatch.item_id == existing.id,
                            IngestDispatch.request_key == request_key,
                        )
                    )
                    if replay is not None:
                        return self._existing_result(
                            prepared, existing, replay
                        )
                    if existing.state not in {"pending", "failed"}:
                        return self._already_exists(prepared, existing)
                    latest = db.scalar(
                        select(IngestDispatch)
                        .where(IngestDispatch.item_id == existing.id)
                        .order_by(IngestDispatch.attempt.desc())
                        .limit(1)
                    )
                    if latest is not None and latest.state in {
                        "pending",
                        "enqueued",
                        "running",
                        "completed",
                    }:
                        return self._already_exists(prepared, existing)
                    content = existing
                    content.state = "pending"
                    content.fail_reason = None
                    attempt = (latest.attempt + 1) if latest is not None else 1
                else:
                    content = ContentItem(
                        user_id=tenant.app_user_id,
                        platform=reference.platform,
                        platform_id=reference.platform_id,
                        kind="video",
                        url=reference.canonical_url,
                        why_saved=why_saved,
                        state="pending",
                    )
                    db.add(content)
                    db.flush()
                    attempt = 1
                dispatch = IngestDispatch(
                    public_id=uuid4().hex,
                    item_id=content.id,
                    request_key=request_key,
                    attempt=attempt,
                    state="pending",
                )
                db.add(dispatch)
                db.flush()
                item_id = content.id
                dispatch_id = dispatch.id
                db.commit()
        except IntegrityError:
            return self._result_after_conflict(
                tenant, prepared, reference
            )
        except Exception:
            return SaveItemResult(
                result_id=result_id,
                input_index=prepared.input_index,
                status="create_failed",
                safe_error_code="create_failed",
            )

        try:
            task_id = self._publisher(dispatch_id)
        except Exception:
            self._set_dispatch_state(
                dispatch_id,
                state="failed",
                error_code="queue_unavailable",
            )
            return SaveItemResult(
                result_id=result_id,
                input_index=prepared.input_index,
                status="queue_unavailable",
                item_id=item_id,
                state="pending",
                safe_error_code="queue_unavailable",
            )

        self._set_dispatch_state(
            dispatch_id,
            state="enqueued",
            task_id=task_id,
        )
        return SaveItemResult(
            result_id=result_id,
            input_index=prepared.input_index,
            status="queued",
            item_id=item_id,
            state="pending",
        )

    @staticmethod
    def _already_exists(
        prepared: PreparedItem, content: ContentItem
    ) -> SaveItemResult:
        return SaveItemResult(
            result_id=f"A{prepared.input_index + 1}",
            input_index=prepared.input_index,
            status="already_exists",
            item_id=content.id,
            state=content.state,
        )

    def _existing_result(
        self,
        prepared: PreparedItem,
        content: ContentItem,
        dispatch: IngestDispatch,
    ) -> SaveItemResult:
        if dispatch.state == "pending":
            return self._already_exists(prepared, content)
        if (
            dispatch.state == "failed"
            and dispatch.error_code == "queue_unavailable"
        ):
            return SaveItemResult(
                result_id=f"A{prepared.input_index + 1}",
                input_index=prepared.input_index,
                status="queue_unavailable",
                item_id=content.id,
                state=content.state,
                safe_error_code="queue_unavailable",
            )
        return SaveItemResult(
            result_id=f"A{prepared.input_index + 1}",
            input_index=prepared.input_index,
            status="queued",
            item_id=content.id,
            state=content.state,
        )

    def _result_after_conflict(
        self,
        tenant: TenantContext,
        prepared: PreparedItem,
        reference: ItemReference,
    ) -> SaveItemResult:
        try:
            with self._session_factory() as db:
                existing = db.scalar(
                    select(ContentItem).where(
                        ContentItem.user_id == tenant.app_user_id,
                        ContentItem.platform == reference.platform,
                        ContentItem.platform_id == reference.platform_id,
                    )
                )
                if existing is not None:
                    return self._already_exists(prepared, existing)
        except Exception:
            pass
        return SaveItemResult(
            result_id=f"A{prepared.input_index + 1}",
            input_index=prepared.input_index,
            status="create_failed",
            safe_error_code="create_failed",
        )

    def _set_dispatch_state(
        self,
        dispatch_id: int,
        *,
        state: str,
        task_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        try:
            with self._session_factory() as db:
                dispatch = db.get(IngestDispatch, dispatch_id)
                if dispatch is None or dispatch.state != "pending":
                    return
                dispatch.state = state
                dispatch.task_id = task_id
                dispatch.error_code = error_code
                db.commit()
        except Exception:
            # Publishing may already have succeeded. A worker claims pending
            # dispatches safely, so never overwrite a faster worker transition
            # or expose persistence details to the Agent.
            return
