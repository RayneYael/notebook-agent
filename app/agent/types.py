"""Framework-neutral request and response contracts for the knowledge Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from typing_extensions import TypedDict

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from app.channels.types import TenantContext


class Citation(BaseModel):
    """A source that was actually returned by a tenant-scoped tool."""

    model_config = ConfigDict(frozen=True)

    item_id: int
    segment_id: int
    title: str
    excerpt: str
    url: str
    start_sec: float | None = None
    _retrieval_score: float | None = PrivateAttr(default=None)

    def __eq__(self, other: object) -> bool:
        """Keep private retrieval diagnostics out of the public source contract."""

        if not isinstance(other, Citation):
            return NotImplemented
        return self.model_dump() == other.model_dump()


class AgentAnswer(BaseModel):
    """Stable answer contract shared by CLI and channel adapters."""

    status: Literal["ok", "not_found", "failed"]
    text: str
    citations: list[Citation] = Field(default_factory=list)
    action_results: list[dict] = Field(default_factory=list)
    thread_id: str | None = None
    error_code: str | None = None


class RetrievalToolPayload(TypedDict):
    """The only retrieval-tool result shape exposed to the planning Agent.

    ``skipped`` is deliberately distinct from an empty successful search: a
    provider may emit a batch despite ``parallel_tool_calls=False``, but only
    the first retrieval in that model step is allowed to reach backend
    services.
    """

    status: Literal["ok", "skipped"]
    evidence: list[dict]
    reason: Literal["same_model_step", "budget_exhausted"] | None


class AnswerSection(BaseModel):
    """One composer-written section backed by server-owned segment ids."""

    text: str = Field(min_length=1)
    citation_ids: list[int] = Field(min_length=1)


class AnswerDraft(BaseModel):
    """Private structured composer output; never persisted verbatim."""

    sections: list[AnswerSection] = Field(min_length=1, max_length=8)


@dataclass(frozen=True)
class AgentRequest:
    """A trusted request assembled by application code, never by the model."""

    question: str
    tenant: TenantContext
    thread_db_id: int
    thread_public_id: str
    message_id: str
    request_id: str
    history: tuple[dict, ...] = ()
    # Server-owned correlation for high-risk confirmations.  This is the
    # message id of the newest completed turn before the current message;
    # model/tool arguments never carry it.
    latest_turn_message_id: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")


# Management contracts live in their focused module to keep retrieval types
# small.  Re-exporting them here preserves the package-level contract for
# integrations that historically imported all Agent payloads from ``types``.
from app.agent.management import (  # noqa: E402  (intentional compatibility export)
    BatchItemOperationResult,
    ItemFilters,
    ItemOperationResult,
    KnowledgeItemManagementService,
    SavedItem,
    SavedItemPage,
    decode_cursor,
    encode_cursor,
)
