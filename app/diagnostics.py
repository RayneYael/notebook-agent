"""Redacted, correlation-safe runtime diagnostics for knowledge requests."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass


LOGGER = logging.getLogger("notebook_agent.runtime")


@dataclass(frozen=True)
class RequestDiagnostics:
    """Emit only stable operational fields, never user or provider payloads."""

    request_id: str
    tenant_id: int
    started_at: float

    @classmethod
    def start(cls, request_id: str, tenant_id: int) -> "RequestDiagnostics":
        return cls(request_id=request_id, tenant_id=tenant_id, started_at=time.monotonic())

    def event(
        self,
        stage: str,
        *,
        error_code: str | None = None,
        exception: BaseException | None = None,
    ) -> None:
        """Log fixed fields without interpolating exception messages or payloads."""

        LOGGER.info(
            "knowledge_request stage=%s request_id=%s tenant_id=%s error_code=%s "
            "error_class=%s duration_ms=%d",
            stage,
            self.request_id,
            self.tenant_id,
            error_code or "-",
            type(exception).__name__ if exception is not None else "-",
            int((time.monotonic() - self.started_at) * 1000),
        )
