"""Concurrent lifecycle and fault isolation for channel adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from app.agent.types import AgentAnswer
from app.channels.service import ChannelService
from app.channels.types import ChannelEnvelope


InboundHandler = Callable[[ChannelEnvelope], Awaitable[None]]


class ChannelAdapter(Protocol):
    name: str

    async def run(self, on_message: InboundHandler) -> None:
        """Run until stopped or disconnected."""

    async def send(self, envelope: ChannelEnvelope, answer: AgentAnswer) -> None:
        """Reply through the same account/channel that received the envelope."""

    async def stop(self) -> None:
        """Request a graceful stop."""


@dataclass(frozen=True)
class AdapterHealth:
    name: str
    status: str
    error: str | None = None


class ChannelGatewaySupervisor:
    """Start all enabled adapters; one failure never cancels its siblings."""

    def __init__(
        self, adapters: list[ChannelAdapter], service: ChannelService
    ) -> None:
        names = [adapter.name for adapter in adapters]
        if len(names) != len(set(names)):
            raise ValueError("channel adapter names must be unique")
        self._adapters = {adapter.name: adapter for adapter in adapters}
        self._service = service
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._health = {
            name: AdapterHealth(name, "stopped") for name in self._adapters
        }

    async def start(self) -> None:
        for name, adapter in self._adapters.items():
            if name in self._tasks and not self._tasks[name].done():
                continue
            self._health[name] = AdapterHealth(name, "starting")
            self._tasks[name] = asyncio.create_task(
                self._run_one(adapter), name=f"channel:{name}"
            )
        await asyncio.sleep(0)

    async def _run_one(self, adapter: ChannelAdapter) -> None:
        self._health[adapter.name] = AdapterHealth(adapter.name, "running")

        async def inbound(envelope: ChannelEnvelope) -> None:
            answer = await self._service.handle(envelope)
            await adapter.send(envelope, answer)

        try:
            await adapter.run(inbound)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._health[adapter.name] = AdapterHealth(
                adapter.name, "failed", type(exc).__name__
            )
        else:
            self._health[adapter.name] = AdapterHealth(adapter.name, "stopped")

    def health(self) -> list[AdapterHealth]:
        return [self._health[name] for name in sorted(self._health)]

    async def stop(self) -> None:
        await asyncio.gather(
            *(adapter.stop() for adapter in self._adapters.values()),
            return_exceptions=True,
        )
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        for name in self._adapters:
            if self._health[name].status != "failed":
                self._health[name] = AdapterHealth(name, "stopped")
