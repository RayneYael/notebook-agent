# Integration context

## 2026-08-09 baseline and ownership

- Integration owner: `/root` in
  `C:/Users/raede/.codex/worktrees/frontend-delivery-integration` on
  `codex/frontend-delivery-integration`.
- Base: collection handoff `5b8148521fc440c514a76a24317e65293b8069b9`,
  which is 17 commits ahead and 0 behind `upstream/main@a5d244e`.
- Showcase handoff: `codex/showcase-site@b123d0f`, ready for integration; its
  source worktree retains an unrelated uncommitted `uv.lock` that must not be
  staged or changed.
- Active Web handoff: thread `019fe22c-786a-70d1-9aea-8a57cb64c42b` owns
  `web-mvp-final` until it reports committed completion. Integration owner will
  not write there.
- Root `main` is not an integration surface: it contains untracked runtime,
  screenshots, output, and an old `web/` tree. Preserve all of it.
- Live processes: this task does not currently own a server. The collection
  preview on 5175 remains owned by the earlier collection task; the active Web
  thread owns any 5173 process it reports.

## 2026-08-09 delivery decision

- Repository evidence shows `web/` is already a standalone private application
  package: package manifest, lockfile, Vite build, tests, lint, typecheck, and
  committed OpenAPI schema all live under that boundary.
- It is not a reusable UI library because it owns routes, authentication,
  queries, CSRF, and product pages and has no second package consumer.
- Current security is intentionally same-origin. Relative `/api/v1` calls,
  exact Origin validation, `Sec-Fetch-Site: same-origin`, host-only `__Host-`
  cookies, and CSRF headers make direct cross-origin frontend/backend deployment
  unsupported.
- Official Vercel documentation confirms a `web/` monorepo Root Directory can
  be a separate project, SPA fallback can target `index.html`, and external
  rewrites can proxy the API without changing the browser URL. The concrete
  backend destination is deployment-specific and is not yet known, so it is not
  hardcoded in repository configuration.

## 2026-08-09 API-only implementation

- Added `WEB_SERVE_STATIC` with strict boolean parsing and default `true`.
- `build_web_app` now follows that setting only when tests/callers do not pass
  an explicit `mount_static` override. Existing bundled behavior is unchanged.
- `WEB_SERVE_STATIC=false` skips SPA mounting and does not inspect
  `WEB_STATIC_DIR`, allowing a backend image without `web/dist`.
- Documentation now covers bundled and split-service same-origin layouts,
  Vercel project boundaries, proxy/caching rules, verification, and rollback.
- Fresh focused verification: 16 tests passed across Web runtime/auth/CLI;
  `compileall app` and `git diff --check` passed.

## 2026-08-09 source integration and audit

- The active Web task finished cleanly and handed off commits
  `36d37d4c7ccf8d9d743070c5e798e2c84a578c21` and
  `0283811d4b184f4f80f634c96bc7b2055f5356b9`. They were integrated as
  `792b782` and `47c517d`; the focused 20-test frontend slice passed after the
  behavior merge.
- The Showcase source commit was already contained by the integrated history,
  so it was not cherry-picked a second time. Its unrelated source-worktree
  `uv.lock` remained untouched.
- Static review found no product use of unsafe HTML injection, browser-stored
  authentication tokens, console leakage, or a second package consumer that
  would justify extracting a reusable npm library. Large page components remain
  cohesive page-level owners; splitting them now would add indirection without
  a second responsibility or consumer.
- One deployment-documentation gap was fixed: when static assets are served by
  a separate frontend service, that service must reproduce the browser security
  headers previously added by the Python middleware. This includes CSP,
  anti-framing, MIME-sniffing, referrer, permissions, and HSTS policy.

## 2026-08-09 verification evidence

- Backend Web suite excluding the environment-gated PostgreSQL file:
  `90 passed, 9 skipped`. The two PostgreSQL cases were not run because this
  machine has no isolated `POSTGRES_PASSWORD`; the unconfigured run reported
  exactly those two fixture errors and no product-test failure.
