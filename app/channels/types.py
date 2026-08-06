"""Framework-neutral trusted channel contracts."""

from __future__ import annotations

from dataclasses import dataclass


def _required(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


@dataclass(frozen=True)
class ChannelEnvelope:
    channel: str
    account_id: str
    external_user_id: str
    conversation_id: str
    message_id: str
    text: str

    def __post_init__(self) -> None:
        for field in (
            "channel",
            "account_id",
            "external_user_id",
            "conversation_id",
            "message_id",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        object.__setattr__(self, "text", str(self.text).strip())


@dataclass(frozen=True)
class TenantContext:
    app_user_id: int
    channel_identity_id: int
    channel: str
    account_id: str
    external_user_id: str

    def __post_init__(self) -> None:
        if self.app_user_id <= 0 or self.channel_identity_id <= 0:
            raise ValueError("tenant identifiers must be positive")
