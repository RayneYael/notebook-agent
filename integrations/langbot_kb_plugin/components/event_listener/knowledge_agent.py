from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.request
import uuid

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import context, events
from langbot_plugin.api.entities.builtin.platform import message as platform_message


class KnowledgeAgentEventListener(EventListener):
    async def initialize(self):
        await super().initialize()

        # This fires before LangBot's MessageProcessor. Preventing the default
        # path therefore also avoids its info-level private-message log.
        @self.handler(events.PersonMessageReceived)
        async def on_message(event_context: context.EventContext) -> None:
            await self._handle(event_context)

    async def _handle(self, event_context: context.EventContext) -> None:
        event_context.prevent_default()
        event_context.prevent_postorder()
        try:
            bot_uuid = await event_context.get_bot_uuid()
            event = event_context.event
            channel = _channel_for_bot(bot_uuid)
            message_text = str(event.message_chain).strip()
            payload = {
                "channel": channel,
                "account_id": bot_uuid,
                "external_user_id": str(event.sender_id),
                "conversation_id": str(event.launcher_id),
                "message_id": _message_id(bot_uuid, event, message_text),
                "text": message_text,
            }
            answer = await asyncio.to_thread(_post, payload)
            text = str(answer.get("text") or "知识库暂时无法回复，请稍后重试。")
        except Exception:
            # Identity and message contents are intentionally not logged here.
            text = "知识库渠道暂时不可用，请稍后重试。"
        # PersonMessageReceived is emitted before LangBot's pipeline stages.
        # Once default processing is prevented, PipelineManager returns without
        # consuming event.reply_message_chain. Use the query-scoped reply API so
        # the adapter sends the response before that early return.
        await event_context.reply(
            platform_message.MessageChain([platform_message.Plain(text=text)])
        )


def _channel_for_bot(bot_uuid: str) -> str:
    configured = json.loads(os.environ.get("KB_BOT_CHANNELS", "{}"))
    channel = str(configured.get(bot_uuid, "")).strip().lower()
    if channel not in {"telegram", "wechat", "slack"}:
        raise RuntimeError("bot UUID is not mapped to an allowed channel")
    return channel


def _message_id(bot_uuid: str, event, message_text: str) -> str:
    chain_id = getattr(getattr(event, "message_chain", None), "message_id", -1)
    if chain_id not in {-1, None, ""}:
        return str(chain_id)
    event_time = getattr(getattr(event, "message_event", None), "time", None)
    material = "\n".join(
        [
            bot_uuid,
            str(event.sender_id),
            str(event.launcher_id),
            str(event_time or "unknown-time"),
            message_text,
        ]
    )
    return "compat-" + hashlib.sha256(material.encode()).hexdigest()


def _post(payload: dict) -> dict:
    secret = os.environ.get("CHANNEL_GATEWAY_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("CHANNEL_GATEWAY_SECRET is missing")
    endpoint = os.environ.get(
        "CHANNEL_GATEWAY_URL", "http://127.0.0.1:8765/v1/messages"
    )
    if not endpoint.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("channel gateway URL must use loopback")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-KB-Timestamp": timestamp,
            "X-KB-Nonce": nonce,
            "X-KB-Signature": signature,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())