- Frontend: 13 Vitest files / 59 tests passed; typecheck, ESLint, frozen OpenAPI
  contract check, and production Vite build all passed. The build emitted
  52.06 kB CSS (11.19 kB gzip) and 321.30 kB JavaScript (100.69 kB gzip).
- Python compilation passed and Alembic reported the single expected head
  `f6a7b8c9d0e1`.
- A task-owned Vite server ran only on `127.0.0.1:5176`. Desktop and exact
  390x844 browser smoke covered Showcase, login, an isolated logged-in library
  fixture, add dialog, and the long-title detail page. Evidence confirmed no
  horizontal overflow, three distinct loaded Showcase covers, configured login
  choices, correct per-region counts, collection filters, approximate progress,
  search suggestions, outside-click account-menu dismissal, tokenized URL
  input, vertically resizable notes, compact long-title layout, personalized
  descriptions, and an independently scrolling chapter region with separators.
  Browser logs contained only Vite connection and React development notices.
- The isolated browser fixture existed only inside the disposable verification
  tab; it did not alter repository files or production behavior. The tab was
  finalized and the owned 5176 process tree was stopped. Existing 5173/5175
  services were not inspected or changed.

## 2026-08-09 handoff decision

- The existing upstream PR is `deequoique/notebook-agent#2`, sourced from the
  user's fork branch `codex/web-video-library-mvp`. To avoid a duplicate PR, the
  verified integration head will fast-forward that fork branch and update the
  same PR. No merge is authorized or planned.

## 2026-08-09 final upstream refresh

- A final fetch found `upstream/main` had advanced from `a5d244e` to
  `3e8c2f8` through PR 3. The only product delta was an MCP worker readiness
  timeout increase from 0.35/0.75 seconds to 1/3 seconds; it was merged without
  conflict and did not touch the Web package or API contract.
- The upstream product change left one unit-test assertion at the old
  `timeout <= 0.35` boundary. With the required placeholder test environment,
  the MCP suite reproduced exactly that one failure. Updating the assertion to
  the new one-second inspect limit produced `18 passed`.

## 2026-08-09 fork and PR handoff

- Verified `origin/codex/web-video-library-mvp@f29b982` was an ancestor of the
  integration head, then fast-forwarded that fork branch to `ef9dec6` without
  rewriting history. Neither local nor remote `main` was updated.
- Updated the existing upstream PR 2 instead of opening a duplicate. It is open,
  non-draft, and mergeable, and explicitly states that maintainers must review
  and merge it. No merge action was performed.
- The only reported check failure is the external Vercel repository-owner
  authorization link. The PR records that as an environment/ownership gate,
  not as a passing deployment claim.

## 2026-08-09 final residual frontend pass

- Integration owner remains `/root` in this worktree. It is the only owner of
  Git integration, final validation processes, fork push, and PR updates.
- Residual product UI changes are owned by two source worktrees:
  `web-mvp-final` for brand/login/Showcase presentation and
  `why-saved-collections` for library progress and transcript reading.
- The source worktrees will receive narrow recovery commits before their new
  commits are integrated here one at a time. Their old histories must not be
  pushed over the existing PR branch because both are behind the current
  integration head.
- Root `main`, its untracked `web/` build/dependency tree, screenshots, runtime
  directories, and the Showcase worktree's unrelated `uv.lock` remain outside
  this delivery.
- The untracked `design-qa.md` contains machine-local absolute evidence paths
  and is not a portable repository artifact. Its durable conclusions are
  summarized here instead: the login background uses a generated raster
  halftone asset, retains card legibility, respects reduced motion, and passed
  desktop/mobile overflow checks in the producing task.
- Review removed one false-precision behavior before integration: subtitle
  links now retain backend-provided block timestamps and source URLs instead of
  inventing per-sentence times. The approximate queue progress remains clearly
  labeled as an estimate and resets when the visible work item set changes.
- No live server is currently owned by this pass. If a final browser smoke is
  required, `/root` will use a new task-owned loopback port and will not touch
  the existing 5173/5175 listeners.
