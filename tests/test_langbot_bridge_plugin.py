from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest


class _Plain:
    def __init__(self, *, text: str):
        self.text = text


class _MessageChain:
    def __init__(self, root):
        self.root = root


def _load_bridge_module(monkeypatch: pytest.MonkeyPatch):
    event_listener_module = types.ModuleType(
        "langbot_plugin.api.definition.components.common.event_listener"
    )
    event_listener_module.EventListener = object

    context_module = types.ModuleType("langbot_plugin.api.entities.context")
    events_module = types.ModuleType("langbot_plugin.api.entities.events")
    events_module.PersonMessageReceived = type("PersonMessageReceived", (), {})

    entities_module = types.ModuleType("langbot_plugin.api.entities")
    entities_module.context = context_module
    entities_module.events = events_module

    message_module = types.ModuleType(
        "langbot_plugin.api.entities.builtin.platform.message"
    )
    message_module.MessageChain = _MessageChain
    message_module.Plain = _Plain

    modules = {
        "langbot_plugin": types.ModuleType("langbot_plugin"),
        "langbot_plugin.api": types.ModuleType("langbot_plugin.api"),
        "langbot_plugin.api.definition": types.ModuleType(
            "langbot_plugin.api.definition"
        ),
        "langbot_plugin.api.definition.components": types.ModuleType(
            "langbot_plugin.api.definition.components"
        ),
        "langbot_plugin.api.definition.components.common": types.ModuleType(
            "langbot_plugin.api.definition.components.common"
        ),
        "langbot_plugin.api.definition.components.common.event_listener": (
            event_listener_module
        ),
        "langbot_plugin.api.entities": entities_module,
        "langbot_plugin.api.entities.context": context_module,
        "langbot_plugin.api.entities.events": events_module,
        "langbot_plugin.api.entities.builtin": types.ModuleType(
            "langbot_plugin.api.entities.builtin"
        ),
        "langbot_plugin.api.entities.builtin.platform": types.ModuleType(
            "langbot_plugin.api.entities.builtin.platform"
        ),
        "langbot_plugin.api.entities.builtin.platform.message": message_module,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    path = (
        Path(__file__).parents[1]
        / "integrations/langbot_kb_plugin/components/event_listener/knowledge_agent.py"
    )
    spec = importlib.util.spec_from_file_location("test_knowledge_agent", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Event:
    sender_id = "trusted-sender"
    launcher_id = "trusted-conversation"
    message_event = types.SimpleNamespace(time=123)

    class _Chain:
        message_id = "platform-message-id"

        def __str__(self) -> str:
            return "/whoami"

    message_chain = _Chain()


class _EventContext:
    def __init__(self):
        self.event = _Event()
        self.bot_uuid = "wechat-bot"
        self.default_prevented = False
        self.postorder_prevented = False
        self.replies = []

    def prevent_default(self):
        self.default_prevented = True

    def prevent_postorder(self):
        self.postorder_prevented = True

    async def get_bot_uuid(self) -> str:
        return self.bot_uuid

    async def reply(self, message_chain):
        self.replies.append(message_chain)


@pytest.mark.asyncio
async def test_early_event_uses_query_reply_api(monkeypatch: pytest.MonkeyPatch):
    module = _load_bridge_module(monkeypatch)
    monkeypatch.setenv("KB_BOT_CHANNELS", '{"wechat-bot":"wechat"}')
    forwarded = []
    monkeypatch.setattr(module, "_post", lambda payload: (forwarded.append(payload) or {"text": "user 42"}))
    event_context = _EventContext()

    listener = object.__new__(module.KnowledgeAgentEventListener)
    await listener._handle(event_context)

    assert event_context.default_prevented is True
    assert event_context.postorder_prevented is True
    assert len(event_context.replies) == 1
    assert event_context.replies[0].root[0].text == "user 42"
    assert len(forwarded[0]["trace_id"]) == 32
    assert forwarded[0]["trace_id"].isalnum()
    assert not hasattr(event_context.event, "reply_message_chain")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bot_uuid", "channel", "command"),
    [
        ("telegram-bot", "telegram", "/link wechat"),
        ("wechat-bot", "wechat", "/link telegram"),
    ],
)
async def test_link_commands_keep_normalized_channel_envelope(
    monkeypatch: pytest.MonkeyPatch,
    bot_uuid: str,
    channel: str,
    command: str,
):
    module = _load_bridge_module(monkeypatch)
    monkeypatch.setenv(
        "KB_BOT_CHANNELS",
        '{"telegram-bot":"telegram","wechat-bot":"wechat"}',
    )
    forwarded = []
    monkeypatch.setattr(
        module,
        "_post",
        lambda payload: (forwarded.append(payload) or {"text": "ok"}),
    )
    event_context = _EventContext()
    event_context.bot_uuid = bot_uuid
    command_chain = type(
        "CommandChain",
        (),
        {
            "message_id": "link-command-message",
            "__str__": lambda self: command,
        },
    )
    event_context.event.message_chain = command_chain()

    listener = object.__new__(module.KnowledgeAgentEventListener)
    await listener._handle(event_context)

    assert len(forwarded) == 1
    assert forwarded[0]["channel"] == channel
    assert forwarded[0]["text"] == command
    assert len(event_context.replies) == 1


@pytest.mark.asyncio
async def test_gateway_failure_is_replied_without_default_pipeline(
    monkeypatch: pytest.MonkeyPatch,
):
    module = _load_bridge_module(monkeypatch)
    monkeypatch.setenv("KB_BOT_CHANNELS", '{"wechat-bot":"wechat"}')

    def fail(_payload):
        raise TimeoutError

    monkeypatch.setattr(module, "_post", fail)
    event_context = _EventContext()

    listener = object.__new__(module.KnowledgeAgentEventListener)
    await listener._handle(event_context)

    assert event_context.default_prevented is True
    assert event_context.postorder_prevented is True
    assert event_context.replies[0].root[0].text == "知识库渠道暂时不可用，请稍后重试。"


@pytest.mark.asyncio
async def test_duplicate_delivery_only_claims_one_platform_reply(
    monkeypatch: pytest.MonkeyPatch,
):
    module = _load_bridge_module(monkeypatch)
    monkeypatch.setenv("KB_BOT_CHANNELS", '{"wechat-bot":"wechat"}')
    calls = []

    def post(_payload):
        calls.append(True)
        return {"text": "stable answer"}

    monkeypatch.setattr(module, "_post", post)
    listener = object.__new__(module.KnowledgeAgentEventListener)
    first = _EventContext()
    duplicate = _EventContext()

    await listener._handle(first)
    await listener._handle(duplicate)

    assert len(calls) == 1
    assert len(first.replies) == 1
    assert duplicate.replies == []
    assert duplicate.default_prevented is True


def test_bridge_event_projects_invalid_values(monkeypatch: pytest.MonkeyPatch, caplog):
    module = _load_bridge_module(monkeypatch)
    with caplog.at_level(logging.INFO, logger="notebook_agent.bridge"):
        module._event(stage="PRIVATE-stage", trace_id="PRIVATE-trace", channel="PRIVATE-channel", outcome="PRIVATE-outcome")
    text = caplog.records[-1].getMessage()
    assert "PRIVATE" not in text
    assert '"stage":"gateway_result"' in text
    assert '"trace_id":"-"' in text
    assert '"channel":"unknown"' in text
