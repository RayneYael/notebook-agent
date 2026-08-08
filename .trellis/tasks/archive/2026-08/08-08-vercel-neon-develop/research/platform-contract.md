# Vercel and Neon deployment contract

Research date: 2026-08-08

## Official-source findings

- Vercel's Python runtime supports ASGI, WSGI, and
  `BaseHTTPRequestHandler` entrypoints. It detects supported files under the
  project root, `src/`, `app/`, or `api/`, and discovers dependencies from
  `pyproject.toml`, `requirements.txt`, or `Pipfile`.
- Vercel currently supports Python 3.12, 3.13, and 3.14, with 3.12 as the
  default. Notebook Agent declares Python `>=3.11`, so 3.12 is compatible.
- Python bundles receive no automatic tree shaking. The standard uncompressed
  bundle limit is 500 MB; `excludeFiles` should remove non-runtime content.
- Vercel has Local, Preview, and Production environments. A new project's first
  deployment is always Production-labelled. For this competition, that stable
  Production target is the only hosted environment; no second project is
  planned.
- Git-connected Vercel projects create deployments from repository commits and
  can automatically deploy branch pushes. Git provenance must be checked in
  the live deployment.
- Neon recommends pooled PgBouncer connection strings for serverless functions
  and direct strings for schema migrations and administrative operations.
- Neon pooling uses transaction mode. Runtime code must not depend on
  session-level `SET`, `LISTEN/NOTIFY`, or other persistent-session behavior.
- Neon connection strings require TLS. SQLAlchemy `pool_pre_ping` or bounded
  fresh connections mitigate stale connections after scale to zero.

## Primary sources

- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/docs/deployments/environments
- https://vercel.com/docs/deployments/git
- https://neon.com/docs/connect/connect-from-any-app
- https://neon.com/docs/connect/connection-pooling
- https://neon.com/docs/guides/sqlalchemy

## Repository-specific implications

- The initial deployment must not run Celery, Redis, MinIO, LangBot, ingestion,
  or background maintenance because Vercel Functions are request-driven and
  this task is infrastructure-only.
- The current `pyproject.toml` contains the real application dependencies. A
  successful first build is useful evidence that the standard Vercel Python
  bundle can carry the repository; failure above 500 MB is a real feasibility
  result and should trigger dependency splitting in a separate decision.
- The committed first migration already creates `vector` and `pg_trgm`, so the
  empty Neon database can be initialized by the existing Alembic chain.
- Vercel builds must not execute migrations automatically. The task uses the
  direct Neon URL in a controlled one-time migration command and the pooled URL
  only at runtime.
