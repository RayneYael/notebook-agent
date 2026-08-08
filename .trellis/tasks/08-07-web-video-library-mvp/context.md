# Live validation ownership

- Owner: `/root` (primary integration agent). No subagent may start, poll,
  retry, or stop the owned full-suite, build, migration, server, or browser
  processes.
- Integration repository:
  `C:\Users\raede\.codex\worktrees\web-mvp-final`.
- Full Python verification uses the project virtual environment with an
  explicit port-1 PostgreSQL URL (`connect_timeout=1`) and a dummy OpenAI key.
  Database-gated tests therefore skip explicitly instead of hanging or
  connecting to an unknown database.
- Frontend verification uses the pinned pnpm version in `web/`; the owned
  commands are OpenAPI contract check, lint, Vitest, typecheck, and production
  build.
- Migration verification uses Alembic graph inspection and offline upgrade
  SQL. Docker, PostgreSQL executables, and a dedicated database are absent on
  this host, so a real upgrade/downgrade/upgrade remains an explicit CI or test
  database gate.
- Browser smoke used temporary loopback fixtures owned by this task. All owned
  browser and server processes were stopped after evidence capture.
- Stop conditions: verification complete; an unrecoverable missing runtime; or
  the same failure three times under the same hypothesis.

## Current integration evidence

- The feature branch is based on refreshed `upstream/main` at `a5d244e`. The
  integration preserves upstream item-management tools, Composer and
  diagnostics behavior, channel identity linking, diversified retrieval,
  Vercel static-boundary rules, and Neon deployment documentation.
- Web archive and Agent recycle-bin semantics are reconciled: `archived_at` is
  a reversible Web-only archive, `deleted_at` is the recycle bin, deletion wins
  when both exist, Agent reads exclude both, and restore/re-save clears both.
- Ingestion retry remains tenant-bound, quota-bound, budget-bound, and durable.
  Queue publication failure now converges the item and dispatch atomically even
  when a concurrent delete wins the race. Internal item-management statuses are
  mapped to the stable public Web batch contract instead of causing a 500.
- Alembic has one head, `f6a7b8c9d0e1`, which is a no-op merge revision over
  the Web branch (`d3f4a5b6c7d8`) and upstream MCP branch
  (`d4e5f6a7b8c9` -> `e5f6a7b8c9d0`).
  `alembic upgrade head --sql` succeeds. Offline downgrade intentionally cannot
  cross the published item-management revision because that downgrade performs
  a live deleted-row safety check; the published revision was not rewritten.
- Final post-MCP backend verification passed in one run: `331 passed, 58
  skipped in 167.67s`. All skips are PostgreSQL-gated under the explicit
  port-1 URL. The frozen lock now includes both MCP and Web/FastAPI runtime
  dependencies, and the Windows stdio protocol test uses explicit UTF-8 plus a
  cross-platform pipe timeout.
- Final frontend verification passed: OpenAPI JSON and generated TypeScript
  contract were unchanged, ESLint passed, all 39 Vitest cases across 12 files
  passed, TypeScript typecheck passed, and the Vite production build completed
  (`307.38 kB` JavaScript, `96.65 kB` gzip).
- The new upstream environment guide now includes a first-class same-origin
  Web profile, the complete `WEB_*` variable reference, frozen frontend build
  commands, login-channel dependency, port separation from MCP, and the
  browser/API smoke sequence.
- Earlier Chromium smoke verified the private login/library/detail journey and
  the public Showcase at desktop and 390x844 widths, including direct-route
  refresh, source timestamp links, no horizontal overflow, and clean console
  output. The latest integration did not change those UI files.
- Correctness/security reviewers report no open P0-P2 blocker. Remaining
  non-blocking risks are the unavailable real PostgreSQL migration/concurrency
  run, deliberate duplication between the two retry admission surfaces, and
  Windows file-log privacy depending on the deployment directory's NTFS ACL.
- One stale PostgreSQL test process tree left by a completed agent was detected
  before the final suite and stopped by exact PID. No owned pytest, browser, or
  server process remains after validation.

## Delivery boundary

- Push only `codex/web-video-library-mvp` to the user's `origin` fork.
- Open a ready-for-review PR from
  `raederhans:codex/web-video-library-mvp` to
  `deequoique/notebook-agent:main`.
- Never push either repository's `main` branch and never merge the PR.
- Keep this task in `review` after PR creation; do not archive it while the real
  PostgreSQL migration roundtrip and manual Telegram/WeChat acceptance remain
  outstanding.
