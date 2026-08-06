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
`../langbot-4.10.6-redact-monitoring.patch` to the fixed LangBot 4.10.6 source
with `patch --dry-run -p1` first. Despite its retained filename, the patch does
three jobs: it redacts LangBot monitoring/adapter/processor/diagnostic paths,
waits for configured required plugins before any enabled adapter starts, and
fails closed if a required bridge plugin does not handle an early event. Configure
`plugin.required_plugins` with `notebook-agent/notebook-knowledge-agent` and
bind this plugin explicitly to each bridge pipeline. Do not use a fixed startup
sleep or enable LangBot Local Agent as a fallback.

The early `PersonMessageReceived` interception prevents default processing. At
this early event, replies must be sent with `EventContext.reply(...)`: after
`prevent_default()`, LangBot returns before it consumes `event.reply_message_chain`.
If the patch is not applied, the privacy and channel-availability acceptance
items must be treated as failed.

The runtime worker loads its secret configuration from the installed plugin
directory, for example
`data/plugins/notebook-agent__notebook-knowledge-agent/.env`. Copy
`.env.example` there and set mode `0600`; never place its real values in this
repository, screenshots, or normal LangBot configuration logs.

LangBot 4.10.6 does not consistently serialize the original platform message
ID into plugin events. The bridge prefers `MessageChain.Source`; when absent it
uses a deterministic compatibility digest of trusted routing fields, event time
and text. The real Telegram/WeChat acceptance checklist records this limitation.
