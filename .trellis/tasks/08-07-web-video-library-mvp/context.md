# Live validation ownership

- Owner: `/root` (primary integration agent). No subagent may start, poll, retry, or stop these processes.
- Repository: `C:\Users\raede\Desktop\dev\hackathon1`.
- Full Python verification: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`; owner-only log `.runtime/web-mvp-pytest-stable.log`; the process uses a port-1 PostgreSQL URL with `connect_timeout=1` so unavailable database tests skip explicitly instead of hanging. No shared port; stop on first repeatable product failure and fix before rerun.
- Frontend verification: bundled `pnpm` in `web/`; commands `test`, `typecheck`, `lint`, `build`, and `check:api`; output directory `web/dist` has one owner.
- Migration verification: offline Alembic SQL plus PostgreSQL-marked tests. Docker/PostgreSQL executables and port 5432 are absent on this host, so real upgrade/downgrade/upgrade is an explicit environment gap rather than a second owner.
- Browser smoke: one temporary HTTPS or loopback fixture on reserved port `8017`; stable log `.runtime/web-mvp-smoke.log`; screenshot output `.trellis/tasks/08-07-web-video-library-mvp/research/screenshots/`; success requires `/login`, `/library`, `/videos/:id`, 390x844 no horizontal overflow, desktop max-width, SPA refresh, API typo JSON, and shutdown after evidence capture.
- Shared existing ports checked before start: 5173, 8000, 8765, 5432, 6379, 9000, and 9001 had no listeners. Docker CLI is not installed.
- Stop conditions: verification complete; unrecoverable missing runtime; or the same failure repeats three times under the same hypothesis.
- Read-only evidence for handoff: pytest output, frontend command output, `.runtime/web-mvp-smoke.log`, generated OpenAPI files, and screenshots under the task research directory.

## Current environment evidence

- Node `v22.23.0`, pnpm `11.16.0`; frozen install, OpenAPI check, ESLint,
  32 Vitest cases, TypeScript typecheck, and production build passed on the
  stable pre-rebase snapshot.
- Alembic upgrade and downgrade offline PostgreSQL SQL generation both exited
  zero. Port 5432 and Docker CLI remain unavailable, so real migration
  roundtrip, advisory-lock concurrency, index plans, and PostgreSQL-specific
  assertions remain CI/test-database gates.
- Security review reports no open P0-P3 blocker after challenge limits, bounded
  cleanup, trusted proxy checks, request limits, safe logging, tenant/global
  ingestion quotas, and daily retry-dispatch quotas were added.
