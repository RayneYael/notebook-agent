# Completion consumer: source-channel outbound notification research

Date: 2026-08-09

> Execution update: source-target and LangBot transport findings remain
> authoritative, but the user selected a periodic PostgreSQL poller on the
> existing Celery Beat + `maintenance` path instead of a dedicated queue
> consumer. Queue-specific recommendations below are superseded by
> `periodic-notification-poller.md`.

## Scope and conclusion

The completion consumer can notify the channel/conversation that submitted a
save or retry, but it cannot derive that destination from the current schema.
`IngestCompletionEvent` and `IngestDispatch` carry no source channel,
conversation, target kind, or bot account. `request_key` is an opaque
idempotency key with different formats for channel and MCP callers and must not
be parsed for routing.

The destination therefore has to be captured as server-owned state at
admission time, copied to the dispatch in the same transaction, and loaded by
the consumer using the dispatch ID. Pending confirmation is the important
exception: the target must be captured by the original bare-URL save request,
then carried through the later confirmation. The confirmation message's
channel is not a safe substitute.

The repository does contain a possible LangBot transport, but not a complete
notification contract. The ignored LangBot runtime exposes an API-key
protected `send_message` route; it has no idempotency key, source-target
authorization contract, or deployment configuration in this repository. A
product decision is still required between calling that route directly from
the completion worker and adding a signed loopback callback handled by the
bridge/plugin.

## Evidence: trusted inbound target fields

### Envelope, tenant and conversation

- `ChannelEnvelope` already receives the minimum identity tuple plus the
  conversation and source message IDs: `channel`, `account_id`,
  `external_user_id`, `conversation_id`, `message_id`, `request_id`, and
  `trace_id` (`app/channels/types.py:19-47`). The gateway replaces an
  untrusted request ID with its own value (`app/channels/http_gateway.py:98-104`).
- `ChannelService` resolves/registers the identity, gets the tenant-scoped
  conversation thread, and constructs `AgentRequest` with the internal thread
  IDs and source `message_id` (`app/channels/service.py:91-96`, `145-184`).
- A `ConversationThread` stores the immutable routing snapshot needed for a
  reply: `channel_identity_id`, `channel`, `account_id`, and
  `external_conversation_id` (`app/models.py:181-216`; created in
  `app/channels/conversations.py:26-48`).
- `AgentRequest` currently stores `TenantContext`, thread IDs, `message_id`,
  and `request_id`, but does not carry an explicit target or target kind
  (`app/agent/types.py:74-88`). `TenantContext` does include
  `channel_identity_id`, `channel`, `account_id`, and `external_user_id`
  (`app/channels/types.py:50-60`), so the request-scoped target can be built
  without consulting model history.

The target kind is a missing field. LangBot's generic outbound API requires
`target_type` (`person` or `group`), while the Notebook Agent envelope only
has `conversation_id`. If group support is in scope, capture a server-derived
`target_type`/`conversation_kind` in the bridge event; do not infer it from an
ID's shape.

### Direct save and retry paths

- Direct model actions eventually call the trusted submission service. `save_videos`
  builds an opaque request key from thread/message IDs and calls `_submit`
  (`app/agent/actions.py:417-438`, `526-544`).
- Retry similarly calls `IngestSubmissionService.retry_item` with a different
  opaque request-key format (`app/agent/actions.py:318-338`). These two formats
  are application idempotency keys, not transport addresses.
- `_submit_reference` creates the `ContentItem` and `IngestDispatch` in one
  transaction, but the dispatch only stores `public_id`, `item_id`,
  `request_key`, `attempt`, and state (`app/ingest/submission.py:323-437`;
  `app/models.py:374-416`). `retry_item` has the same omission
  (`app/ingest/submission.py:480-589`).
- `AgentActionRuntime` is request-scoped, so it is the correct boundary to
  pass an internal source-target snapshot to submission. The snapshot must
  never be a model/tool argument or be put into model history.

