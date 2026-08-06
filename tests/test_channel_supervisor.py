import asyncio

import pytest

from app.agent.types import AgentAnswer
from app.channels.supervisor import ChannelGatewaySupervisor
from app.channels.types import ChannelEnvelope


class Service:
    async def handle(self, envelope):
        return AgentAnswer(status="ok", text=f"reply:{envelope.channel}")


class Adapter:
    def __init__(self, name, envelope=None, failure=None):
        self.name = name
        self.envelope = envelope
        self.failure = failure
        self.replies = []
        self.stopped = asyncio.Event()

    async def run(self, on_message):
        if self.failure:
            raise self.failure
        if self.envelope:
            await on_message(self.envelope)
        await self.stopped.wait()

    async def send(self, envelope, answer):
        self.replies.append((envelope, answer))

    async def stop(self):
        self.stopped.set()


@pytest.mark.asyncio
async def test_all_adapters_run_and_one_failure_is_isolated():
    telegram = Adapter(
        "telegram",
        ChannelEnvelope("telegram", "bot", "u1", "c1", "m1", "question"),
    )
    wechat = Adapter("wechat", failure=RuntimeError("disconnected"))
    supervisor = ChannelGatewaySupervisor([telegram, wechat], Service())

    await supervisor.start()
    for _ in range(10):
        if telegram.replies:
            break
        await asyncio.sleep(0)

    health = {value.name: value.status for value in supervisor.health()}
    assert telegram.replies[0][1].text == "reply:telegram"
    assert health["telegram"] == "running"
    assert health["wechat"] == "failed"
    await supervisor.stop()

