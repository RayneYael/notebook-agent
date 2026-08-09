# Deployment Lifecycle

Notebook Agent exposes a profile-aware launcher at `scripts/notebook-agent`.
It is the preferred single-host deployment entry point; the direct Python,
Celery, and Docker Compose commands remain supported for advanced operators.

## Runtime profiles

- `read` starts Streamable HTTP MCP and requires PostgreSQL. It must not require
  or start Redis, MinIO, a Celery worker, or Celery Beat.
- `full` starts MCP, one Celery worker consuming both `ingest` and
  `maintenance`, and exactly one Beat scheduler. It requires PostgreSQL, Redis,
  and object storage.
- `langbot` starts the full background runtime and the loopback-only LangBot
  gateway. It does not start the public MCP endpoint by default.

Adding a profile or component requires updating the immutable plan in
`app/deployment.py`, its readiness and shutdown behavior, focused CLI tests,
and both deployment guides.

## Configuration ownership

The launcher writes only non-default profile choices and required secrets to
the ignored `.env.runtime` file. The file must use mode `0600`. Do not generate
a copy of the exhaustive `.env.example` catalog.

Effective precedence is:

1. process environment;
2. operator-owned `.env`;
3. launcher-owned `.env.runtime`;
4. application defaults.

The launcher must never overwrite `.env`, log credential values, or expose
migration-only credentials to long-running children. Redaction must cover
explicit secret settings and credential-bearing URLs.

## Lifecycle and ownership

The launcher presents all selected components as one managed runtime while
keeping worker and Beat in separate OS processes. A reservation plus run ID
prevents concurrent supervisors and duplicate Beat instances. PID-only checks
are insufficient: lifecycle commands must validate the recorded process
identity before signaling it.

Startup order is dependencies, migration, then every application child in the
selected profile. Do not place a deep dependency probe between child launches:
`full` must launch worker, Beat, and MCP as one operation. The selected
application listener is the only post-launch readiness gate. All pre-start
checks and subprocesses must have bounded timeouts, and the outer launcher and
stop budgets must exceed the corresponding listener and cleanup budgets. A
child exit stops the owned runtime immediately. Dependency probe failures
are reported by on-demand `status` checks but are not lifecycle signals:
transient or slow external checks must never block the supervisor loop or tear
down otherwise-live owned processes. Shutdown must include process groups and
Celery descendants without signaling unrelated processes.

On-demand status checks must verify that their effective non-secret service
targets match a fingerprint captured by the running supervisor. If an
operator's one-shot environment override is no longer present or points to a
different database, broker, object store, Compose project, or listener, status
must report configuration mismatch instead of probing the wrong runtime.

External PostgreSQL, Redis, and object storage are readiness-checked but never
stopped or mutated. Compose services may be rolled back only when the current
start attempt can prove ownership. External object-store bucket checks are
read-only; bucket creation is limited to launcher-owned local Compose MinIO.

## Safety gates

- Run the single Alembic head before starting application children.
- Neon pooled runtime URLs require TLS and a direct migration URL targeting
  the same host family and database.
- Non-loopback MCP binding requires the explicit
  `NOTEBOOK_AGENT_ALLOW_NON_LOOPBACK=true` acknowledgement.
- Validate custom CA bundles before starting infrastructure or children.
- Keep health and status snapshots redacted and bounded in size.

## Quality checks

Changes to the lifecycle must run at least:

```bash
python -m pytest -q tests/test_deployment_cli.py \
  tests/test_deployment_health.py tests/test_mcp_server.py \
  tests/test_tasks.py tests/test_ingest_notifications.py
sh -n scripts/notebook-agent
git diff --check
```

Tests should use injected or monkeypatched runners and must not require real
provider credentials or mutate external services.

## Forbidden patterns

- Starting worker and Beat as one process or allowing more than one Beat.
- Killing by process name, unvalidated PID, or broad wildcard.
- Passing `MIGRATION_DATABASE_URL` to long-running processes.
- Copying all example variables into generated runtime configuration.
- Creating buckets or stopping services that the launcher does not own.
- Logging raw subprocess output without secret redaction.