For a direct save, the target should be the current request's channel,
account, user, conversation, target kind, and source message. For a retry, the
new dispatch should use the channel/conversation that issued that retry. The
old dispatch target is immutable; a retry from a linked second channel should
not silently rewrite the original notification destination.

### Pending confirmation: preserve the original target

Bare URL saves first call `PendingConfirmationService.request_save`, which
persists a `PendingChannelAction` containing only versioned URLs and an expiry
(`app/channels/pending_actions.py:86-125`; `app/models.py:253-285`). The later
`confirm_save` locks and consumes the active action, records the confirming
message ID, and returns only the URLs/action ID (`app/channels/pending_actions.py:127-182`).
`AgentActionRuntime.confirm` then submits those URLs using a new confirmation
request key (`app/agent/actions.py:440-463`).

The confirmation can be a separate message and can arrive after a channel link
has changed. Recommended propagation is:

1. `request_confirmation` passes the current `ChannelEnvelope` target to
   `request_save`.
2. `request_save` stores a normalized, server-owned target row keyed by the
   pending action ID (or equivalent explicit columns); only a bounded action
   reference is exposed in the model-facing result.
3. `confirm_save` returns the original action ID/target as an internal field.
4. `AgentActionRuntime.confirm` passes that original target to submission,
   regardless of the confirmation message's current `message_id` or channel.
5. Submission copies the target into the dispatch notification-target row in
   the same transaction that creates the dispatch.

Do not put the target or URL into `ConversationTurn.model_messages`, tool
arguments, broker payloads, or logs. Existing pending inspection deliberately
returns only `active` and a bounded count (`app/channels/pending_actions.py:208-251`),
which should remain the public contract.

## Recommended persistent boundary

Use immutable normalized records rather than parsing `request_key` or resolving
the latest channel identity at delivery time.

```text
ingest_notification_target
  dispatch_id                 PK/FK -> ingest_dispatch ON DELETE CASCADE
  channel                     check telegram|wechat (or an explicitly chosen set)
  account_id                  LangBot bot UUID snapshot
  external_user_id            platform sender ID snapshot
  conversation_id             platform launcher/chat ID snapshot
  target_type                 check person|group
  channel_identity_id         nullable FK channel_identity ON DELETE SET NULL
  source_message_id           optional correlation-only field
  created_at                  timestamptz not null
```

For a pending action, use a separate one-to-one target table keyed by
`pending_channel_action.id`, or add explicit immutable target columns to that
row. Do not overload the `payload` JSON with an unvalidated transport object.
At submission time validate that the target identity belongs to the tenant and
is active; copy the snapshot to `ingest_notification_target` before commit.
The dispatch target is a historical routing decision, not a pointer to the
user's latest identity.

The consumer should join `event -> dispatch -> target -> item -> owner` from
PostgreSQL. It should verify the current identity still matches
`(channel, account_id, external_user_id)`, belongs to the item tenant, and is
not disabled. If the event/item is missing, soft-deleted, purge-claimed, or
the owner/target identity is disabled, record a fixed `skipped_no_channel` or
`skipped_deleted` disposition and ACK without sending. A restore creates a new
dispatch/event/target and must never reuse the old row.

The queue envelope remains exactly `[completion_event_id]`; the target is not
serialized into Celery. The existing producer explicitly sends only the event
ID (`app/ingest/tasks.py:1270-1344`; `tests/test_ingest_completion.py:50-96`).

## Existing LangBot outbound capability

The local ignored LangBot 4.10.6 runtime has a generic outbound service:

- `BotService.send_message(bot_uuid, target_type, target_id,
  message_chain_data)` validates a platform `MessageChain` and calls
  `runtime_bot.adapter.send_message` (`.runtime/langbot/patched_site/langbot/pkg/api/http/service/bot.py:177-201`).
