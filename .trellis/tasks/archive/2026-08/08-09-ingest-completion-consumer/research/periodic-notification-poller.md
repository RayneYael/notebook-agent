# Periodic completion-notification poller audit

Date: 2026-08-09

## Decision summary

There is no OS cron, APScheduler, or application-owned timer in this
repository. The existing periodic entry point is **Celery beat**, which submits
ordinary Celery tasks to the `maintenance` queue. Reusing that path for direct
completion polling is technically reliable **if the poller becomes the
authoritative notification path and uses a separate delivery ledger**.

It is not safe to merely add notification I/O to the existing completion
publisher sweep. That sweep claims `IngestCompletionEvent.publish_state` only
to publish broker messages; `publish_state='enqueued'` means Redis accepted an
event, not that a user was notified. The producer currently also performs an
immediate best-effort publish after every terminal transition. If that producer
is left enabled while no `ingest-completion` consumer exists, Redis accumulates
an unbounded durable queue of unused event IDs. If a future consumer is later
enabled, it would race the poller and may send duplicate notifications.

Recommended shape:

1. Keep PostgreSQL `IngestCompletionEvent` as the terminal-event outbox.
2. Add an immutable source-channel target and a separate
   `(event_id, handler_key)` notification delivery ledger.
3. Add one bounded `maintenance`-queue task scheduled by the existing Celery
   beat to claim and deliver notification rows directly.
4. Disable/retire completion-event broker publication (immediate publish and
   the broker-repair beat entry) when this poller becomes authoritative, or
   explicitly retain a separately owned queue consumer. Do not leave a producer
   writing an unconsumed queue in production.

This gives at-least-once notification with bounded poll latency, DB-backed
duplicate claims, stale-claim recovery, and no new completion worker process.
It does not give exactly-once platform sends; an outbound adapter crash after
acceptance and before the ledger commit remains a duplicate window.

## Existing periodic execution path

### Celery beat is the only scheduler

- `app/ingest/tasks.py:773-784` defines the entire `celery_app.conf.beat_schedule`.
  The existing schedules are `publish-pending-ingest-completion-events` and
  `purge-expired-items`, both routed to `maintenance`.
- The completion repair interval defaults to 60 seconds and is validated as a
  positive integer by `_completion_interval_from_env`
  (`app/ingest/tasks.py:751-768`; settings in `app/config.py:181-201,
  269-283`). Purge defaults to 3600 seconds
  (`app/ingest/tasks.py:746-749`).
- There is no `cron`, `apscheduler`, `systemd` timer, or `vercel.json` cron
  entry. `docker-compose.yml` provisions PostgreSQL, Redis and MinIO only
  (`docker-compose.yml:1-54`).
- Deployment starts one worker listening to `ingest,maintenance` and one beat
  process (`docs/deployment.md:207-215`; the equivalent full-MCP instructions
  are `docs/environment-configuration.md:126-151`). There is no Compose health
  check for beat liveness.

An external OS cron could invoke a new command, but that would be a new
deployment contract: it would need its own DB session lifecycle, lock/claim
semantics, secret configuration, timeout, metrics, and health monitoring. It
would not be reuse of an existing project entry point.

### Beat singleton and duplicate ticks

The deployment documentation says to start **only one beat**
(`docs/deployment.md:213-215`). Celery beat itself does not provide a database
leader lock here. A second beat would enqueue duplicate periodic task messages.
That is survivable for a poller only when its database claims are idempotent;
it is not a substitute for a delivery ledger or outbound idempotency key.

The current readiness checks inspect only the worker and its active queues:

- required worker queues are exactly `ingest` and `maintenance`
  (`app/mcp_readiness.py:24-38`);
- `_inspect_worker` requires a pong and those queues
  (`app/mcp_readiness.py:146-178`);
- readiness does not verify that beat is running or that a periodic task has
  executed recently (`app/mcp_readiness.py:218-267`).

