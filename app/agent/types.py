"""Framework-neutral request and response contracts for the knowledge Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class AgentAnswer(BaseModel):
    """Stable answer contract shared by CLI and channel adapters."""

    status: Literal["ok", "not_found", "failed"]
    text: str
    citations: list[Citation] = Field(default_factory=list)
    action_results: list[dict] = Field(default_factory=list)
    thread_id: str | None = None
    error_code: str | None = None


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

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")