- The controller exposes `POST
  /api/v1/platform/bots/<bot_uuid>/send_message` and requires an API key,
  either `X-API-Key` or `Authorization: Bearer ...`; accepted target types are
  exactly `person` and `group` (`.runtime/langbot/patched_site/langbot/pkg/api/http/controller/groups/platform/bots.py:41-64`,
  `.runtime/langbot/patched_site/langbot/pkg/api/http/controller/group.py:90-109`).
- API keys are either `api.global_api_key` or a database key prefixed `lbk_`
  (`.runtime/langbot/patched_site/langbot/pkg/api/http/service/apikey.py:43-80`).
  The checked-in `.runtime/langbot/data/config.yaml` has an empty global key,
  and this repository does not configure a worker-side LangBot API key.
- The endpoint returns success only after the adapter call, but has no
  event-id/idempotency field and catches/logs arbitrary adapter exception text
  before returning a 500 (`.../bots.py:49-64`). A completion worker crash after
  platform acceptance and before its ledger commit can therefore duplicate a
  message.
- LangBot's HTTP controller enables CORS `*` and binds to `0.0.0.0`
  (`.runtime/langbot/patched_site/langbot/pkg/api/http/controller/main.py:25-31`,
  `55-93`). Treat the API key as a high-value deployment secret and restrict
  network reachability; do not assume this is a loopback-only endpoint.

This proves that a direct transport is technically possible, but does not make
it a complete product boundary. The worker still needs an explicit URL,
credential, timeout/retry policy, bot UUID allow-list, target conversion, and
an at-least-once duplicate policy.

### Platform target semantics

- Telegram converts a private event to a friend whose ID is the effective chat
  ID and a group event to a group whose ID is the effective chat ID
  (`.runtime/langbot/patched_site/langbot/pkg/platform/sources/telegram.py:213-243`).
  The outbound adapter parses `target_id` as `chat_id[#message_thread_id]` and
  sends text/photo/document components to that chat (`.../telegram.py:449-481`).
  The adapter's `get_launcher_id` uses the same `chat_id#thread_id` encoding for
  forum/private topics (`.../telegram.py:789-805`). Persisting the exact
  `conversation_id` therefore preserves Telegram topic routing.
- WeChatPad's converter uses `from_user_name.str` as the friend ID and
  `from_user_name.str` ending in `@chatroom` as the group ID
  (`.runtime/langbot/patched_site/langbot/pkg/platform/sources/wechatpad.py:471-519`).
  Its outbound method sends to the supplied target ID via `to_wxid`; it accepts
  the generic `target_type` parameter but does not use it
  (`.../wechatpad.py:573-633`). Persist the exact WeChat wxid, not a nickname.
- The committed bridge maps each LangBot bot UUID to a normalized channel and
  forwards `channel`, bot UUID, sender ID, launcher/conversation ID, and source
  message ID (`integrations/langbot_kb_plugin/components/event_listener/knowledge_agent.py:87-102`,
  `131-153`). Its documented private mapping is currently Telegram and
  WeChat (`integrations/langbot_kb_plugin/.env.example:3-7`,
  `docs/deployment.md:399-409`).
- The bridge currently registers only `events.PersonMessageReceived`
  (`.../knowledge_agent.py:81-85`). LangBot emits a separate
  `GroupMessageReceived` event (`.runtime/langbot/patched_site/langbot/pkg/pipeline/pipelinemgr.py:340-367`).
  If group saves are required, the bridge must explicitly handle that event and
  persist a server-derived `target_type="group"`; otherwise the notification
  contract should state that only private conversations are supported.

## MCP behavior

MCP intentionally has no Telegram/WeChat destination:

- MCP creates a synthetic `ChannelEnvelope` with `channel="mcp"`, account ID
  and external user ID derived from the grant (`app/mcp_server.py:560-589`,
  `633-667`, `707-716`).
- Direct submit and retry call the submission service with synthetic opaque
  request keys (`app/mcp_server.py:787-828`, `1010-1033`).
