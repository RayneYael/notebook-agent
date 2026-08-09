"""Turn-local contracts for bounded Agent autonomy.

This module intentionally contains no framework, persistence, or domain-service
integration.  ``TurnTodoStore`` and ``RecoveryLedger`` are created by one Agent
run and should be discarded with that run.  Keeping these contracts separate
from the runtime makes the safety limits easy to test and prevents model-owned
working memory from becoming durable application state.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal


TodoStatus = Literal["pending", "in_progress", "completed", "blocked"]
RecoveryCategory = Literal[
    "transient_read",
    "read_unavailable",
    "missing_context",
    "policy_or_security",
    "side_effect_indeterminate",
    "provider_failure",
    "answer_validation",
]
RecoveryOperation = Literal["read", "mutation", "provider", "answer"]
RecoveryAction = Literal[
    "retry_same_read",
    "use_existing_evidence",
    "return_partial",
    "ask_clarification",
    "report_unavailable",
    "reformulate_search",
    "repair_answer",
]

TODO_STATUSES: frozenset[str] = frozenset(
    {"pending", "in_progress", "completed", "blocked"}
)
MAX_TODO_ITEMS = 6
MAX_TODO_ID_CHARS = 32
MAX_TODO_TITLE_CHARS = 120
MAX_TOTAL_RECOVERY_ACTIONS = 2
MAX_SAME_READ_RECOVERY_RETRIES = 1
MAX_ANSWER_REPAIR_ACTIONS = 1
MAX_MUTATION_RECOVERY_RETRIES = 0
MAX_PROVIDER_RECOVERY_RETRIES = 0

# A todo is intentionally a short, human-readable plan.  These tokens catch
# common attempts to smuggle server-owned references or tool data into it.
_SENSITIVE_TODO_PATTERN = re.compile(
    r"(?:https?://|www\.|\b(?:tenant|thread|pending|claim)(?:[_ -]?id)?\b|"
    r"\b(?:item|segment)[_ -]?id\b|\b(?:tool|raw|request|response)[_ -]?"
    r"(?:arg(?:ument)?s?|payload|result|body)\b|\b(?:citation|evidence)"
    r"\s*(?:id|url|excerpt|:|=)\b|\b(?:sql|postgres(?:ql)?)\b)",
    re.IGNORECASE,
)
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_TODO_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


class TodoValidationError(ValueError):
    """Raised when a turn Todo snapshot violates a server invariant."""


def _validate_todo_text(value: Any, *, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise TodoValidationError(f"{field_name} must be text")
    normalized = value.strip()
    if not normalized:
        raise TodoValidationError(f"{field_name} must not be empty")
    if len(normalized) > limit:
        raise TodoValidationError(f"{field_name} exceeds the bounded length")
    if _CONTROL_CHARACTER_PATTERN.search(normalized):
        raise TodoValidationError(f"{field_name} contains a control character")
    if _SENSITIVE_TODO_PATTERN.search(normalized):
        raise TodoValidationError(f"{field_name} contains server-owned data")
    return normalized


def _validate_todo_id(value: Any) -> str:
    normalized = _validate_todo_text(
        value, field_name="todo id", limit=MAX_TODO_ID_CHARS
    )
    if not _TODO_ID_PATTERN.fullmatch(normalized):
        raise TodoValidationError(
            "todo id must be a short turn-local identifier"
        )
    if _SENSITIVE_TODO_PATTERN.search(normalized):
        raise TodoValidationError("todo id contains server-owned data")
    return normalized


@dataclass(frozen=True, slots=True)
class TurnTodoItem:
    """One short, turn-local Todo step."""

    id: str
    title: str
    status: TodoStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _validate_todo_id(self.id))
        object.__setattr__(
            self,
            "title",
            _validate_todo_text(
                self.title, field_name="todo title", limit=MAX_TODO_TITLE_CHARS
            ),
        )
        if not isinstance(self.status, str) or self.status not in TODO_STATUSES:
            raise TodoValidationError("todo status is not allowed")


def _validate_todo_items(items: tuple[TurnTodoItem, ...]) -> None:
    if len(items) > MAX_TODO_ITEMS:
        raise TodoValidationError(
            f"a turn Todo may contain at most {MAX_TODO_ITEMS} items"
        )
    ids: set[str] = set()
    in_progress = 0
    for item in items:
        if not isinstance(item, TurnTodoItem):
            raise TodoValidationError("todo items must be TurnTodoItem values")
        if item.id in ids:
            raise TodoValidationError("todo ids must be unique")
        ids.add(item.id)
        if item.status == "in_progress":
            in_progress += 1
    if in_progress > 1:
        raise TodoValidationError("at most one todo may be in_progress")


@dataclass(frozen=True, slots=True)
class TurnTodoSnapshot:
    """An immutable, validated replacement snapshot for ``todo_write``."""

    items: tuple[TurnTodoItem, ...] = ()

    def __post_init__(self) -> None:
        try:
            normalized = tuple(self.items)
        except TypeError as exc:  # pragma: no cover - defensive API guard
            raise TodoValidationError("todo items must be iterable") from exc
        object.__setattr__(self, "items", normalized)
        _validate_todo_items(normalized)

    @classmethod
    def empty(cls) -> "TurnTodoSnapshot":
        return cls(())

    @property
    def in_progress(self) -> TurnTodoItem | None:
        """Return the sole in-progress step, if one exists."""

        return next((item for item in self.items if item.status == "in_progress"), None)

    @property
    def unfinished(self) -> tuple[TurnTodoItem, ...]:
        return tuple(
            item for item in self.items if item.status in {"pending", "in_progress"}
        )


def normalize_todo_snapshot(value: Any) -> TurnTodoSnapshot:
    """Normalize supported ``todo_write`` input to a validated snapshot.

    The model-facing adapter can pass either the internal immutable type or a
    JSON-like mapping with an ``items`` array.  No other fields are accepted;
    in particular, a caller cannot attach evidence, payloads, or authorization
    state to a Todo.
    """

    if isinstance(value, TurnTodoSnapshot):
        return value
    if value is None:
        return TurnTodoSnapshot.empty()
    if isinstance(value, Mapping):
        unknown = set(value) - {"items"}
        if unknown:
            raise TodoValidationError("todo snapshot contains unsupported fields")
        value = value.get("items", ())
    if isinstance(value, (str, bytes)):
        raise TodoValidationError("todo snapshot items must be an array")
    try:
        raw_items = tuple(value)
    except TypeError as exc:
        raise TodoValidationError("todo snapshot items must be iterable") from exc

    items: list[TurnTodoItem] = []
    for raw in raw_items:
        if isinstance(raw, TurnTodoItem):
            items.append(raw)
            continue
        if not isinstance(raw, Mapping):
            raise TodoValidationError("todo item must be an object")
        unknown = set(raw) - {"id", "title", "status"}
        if unknown:
            raise TodoValidationError("todo item contains unsupported fields")
        try:
            items.append(
                TurnTodoItem(
                    id=raw["id"], title=raw["title"], status=raw["status"]
                )
            )
        except KeyError as exc:
            raise TodoValidationError("todo item is missing a required field") from exc
    return TurnTodoSnapshot(tuple(items))


def validate_todo_snapshot(value: Any) -> TurnTodoSnapshot:
    """Public alias used by tool adapters and focused tests."""

    return normalize_todo_snapshot(value)


_TODO_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"pending", "in_progress", "completed", "blocked"}),
    "in_progress": frozenset({"in_progress", "completed", "blocked"}),
    # Once a step is truthfully terminal, a replacement snapshot cannot claim
    # that it has become unfinished.  Removing a completed step is allowed.
    "completed": frozenset({"completed"}),
    "blocked": frozenset({"blocked"}),
}


class TurnTodoStore:
    """In-memory Todo store owned by exactly one Agent turn.

    ``write`` is an atomic complete-snapshot replacement.  A failed
    validation/transition leaves the previous snapshot untouched.
    """

    def __init__(self, initial: Any = None) -> None:
        self._snapshot = TurnTodoSnapshot.empty()
        if initial is not None:
            self.write(initial)

    @property
    def snapshot(self) -> TurnTodoSnapshot:
        return self._snapshot

    def read(self) -> TurnTodoSnapshot:
        return self._snapshot

    def write(self, value: Any) -> TurnTodoSnapshot:
        candidate = normalize_todo_snapshot(value)
        self._validate_transition(candidate)
        self._snapshot = candidate
        return candidate

    # Names that make the complete-replacement contract explicit for callers.
    replace = write
    write_snapshot = write

    def _validate_transition(self, candidate: TurnTodoSnapshot) -> None:
        previous_by_id = {item.id: item for item in self._snapshot.items}
        for item in candidate.items:
            previous = previous_by_id.get(item.id)
            if previous is None:
                continue
            if item.status not in _TODO_STATUS_TRANSITIONS[previous.status]:
                raise TodoValidationError(
                    f"todo step {item.id!r} cannot transition from "
                    f"{previous.status!r} to {item.status!r}"
                )

    def finalize(
        self,
        *,
        normal_completion: bool = True,
        allow_blocked: bool = False,
        terminal_action: bool = False,
    ) -> TurnTodoSnapshot:
        """Validate end-of-turn state without making Todo authoritative.

        A terminal mutation/action may pre-empt Todo finalization because its
        canonical outcome is authoritative.  A clarification or partial read
        may finish with blocked steps when the caller explicitly proves that it
        is presenting one of those safe outcomes.
        """

        current = self._snapshot
        if terminal_action:
            return current
        # Whether the visible answer is a normal completion or a partial/
        # clarification outcome, unfinished steps must be made ``blocked``
        # explicitly before finalization.  ``normal_completion`` is retained
        # for a readable call site and backwards-compatible adapter signature.
        if current.unfinished:
            raise TodoValidationError(
                "finalization cannot leave pending or in_progress todos"
            )
        if any(item.status == "blocked" for item in current.items) and not allow_blocked:
            raise TodoValidationError(
                "blocked todos require a clarification or unavailable-remainder outcome"
            )
        return current

    def mark_blocked(self, item_ids: Iterable[str] | None = None) -> TurnTodoSnapshot:
        """Mark selected unfinished steps blocked for a safe partial outcome."""

        selected = None if item_ids is None else {_validate_todo_id(item) for item in item_ids}
        if selected is not None:
            unknown = selected - {item.id for item in self._snapshot.items}
            if unknown:
                raise TodoValidationError("cannot block an unknown todo step")
        replacement = tuple(
            TurnTodoItem(
                id=item.id,
                title=item.title,
                status=(
                    "blocked"
                    if item.status in {"pending", "in_progress"}
                    and (selected is None or item.id in selected)
                    else item.status
                ),
            )
            for item in self._snapshot.items
        )
        return self.write(TurnTodoSnapshot(replacement))


# Safe codes are deliberately finite and category-oriented.  The category is
# the machine contract; the code is a stable public diagnostic, never a raw
# provider/database code or exception message.
SAFE_ERROR_CODES: frozenset[str] = frozenset(
    {
        "action_failed",
        "answer_invalid",
        "answer_validation",
        "answer_unavailable",
        "confirmation_required",
        "confirmation_missing",
        "deleted_or_unavailable",
        "embedding_unavailable",
        "item_not_found",
        "limit",
        "management_unavailable",
        "missing_context",
        "no_evidence",
        "not_found",
        "policy_denied",
        "provider_failure",
        "provider_unavailable",
        "queue_unavailable",
        "read_unavailable",
        "retry_not_allowed",
        "retrieval_unavailable",
        "runtime_error",
        "save_failed",
        "save_unavailable",
        "scope_denied",
        "search_required",
        "side_effect_unknown",
        "timeout",
        "transient_read",
        "unauthorized",
        "usage_limit",
    }
)
_SAFE_MESSAGE_PATTERN = re.compile(
    r"(?:https?://|www\.|\b(?:tenant|thread|pending|claim)(?:[_ -]?id)?\b|"
    r"\b(?:item|segment)[_ -]?id\b|\b(?:sql|postgres(?:ql)?)\b|"
    r"\b(?:payload|stack\s*trace|traceback|provider\s*body)\b)",
    re.IGNORECASE,
)


def _safe_message(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("safe_message must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > 240:
        raise ValueError("safe_message must be a short non-empty message")
    if _CONTROL_CHARACTER_PATTERN.search(normalized) or _SAFE_MESSAGE_PATTERN.search(
        normalized
    ):
        raise ValueError("safe_message contains private runtime data")
    return normalized


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    """Safe typed failure returned to a turn agent.

    Construction intentionally rejects private-looking strings so adapters do
    not accidentally pass exception text or provider bodies into model context.
    """

    category: RecoveryCategory
    code: str
    operation: RecoveryOperation
    safe_message: str
    partial_evidence: bool = False

    def __post_init__(self) -> None:
        if self.category not in {
            "transient_read",
            "read_unavailable",
            "missing_context",
            "policy_or_security",
            "side_effect_indeterminate",
            "provider_failure",
            "answer_validation",
        }:
            raise ValueError("error category is not allowed")
        if self.operation not in {"read", "mutation", "provider", "answer"}:
            raise ValueError("error operation is not allowed")
        if self.code not in SAFE_ERROR_CODES:
            raise ValueError("error code is not allow-listed")
        if not isinstance(self.partial_evidence, bool):
            raise ValueError("partial_evidence must be a boolean")
        object.__setattr__(self, "safe_message", _safe_message(self.safe_message))

    @classmethod
    def from_category(
        cls,
        category: RecoveryCategory,
        *,
        operation: RecoveryOperation,
        code: str | None = None,
        partial_evidence: bool = False,
    ) -> "ErrorEnvelope":
        """Build an envelope with a fixed safe message for a category."""

        defaults: dict[str, tuple[str, str]] = {
            "transient_read": ("transient_read", "The read was temporarily unavailable."),
            "read_unavailable": ("read_unavailable", "The requested read is unavailable."),
            "missing_context": ("missing_context", "More context is needed to continue."),
            "policy_or_security": ("policy_denied", "The requested operation is not allowed."),
            "side_effect_indeterminate": (
                "side_effect_unknown",
                "The operation outcome is still being resolved.",
            ),
            "provider_failure": ("provider_failure", "The assistant service is unavailable."),
            "answer_validation": (
                "answer_validation",
                "The answer could not be validated against the available evidence.",
            ),
        }
        default_code, message = defaults[category]
        return cls(
            category=category,
            code=code or default_code,
            operation=operation,
            safe_message=message,
            partial_evidence=partial_evidence,
        )


@dataclass(frozen=True, slots=True)
class RecoveryGrant:
    """Server-issued legal next actions for one failure observation."""

    allowed: tuple[RecoveryAction, ...]
    remaining_actions: int

    def __post_init__(self) -> None:
        normalized = tuple(self.allowed)
        if len(set(normalized)) != len(normalized):
            raise ValueError("recovery actions must be unique")
        allowed_actions = {
            "retry_same_read",
            "use_existing_evidence",
            "return_partial",
            "ask_clarification",
            "report_unavailable",
            "reformulate_search",
            "repair_answer",
        }
        if any(action not in allowed_actions for action in normalized):
            raise ValueError("recovery action is not allowed")
        if not isinstance(self.remaining_actions, int) or self.remaining_actions < 0:
            raise ValueError("remaining_actions must be a non-negative integer")
        object.__setattr__(self, "allowed", normalized)

    def permits(self, action: RecoveryAction) -> bool:
        return action in self.allowed

    # A compact alias reads naturally in call sites and tests.
    allows = permits


@dataclass(frozen=True, slots=True)
class RecoveryLedgerSnapshot:
    """Safe numeric/category view of a turn ledger (no fingerprints)."""

    total_actions: int
    answer_repairs: int
    same_read_retries: int
    category_counts: tuple[tuple[str, int], ...]


def _canonical_fingerprint_value(value: Any) -> Any:
    """Return a deterministic, non-sensitive shape for hashing arguments."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        values = [_canonical_fingerprint_value(item) for item in value]
        if isinstance(value, (set, frozenset)):
            values.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return values
    # Do not call repr(value): an arbitrary object's repr can contain a URL,
    # token, query, or exception body.  Its type is sufficient for a stable
    # server-side distinction in the rare unsupported case.
    return {"__type__": type(value).__module__ + "." + type(value).__qualname__}


