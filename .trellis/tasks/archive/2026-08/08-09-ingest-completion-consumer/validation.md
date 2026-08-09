# Validation

Date: 2026-08-09

## Passing checks

- `./.venv/bin/pytest -q tests/test_ingest_notifications.py` — 28 passed.
- Notification observability additions — focused notification suite now covers
  the read-only oldest-eligible-age query, explicit 250 ms / 10% observation
  cap, empty-versus-young backlog signal, numeric diagnostic privacy allow-list,
  heartbeat fields, and isolation when that optional query fails.
- Focused notification/ingestion/action/deployment/LangBot/diagnostics/Trellis
  regression run — 135 passed, 1 skipped:
  `tests/test_ingest_notifications.py tests/test_action_models.py
  tests/test_ingest_completion.py tests/test_tasks.py tests/test_agent_actions.py
  tests/test_action_persistence.py tests/test_ingest_submission.py
  tests/test_deployment_health.py tests/test_langbot_startup_patch.py
  tests/test_diagnostics.py tests/test_validate.py`.
- Within that run, `tests/test_diagnostics.py` contributed 28 passing tests;
  existing diagnostic logging remains compatible with the notification
  heartbeat.
- `tests/test_action_models.py` now covers the new source-thread column,
  `ON DELETE SET NULL` foreign key, and source-thread index.
- `./.venv/bin/pytest -q tests/test_validate.py` — 3 passed.
- `python3 ./.trellis/scripts/task.py validate ingest-completion-consumer` —
  implement/check context manifests valid (7 entries each).
- Python compilation for the changed ingestion, model, action, pending-action,
  and migration modules — passed (including
  `app/ingest/notifications.py`, `app/ingest/tasks.py`, `app/models.py`,
  `app/config.py`, the migration, and notification tests).
- `./.venv/bin/alembic heads` — single head `a1b2c3d4e5f6`.
- `git diff --check` — passed.
- Sandbox-external PostgreSQL integration run:
  `./.venv/bin/pytest -q tests/test_ingest_submission_postgres.py
  tests/test_migration_roundtrip_postgres.py` — 17 passed in 371.58 seconds.
  The suites used their isolated-schema fixtures and completed without a
  failure.
- Sandbox-external notification PostgreSQL run:
  `./.venv/bin/pytest -q tests/test_ingest_notifications_postgres.py` —
  7 passed in 125.48 seconds. This exercises trusted source capture/replay,
  cross-tenant fail-closed behavior, real outer-join claims, fresh/stale claim
  fencing, retry ceiling/manual re-drive, and event/delivery cascade in
  disposable schemas without calling LangBot.

The deployment and environment guides now document the
`notification_poller_heartbeat` log marker, privacy-safe backlog/failed-ledger
inspection, and the implemented
`redrive_failed_ingest_notification(event_id)` Python hook. No public CLI or
HTTP endpoint was invented.

The follow-up check also verified that source-thread database failures abort
admission without creating a targetless dispatch, direct/confirmed/retry Agent
actions pass the trusted server thread, and terminal worker hooks do not call
the retired completion publisher. Runtime/model/migration constraints now
reserve `terminal_failure` and `retry_exhausted` dispositions for failed rows.
`README.zh-CN.md` and the deployment/environment topology, Redis durability,
full-profile, and rollback sections now consistently describe the PostgreSQL
poller/ledger and retired Redis completion queue.

## Concurrent-work boundary

After the concurrent bounded-autonomy commit became the `dev` branch HEAD, the
focused regression run completed with 134 passed, 1 skipped, and 2 failures.
Both remaining failures are owned by that concurrent change: a bare invalid URL
and a disabled save feature now hide their action tools before the canonical
`invalid_url` / `save_unavailable` results can be returned, so the model exhausts
its retries and reports `runtime_error`. The notification task's confirmation
test was updated to seed the trusted active-pending snapshot now required by the
bounded-autonomy runtime; its focused test passes.

- Re-running the focused suite while deselecting those two affected test
  functions completed with 133 passed, 1 skipped, and 3 deselected (the bare
  invalid/unsupported function is parametrized twice).
- Final Trellis context validation, Alembic single-head verification, and
  staged diff whitespace checks passed against the updated `dev` HEAD.

The concurrent autonomy setting in `app/config.py` was preserved while the
notification settings were merged additively. Natural-language evaluation,
MCP, Tencent deployment, and other shared-worktree files were excluded from
this task's validation and ownership.