- `MCP_CHANNEL`/`MCP_ACCOUNT` are fixed to `mcp` (`app/mcp_grants.py:29-33`),
  and `ChannelIdentity`/linking intentionally treats Telegram and WeChat as
  the linkable user-facing channels (`app/channels/identity.py:37-40`,
  `254-278`).

MCP submissions should persist no outbound target. The consumer should ACK with
`skipped_no_channel`; it must not retroactively notify a Telegram/WeChat
identity later linked to the same tenant. If product wants MCP callbacks, that
is a separate transport and target contract.

## Outbound transport choices

### Option A: completion worker calls LangBot's generic API

The worker calls the API-key-protected `send_message` endpoint using the
immutable bot UUID and target snapshot. This is the smallest implementation,
but requires:

- a new worker-side LangBot URL/API-key setting and secret handling;
- network placement/restriction because LangBot binds publicly by default;
- mapping `target_type` and platform-specific IDs (`chat#topic` for Telegram,
  wxid for WeChatPad);
- bounded HTTP timeout and classification of 4xx (terminal target/config)
  versus 5xx/timeouts (retryable transport);
- downstream dedupe. The existing route has no idempotency key, so the
  completion ledger can only provide at-least-once delivery, not exactly-once
  platform sends.

### Option B: add a signed loopback notification callback

Add a distinct callback endpoint/component to the installed bridge/plugin. The
completion worker sends a bounded payload containing `event.public_id`, fixed
outcome/disposition, target snapshot, and a short-lived timestamp/nonce. The
callback verifies an HMAC, rejects replay, resolves the configured LangBot bot,
and invokes the adapter. The existing inbound gateway supplies a reusable
pattern: 32-byte secret, timestamp/nonce, HMAC-SHA256, a 60-second freshness
window, and nonce replay protection (`app/channels/http_gateway.py:27-64`,
`78-111`; bridge signing at
`integrations/langbot_kb_plugin/components/event_listener/knowledge_agent.py:156-182`).

This keeps the worker from using LangBot's broad admin API and allows the
bridge to own platform conversion, but it requires a plugin-side listener/API
that does not exist today. The callback must still use `event.public_id` as its
downstream dedupe key; a crash after adapter acceptance remains an at-least-once
duplicate window unless the adapter itself supports idempotency.

Do not reuse the inbound `/v1/messages` endpoint for completion payloads: its
contract is an authenticated user envelope and it synchronously invokes the
agent. Use a separate path and allow-listed schema if Option B is chosen.

## Consumer delivery contract for notifications

The notification handler should be an additional named handler (for example
`channel.notification.v1`) in the existing `(event_id, handler_key)` ledger;
it must not overload producer `publish_state`. Recommended rules:

1. Claim one event/handler row with a random token in a short DB transaction.
2. Load event, dispatch, item, owner, and immutable target from PostgreSQL.
3. Verify tenant ownership, target identity state, deletion/purge state, and
   target fields before rendering.
4. Render bounded, fixed messages from the event snapshot only. Do not include
   transcript, provider error text, credentials, raw URLs, unbounded title or
   metadata. Suggested routes are `ready`, `needs_extension`, `needs_asr`, and
   `failed` with stable user-safe text.
5. Release the DB claim before external I/O. After a successful send, mark the
   ledger row `succeeded` using `event_id + handler_key + claim_token`; after a
   classified terminal skip, mark it succeeded with a skip disposition.
6. Use `event.public_id` as the transport idempotency key wherever the selected
   adapter/callback supports one. A crash after external acceptance and before
   ledger commit is otherwise an expected duplicate under at-least-once
   delivery.
7. Retry only bounded transient DB/transport errors. Missing/purged/disabled
   targets and invalid contract data are terminal no-ops or stable failures.

Do not send a completion notification merely because `publish_state` is
`enqueued`; that state only means the broker accepted the event
(`app/models.py:419-459`, `app/ingest/tasks.py:1270-1344`).

