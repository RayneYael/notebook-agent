# Ingestion completion consumer boundary

Date: 2026-08-09

> Superseded execution decision: this document established the need for a real
> business sink and a durable delivery ledger. The user subsequently selected
> the existing Celery Beat + `maintenance` database poller instead of a
> dedicated `ingest-completion` queue worker. See
> `periodic-notification-poller.md`; the deletion, privacy, ledger and
> source-of-truth findings below still apply.

## Finding

The producer-side queue is complete, but the repository has no existing
downstream business effect that a completion consumer can safely perform. The
current completion task name is intentionally not registered
(`app/ingest/tasks.py:43-64`; `tests/test_ingest_completion.py:21-27`). The
consumer therefore needs an explicit business sink and a durable consumer-side
claim/ack record; registering a task that only returns would acknowledge and
discard the message without implementing the requested post-processing.

The smallest useful first consumer is a database-backed dispatcher:

1. accept exactly one `completion_event_id`;
2. load the event, dispatch, and item from PostgreSQL (never trust queue data
   beyond the integer ID);
3. atomically claim one consumer delivery by stable event ID;
4. route the immutable `(outcome, item_state, error_code)` snapshot to an
   injected, versioned business handler;
5. persist handler success and acknowledge the Celery message only after the
   side effect is durable; and
6. treat a missing/purged/deleted target as a privacy-safe no-op.

Until a real handler is selected, the deployment should keep the queue
unconsumed rather than installing a no-op task.

## Existing source contract and integration points

### Event and worker state

- `process_dispatch()` claims an `IngestDispatch`, runs `process_item()`, and
  finalizes terminal state (`app/ingest/tasks.py:804-838`). The normal terminal
  snapshots are `ready`, `needs_extension`, and `needs_asr`; only retry
  exhaustion or a non-transient error becomes `failed`.
- `_complete_dispatch()` and `_mark_dispatch_failed()` create at most one event
  in the same locked transaction as the terminal dispatch transition
  (`app/ingest/tasks.py:938-1024`, `1375-1472`). A ready item wins the crash
  window in the failure hook, so the consumer must not downgrade a `ready`
  snapshot based on a later task result.
- `IngestCompletionEvent` contains `public_id`, `dispatch_id`, `item_id`, an
  immutable `outcome`/`item_state` snapshot, stable `error_code`, and publisher
  state only (`app/models.py:419-490`). `publish_state='enqueued'` means the
  durable broker accepted the envelope; it does **not** mean a business
  consumer ran.
- The event has unique `dispatch_id` and cascading FKs to both dispatch and
  item. Physical purge therefore removes the event before a late message can
  load it (`app/models.py:433-439`; `migrations/versions/f6a7b8c9d0e1_ingest_completion_events.py:52-72`).

### Current downstream behavior

- Retrieval already reads PostgreSQL directly and requires
  `ContentItem.state == 'ready'` plus `deleted_at IS NULL`; there is no search
  index or cache that needs a completion callback
  (`app/agent/services.py:230-259`, `app/retrieval/search.py:47-79`).
- Save and retry responses are immediate `queued`/`retry_queued` outcomes and
  do not persist a notification target in `IngestDispatch`; submission stores
  only item, request key, and dispatch metadata
  (`app/ingest/submission.py:172-184`, `323-475`, `480-589`).
- The LangBot bridge is inbound-only: it receives a `PersonMessageReceived`,
  POSTs a signed envelope to the loopback gateway, and replies in that same
  request (`integrations/langbot_kb_plugin/components/event_listener/knowledge_agent.py:79-132`,
  `156-190`). There is no outbound adapter API, pending notification table,
  channel/conversation target on the dispatch, or webhook configuration.
- `NeedsExtension` and `NeedsASR` are terminal capability states, but the
  repository has no extension/ASR follow-up task or handler
  (`app/connectors/base.py:40-58`; `app/connectors/youtube.py:149-177`).

Consequently, a consumer that proactively sends a Telegram/WeChat message
would have to guess the originating channel/conversation, bypass the bridge's
authorization boundary, and potentially disclose a deleted item. That is not
safe without a separate notification design.

## Minimal consumer contract

### Durable idempotency state

`IngestCompletionEvent` has no consumer status. Add a migration/model for a
consumer delivery ledger, for example `ingest_completion_delivery`:

```text
id                  bigint primary key
event_id            bigint not null -> ingest_completion_event(id) on delete cascade
handler_key         text not null                 # e.g. "internal.v1"
status              text not null                 # claimed | succeeded | failed
claim_token         text nullable
claimed_at          timestamptz nullable
attempts            integer not null default 0
last_error_code     text nullable                 # stable allow-listed code
completed_at        timestamptz nullable
created_at          timestamptz not null
updated_at          timestamptz not null
unique(event_id, handler_key)
```

The ledger must be forward-compatible and use PostgreSQL checks/indices rather
than a new enum. Claim rows in a short transaction with `FOR UPDATE` (or
`SKIP LOCKED` for a batch), commit before external handler I/O, and use a
claim-timeout token for crash recovery. `succeeded` is the durable duplicate
guard. A single event may later fan out to multiple handlers, hence the
`handler_key` even if the first release has one handler.

If the chosen handler is entirely database-local, the claim and success
projection may be committed in one transaction. Do not hold a database lock
while calling a future HTTP/webhook/platform adapter.

