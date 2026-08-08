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
