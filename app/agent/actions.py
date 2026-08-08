"""Trusted action execution behind model-visible schemas."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Annotated, Literal

from pydantic import Field

from app.agent.types import AgentRequest
from app.channels.pending_actions import (
    ConfirmationResult,
    PendingConfirmationService,
    PendingSaveSnapshot,
    PendingValidationError,
)
from app.agent.management import (
    BatchItemOperationResult,
    ItemNotFound,
    KnowledgeItemManagementService,
    ManagementError,
    SavedItemPage,
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
    management: KnowledgeItemManagementService | None = None


@dataclass(frozen=True)
class ActionOutcome:
    status: Literal["ok", "failed"]
    error_code: str
    text: str
    results: tuple[dict, ...]
    # Management outcomes are safe, server-rendered context for the next
    # turn.  Save/pending actions keep their historical empty model message
    # contract so raw URLs and confirmation state never enter model history.
    history_visible: bool = False

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
        management_enabled: bool | None = None,
    ) -> None:
        self._request = request
        self._services = services
        self._enabled = enabled
        self._management_enabled = enabled if management_enabled is None else management_enabled
        self.outcome: ActionOutcome | None = None
        self.input_mismatch = False
        self._pending_snapshot: PendingSaveSnapshot | None = None
        self._pending_snapshot_read = False

    def pending_delete_snapshot(self):
        if not self._management_enabled or self._services is None or self._services.management is None:
            return None
        try:
            return self._services.pending.inspect_delete(
                self._request.tenant, self._request.thread_db_id
            )
        except Exception:
            return None

    def _management_failure(self) -> ActionOutcome | None:
        if self._management_enabled and self._services is not None and self._services.management is not None:
            return None
        return self._finish(self._failure("management_unavailable"))

    def list_saved_items(self, **filters) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            page: SavedItemPage = self._services.management.list_items(  # type: ignore[union-attr]
                self._request.tenant, **filters
            )
        except ManagementError as exc:
            return self._finish(self._failure(exc.error_code))
        except Exception:
            return self._finish(self._failure("management_failed"))
        rows = [item.model_dump(mode="json") for item in page.items]
        if not rows:
            text = "回收站里没有可恢复条目。" if filters.get("location") == "trash" else "知识库里还没有保存的条目。"
        else:
            text = _render_inventory_rows(rows, location=filters.get("location", "library"))
        if page.next_cursor:
            text += "\n如需下一页，请把安全翻页标记原样交给助手继续：" + page.next_cursor
        # Keep the keyset cursor in the canonical result so a repeated
        # channel delivery can resume the same bounded page without rerunning
        # retrieval or exposing a tenant credential.
        page_result = {"items": rows, "next_cursor": page.next_cursor}
        return self._finish(
            ActionOutcome(
                "ok", "items_listed", text, (page_result,), history_visible=True
            )
        )

    def get_saved_item(self, item_id: int) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            item = self._services.management.get_item(self._request.tenant, item_id)  # type: ignore[union-attr]
        except ManagementError as exc:
            return self._finish(self._failure(exc.error_code))
        except Exception:
            return self._finish(self._failure("management_failed"))
        row = item.model_dump(mode="json")
        text = _render_inventory_rows([row], location="library", detail=True)
        return self._finish(
            ActionOutcome("ok", "item_read", text, (row,), history_visible=True)
        )

    def update_saved_item(self, item_id: int, why_saved: str | None) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.management.update_why_saved(self._request.tenant, item_id, why_saved)  # type: ignore[union-attr]
        except ManagementError as exc:
            return self._finish(self._failure(exc.error_code))
        except Exception:
            return self._finish(self._failure("management_failed"))
        text = "已更新收藏原因。" if result.status == "updated" else "收藏原因没有变化。"
        return self._finish(
            ActionOutcome(
                "ok", "item_updated", text, (result.model_dump(),),
                history_visible=True,
            )
        )

    def request_delete(self, item_ids: list[int]) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.pending.request_delete(  # type: ignore[union-attr]
                self._request.tenant,
                self._request.thread_db_id,
                item_ids,
                management=self._services.management,  # type: ignore[union-attr]
                request_message_id=self._request.message_id,
                latest_turn_message_id=self._request.latest_turn_message_id,
            )
        except ManagementError as exc:
            return self._finish(self._failure(exc.error_code))
        except Exception:
            return self._finish(self._failure("management_failed"))
        if result.status == "effect_in_progress":
            return self._finish(self._failure("delete_in_progress"))
        if result.status != "confirmation_required":
            return self._finish(
                self._failure(result.error_code or "confirmation_missing")
            )
        count = len(result.item_ids)
        text = "确认要删除这个条目吗？" if count == 1 else f"确认要删除这 {count} 个条目吗？"
        if result.confirmation_code:
            text += f"\n请回复“确认删除 {result.confirmation_code}”完成本次确认。"
        return self._finish(
            ActionOutcome(
                "ok", "confirmation_required", text,
                (({"status": "confirmation_required", "count": count},)),
                history_visible=True,
            )
        )

    def confirm_delete(self) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            confirmation, result = self._services.pending.confirm_delete(  # type: ignore[union-attr]
                self._request.tenant,
                self._request.thread_db_id,
                message_id=self._request.message_id,
                message_text=self._request.question,
                management=self._services.management,  # type: ignore[union-attr]
                latest_turn_message_id=self._request.latest_turn_message_id,
            )
        except Exception:
            return self._finish(self._failure("confirmation_missing"))
        if confirmation.status == "effect_failed":
            return self._finish(self._failure("delete_failed"))
        if confirmation.status == "effect_in_progress":
            return self._finish(self._failure("delete_in_progress"))
        if confirmation.status != "confirmed":
            return self._finish(self._failure("confirmation_expired" if confirmation.status == "confirmation_expired" else "confirmation_missing"))
        if result is None:
            # Duplicate delivery has already consumed the durable action; the
            # original turn is replayed by ChannelService before this method.
            rows = confirmation.results
            return self._finish(
                ActionOutcome(
                    "ok", "items_deleted", _delete_outcome_text(rows), rows,
                    history_visible=True,
                )
            )
        rows = tuple(value.model_dump() for value in result.results)
        return self._finish(
            ActionOutcome(
                "ok", "items_deleted", _delete_outcome_text(rows), rows,
                history_visible=True,
            )
        )

    def clarify_delete(self) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.pending.clarify_delete(  # type: ignore[union-attr]
                self._request.tenant,
                self._request.thread_db_id,
                message_id=self._request.message_id,
                latest_turn_message_id=self._request.latest_turn_message_id,
            )
        except Exception:
            return self._finish(self._failure("confirmation_missing"))
        if result.status != "confirmation_required":
            return self._finish(
                self._failure(
                    "confirmation_expired"
                    if result.status == "confirmation_expired"
                    else "confirmation_missing"
                )
            )
        count = len(result.item_ids)
        text = "确认要删除这个条目吗？" if count == 1 else f"确认要删除这 {count} 个条目吗？"
        return self._finish(
            ActionOutcome(
                "ok", "confirmation_required", text,
                (({"status": "confirmation_required", "count": count},)),
            )
        )

    def cancel_delete(self) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.pending.cancel_delete(self._request.tenant, self._request.thread_db_id)  # type: ignore[union-attr]
        except Exception:
            return self._finish(self._failure("confirmation_missing"))
        if result.status == "effect_in_progress":
            return self._finish(self._failure("delete_in_progress"))
        if result.status != "cancelled":
            return self._finish(self._failure("confirmation_expired" if result.status == "confirmation_expired" else "confirmation_missing"))
        return self._finish(
            ActionOutcome(
                "ok", "delete_cancelled", "已取消删除。", (({"status": "cancelled"},)),
                history_visible=True,
            )
        )

    def restore_saved_items(self, item_ids: list[int]) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.management.restore(self._request.tenant, item_ids)  # type: ignore[union-attr]
        except ManagementError as exc:
            return self._finish(self._failure(exc.error_code))
        except Exception:
            return self._finish(self._failure("management_failed"))
        return self._finish(
            ActionOutcome(
                "ok", "items_restored", "已恢复选中的条目。",
                tuple(value.model_dump() for value in result.results),
                history_visible=True,
            )
        )

    def retry_item_ingestion(self, item_id: int) -> ActionOutcome:
        if self.outcome is not None:
            return self.outcome
        unavailable = self._management_failure()
        if unavailable is not None:
            return unavailable
        try:
            result = self._services.submission.retry_item(  # type: ignore[union-attr]
                self._request.tenant,
                item_id,
                request_key=f"{self._request.thread_public_id}:{self._request.message_id}:retry",
            )
        except Exception:
            return self._finish(self._failure("retry_not_allowed"))
        if result.status == "queued":
            return self._finish(
                ActionOutcome(
                    "ok", "retry_queued", "已重新加入处理队列。", (asdict(result),),
                    history_visible=True,
                )
            )
        return self._finish(
            ActionOutcome(
                "failed", result.safe_error_code or "retry_not_allowed",
                "这个条目当前不能重试。", (asdict(result),),
                history_visible=True,
            )
        )

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
        if result.status == "effect_in_progress":
            return self._finish(self._failure(result.error_code or "save_failed"))
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
        restored = sum(value.status == "restored" for value in result.results)
        accepted = queued + already_exists + restored
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
            "restored": "已从回收站恢复。",
            "purge_in_progress": "该条目正在清理，请稍后再试。",
            "retry_not_allowed": "该条目当前不能重试。",
            "unsupported_url": "暂不支持此链接，请换用受支持的视频链接。",
            "invalid_url": "链接无效，请检查后重新发送。",
            "queue_unavailable": "处理队列暂时不可用，请稍后重试该链接。",
            "create_failed": "创建保存记录失败，请稍后重试。",
        }
        details = "\n".join(
            f"- [{value.result_id}] {safe_messages[value.status]}"
            for value in result.results
        )
        if restored:
            summary = f"已入队 {queued} 个，已存在 {already_exists} 个，恢复 {restored} 个，失败 {failed} 个。"
        else:
            summary = f"已入队 {queued} 个，已存在 {already_exists} 个，失败 {failed} 个。"
        text = f"处理完成：共 {len(result.results)} 个，{summary}"
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
            "confirmation_expired": "待确认链接已过期，请重新发送链接。",
            "confirmation_missing": "待确认操作已失效，请重新发起操作。",
            "management_unavailable": "知识库管理功能暂时不可用，请稍后重试。",
            "management_failed": "知识库管理操作暂时失败，请稍后重试。",
            "delete_failed": "删除操作未完成，请稍后重试确认。",
            "delete_in_progress": "删除确认正在处理中，请稍后再试。",
            "item_not_found": "找不到这个知识库条目。",
            "invalid_cursor": "翻页标记无效，请重新开始翻页。",
            "invalid_batch": "一次最多操作 10 个条目。",
            "invalid_why_saved": "收藏原因不能为空格且最多 500 个字符。",
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


def _render_inventory_rows(
    rows: list[dict], *, location: str, detail: bool = False
) -> str:
    """Render bounded public metadata for channels that only print answer.text."""

    lines = ["知识库条目详情：" if detail else "知识库条目："]
    for row in rows[:50]:
        title = str(row.get("title") or "未命名条目")[:120]
        item_id = row.get("item_id", "?")
        state = str(row.get("ingestion_state") or "unknown")[:40]
        why = row.get("why_saved")
        saved = str(row.get("saved_at") or "")[:32]
        line = f"- #{item_id}《{title}》· 状态：{state}"
        if detail:
            platform = str(row.get("platform") or "")[:24]
            url = str(row.get("url") or "")[:300]
            author = str(row.get("author") or "")[:120]
            duration = row.get("duration_sec")
            if platform:
                line += f" · 平台：{platform}"
            if author:
                line += f" · 作者：{author}"
            if duration is not None:
                line += f" · 时长：{duration} 秒"
            if url:
                line += f" · 链接：{url}"
        if saved:
            line += f" · 保存于 {saved}"
        if why:
            line += f" · 收藏原因：{str(why)[:200]}"
        if location == "trash":
            if row.get("restorable"):
                line += " · 可恢复"
            else:
                line += " · 已不可恢复或正在清理"
            expires = row.get("expires_at")
            if expires:
                line += f" · 到期 {str(expires)[:32]}"
        lines.append(line)
    return "\n".join(lines)


def _delete_outcome_text(rows: tuple[dict, ...]) -> str:
    """Render per-item delete fences without claiming stale effects succeeded."""

    counts: dict[str, int] = {}
    for row in rows:
        status = row.get("status") if isinstance(row, dict) else None
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1
    deleted = counts.get("deleted", 0)
    already_deleted = counts.get("already_deleted", 0)
    already_restored = counts.get("already_restored", 0)
    parts: list[str] = []
    if deleted:
        parts.append("已移入回收站。" if deleted == len(rows) else f"已移入回收站 {deleted} 个条目。")
    if already_deleted:
        parts.append(f"{already_deleted} 个条目此前已在回收站。")
    if already_restored:
        parts.append(f"{already_restored} 个条目已恢复，未重复删除。")
    known = deleted + already_deleted + already_restored
    if known < len(rows):
        parts.append(f"{len(rows) - known} 个条目的删除状态未改变，请稍后重试。")
    return " ".join(parts) or "删除操作未发生。"