For a production notification poller, add a safe scheduler heartbeat/backlog
age metric or operational check. Do not make MCP read readiness depend on
outbound notification availability unless product explicitly requires it.

## Existing claim, mutex and retry behavior

### Completion publisher claim is producer-only

`IngestCompletionPublisher` is a bounded repair publisher, not a notification
consumer:

- it selects only `publish_state='pending'` or stale `publish_state='claimed'`
  rows with `FOR UPDATE SKIP LOCKED`, writes a random `claim_token` and DB
  timestamp, and commits before broker I/O (`app/ingest/tasks.py:528-564`);
- it publishes each claimed event separately, uses a whole-sweep elapsed-time
  budget, isolates peer failures, and conditionally changes the same row to
  `enqueued` with the claim token (`app/ingest/tasks.py:566-669`);
- a publish failure releases the claim to `pending`, while a crash after broker
  acceptance leaves a stale claim for the next sweep
  (`app/ingest/tasks.py:613-652`, `1203-1231`).

The task wrapper (`app/ingest/tasks.py:710-721`) returns counters and does not
declare Celery retry/backoff. A database failure is converted to a safe failed
counter, so the next beat tick is the retry. The producer's immediate terminal
hook also calls best-effort publish (`app/ingest/tasks.py:1005-1019,
1472-1487`).

Do not reuse these publisher fields for user notification. In particular,
`publish_state='enqueued'` is only broker publication, and changing it to
`notified` would conflate producer recovery with consumer delivery and break
the existing queue contract.

### Purge service demonstrates the reusable pattern

`RecycleBinPurgeService` is the strongest existing periodic-worker pattern:

- candidates are claimed in bounded batches with PostgreSQL `now()` and
  `FOR UPDATE SKIP LOCKED`, then marked with a claim timestamp/attempt count
  before external object-store I/O (`app/agent/management.py:623-667`);
- each item is processed independently under a whole-sweep wall-clock budget;
  failures retain a fixed error code and clear the claim for a future pass
  (`app/agent/management.py:669-797`, `920-942`);
- stale claims become eligible again using `claim_timeout_seconds`; no process
  mutex is required because the row lock and claim token fence competing
  workers.

The notification poller should copy this structure but use its own delivery
ledger. It must claim rows, commit, call the external channel, and then perform
conditional success/failure updates; it must never hold a PostgreSQL lock while
calling LangBot/Telegram/WeChat.

### Celery task-level retry is not the safety mechanism

Only `fetch_text_task` declares Celery autoretry/backoff for
`TransientFetchError` (`app/ingest/tasks.py:433-445`). The periodic maintenance
tasks are plain tasks. Their reliability comes from the next beat tick plus
DB stale-claim recovery, not Celery redelivery. They also do not set
`acks_late`/`reject_on_worker_lost` in this module; a worker crash can lose that
particular scheduled invocation, but the next schedule tick will run again.

For notifications, this is acceptable only if every external effect is fenced
by the ledger and the poller is bounded. A poller crash after send and before
ledger success must leave a stale claim that a later tick reclaims; use the
stable event public ID as the adapter idempotency key where available.

## Proposed poller contract

### Task and schedule

Use a distinct task name on the existing maintenance queue, for example:

```text
task:     app.ingest.tasks.notify_ingest_completion_task
queue:    maintenance
schedule: INGEST_NOTIFICATION_INTERVAL_SECONDS (accepted default 10)
args:     none (the task selects bounded event IDs from PostgreSQL)
```

The user selected a 10-second default after this audit. Keep the whole-sweep
wall-clock budget below the interval and cap each outbound timeout by the
remaining sweep budget so slow LangBot calls do not create an unbounded stream
of overlapping maintenance tasks.

The task should return only safe counters such as `claimed`, `succeeded`,
`duplicate`, `skipped`, `retryable_failed`, `deferred`, and `duration_ms`.
Keep the current completion-repair task separate until broker publication is
retired; never make one task perform both producer claims and user effects.

