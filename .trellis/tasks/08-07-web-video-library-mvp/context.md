# Live validation ownership

- Owner: `/root` (primary integration agent). No subagent may start, poll, retry, or stop these processes.
- Integration repository: `C:\Users\raede\.codex\worktrees\web-mvp-final`.
- Full Python verification: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`; owner-only log `.runtime/web-mvp-pytest-stable.log`; the process uses a port-1 PostgreSQL URL with `connect_timeout=1` so unavailable database tests skip explicitly instead of hanging. No shared port; stop on first repeatable product failure and fix before rerun.
- Frontend verification: bundled `pnpm` in `web/`; commands `test`, `typecheck`, `lint`, `build`, and `check:api`; output directory `web/dist` has one owner.
- Migration verification: offline Alembic SQL plus PostgreSQL-marked tests. Docker/PostgreSQL executables and port 5432 are absent on this host, so real upgrade/downgrade/upgrade is an explicit environment gap rather than a second owner.
- Browser smoke: one temporary loopback fixture on reserved port `8017` for the private app and one isolated Showcase worktree server on port `5173`; screenshots and logs remain ignored. Success requires `/login`, `/library`, `/videos/:id`, the public Showcase `/`, 390x844 no horizontal overflow, desktop max-width, source-backed preset interaction, SPA refresh, API typo JSON, and shutdown after evidence capture.
- Shared existing ports checked before start: 5173, 8000, 8765, 5432, 6379, 9000, and 9001 had no listeners. Docker CLI is not installed.
- Stop conditions: verification complete; unrecoverable missing runtime; or the same failure repeats three times under the same hypothesis.
- Read-only evidence for handoff: pytest output, frontend command output,
  generated OpenAPI files, and ignored `.runtime/web-mvp-mobile-*.png`
  screenshots.

## Current environment evidence

- Rebased the feature commits onto refreshed `upstream/main` at `36dded4` and
  preserved the upstream Composer, diagnostics, channel-linking, diversified
  retrieval, missing-item dispatch no-op, and Vercel/Neon deployment contracts.
- Full final Python verification passed after that rebase: `260 passed, 56 skipped`; all
  skips are PostgreSQL-gated under an explicit port-1 URL. Windows diagnostics
  tests now preserve POSIX `0750`/`0640` enforcement while relying on inherited
  NTFS ACLs where POSIX mode bits do not exist.
- Node `v22.23.0`, pnpm `11.16.0`; frozen install, OpenAPI check, ESLint,
  39 Vitest cases across 12 test files, TypeScript typecheck, production build, and production
  dependency audit passed after the
  rebase. Generated OpenAPI artifacts are fixed to LF so Windows checkout does
  not create false byte-level drift.
- Alembic upgrade and downgrade offline PostgreSQL SQL generation both exited
  zero. Port 5432 and Docker CLI remain unavailable, so real migration
  roundtrip, advisory-lock concurrency, index plans, and PostgreSQL-specific
  assertions remain CI/test-database gates.
- Final Chromium smoke verified `/login`, `/library`, direct
  `/videos/design-better` navigation, chapters, transcript, and the two-link Add
  dialog result. The login/library/detail pages and result dialog contained no
  old internal copy, the 390x844 pages had no horizontal overflow, and the
  console remained clean. Fresh screenshots are stored under ignored
  `.runtime/`; port 8017 and all owned smoke processes were stopped after
  capture.
- The public Showcase was completed in the isolated `codex/showcase-site`
  worktree and integrated as commit `02ca354`. Chromium smoke at 1440x900 and
  390x844 verified the responsive layouts, three real-source preset scenarios,
  clickable source timestamps, no horizontal overflow, and no browser errors;
  its owned port 5173 process was stopped after capture.
- The integration-owner browser rerun found a default `/favicon.ico` 404. A
  fail-first document-shell test now requires an explicit SVG favicon; the
  rebuilt page returns it with HTTP 200 and the fresh desktop/mobile browser
  session reported zero console errors or warnings. Owned port 5174 was
  released after the rerun.
- Security review reports no open P0-P3 blocker after challenge limits, bounded
  cleanup, trusted proxy checks, request limits, safe logging, tenant/global
  ingestion quotas, and daily retry-dispatch quotas were added.
- A dedicated three-lane frontend-copy audit removed user-visible implementation
  terms (`TG`/`WX`/`YT`, raw language codes, queue/request/cookie/token wording),
  replaced placeholder marketing copy with task-oriented Chinese, and kept real
  user/source text visible. Component tests first failed against the intended
  copy contract, then the focused frontend suite passed with 36 tests.
- The post-rebase review also closed three Web write-path gaps: the shared
  `AGENT_SAVE_ENABLED` switch now makes batch/retry read-only, retry publishing
  consumes the configured total broker budget, and the login screen no longer
  claims a hard-coded ten-minute TTL. Focused backend verification passed with
  49 tests.
- Windows file logging still depends on the configured log directory's inherited
  NTFS ACL. Deployment must verify that ACL explicitly and keep retrieval-content
  logging disabled until it is private; this is a documented environment risk,
  not evidence of a cross-tenant Web data leak.
