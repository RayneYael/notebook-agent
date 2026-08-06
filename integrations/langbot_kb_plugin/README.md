# LangBot knowledge Agent bridge

This plugin intercepts private normal messages and commands before LangBot's
Local Agent, translates trusted event fields into the project's
`ChannelEnvelope`, and replies with the project's `AgentAnswer`.

It deliberately does not own users, sessions, retrieval tools, model prompts,
or knowledge permissions. Telegram and WeChat bots can remain enabled together;
each bot UUID must be explicitly mapped in `KB_BOT_CHANNELS`.

The bridge calls only the loopback gateway and signs every request with an HMAC,
timestamp and nonce. Copy this directory into the LangBot plugin workspace,
configure the three values shown in `.env.example`, and start
`python -m app.cli gateway-server` from the notebook-agent project first.

Before platform acceptance, apply
`../langbot-4.10.6-redact-monitoring.patch` to the fixed LangBot 4.10.6 source.
The early `PersonMessageReceived` interception prevents the later processor log,
while the patch prevents LangBot monitoring storage from duplicating message
content and external identity values. At this early event, replies must be sent
with `EventContext.reply(...)`: after `prevent_default()`, LangBot returns before
it consumes `event.reply_message_chain`. If this patch is not applied, the
privacy acceptance item must be treated as failed.

LangBot 4.10.6 does not consistently serialize the original platform message
ID into plugin events. The bridge prefers `MessageChain.Source`; when absent it
uses a deterministic compatibility digest of trusted routing fields, event time
and text. The real Telegram/WeChat acceptance checklist records this limitation.
