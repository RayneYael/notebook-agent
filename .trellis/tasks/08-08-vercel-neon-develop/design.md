# Design: Vercel + Neon develop environment

## Deployment topology

```text
GitHub branch: codex/vercel-neon-deploy
                  |
                  | Git integration / automatic deploy
                  v
Vercel project: notebook-agent
  - public HTTPS health endpoint
  - Python serverless function
  - DATABASE_URL (pooled Neon URL, secret)
  - DEPLOYMENT_ENV=competition
                  |
                  | TLS + PgBouncer transaction pooling
                  v
Neon project/database: notebook-agent
  - PostgreSQL
  - vector + pg_trgm
  - committed Alembic schema

Operator migration path
  - direct Neon URL (never used by the Vercel function)
  - `alembic upgrade head`
```

## Git and environment isolation

The existing working tree is dirty with changes owned by another task. The
deployment branch is created from the current committed HEAD, and only files
listed by this task are staged. Before every commit and push, compare the staged
diff and branch diff against the base commit. The deployment must be sourced
from a Git commit, not from a CLI upload of the dirty local directory.

Use one Vercel project named `notebook-agent`. Configure the deployment branch
as that project's stable Production target. This is the final competition
environment; later Chat/MCP tasks update the same project instead of creating a
second develop or production deployment.

Use one Neon project/database named `notebook-agent`. No data is
copied from Tencent Cloud or local Docker. The environment begins empty except
for migrations and any explicit smoke-test principal created later by another
task.

## Runtime entrypoint

Add a minimal Vercel Python HTTP entrypoint using the supported
`BaseHTTPRequestHandler` contract. It exposes a health response and performs a
bounded `SELECT 1` plus an Alembic revision lookup. The handler opens a short
transaction against the pooled Neon endpoint and closes it before returning.

Response contract:

```json
{
  "status": "ok",
  "environment": "competition",
  "database": {
    "status": "ok",
    "revision": "<committed revision>"
  }
}
```

Failure contract:

```json
{
  "status": "unavailable",
  "environment": "competition",
  "database": {
    "status": "unavailable"
  }
}
```

Failures return 503. Logs may record a stable error category but never the
connection URL, exception `repr`, SQL parameters, or provider secrets. The
connection and query each have bounded timeouts so a sleeping/unreachable Neon
compute cannot hold the function indefinitely.

The entrypoint is deliberately not the Agent API. It is a deployment probe that
can remain useful after Chat/MCP endpoints are added in their own task.

## Database connections and migrations

Neon provides two connection forms:

- `DATABASE_URL`: pooled hostname containing `-pooler`, used only by Vercel
  runtime requests. This is appropriate for serverless connection churn.
- Direct connection URL: used locally or in a controlled migration job for
  Alembic. It is not added to the runtime function environment.

Both require TLS (`sslmode=require`). Runtime code must tolerate Neon scale to
zero. The health endpoint uses a fresh, short-lived connection; the existing
Agent SQLAlchemy engine already uses `pool_pre_ping` and will be evaluated when
the Agent endpoint is deployed in a later task.

Migrations never run as a Vercel build or import side effect. Vercel may build
the same commit multiple times, and build-time schema writes create ordering and
rollback hazards. For this initial environment an operator runs
`alembic upgrade head` once with the direct connection and verifies
`alembic current` afterward.

## Dependency and bundle strategy

Vercel's Python runtime discovers dependencies from the existing
`pyproject.toml`. The first deploy intentionally tests the repository's real
runtime dependency set rather than a fake static-only build. Configure
`excludeFiles` for non-runtime directories such as tests, Trellis artifacts,
local runtime data, and optional integrations. The standard uncompressed Python
function limit is 500 MB; a build above that limit fails this task rather than
silently enabling a paid/beta large-function feature.

Pin the Vercel Python version to a runtime supported by both Vercel and the
project's `>=3.11` requirement. Python 3.12 is the current Vercel default and is
the initial target.

## Secrets and external state

The repository contains names and examples only. Actual Neon URLs are written
only to Neon/Vercel secret stores and a local ignored environment file when a
local migration command requires one. The final report records resource names
and public URLs, never tokens or connection strings.

Creating the Neon project, Vercel project, Git integration, remote branch, and
first deployment changes external state. They are within the explicitly
requested deployment scope after the Trellis implementation gate is approved.
Any paid upgrade, custom domain, or production resource requires separate user
approval.

## Rollout and rollback

1. Validate handler tests locally without cloud credentials.
2. Create the isolated Neon database and apply migrations through the direct
   endpoint.
3. Push the deployment branch and connect it to the dedicated Vercel project.
4. Add the pooled URL to the develop project environment and deploy.
5. Verify HTTPS, response redaction, database revision, and Git provenance.

Application rollback redeploys the previous known-good Git commit in Vercel.
Schema rollback is not automatic and must not use `alembic downgrade` against
the shared develop database without reviewing migration-specific data-loss
guards. Teardown first removes the Vercel project, then the Neon project, only
on explicit user request.

## Key tradeoffs

- One Vercel project and one Neon database avoid configuration drift and extra
  cost; experimental changes must therefore use Git preview deployments or be
  validated locally before promotion to the competition branch.
- An explicit migration step is less automatic than build-time migration but
  is deterministic and avoids concurrent schema mutations.
- The initial health endpoint proves infrastructure only. It does not claim the
  full Agent is Vercel-ready; Chat/MCP and model latency remain separate gates.