### Delivery ledger

Add the ledger already recommended by the consumer design, with fields along
these lines:

```text
event_id                 FK -> ingest_completion_event ON DELETE CASCADE
handler_key              e.g. channel.notification.v1
status                   pending | claimed | succeeded | failed
disposition              ready | needs_extension | needs_asr | failed |
                         skipped_no_channel | skipped_deleted | skipped_disabled
claim_token              random opaque token
claimed_at               DB timestamp
attempts                 integer
next_attempt_at          DB timestamp for bounded retry/backoff
last_error_code          allow-listed stable code only
completed_at             DB timestamp
created_at / updated_at
UNIQUE(event_id, handler_key)
```

The poller query must use a compound index on status/next-attempt/claim time,
`FOR UPDATE SKIP LOCKED`, a stable `(created_at,id)` order, and a batch/elapsed
budget. A duplicate beat tick sees an existing unexpired claim and skips it;
stale claims are safely reclaimed. The ledger, not a Celery task ID or Redis
lock, is the duplicate-suppression root.

### Event selection and queue retirement

The poller should select terminal events from PostgreSQL independently of
`publish_state`; a failed broker publish must not suppress a user notification
if the event is otherwise deliverable. It should join the immutable target,
item and owner and apply delete/tenant/identity checks before claiming or
before the outbound send.

If the poller is authoritative, stop the terminal hook's immediate
`publish_ingest_completion_event` call and remove/disable the
`publish-pending-ingest-completion-events` beat entry after a migration/rollout
window. Existing `ingest-completion` Redis messages need an explicit drain or
expiry procedure; do not silently leave them accumulating. A future queue
consumer and this poller must never both own the same `channel.notification.v1`
handler.

If product insists on preserving the queue for another downstream consumer,
give that consumer a different named handler and document that the poller is a
separate subscription. Do not make the poller consume or mutate broker task
state, and do not claim the queue is unused while it is still being published.

### Retry and external send

1. Claim a pending/eligible failed row in a short DB transaction and increment
   `attempts`.
2. Commit before calling the selected outbound transport.
3. Render a bounded fixed message from the immutable event snapshot; never
   include URL, transcript, provider exception text, credentials, or unbounded
   metadata.
4. On a successful transport response, mark `succeeded` with a conditional
   `(event_id, handler_key, claim_token)` update.
5. On a terminal target/identity/deletion condition, mark a safe skipped
   disposition and ACK the effect without retry.
6. On classified timeout/5xx/DB transient failure, set a stable error code and
   `next_attempt_at` using bounded exponential backoff; a later beat tick picks
   it up. After the retry ceiling, keep `failed` for manual re-drive.

The poller must not rely on Celery task retry to recover a partially processed
batch. One event's failure must not prevent peer events from being claimed and
processed.

## Reliability assessment

| Concern | Existing periodic path | Reuse assessment |
| --- | --- | --- |
| Scheduler | One Celery beat, 60-second completion interval | Reusable; latency is interval-bounded, but beat liveness is not in readiness |
| Duplicate ticks | No beat leader lock | Safe only with per-row DB ledger claims |
| Distributed mutex | `FOR UPDATE SKIP LOCKED` + claim timestamps in maintenance services | Reusable; add claim token/expiry to notification ledger |
| External I/O | Purge releases DB lock before MinIO | Reusable pattern; use bounded LangBot HTTP timeout |
| Retry | Next beat tick and stale claim; no task autoretry | Reusable for bounded eventual retry; add `next_attempt_at`/backoff |
| Worker crash | Scheduled task may be lost; stale rows recover later | Acceptable if claim timeout < operational SLA and beat stays up |
| Queue isolation | Shared `ingest,maintenance` worker | Reusable but outbound I/O can delay purge/publisher; enforce batch/time budgets or add a dedicated notifications worker later |
| Readiness | Checks worker + maintenance config, not beat/backlog | Add notification backlog/heartbeat monitoring, keep MCP read path independent |
| Existing completion queue | Producer publishes durable `ingest-completion` IDs | Not reusable as-is; retire publication or add a real consumer, otherwise backlog/dual-send risk |

