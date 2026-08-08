# Reviewer findings — round 1

Status: resolved after seven implementation/review rounds. This file preserves
the round-1 baseline; the final independent review found no code release
blockers in the task scope.

## Resolution summary

- Delete confirmation now uses a server-owned code, trusted target snapshot,
  durable effect claim/lease, fenced idempotent outcomes, and fail-closed
  replacement/cancel/reset behavior.
- Inventory/detail output and bounded canonical history support visible rows,
  cursor continuation, and ordinal follow-ups.
- Auto-restore, broker failure recovery, worker/delete convergence, object
  cleanup intent, database-time retention, bounded purge, diagnostics, and
  downgrade safety were implemented and covered by focused tests.
- Final validation after migrating the local PostgreSQL database to
  `d4e5f6a7b8c9`: `228 passed, 1 skipped`, including `26 passed` for the real
  PostgreSQL + HTTP integration subset. The remaining skip requires an
  optional external provider/runtime, not task code.
- Real MinIO slow-connect/slow-response fault injection remains a deployment
  smoke item; adapter capability, retry count, timeout budgeting, and failure
  behavior are covered offline.

## P1 correctness

1. Delete confirmation is marked consumed before `soft_delete` succeeds. Crash/DB failure can persist a replayable
   success with no deletion. Build a recoverable idempotent state machine and persist canonical operation result;
   consumed must never mean effect unknown (`app/channels/pending_actions.py:327-353`,
   `app/agent/actions.py:186`).

2. A delayed “yes” for delete request A can consume newer active request B. Confirmation needs trusted generation/
   request correlation or must fail closed when correlation is unavailable (`pending_actions.py:262,334`).

3. Inventory/detail canonical text exposes only counts, while supported channels print only `answer.text`; users cannot
   see titles/IDs/details or continue cursor pages. Render bounded canonical metadata and retain safe server-owned
   continuation/reference context (`actions.py:106-131`, LangBot listener, CLI, runtime terminal action history).

4. Save-time auto-restore clears delete fields but fails to commit several pending/active dispatch return paths, so it
   can report accepted/already-exists while the item remains in trash. Every restore path must commit or atomically
   converge with dispatch creation (`app/ingest/submission.py:242-283`).

5. Explicit retry changes item to pending; broker publish failure marks only dispatch failed, leaving item permanently
   ineligible for retry. Restore a stable failed item state or safely recognize the matching failed dispatch
   (`submission.py:396-436`).

6. Delete during embedding can orphan a newly written MinIO object: raw key exists only in an uncommitted transaction,
   then deleted check rolls it back without deleting the object. Persist cleanup intent/key or delete explicitly across
   delete-during-put/embedding and crash windows (`app/ingest/tasks.py:214-230`).

7. Retention/purge decisions use worker `datetime.now()` instead of PostgreSQL time, so host clock skew can purge
   recoverable data early. Use database `now()`/interval decisions in list/delete/restore/claim/final delete; injected
   times may remain test-only (`app/agent/management.py:579,616` and related paths).

## P2 operations and rollback

8. Purge lacks elapsed-time bound, bounded object-client timeouts, diagnostics stages/metrics, and promised deployment
   capacity queries. Add a sweep wall-clock budget, safe purge observability, and DB/index/dead-tuple/backlog checks.

9. Migration downgrade unconditionally drops deleted fields and can resurrect trash. Downgrade must refuse with trash
   rows, and docs must require backup, restore-or-purge verification, disabling management/Beat, and retrieval smoke.

## P1 coverage

10. Add focused automated tests for all new behavior: tool schemas/routing/canonical visible rows and continuation,
    cursor bounds, tenant isolation, update, delete confirmation state/races and late generation, save auto-restore,
    retry/publish failure, worker/MinIO interleavings, database-time retention, purge concurrency/time bounds,
    diagnostics privacy, Beat routing, and migration safety. Existing-test passes are insufficient.

## Reviewer validation baseline

- Compilation passed.
- Existing focused tests: 100 passed.
- Offline Alembic SQL generation passed through `d4e5f6a7b8c9`.
- `git diff --check` passed.
- Full suite: 161 passed, 21 skipped; HTTP bind and PostgreSQL setup were sandbox-blocked.
