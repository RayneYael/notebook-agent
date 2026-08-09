# Implementation plan: profile-aware one-command startup

## 1. Freeze the deployment contract

- Confirm the profile names and the default profile with the user.
- Inventory exact required settings for `read`, `full`, and `langbot` without
  duplicating values already defaulted by `app.config.Settings`.
- Decide whether managed values use a separate generated file or append-only
  updates to `.env`; preserve operator-owned data in either case.
- Gate: review `prd.md` and `design.md` before task activation.

## 2. Build testable planning and configuration primitives

- Add immutable profile/process plans and profile-specific validation.
- Add minimal environment serialization with secure file creation and secret
  redaction.
- Add injected command runner, readiness waiter, and runtime-state abstractions
  so lifecycle behavior can be tested without real services.
- Cover precedence, missing values, local versus remote dependencies, and
  unsafe listener errors with focused tests.

## 3. Implement supervised lifecycle

- Add a thin executable repository script and the Python command module.
- Implement lock acquisition, validated PID metadata, foreground supervision,
  signal forwarding, bounded shutdown, restart, status, and component logs.
- Start separate worker and Beat children under one supervisor and reject
  duplicate ownership.
- Preserve child exit codes and produce concise redacted failures.

## 4. Integrate dependencies, migrations, and readiness

- Select only the Compose services needed by the profile when local services
  are requested.
- Wait for PostgreSQL and, when applicable, Redis and MinIO health with bounded
  timeouts.
- Run Alembic upgrade/check before application children.
- Reuse or align with existing MCP worker readiness checks for `pong` and both
  queues.
- Verify a failed step cleans up only processes/containers owned by that start
  attempt and preserves volumes/configuration.

## 5. Simplify operator documentation

- Make the one-command path primary in both READMEs.
- Explain the three profiles and the minimal values each asks for.
- Keep manual startup commands as advanced/compatibility instructions.
- Reframe `.env.example` as the exhaustive override catalog and update the
  environment/deployment guides with ownership, logs, stop, and rollback.

## 6. Validate and review

- Run new lifecycle/configuration tests.
- Run existing configuration, deployment health, MCP readiness/server, worker,
  ingestion notification, and item-management tests affected by the change.
- Run `git diff --check` and inspect tracked files for generated secrets,
  absolute machine paths, or runtime state.
- Perform a local `read` smoke and, where dependencies are available, a `full`
  start/status/stop smoke proving one worker and one Beat.
- Dispatch the Trellis check role, address findings, update reusable specs only
  if a new stable convention was established, then commit and finish the task.

## Rollback points

- Configuration primitives can be reverted without changing existing manual
  deployment.
- The new command is additive until documentation makes it primary; reverting
  it leaves all direct commands valid.
- Compose changes must remain backward compatible or be reverted together with
  the new command and docs.

## Implementation result

- Added `scripts/notebook-agent` and the profile-aware lifecycle implementation
  in `app/deployment.py`.
- Added focused lifecycle, configuration, migration-safety, ownership, signal,
  timeout, and redaction coverage in `tests/test_deployment_cli.py`.
- Made the minimal `.env.runtime` flow primary in both READMEs and documented
  profiles, precedence, ownership, lifecycle commands, and compatibility.
- Recorded the stable lifecycle contract in
  `.trellis/spec/backend/deployment-lifecycle.md`.
- Validation: 35 focused deployment CLI tests and 102 deployment/MCP/worker
  regression tests passed; shell syntax, executable mode, diff whitespace, and
  Trellis context validation passed.
- The complete repository suite was also sampled during implementation: its
  remaining failures require unavailable PostgreSQL/model credentials or
  reproduce a pre-existing SQLite fixture/schema mismatch outside this change.
