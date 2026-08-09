# Simplify deployment and provide one-command startup

## Goal

Replace the current copy-the-superset-`.env` and multi-terminal startup flow
with one operator-facing command that creates a minimal profile-specific
configuration and starts the required Notebook Agent processes safely.

## Problem statement

- The current quick start asks operators to copy a large `.env.example` even
  though most settings already have application defaults.
- A full runtime requires separate MCP or LangBot gateway, Celery worker, and
  Celery Beat commands, so process ownership and shutdown are easy to get
  wrong.
- The documentation describes several valid profiles, but the operator must
  manually translate the selected profile into environment values and process
  commands.
- Running more than one Beat instance can duplicate scheduled maintenance;
  omitting Beat disables notification and purge schedules.

## Requirements

- Add one repository-owned executable command for initialization, startup,
  shutdown, restart, status, and logs.
- Make the common path one command: when configuration is absent and stdin is
  interactive, startup may collect the few required provider values before
  continuing.
- Support explicit non-interactive options or pre-set environment values so
  CI and server provisioning never depend on prompts.
- Support at least these runtime profiles:
  - `read`: Streamable HTTP MCP backed by PostgreSQL and providers; no Redis,
    MinIO, worker, or Beat requirement.
  - `full`: Streamable HTTP MCP plus Redis, MinIO, one Celery worker consuming
    `ingest,maintenance`, and exactly one Celery Beat instance.
  - `langbot`: the full background runtime plus the private LangBot gateway;
    MCP HTTP may remain independently selectable.
- Generate a minimal ignored environment file containing only secrets and
  values that differ from application defaults. Do not copy the complete
  `.env.example` into the generated file.
- Preserve existing environment-variable precedence and allow advanced
  operators to add any documented override without changing the script.
- Never print secret values in command output, status output, logs, or error
  messages. Newly generated local infrastructure credentials must be random.
- Start only the infrastructure required by the selected profile and run the
  single Alembic head migration before application processes.
- Treat the application processes as one managed runtime for lifecycle
  commands while preserving their separate OS processes and failure signals.
- Refuse duplicate runtime ownership, stale or foreign PID reuse, a second
  Beat instance, missing required credentials, unavailable dependencies, and
  unsafe production exposure.
- Forward termination cleanly, stop all child processes started by the command,
  and leave externally managed PostgreSQL/Redis/MinIO untouched.
- Keep the current manual commands and full `.env.example` variable reference
  supported for compatibility.
- Update English and Chinese quick-start documentation plus the deployment and
  environment guides.

## Acceptance criteria

- [ ] A fresh checkout with the Python environment installed can select a
      profile and reach a healthy runtime through one operator command.
- [ ] The generated local configuration contains only required secrets and
      explicit profile choices, not the full environment-variable catalog.
- [ ] `read` does not start or require Redis, MinIO, Celery worker, or Beat.
- [ ] `full` starts exactly one worker serving both required queues and exactly
      one Beat scheduler, and MCP readiness reports the mutation dependencies.
- [ ] `langbot` additionally starts the loopback-only private gateway without
      weakening its host or shared-secret validation.
- [ ] `status` reports process/dependency health without revealing credentials;
      `logs` identifies process sources; `stop` terminates only owned processes.
- [ ] A second `start` is idempotent or fails with a clear non-secret message;
      it never creates a second Beat instance.
- [ ] Interactive and non-interactive configuration paths validate required
      values before starting infrastructure or application processes.
- [ ] Existing user-authored `.env` values and externally managed service URLs
      are preserved and take precedence over generated defaults.
- [ ] Focused automated tests cover profile planning, minimal configuration,
      secret redaction, duplicate startup, process cleanup, and command errors.
- [ ] Existing deployment/readiness tests continue to pass.

## Constraints and non-goals

- This task does not merge Celery worker and Beat into one Python process;
  process isolation and the exactly-one-Beat invariant remain visible.
- This task does not install Python, Docker, Redis, MinIO, Caddy, systemd units,
  LangBot, or provider accounts.
- This task does not modify Tencent-specific disks, Caddy routes, firewall, or
  systemd policy; those remain in `08-09-tencent-full-stack-deploy`.
- This task does not replace secret managers in production. Generated `.env`
  files are a local/single-host convenience boundary only.
- Public TLS termination and MCP grant issuance remain explicit operator steps.

## Compatibility

- `docker compose up -d`, direct `celery` commands, and direct `python -m
  app.cli ...` commands remain valid.
- `.env.example` remains the exhaustive reference; the new command writes a
  separate minimal runtime file or carefully augments an existing ignored
  `.env` without deleting user values.