The polling design is therefore viable for a modest notification volume and a
60-second-or-lower latency target. It is not a reason to skip the ledger,
source-target table, outbound auth, or idempotency analysis. If the required
latency, volume, or transport retry duration exceeds the maintenance worker's
budget, split the poller onto a dedicated queue/worker while retaining the same
DB claim contract.

## Planning-document changes required

The current task artifacts were written for a future Celery completion
consumer. If this alternative is accepted, update them together:

### `prd.md`

- Replace R1's requirement to register
  `app.ingest.completion.consume`/`ingest-completion` with a periodic
  `maintenance` task and explicit beat interval/backlog SLA.
- Change the first sink from an internal queue consumer to
  `channel.notification.v1` delivery through the poller, while retaining the
  independent `(event_id, handler_key)` ledger requirement.
- Add source-target persistence and pending-confirmation propagation as an
  acceptance criterion; current `Out of scope` notification text is no longer
  valid.
- Add the queue-retirement decision: no unconsumed `ingest-completion` producer
  may remain enabled when the poller is authoritative.

### `design.md`

- Replace the Celery task/queue boundary with the periodic task boundary and
  document that Celery beat is a scheduler, not a distributed lock.
- Add poller selection/claim SQL, `next_attempt_at`, stale claim recovery,
  external-I/O timeout, and bounded sweep behavior.
- Keep producer `publish_state` separate from notification `status`; do not
  mutate the existing outbox state machine into a notification state.
- Add the source target table and direct-save/retry/pending-confirmation data
  flow from `source-channel-outbound-notification.md`.
- Document whether immediate broker publication and its repair schedule are
  removed, retained as a separate subscription, or migrated during rollout.

### `implement.md`

- Remove the task-registration/independent completion-worker step.
- Add migration/model work for notification target + delivery ledger, then
  implement the bounded periodic poller and outbound adapter.
- Add rollout steps for disabling old completion publishing, draining any
  existing Redis completion backlog, and monitoring beat heartbeat/notification
  backlog age.
- Test duplicate beat invocations, stale claims, worker crash after send,
  retry backoff, no-beat recovery, queue-retirement behavior, and source target
  privacy.

### Existing research/deployment docs

- Update `research/current-consumer-boundary.md`: the downstream boundary is a
  periodic poller, not an unregistered Celery task; its durable ledger still
  provides consumer idempotency.
- Update `design.md`/`prd.md` statements that say Telegram/WeChat notifications
  are out of scope once the source target and transport are selected.
- Update `docs/deployment.md` and `docs/environment-configuration.md`: start
  one beat + maintenance worker, remove the warning that the queue must await a
  future consumer, add LangBot outbound secret/network settings, and document
  scheduler/backlog/failed-ledger checks and rollback.

## Tests required for the poller path

- Beat schedule/task route points to the maintenance queue and validates a
  positive interval.
- Two simultaneous poller invocations claim disjoint ledger rows; duplicate
  invocations produce one successful effect.
- Stale claim recovery, `next_attempt_at` backoff, retry ceiling/manual
  re-drive, and peer isolation.
- Crash after platform acceptance before ledger success causes a duplicate
  attempt only when the transport lacks event-ID idempotency; idempotent fake
  transport sends once.
- Missing/purged/soft-deleted/disabled targets become terminal skips; restore
  creates a new dispatch/event/target.
- Beat outage and worker crash leave rows eligible for the next tick; backlog
  age and scheduler heartbeat diagnostics remain bounded and privacy-safe.
- Existing producer queue is either absent/disabled after migration or proven
  to have a distinct handler; no notification is sent by two active paths.
