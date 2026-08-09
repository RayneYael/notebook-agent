# 稳定 full 启动与评测清理

## Goal

Make full launch start worker, Beat, and MCP without dependency probes controlling lifecycle; fix natural-language eval teardown task affinity.

## Requirements

- `full` must launch the Celery worker, the single Beat scheduler, and the MCP
  server as one command without waiting for deep dependency probes before
  launching later components.
- Slow or transient PostgreSQL, Redis, MinIO, or Celery inspection results may
  update diagnostics, but must not stop otherwise-live managed processes.
- A managed child process that actually exits must still stop its sibling
  processes so the runtime does not remain partially owned.
- Static configuration validation, owned Compose startup, and the single
  Alembic migration remain required before application children are launched.
- The MCP listener must be reachable before `start` reports success; deep
  dependency health is checked separately and on demand through `status`.
- Natural-language evaluation teardown must close the MCP stdio context in the
  same asyncio task that opened it, while retaining bounded teardown.
- Preserve secret redaction, PID/run ownership, exactly-one-Beat protection,
  and existing manual deployment commands.
- Commit and push the fix only to `dev`; do not modify or push `main`.

## Acceptance Criteria

- [x] `full` spawns worker, Beat, and MCP before any deep runtime health
      snapshot is required.
- [x] Dependency health degradation changes `status` diagnostics but is not a
      lifecycle stop signal and does not block the supervisor loop.
- [x] Immediate child exit still fails startup or stops a running sibling set.
- [x] MCP and evaluation readiness budgets cover a real single-worker Celery
      inspection on the supported local environment.
- [x] `--preflight` exits cleanly without AnyIO cross-task cancel-scope errors.
- [x] Focused deployment, MCP, worker, and evaluation regressions pass, apart
      from any independently reproduced baseline failure.
- [x] No generated runtime config, logs, evaluation output, or secrets are
      committed.

## Constraints

- This change does not merge worker and Beat into one OS process.
- This change does not make startup responsible for external service recovery.
- A paid live-model smoke run requires separate explicit authorization; the
  no-cost full-stack preflight is sufficient for lifecycle verification.