class RecoveryLedger:
    """Turn-scoped recovery counters and exact-read retry fingerprints."""

    MAX_TOTAL_ACTIONS = MAX_TOTAL_RECOVERY_ACTIONS
    MAX_SAME_READ_RETRIES = MAX_SAME_READ_RECOVERY_RETRIES
    MAX_ANSWER_REPAIRS = MAX_ANSWER_REPAIR_ACTIONS
    MAX_MUTATION_RETRIES = MAX_MUTATION_RECOVERY_RETRIES
    MAX_PROVIDER_RETRIES = MAX_PROVIDER_RECOVERY_RETRIES

    def __init__(
        self,
        *,
        max_total_actions: int = MAX_TOTAL_ACTIONS,
        max_same_read_retries: int = MAX_SAME_READ_RETRIES,
        max_answer_repairs: int = MAX_ANSWER_REPAIRS,
    ) -> None:
        if max_total_actions < 0:
            raise ValueError("max_total_actions must be non-negative")
        if max_same_read_retries < 0:
            raise ValueError("max_same_read_retries must be non-negative")
        if max_answer_repairs < 0:
            raise ValueError("max_answer_repairs must be non-negative")
        self.max_total_actions = max_total_actions
        self.max_same_read_retries = max_same_read_retries
        self.max_answer_repairs = max_answer_repairs
        self._total_actions = 0
        self._answer_repairs = 0
        self._read_retries: dict[str, int] = {}
        self._category_counts: dict[str, int] = {}

    @staticmethod
    def fingerprint_read(tool_name: str, arguments: Any) -> str:
        """Hash a tool name and normalized arguments without retaining either."""

        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool_name must be non-empty text")
        payload = {
            "tool": tool_name.strip(),
            "arguments": _canonical_fingerprint_value(arguments),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    # Convenient spelling for callers that already have a normalized call.
    read_fingerprint = fingerprint_read

    @staticmethod
    def _normalize_fingerprint(fingerprint: str) -> str:
        if not isinstance(fingerprint, str) or not fingerprint.strip():
            raise ValueError("read fingerprint must be non-empty text")
        value = fingerprint.strip()
        # Keep a server-created digest as-is; hash opaque labels supplied by a
        # test/adapter so raw arguments never become ledger state.
        if re.fullmatch(r"[0-9a-f]{64}", value):
            return value
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @property
    def total_actions(self) -> int:
        return self._total_actions

    @property
    def recovery_actions(self) -> int:
        return self._total_actions

    @property
    def remaining_recovery_actions(self) -> int:
        return self.remaining_actions

    @property
    def answer_repairs(self) -> int:
        return self._answer_repairs

    @property
    def answer_repair_count(self) -> int:
        return self._answer_repairs

    @property
    def remaining_actions(self) -> int:
        return max(0, self.max_total_actions - self._total_actions)

    @property
    def same_read_retries(self) -> int:
        return sum(self._read_retries.values())

    @property
    def same_read_attempts(self) -> int:
        return self.same_read_retries

    @property
    def mutation_retries(self) -> int:
        """Autonomous mutation retries are a hard zero ceiling."""

        return 0

    @property
    def provider_retries(self) -> int:
        """Agent-level provider retries are a hard zero ceiling."""

        return 0

    def can_retry_mutation(self) -> bool:
        return False

    def can_retry_provider(self) -> bool:
        return False

    def same_read_retry_count(self, fingerprint: str) -> int:
        return self._read_retries.get(self._normalize_fingerprint(fingerprint), 0)

    def can_retry_same_read(self, fingerprint: str | None) -> bool:
        if fingerprint is None or self.remaining_actions <= 0:
            return False
        normalized = self._normalize_fingerprint(fingerprint)
        return self._read_retries.get(normalized, 0) < self.max_same_read_retries

    def can_repair_answer(self) -> bool:
        return (
            self.remaining_actions > 0
            and self._answer_repairs < self.max_answer_repairs
        )

    def record_recovery(
        self,
        action: str,
        *,
        operation: RecoveryOperation | None = None,
        fingerprint: str | None = None,
        category: RecoveryCategory | None = None,
    ) -> bool:
        """Consume one granted action, returning ``False`` at a hard ceiling.

        Mutation and provider retries are intentionally not represented as
        legal actions.  Passing them (or a retry action with the wrong
        operation) is rejected without changing any counter.
        """

        if action == "retry_same_read":
            if operation != "read" or fingerprint is None:
                return False
            if not self.can_retry_same_read(fingerprint):
                return False
            normalized = self._normalize_fingerprint(fingerprint)
            self._read_retries[normalized] = self._read_retries.get(normalized, 0) + 1
        elif action == "repair_answer":
            if operation != "answer" or not self.can_repair_answer():
                return False
            self._answer_repairs += 1
        elif action in {
            "use_existing_evidence",
            "return_partial",
            "ask_clarification",
            "report_unavailable",
            "reformulate_search",
        }:
            if self.remaining_actions <= 0:
                return False
        else:
            # Includes mutation/provider retry spellings, which must remain at
            # zero even if a model attempts to invent an action name.
            return False

        self._total_actions += 1
        if category is not None:
            self._category_counts[category] = self._category_counts.get(category, 0) + 1
        return True

    # Explicit aliases make the intended consume-vs-inspect distinction clear.
    consume = record_recovery
    record = record_recovery

    def record_answer_repair(self, *, category: RecoveryCategory = "answer_validation") -> bool:
        return self.record_recovery(
            "repair_answer", operation="answer", category=category
        )

    def record_same_read_retry(
        self,
        fingerprint: str,
        *,
        category: RecoveryCategory = "transient_read",
    ) -> bool:
        return self.record_recovery(
            "retry_same_read",
            operation="read",
            fingerprint=fingerprint,
            category=category,
        )

    def snapshot(self) -> RecoveryLedgerSnapshot:
        return RecoveryLedgerSnapshot(
            total_actions=self._total_actions,
            answer_repairs=self._answer_repairs,
            same_read_retries=self.same_read_retries,
            category_counts=tuple(sorted(self._category_counts.items())),
        )


class RecoveryPolicy:
    """Deterministic grant policy for safe, turn-local recovery choices."""

    def __init__(self, ledger: RecoveryLedger | None = None) -> None:
        self.ledger = ledger or RecoveryLedger()

    @staticmethod
    def _fingerprint(
        ledger: RecoveryLedger,
        *,
        read_fingerprint: str | None,
        tool_name: str | None,
        arguments: Any,
    ) -> str | None:
        if read_fingerprint is not None:
            return read_fingerprint
        if tool_name is None:
            return None
        return ledger.fingerprint_read(tool_name, arguments)

    def grant(
        self,
        error: ErrorEnvelope,
        *,
        trusted_trace: bool = True,
        trusted_execution: bool | None = None,
        has_evidence: bool | None = None,
        evidence_available: bool | None = None,
        read_fingerprint: str | None = None,
        same_read_fingerprint: str | None = None,
        tool_name: str | None = None,
        arguments: Any = None,
        retrieval_budget_remaining: int | None = None,
        search_budget_remaining: int | None = None,
        tool_budget_remaining: int | None = None,
        request_budget_remaining: int | None = None,
        provider_budget_remaining: int | None = None,
        answer_budget_remaining: int | None = None,
        output_budget_remaining: int | None = None,
        wall_clock_remaining: bool = True,
    ) -> RecoveryGrant:
        """Return legal actions without consuming one.

        ``trusted_trace`` and all budget arguments are server-owned facts.  A
        model cannot make a denied grant valid by editing Todo text or tool
        arguments.
        """

        if trusted_execution is not None:
            trusted_trace = trusted_execution
        if evidence_available is not None:
            has_evidence = evidence_available
        evidence = bool(error.partial_evidence if has_evidence is None else has_evidence)
        fingerprint = same_read_fingerprint or read_fingerprint
        fingerprint = self._fingerprint(
            self.ledger,
            read_fingerprint=fingerprint,
            tool_name=tool_name,
            arguments=arguments,
        )
        remaining = self.ledger.remaining_actions

        if not trusted_trace or remaining <= 0:
            return RecoveryGrant((), remaining)

        def budget_available(value: int | None) -> bool:
            return value is None or value > 0

        if not wall_clock_remaining:
            return RecoveryGrant((), remaining)

        allowed: list[RecoveryAction] = []
        category = error.category
        operation = error.operation

        if category == "transient_read" and operation == "read":
            if (
                fingerprint is not None
                and self.ledger.can_retry_same_read(fingerprint)
                and budget_available(retrieval_budget_remaining)
                and budget_available(tool_budget_remaining)
                and budget_available(request_budget_remaining)
                and budget_available(provider_budget_remaining)
            ):
                allowed.append("retry_same_read")
            if evidence:
                allowed.extend(("use_existing_evidence", "return_partial"))
            allowed.append("report_unavailable")
        elif category == "read_unavailable" and operation == "read":
            if evidence:
                allowed.extend(("use_existing_evidence", "return_partial"))
            allowed.append("report_unavailable")
        elif category == "missing_context":
            allowed.append("ask_clarification")
        elif category == "answer_validation" and operation == "answer":
            if (
                evidence
                and self.ledger.can_repair_answer()
                and budget_available(request_budget_remaining)
                and budget_available(provider_budget_remaining)
                and budget_available(answer_budget_remaining)
                and budget_available(output_budget_remaining)
            ):
                allowed.append("repair_answer")
        # policy/security, side-effect-indeterminate, provider failures, and
        # mutation failures intentionally receive no autonomous action.

        return RecoveryGrant(tuple(allowed), remaining)

    # The aliases keep adapters readable and make the policy contract easy to
    # consume without coupling callers to one verb.
    evaluate = grant
    decide = grant
    for_error = grant

    def grant_for_empty_search(
        self,
        *,
        trusted_trace: bool = True,
        search_budget_remaining: int = 0,
        retrieval_budget_remaining: int | None = None,
        has_evidence: bool = False,
    ) -> RecoveryGrant:
        """Grant query reformulation for a normal empty-search observation."""

        remaining = self.ledger.remaining_actions
        if (
            not trusted_trace
            or remaining <= 0
            or search_budget_remaining <= 0
            or not (retrieval_budget_remaining is None or retrieval_budget_remaining > 0)
        ):
            return RecoveryGrant((), remaining)
        allowed: list[RecoveryAction] = ["reformulate_search"]
        if has_evidence:
            allowed.append("use_existing_evidence")
        allowed.append("report_unavailable")
        return RecoveryGrant(tuple(allowed), remaining)

    # Alternate spelling used by some tool adapters.
    empty_search = grant_for_empty_search


__all__ = [
    "ErrorEnvelope",
    "MAX_ANSWER_REPAIR_ACTIONS",
    "MAX_MUTATION_RECOVERY_RETRIES",
    "MAX_PROVIDER_RECOVERY_RETRIES",
    "MAX_SAME_READ_RECOVERY_RETRIES",
    "MAX_TOTAL_RECOVERY_ACTIONS",
    "MAX_TODO_ID_CHARS",
    "MAX_TODO_ITEMS",
    "MAX_TODO_TITLE_CHARS",
    "RecoveryAction",
    "RecoveryCategory",
    "RecoveryGrant",
    "RecoveryLedger",
    "RecoveryLedgerSnapshot",
    "RecoveryOperation",
    "RecoveryPolicy",
    "SAFE_ERROR_CODES",
    "TodoStatus",
    "TodoValidationError",
    "TurnTodoItem",
    "TurnTodoSnapshot",
    "TurnTodoStore",
    "normalize_todo_snapshot",
    "validate_todo_snapshot",
]
