"""Durable, tenant-bound pending channel action lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.channels.types import TenantContext
from app.ingest.submission import normalize_item_reference, prepare_submission
from app.models import ConversationThread, PendingChannelAction


@dataclass(frozen=True)
class ConfirmationResult:
    status: Literal[
        "confirmation_required",
        "confirmed",
        "cancelled",
        "confirmation_missing",
        "confirmation_expired",
    ]
    urls: tuple[str, ...] = ()
    action_id: int | None = None
    replayed: bool = False


@dataclass(frozen=True)
class PendingSaveSnapshot:
    """Minimal server-owned state that may be shown to the Agent."""

    active: bool
    count: int = 0


class PendingValidationError(ValueError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class PendingConfirmationService:
    """Persist and atomically consume one save batch per conversation."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("pending confirmation TTL must be positive")
        self._session_factory = session_factory
        self._ttl = ttl

    def request_save(
        self,
        tenant: TenantContext,
        thread_id: int,
        urls: list[str],
    ) -> ConfirmationResult:
        canonical_urls = self._canonical_urls(urls)
        with self._session_factory() as db:
            thread = self._lock_thread(db, tenant, thread_id)
            if thread is None:
                return ConfirmationResult("confirmation_missing")
            now = db.scalar(select(func.now()))
            current = self._active(db, thread.id)
            if current is not None:
                current.cancelled_at = now
                db.flush()
            action = PendingChannelAction(
                thread_id=thread.id,
                kind="save_videos",
                payload={"version": 1, "urls": list(canonical_urls)},
                expires_at=now + self._ttl,
            )
            db.add(action)
            db.flush()
            action_id = action.id
            db.commit()
        return ConfirmationResult(
            "confirmation_required",
            urls=canonical_urls,
            action_id=action_id,
        )

    def confirm_save(
        self,
        tenant: TenantContext,
        thread_id: int,
        *,
        message_id: str,
    ) -> ConfirmationResult:
        if not message_id.strip():
            raise ValueError("message id is required")
        with self._session_factory() as db:
            thread = self._lock_thread(db, tenant, thread_id)
            if thread is None:
                return ConfirmationResult("confirmation_missing")
            replay = db.scalar(
                select(PendingChannelAction)
                .where(
                    PendingChannelAction.thread_id == thread.id,
                    PendingChannelAction.kind == "save_videos",
                    PendingChannelAction.consumed_message_id == message_id,
                    PendingChannelAction.consumed_at.is_not(None),
                )
                .order_by(PendingChannelAction.id.desc())
                .limit(1)
            )
            if replay is not None:
                urls = self._payload_urls(replay)
                if urls is None:
                    return ConfirmationResult("confirmation_missing")
                return ConfirmationResult(
                    "confirmed",
                    urls=urls,
                    action_id=replay.id,
                    replayed=True,
                )

            current = self._active(db, thread.id)
            if current is None:
                return ConfirmationResult("confirmation_missing")
            now = db.scalar(select(func.now()))
            if current.expires_at <= now:
                current.cancelled_at = now
                db.commit()
                return ConfirmationResult("confirmation_expired")
            urls = self._payload_urls(current)
            if urls is None:
                current.cancelled_at = now
                db.commit()
                return ConfirmationResult("confirmation_missing")
            current.consumed_at = now
            current.consumed_message_id = message_id
            db.commit()
            return ConfirmationResult(
                "confirmed",
                urls=urls,
                action_id=current.id,
            )

    def cancel_save(
        self,
        tenant: TenantContext,
        thread_id: int,
    ) -> ConfirmationResult:
        with self._session_factory() as db:
            thread = self._lock_thread(db, tenant, thread_id)
            if thread is None:
                return ConfirmationResult("confirmation_missing")
            current = self._active(db, thread.id)
            if current is None:
                return ConfirmationResult("confirmation_missing")
            now = db.scalar(select(func.now()))
            if current.expires_at <= now:
                current.cancelled_at = now
                db.commit()
                return ConfirmationResult("confirmation_expired")
            current.cancelled_at = now
            db.commit()
            return ConfirmationResult(
                "cancelled",
                action_id=current.id,
            )

    def inspect_save(
        self,
        tenant: TenantContext,
        thread_id: int,
    ) -> PendingSaveSnapshot:
        """Return a read-only, tenant-bound summary of a live save batch.

        This deliberately does not reuse the consuming path: it neither locks
        rows nor writes expiry/cancellation timestamps, and never exposes the
        persisted URLs or action identifier to the caller.
        """

        try:
            with self._session_factory() as db:
                action = db.scalar(
                    select(PendingChannelAction)
                    .join(
                        ConversationThread,
                        PendingChannelAction.thread_id
                        == ConversationThread.id,
                    )
                    .where(
                        ConversationThread.id == thread_id,
                        ConversationThread.app_user_id
                        == tenant.app_user_id,
                        ConversationThread.channel_identity_id
                        == tenant.channel_identity_id,
                        ConversationThread.closed_at.is_(None),
                        PendingChannelAction.kind == "save_videos",
                        PendingChannelAction.consumed_at.is_(None),
                        PendingChannelAction.cancelled_at.is_(None),
                        PendingChannelAction.expires_at > func.now(),
                    )
                    .order_by(PendingChannelAction.id.desc())
                    .limit(1)
                )
                urls = self._payload_urls(action) if action is not None else None
                if urls is None:
                    return PendingSaveSnapshot(active=False)
                return PendingSaveSnapshot(active=True, count=len(urls))
        except Exception:
            # This context is advisory only. A database failure must not leak
            # pending data or make an unverified batch actionable.
            return PendingSaveSnapshot(active=False)

    @staticmethod
    def _lock_thread(
        db: Session,
        tenant: TenantContext,
        thread_id: int,
    ) -> ConversationThread | None:
        return db.scalar(
            select(ConversationThread)
            .where(
                ConversationThread.id == thread_id,
                ConversationThread.app_user_id == tenant.app_user_id,
                ConversationThread.channel_identity_id
                == tenant.channel_identity_id,
                ConversationThread.closed_at.is_(None),
            )
            .with_for_update()
        )

    @staticmethod
    def _active(
        db: Session, thread_id: int
    ) -> PendingChannelAction | None:
        return db.scalar(
            select(PendingChannelAction)
            .where(
                PendingChannelAction.thread_id == thread_id,
                PendingChannelAction.kind == "save_videos",
                PendingChannelAction.consumed_at.is_(None),
                PendingChannelAction.cancelled_at.is_(None),
            )
            .order_by(PendingChannelAction.id.desc())
            .limit(1)
            .with_for_update()
        )

    @staticmethod
    def _canonical_urls(urls: list[str]) -> tuple[str, ...]:
        prepared = prepare_submission(urls)
        canonical: list[str] = []
        for item in prepared.items:
            if item.failure is not None:
                raise PendingValidationError(
                    item.failure.safe_error_code or item.failure.status
                )
            if item.reference is None:
                raise PendingValidationError("invalid_url")
            canonical.append(item.reference.canonical_url)
        return tuple(canonical)

    @staticmethod
    def _payload_urls(
        action: PendingChannelAction,
    ) -> tuple[str, ...] | None:
        payload = action.payload
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return None
        urls = payload.get("urls")
        if not isinstance(urls, list) or not 1 <= len(urls) <= 10:
            return None
        canonical_urls: list[str] = []
        for url in urls:
            if not isinstance(url, str):
                return None
            try:
                reference = normalize_item_reference(url)
            except ValueError:
                return None
            # Pending rows are written only by ``request_save`` after
            # canonicalization. Requiring byte-for-byte equality prevents a
            # manually corrupted, whitespace-padded, abbreviated, or merely
            # supported URL from becoming trusted model context.
            if url != reference.canonical_url:
                return None
            canonical_urls.append(reference.canonical_url)
        return tuple(canonical_urls)
