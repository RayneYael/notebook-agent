"""Trusted action execution behind model-visible schemas."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal

from app.agent.types import AgentRequest
from app.channels.pending_actions import (
    ConfirmationResult,
    PendingConfirmationService,
    PendingSaveSnapshot,
    PendingValidationError,
)
from app.ingest.submission import (
    BatchSaveResult,
    BatchValidationError,
    IngestSubmissionService,
    normalize_item_reference,
)


class ActionInputMismatch(ValueError):
    """Model action arguments do not exactly cover current-message inputs."""


@dataclass(frozen=True)
class AgentActionServices:
    submission: IngestSubmissionService
    pending: PendingConfirmationService


@dataclass(frozen=True)
class ActionOutcome:
    status: Literal["ok", "failed"]
    error_code: str
    text: str
    results: tuple[dict, ...]

    def tool_payload(self) -> dict:
        return {
            "status": self.status,
            "error_code": self.error_code,
            "results": list(self.results),
        }


class AgentActionRuntime:
    """Execute at most one terminal action from trusted request context."""

    def __init__(
        self,
        request: AgentRequest,
        services: AgentActionServices | None,
        *,
        enabled: bool,
    ) -> None:
        self._request = request
        self._services = services
        self._enabled = enabled
        self.outcome: ActionOutcome | None = None
        self.input_mismatch = False
        self._pending_snapshot: PendingSaveSnapshot | None = None
        self._pending_snapshot_read = False

    def pending_save_snapshot(self) -> PendingSaveSnapshot:
        """Read the trusted pending summary at most once for this Agent run."""

        if self._pending_snapshot_read:
            return self._pending_snapshot or PendingSaveSnapshot(active=False)
        self._pending_snapshot_read = True
        if not self._enabled or self._services is None:
            self._pending_snapshot = PendingSaveSnapshot(active=False)
            return self._pending_snapshot
        try:
            snapshot = self._services.pending.inspect_save(
                self._request.tenant,
                self._request.thread_db_id,
            )
        except Exception:
            snapshot = PendingSaveSnapshot(active=False)
        # Keep the runtime boundary fail-closed even if an alternate service
        # implementation returns an object outside the public contract.
        if (
            not isinstance(snapshot, PendingSaveSnapshot)
            or not snapshot.active
            or not 1 <= snapshot.count <= 10
        ):
            snapshot = PendingSaveSnapshot(active=False)
        self._pending_snapshot = snapshot
        return snapshot

    def request_confirmation(self, urls: list[str]) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._availability_failure()
        if unavailable is not None:
            return unavailable
        if not self._urls_match_message_batch(urls):
            self.input_mismatch = True
            raise ActionInputMismatch("action_url_batch_mismatch")
        try:
            result = self._services.pending.request_save(
                self._request.tenant,
                self._request.thread_db_id,
                urls,
            )
        except (BatchValidationError, PendingValidationError) as exc:
            return self._finish(self._failure(exc.error_code))
        except Exception:
            return self._finish(self._failure("save_failed"))
        count = len(result.urls)
        text = (
            "需要把这个视频保存到知识库吗？"
            if count == 1
            else f"需要把这 {count} 个视频保存到知识库吗？"
        )
        return self._finish(
            ActionOutcome(
                "ok",
                "save_confirmation_required",
                text,
                (
                    {
                        "result_id": "A1",
                        "status": "confirmation_required",
                        "count": count,
                        "action_id": result.action_id,
                    },
                ),
            )
        )

    def save_videos(
        self,
        urls: list[str],
        *,
        why_saved: str | None,
    ) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._availability_failure()
        if unavailable is not None:
            return unavailable
        if not self._urls_match_message_batch(urls):
            self.input_mismatch = True
            raise ActionInputMismatch("action_url_batch_mismatch")
        return self._submit(
            urls,
            why_saved=why_saved,
            request_key=(
                f"{self._request.thread_public_id}:"
                f"{self._request.message_id}:save"
            ),
        )

    def confirm(self) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._availability_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.pending.confirm_save(
                self._request.tenant,
                self._request.thread_db_id,
                message_id=self._request.message_id,
            )
        except Exception:
            return self._finish(self._failure("save_failed"))
        if result.status != "confirmed":
            return self._finish(self._confirmation_failure(result))
        return self._submit(
            list(result.urls),
            why_saved=None,
            request_key=(
                f"{self._request.thread_public_id}:"
                f"{self._request.message_id}:confirm"
            ),
        )

    def clarify_confirmation(self) -> ActionOutcome:
        """Return a canonical clarification without changing pending state."""

        if self.outcome is not None:
            return self.outcome
        unavailable = self._availability_failure()
        if unavailable is not None:
            return unavailable
        snapshot = self.pending_save_snapshot()
        if not snapshot.active:
            return self._finish(self._failure("confirmation_missing"))
        text = (
            "需要把这个视频保存到知识库吗？"
            if snapshot.count == 1
            else f"需要把这 {snapshot.count} 个视频保存到知识库吗？"
        )
        return self._finish(
            ActionOutcome(
                "ok",
                "save_confirmation_required",
                text,
                (
                    {
                        "result_id": "A1",
                        "status": "confirmation_required",
                        "count": snapshot.count,
                    },
                ),
            )
        )

    def cancel(self) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._availability_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.pending.cancel_save(
                self._request.tenant,
                self._request.thread_db_id,
            )
        except Exception:
            return self._finish(self._failure("save_failed"))
        if result.status == "cancelled":
            return self._finish(
                ActionOutcome(
                    "ok",
                    "save_cancelled",
                    "已取消保存。",
                    (
                        {
                            "result_id": "A1",
                            "status": "cancelled",
                            "action_id": result.action_id,
                        },
                    ),
                )
            )
        return self._finish(self._confirmation_failure(result))

    def _submit(
        self,
        urls: list[str],
        *,
        why_saved: str | None,
        request_key: str,
    ) -> ActionOutcome:
        try:
            result = self._services.submission.submit_urls(
                self._request.tenant,
                urls,
                why_saved=why_saved,
                request_key=request_key,
            )
        except BatchValidationError as exc:
            return self._finish(self._failure(exc.error_code))
        except Exception:
            return self._finish(self._failure("save_failed"))
        return self._finish(self._batch_outcome(result))

    def _availability_failure(self) -> ActionOutcome | None:
        if self._enabled and self._services is not None:
            return None
        return self._finish(self._failure("save_unavailable"))

    def _finish(self, outcome: ActionOutcome) -> ActionOutcome:
        if self.outcome is None:
            self.outcome = outcome
        return self.outcome

    def finalize_input_mismatch(self) -> ActionOutcome:
        """Create one durable safe outcome after tool retries are exhausted."""

        return self._finish(self._failure("invalid_url"))

    def _urls_match_message_batch(self, urls: list[str]) -> bool:
        current = [
            value.rstrip(".,!?)]}，。！？》」")
            for value in re.findall(
                r"https?://[^\s<>]+", self._request.question
            )
        ]
        provided = [
            str(value).strip().rstrip(".,!?)]}，。！？》」")
            for value in urls
        ]
        # Preserve the invalid-input contract for a bare non-URL: exact
        # coverage succeeds, then pending validation classifies it safely.
        if not current and len(provided) == 1:
            bare = self._request.question.strip()
            if bare == provided[0]:
                current = [bare]
        return [self._url_match_key(value) for value in provided] == [
            self._url_match_key(value) for value in current
        ]

    @staticmethod
    def _url_match_key(value: str) -> tuple[str, str]:
        try:
            reference = normalize_item_reference(value)
        except ValueError:
            return ("literal", value)
        return ("canonical", reference.canonical_url)

    @staticmethod
    def _batch_outcome(result: BatchSaveResult) -> ActionOutcome:
        rows = tuple(asdict(value) for value in result.results)
        queued = sum(value.status == "queued" for value in result.results)
        already_exists = sum(
            value.status == "already_exists" for value in result.results
        )
        accepted = queued + already_exists
        failed = len(result.results) - accepted
        if accepted and failed:
            status, code = "ok", "save_partial"
        elif accepted:
            status, code = "ok", "save_accepted"
        else:
            status, code = "failed", "save_failed"
        safe_messages = {
            "queued": "已加入处理队列。",
            "already_exists": "知识库中已存在，无需重复保存。",
            "unsupported_url": "暂不支持此链接，请换用受支持的视频链接。",
            "invalid_url": "链接无效，请检查后重新发送。",
            "queue_unavailable": "处理队列暂时不可用，请稍后重试该链接。",
            "create_failed": "创建保存记录失败，请稍后重试。",
        }
        details = "\n".join(
            f"- [{value.result_id}] {safe_messages[value.status]}"
            for value in result.results
        )
        text = (
            f"处理完成：共 {len(result.results)} 个，"
            f"已入队 {queued} 个，已存在 {already_exists} 个，失败 {failed} 个。"
        )
        if details:
            text = f"{text}\n{details}"
        return ActionOutcome(status, code, text, rows)

    @staticmethod
    def _failure(code: str) -> ActionOutcome:
        messages = {
            "batch_too_large": "一次最多保存 10 个视频，请拆分后重发。",
            "empty_batch": "请提供需要保存的视频链接。",
            "invalid_url": "只能保存当前消息中提供的有效视频链接。",
            "unsupported_url": "当前不支持这个视频链接。",
            "save_unavailable": "保存功能暂时不可用，请稍后重试。",
            "confirmation_missing": "待确认链接已失效，请重新发送链接。",
            "confirmation_expired": "待确认链接已过期，请重新发送链接。",
        }
        return ActionOutcome(
            "failed",
            code,
            messages.get(code, "视频保存暂时失败，请稍后重试。"),
            (
                {
                    "result_id": "A1",
                    "status": code,
                    "safe_error_code": code,
                },
            ),
        )

    @classmethod
    def _confirmation_failure(
        cls, result: ConfirmationResult
    ) -> ActionOutcome:
        code = (
            "confirmation_expired"
            if result.status == "confirmation_expired"
            else "confirmation_missing"
        )
        return cls._failure(code)
