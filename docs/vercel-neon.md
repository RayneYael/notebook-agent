# Vercel + Neon competition deployment

This is the single hosted competition environment. Later Chat and MCP work
must update these resources instead of creating separate develop/production
projects.

## Resource contract

| Resource | Value |
| --- | --- |
| Git branch | `main` |
| Vercel project | `notebook-agent` |
| Neon project | `notebook-agent` |
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

The committed deployment currently expects revision `c7e8a91b2d34`. Update
`EXPECTED_DATABASE_REVISION` in `vercel.json` in the same commit as every future
migration. Never run Alembic from a Vercel build or function import.

## Vercel setup

Connect the GitHub repository to a Vercel project named `notebook-agent` and
configure `main` as its Production branch. Set the pooled
Neon value as the secret `DATABASE_URL` in the Vercel Production environment.

The repository pins Python 3.12. Vercel installs the committed
`pyproject.toml` dependencies and must remain under the standard 500 MB
uncompressed function limit. Non-runtime directories are excluded by
`.vercelignore` and `functions.excludeFiles`.

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
{"status":"ok","environment":"competition","database":{"status":"ok","revision":"c7e8a91b2d34"}}
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

- Public URL: pending
- Vercel project ID: pending
- Neon project ID: pending
- Neon branch ID: pending
- Deployed Git commit: pending
- Alembic revision: `c7e8a91b2d34`
