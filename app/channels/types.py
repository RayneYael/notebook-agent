"""Framework-neutral trusted channel contracts."""

from __future__ import annotations

from dataclasses import dataclass
import re


_TRACE_ID_RE = re.compile(r"[0-9a-f]{32}\Z")


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
    # Generated inside the application boundary. HTTP gateway requests always
    # overwrite this value rather than trusting a channel-provided value.
    request_id: str | None = None
    # A bridge-generated opaque correlation token. It is HMAC protected at the
    # HTTP boundary but is never used for authorization or business state.
    trace_id: str | None = None

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
        if self.request_id is not None:
            object.__setattr__(self, "request_id", _required(self.request_id, "request_id"))
        if self.trace_id is not None and not _TRACE_ID_RE.fullmatch(self.trace_id):
            raise ValueError("trace_id must be 32 lowercase hexadecimal characters")


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
