# Validation: video-worker completion queue

Date: 2026-08-09

## Automated results

- Final focused completion/tasks/management/deployment/migration subset:
  `64 passed, 1 skipped`.
- Sandbox-external PostgreSQL outbox and migration roundtrip:
  `17 passed`.
- Independent final reviewer subset after the last delta:
  `30 passed`.
- Full repository suite: `242 passed, 34 skipped, 3 failed, 9 errors`.
  The two HTTP failures and nine PostgreSQL setup errors are sandbox
  socket/network restrictions. The remaining provider-composition assertion
  belongs to concurrent uncommitted Agent URL/reference work and is outside
  this task's diff.
- Python compilation: passed.
- `git diff --check`: passed.
- Alembic: one head, `f6a7b8c9d0e1`.
- Trellis context manifests: valid.

## Reliability decisions verified

- Dispatch terminal state and one completion event commit atomically.
- `ContentItem.ready` wins a late failure-hook race.
- Broker envelopes contain only the internal event ID and use a durable queue;
  no local completion consumer is registered.
- Immediate publish failure does not change ingestion truth; maintenance
  recovers pending/stale claims with bounded PostgreSQL statements.
- Broker-accepted/DB-ack-crash duplicates retain the same event ID.
- Local Redis persists acknowledged completion messages with AOF
  `appendfsync=always`; remote brokers require equivalent durability.
- Physical item purge cascades the event and makes late publication a no-op.

## Environment note

The running Redis container predates the Compose command change and was not
restarted during this task, to avoid disrupting unrelated local work. New or
recreated Compose environments apply the documented AOF configuration.
