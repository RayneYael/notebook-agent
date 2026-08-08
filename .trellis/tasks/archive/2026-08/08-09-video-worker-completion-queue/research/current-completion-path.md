# Current video-worker completion-path audit

Date: 2026-08-09

## Current path

`IngestSubmissionService` creates a tenant-owned `ContentItem` and durable
`IngestDispatch`, then `publish_ingest_dispatch()` publishes only the internal
dispatch ID to `fetch_text_task` on the `ingest` Celery queue.

The worker path is:

```text
fetch_text_task(dispatch_id)
  -> process_dispatch(dispatch_id, celery_task_id)
  -> _claim_dispatch(): pending/enqueued -> running
  -> process_item(): fetching -> chunking -> embedding -> ready
  -> _complete_dispatch(): running -> completed
```

`NeedsExtension` and `NeedsASR` are normal `process_item()` returns. They set the
item to `needs_extension` or `needs_asr`, after which `_complete_dispatch()`
still marks the dispatch `completed`. A non-transient exception marks the
dispatch and non-ready item failed. A transient exception first releases the
dispatch back to `enqueued`; only retry exhaustion becomes a terminal failure.

Duplicate delivery is already bounded: `_claim_dispatch()` accepts only
`pending/enqueued`, checks a conflicting Celery task ID, and returns no work for
running/completed/failed rows.

## Gap

The terminal database transition has no downstream event. The Celery result
backend records a task result, but it is not the business contract: it cannot
atomically accompany the dispatch state, is addressed by a Celery task ID, and
does not distinguish `ready` from the other normal item states without coupling
consumers to worker return values.

Publishing directly after `_complete_dispatch()` introduces a dual-write gap:

1. if the broker publish happens first and the database transaction later
   rolls back, consumers observe a completion that never happened;
2. if the database commits first and the worker crashes before publish, the
   dispatch is terminal but no consumer is notified;
3. if the broker accepts the event and the worker crashes before recording the
   acknowledgement, a repair pass must publish the event again.

Only the third case is safely representable as at-least-once delivery. A stable
event identifier and idempotent consumer are therefore mandatory.

## Existing patterns to reuse

- `IngestDispatch` conditional row locks and state transitions already enforce
  source idempotency.
- `_bounded_publish_options()` and the request-local Kombu producer provide
  bounded broker connection, socket, retry, and publish behavior without the
  shared-pool hang seen in the Agent save path.
- `RecycleBinPurgeService` demonstrates bounded batches, `FOR UPDATE SKIP
  LOCKED`, stale claim recovery, per-row isolation, safe counters, and beat on
  the `maintenance` queue.
- Runtime logging permits stable stages, internal IDs, safe error codes,
  counters, and durations, but forbids URLs, content, external identities,
  secrets, provider payloads, and exception messages.

## Proposed seam

Create a durable `IngestCompletionEvent` outbox row in the same transaction as
the terminal dispatch transition. The broker message contains only its internal
ID. An immediate bounded publish provides low latency; a bounded maintenance
sweep repairs pending/stale claims. Broker acknowledgement marks only that the
event was enqueued, not that any downstream business consumer completed.

The completion queue is deliberately a consumer seam. This task must not start
an empty worker on that queue, because doing so would acknowledge and discard
events before a real notification or workflow consumer exists.
