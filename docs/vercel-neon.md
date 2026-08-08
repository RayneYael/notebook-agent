# Vercel + Neon competition deployment

This is the single hosted competition environment. Later Chat and MCP work
must update these resources instead of creating separate develop/production
projects.

## Resource contract

| Resource | Value |
| --- | --- |
| Git branch | `main` |
| Vercel project | `notebook-agent` |
| Vercel project ID | `prj_kYOLISpRQ42qnAWq63m3uXfUuCmi` |
| Neon project | `notebook-agent` |
| Neon organization | `deequoique` |
| Neon project ID | `raspy-river-64327139` |
| Neon branch | `main` (`br-morning-dust-auqbf4i2`) |
| Neon database | `notebook_agent` |
| Environment marker | `competition` |
| Public checks | `/`, `/health`, `/api/health` |

Actual credentials stay in Neon and Vercel secret stores. Do not add them to
this document, shell transcripts, Trellis artifacts, or GitHub variables that
are visible to untrusted workflows.

## Database setup

Create an empty Neon project with PostgreSQL in a region suitable for the
competition evaluator. Copy both connection forms from Neon's **Connect**
dialog:

- The pooled URL (`-pooler` hostname) is the Vercel `DATABASE_URL`.
- The direct URL is used only for Alembic and administrative commands.

Both URLs must use `sslmode=require`. Put the direct SQLAlchemy URL in an
ignored `.env.competition.local` file while applying migrations:

```dotenv
DATABASE_URL=postgresql+psycopg://ROLE:PASSWORD@DIRECT_HOST/DATABASE?sslmode=require
```

Load that private file into the migration process without committing it, then
run:

```bash
alembic upgrade head
alembic current
```

The committed deployment currently expects revision `f6a7b8c9d0e1`. Update
`EXPECTED_DATABASE_REVISION` in `vercel.json` in the same commit as every future
migration. Never run Alembic from a Vercel build or function import.

## Shared team development access

Use Neon organization permissions rather than sharing a database password or
the deprecated project-sharing workflow:

1. In the Neon Console, open the `deequoique` organization and its **People**
   page. Invite the teammate using the email address of their Neon account and
   assign the organization role **Collaborator**.
2. Open the `notebook-agent` project, then **Settings** → **Project
   permissions**. Grant that teammate **Editor** on this project only.
3. Verify the teammate appears with an explicit Editor grant. Revoke this grant
   or remove the organization member when access is no longer required.

After accepting the invitation, each teammate authenticates with their own
Neon account and links their checkout without pulling secrets automatically:

```bash
npx neonctl auth
npx neonctl link \
  --project-id raspy-river-64327139 \
  --branch-id br-morning-dust-auqbf4i2 \
  --no-env-pull
```

Each teammate then obtains a connection string from the project's **Connect**
dialog and stores it only in their ignored local `.env` file. For the local
application, use the pooled hostname and the SQLAlchemy `psycopg` scheme:

```dotenv
DATABASE_URL=postgresql+psycopg://ROLE:PASSWORD@POOLED_HOST/notebook_agent?sslmode=require
```

Do not send connection strings in chat, issues, pull requests, or shell
transcripts. The shared `main` database contains common development data, so
destructive tests must use a separate Neon branch or a local database. Only one
designated developer should run migrations at a time, using the direct URL,
after the migration commit is present on GitHub `main`. Everyone else should
pull `main` and confirm `alembic current` before continuing work.

## Vercel setup

Connect the GitHub repository to a Vercel project named `notebook-agent` and
configure `main` as its Production branch. Set the pooled
Neon value as the secret `DATABASE_URL` in the Vercel Production environment.

The repository pins Python 3.12. Vercel installs the committed
`pyproject.toml` dependencies and must remain under the standard 500 MB
uncompressed function limit. Non-runtime directories are excluded by
`.vercelignore` and `functions.excludeFiles`. Public routing is a strict
allowlist for `/`, `/health`, and `/api/health`; repository source paths and
local environment files must return 404 without returning file contents. The
Vercel static output is pinned to the dedicated `public/` directory so the
repository root can never become a static asset tree.

## Verification

The following endpoints are equivalent and must return HTTP 200 only after the
database is reachable and the schema revision matches:

```text
https://<project-domain>/
https://<project-domain>/health
https://<project-domain>/api/health
```

Expected body:

```json
{"status":"ok","environment":"competition","database":{"status":"ok","revision":"f6a7b8c9d0e1"}}
```

Missing credentials, a direct/non-TLS runtime URL, database downtime, or schema
drift returns a redacted HTTP 503 response. Provider exception text and DSNs
must never appear in the body or logs.

## Rollback and teardown

- Application rollback: redeploy the previous known-good Git commit in Vercel.
- Schema rollback: review the specific migration and its data-loss guards;
  never automatically run `alembic downgrade` against the competition data.
- Teardown: delete the Vercel project first and the Neon project second, only
  after explicit operator approval and any required export.

## Deployment record

Fill this section with non-secret identifiers after the live deployment:

- Public URL: `https://notebook-agent.vercel.app`
- Vercel project ID: `prj_kYOLISpRQ42qnAWq63m3uXfUuCmi`
- Verified deployment ID: `dpl_52JEsozDV251kxcioAtGdpBZJtoo`
- Neon project ID: `raspy-river-64327139`
- Neon branch ID: `br-morning-dust-auqbf4i2`
- Verified deployment commit: `3de5d7abe480e411254db64f2cd0f3b40ed3b8ae`
- Verified Alembic revision: `e5f6a7b8c9d0`
- Current branch schema head (not deployed by this PR): `f6a7b8c9d0e1`