### State routing

Route from the event snapshot, not from a live item state that can change after
the worker committed:

| Snapshot | First handler responsibility |
| --- | --- |
| `completed + ready` | publish/record “searchable” completion; never re-run ingestion |
| `completed + needs_extension` | dispatch an explicitly implemented extension workflow, or record “action required”; do not claim ready |
| `completed + needs_asr` | dispatch an explicitly implemented ASR workflow, or record “action required”; do not claim ready |
| `failed + failed + error_code` | record/notify a stable failure outcome; do not mutate the source dispatch/item |

Unknown combinations are non-retryable schema/contract errors. The consumer
must not treat `dispatch.state == completed` as equivalent to `item_state ==
ready`.

### Delivery and retries

- Register exactly `app.ingest.completion.consume` with the existing Celery app
  and route it to `ingest-completion` (`app/ingest/tasks.py:43-64`). The task
  should use late acknowledgement/requeue-on-worker-loss semantics and a
  bounded retry policy for transient handler/DB failures. Never call
  `process_item()` from the consumer.
- On duplicate delivery, a `succeeded` ledger row returns a fixed duplicate
  result and ACKs without executing the handler. If the worker dies after the
  external handler succeeds but before the ledger commit, the handler must
  accept `event.public_id` (or event ID) as its idempotency key; at-least-once
  delivery cannot provide exactly-once effects by itself.
- Handler failures must become stable codes such as
  `completion_handler_unavailable`, `completion_handler_failed`, or
  `completion_contract_invalid`; do not persist/log provider URLs, exception
  text, titles, transcript, or payloads. Retry only the transient classes.
- A missing event/item is a safe terminal no-op: the event may have been
  physically purged, or a tenant merge may have deleted the loser and cascaded
  its event. ACK the message after a numeric `missing`/`purged` diagnostic.

## Deletion, tenant, and privacy rules

- Load the event and item through trusted DB joins and verify the item belongs
  to its persisted `AppUser`; the queue carries no tenant/channel identity.
- If the item is soft-deleted or `purge_claimed_at` is set when the consumer
  runs, skip user-facing effects and ACK as a no-op. A delete-after-event race
  must not resurrect or reveal content. If the item is restored, submission
  creates a new dispatch/event; never reuse the old ledger row.
- A physical purge cascades the event, dispatch, and segments. Late delivery
  must not recreate any row. Tenant merge can similarly retire a duplicate;
  loser events are expected to disappear. See
  `app/agent/management.py:400-530, 620-800` and
  `app/channels/identity.py:314-410`.
- Do not put URL, title, transcript, segment, storage key, channel identity,
  conversation ID, or exception text in the Celery payload or production logs.
  The existing producer already serializes only `[event_id]`
  (`app/ingest/tasks.py:1270-1343`; `tests/test_ingest_completion.py:50-96`).

## Deployment routing

The current ingestion worker intentionally listens only to `ingest,maintenance`
and the readiness probe requires exactly those mutation queues
(`docs/deployment.md:207-229`; `app/mcp_readiness.py:38,146-177`). Deploy the
consumer as a separately named worker with an explicit queue, for example:

```bash
.venv/bin/celery -A app.ingest.tasks.celery_app worker \
  --loglevel=INFO --queues=ingest-completion
```

Co-hosting is possible only when the command explicitly includes all three
queues. Do not add `ingest-completion` to the existing worker command before
the handler is registered. Keep the mutation readiness check independent; if
completion processing is mandatory for a deployment, add a separate
completion-worker/backlog check rather than making read-only MCP startup
depend on it. Beat remains responsible only for the outbox repair sweep on
`maintenance`.

## Observability and validation

Use the existing fixed completion diagnostic style (`completion_event_*` in
`app/diagnostics.py:23-57`) and add only bounded stages/counters such as
`completion_claimed`, `completion_succeeded`, `completion_duplicate`,
`completion_skipped`, `completion_retry`, and `completion_failed`. Include
internal event ID, handler key, stable outcome/error code, counts, and duration;
never exception messages or private item fields.

Minimum tests for the consumer task:

- task registration, exact queue route, one-ID-only payload, and dedicated
  worker command/readiness behavior;
- `ready`, `needs_extension`, `needs_asr`, and terminal `failed` routing;
- concurrent duplicate deliveries and duplicate after handler-success/ledger-
  commit crash;
- transient retry versus terminal non-retryable handler failure;
- missing event, soft-delete, purge-claim, physical purge cascade, tenant merge,
  restore/new-dispatch, and tenant-isolation cases;
- privacy sentinels absent from broker payload, task result, and production
  logs.

## Open decisions before implementation

1. What is the real first business sink: an internal searchable-status
   projection, a Telegram/WeChat notification, a webhook, or an extension/ASR
   scheduler? Only the first option is implementable with current tables.
2. If notifications are required, which origin channel/conversation receives
   them? Add an immutable, tenant-bound notification target to the submission
   transaction and design a durable outbound adapter; do not infer it from
   `request_key` or current identities.
3. Is one handler sufficient, or should the ledger support multiple named
   handlers from day one? The latter avoids changing the uniqueness contract
   when webhook/index/notification consumers are added.
4. Should completion-consumer availability gate the full MCP profile? Current
   readiness only guarantees ingestion and maintenance workers, so this needs
   an explicit rollout decision rather than an accidental queue requirement.
