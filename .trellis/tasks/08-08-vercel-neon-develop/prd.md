# Deploy develop environment with Vercel and Neon

## Goal

Establish the single Git-driven competition environment for Notebook Agent on
Vercel and Neon without changing the existing Tencent Cloud/Hermes runtime or
including unrelated uncommitted MCP work.

## Requirements

- Deploy from a dedicated Git branch based on the current committed `main`
  HEAD. Existing uncommitted files in the working tree must remain unstaged and
  must not be present in the deployed commit.
- Create the competition Vercel project and connect it
  to the GitHub repository so later pushes to the selected develop branch
  deploy automatically to a stable Vercel URL.
- Create the competition Neon database with PostgreSQL extensions and the
  repository's committed Alembic migrations applied to the current committed
  migration head.
- Use a Neon pooled connection string for Vercel runtime requests and a direct
  connection only for migrations and administrative operations.
- Add the smallest repository-owned Vercel entrypoint needed to prove the
  Python runtime, deployment configuration, and Neon connection work together.
- Expose a public health endpoint that reports application and database
  readiness without exposing connection strings, credentials, provider keys,
  stack traces, or database metadata beyond the migration revision.
- Store all cloud credentials and connection strings in platform-managed
  secret/environment-variable stores. No secret may be committed or printed in
  task artifacts, application logs, test output, or the final handoff.
- Keep this initial infrastructure deployment read-only from an application-feature
  perspective: do not enable ingestion, workers, LangBot, Redis, MinIO, model
  calls, MCP tools, or knowledge-item mutation paths in this task.
- Document setup, redeployment, migration, rollback, and teardown steps so the
  environment can be reproduced or removed safely.

## Acceptance Criteria

- [ ] A dedicated competition deployment branch exists on GitHub and contains only the
      intended develop-deployment changes relative to its committed base.
- [ ] A Git-connected Vercel project automatically builds that branch and has a
      stable HTTPS URL.
- [ ] The competition Neon database exists, has `vector` and `pg_trgm`
      available, and reports the repository's committed Alembic head.
- [ ] The deployed health endpoint returns HTTP 200 with redacted JSON showing
      both application and database readiness.
- [ ] An invalid or unavailable database returns a bounded HTTP 503 response
      without leaking secrets or internal exception text.
- [ ] Vercel uses the pooled Neon URL at runtime; migrations are run through a
      direct URL outside the Vercel build.
- [ ] A subsequent Git push to the selected branch is demonstrably connected to
      a Vercel deployment, without manually uploading local files.
- [ ] Local tests for response shape, redaction, and failure behavior pass, and
      the Vercel build completes within the standard Python bundle limit.
- [ ] Existing Tencent Cloud/Hermes services and all unrelated local uncommitted
      files are unchanged.
- [ ] The handoff records the Vercel URL, Git branch, deployed commit, Neon
      project/branch identifiers, migration revision, and any remaining manual
      account/billing action without recording credentials.

## Out of Scope

- Browser Chat UI, public Chat API, MCP transport, MiXer validation, or LLM
  response-speed evaluation.
- LangBot, WeChat, Telegram, ingestion, Celery, Redis, or MinIO deployment.
- A second production/develop environment, custom domain binding, ICP changes,
  or migration of the existing local/Tencent knowledge data.
- Always-on Neon compute or paid-plan upgrades unless the free/on-demand setup
  fails an acceptance criterion and the user approves the cost separately.

## Notes

- Vercel's `Production` environment is the competition environment. There is no
  separate develop/production project in the current competition scope.
- The current working tree contains unrelated MCP task changes. Git staging and
  deployment checks must explicitly prove that they are excluded.