## Identity and deletion races

- `ChannelIdentity` is unique by `(channel, account_id, external_user_id)` and
  has `disabled_at` (`app/models.py:76-101`). Resolve/validate the immutable
  target against this tuple and tenant at submission and again before send.
- A disabled user/identity must produce a fixed skip, not a send to a newly
  bound identity with the same display name. Never resolve “latest identity” by
  tenant alone.
- Tenant linking/merge locks identities, threads, items, and dispatches; loser
  content/dispatch rows can be deleted (`app/channels/identity.py:314-429`). A
  late event for a deleted loser is a missing/purged no-op. Do not retarget it to
  the surviving channel.
- Soft deletion and purge claims are separate from ingestion state
  (`app/models.py:329-340`). A delete-after-event race must suppress the
  user-facing notification. Physical purge cascades the event/dispatch/target;
  a late queue message cannot recreate any row.
- Restore/resave gets a new dispatch/event/target. It must not reuse an old
  notification ledger row or revive a notification for a deleted attempt.

## Required tests before enabling the handler

- Target capture: direct Telegram/WeChat private save, direct group save (once
  group events are supported), retry from each channel, and pending save followed
  by confirmation from a different message.
- Target correctness: exact bot UUID, sender ID, conversation ID, Telegram topic
  suffix, WeChat wxid, `person`/`group` kind, and source message correlation.
- Pending actions: original target survives confirmation; cancellation/expiry
  creates no dispatch target; target is not visible in model history or tool
  payloads.
- MCP direct save/retry creates no target and returns `skipped_no_channel` in the
  consumer; no later-linked channel receives a message.
- Identity races: disabled identity, tenant merge loser, bot deletion/runtime
  unavailable, soft-delete, purge claim, physical purge, restore/new dispatch,
  and target reassignment attempts.
- Delivery semantics: concurrent duplicate events, stale claim recovery,
  handler success followed by ledger-write crash, transport timeout/5xx retry,
  terminal 4xx/no-target skip, callback HMAC timestamp/nonce replay, and API-key
  rejection.
- Privacy: Celery payload/result, logs, diagnostics, and outbound body contain
  only bounded fixed notification fields; no URL, title, transcript, storage
  key, provider exception, raw API key, or tenant secret.

## Product decision required

The current internal lifecycle consumer plan can remain the first sink, but the
user-facing requirement adds a separate outbound-notification scope. Before
implementation, choose:

1. direct LangBot `send_message` with a new API-key/network contract; or
2. a new signed loopback callback/plugin listener.

That choice fixes where adapter conversion, idempotency, retry classification,
and secrets live. Until it is selected and the source target is persisted, do
not register a consumer that guesses from `request_key`, current identities,
thread history, or the latest linked channel.

## Decision after user clarification and official-source verification

The user explicitly selected proactive notification to the source channel.
The planning decision is Option A: call LangBot 4.10.6's official API-key
protected `POST /api/v1/platform/bots/<bot_uuid>/send_message` endpoint from the
completion worker. Official tag `v4.10.6` (commit
`cb6c8d1eb62ebae65425d5a418e92f0ceb53491e`) confirms:

- the controller accepts `target_type`, `target_id`, and a validated
  `message_chain`, and requires API-key auth;
- `BotService.send_message()` resolves the exact runtime bot and delegates to
  its adapter;
- Telegram preserves `chat_id#message_thread_id`, while OpenClaw WeChat sends
  to the exact source wxid.

The implementation will allow loopback HTTP or HTTPS only, use a dedicated
worker-side API key, retain at-least-once duplicate semantics for the narrow
platform-accept/ledger-commit crash window, and extend the maintained LangBot
patch so the upstream endpoint no longer prints/returns raw adapter exception
text. Group notification remains out of scope because the checked-in bridge
currently handles only `PersonMessageReceived`.
