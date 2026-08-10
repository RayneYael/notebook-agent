# Fix Web email authentication integration

## Goal

Restore a usable, secure production login path for the private Web video library by making the production FastAPI composition, OpenAPI contract, generated TypeScript types, and React login experience agree on one email-code authentication protocol.

## Problem statement

- PR #9 shipped a React login page that only understands Telegram and WeChat challenges.
- PR #10 made the production Web runtime advertise email as its only login channel, but changed no file under `web/`.
- The browser therefore renders two disabled legacy methods and no email form when production returns `web_login_channels=["email"]`.
- PR #10 also introduced two incompatible Web authentication surfaces: production uses `app/api/email_auth_routes.py`, while `app/web_api.py`, its tests, and `docs/web-conversation-api.md` describe different session paths, cookie names, error envelopes, and response bodies.
- `scripts/export_web_openapi.py` still constructs the legacy channel-auth application, so the tracked frontend contract does not describe production email auth.
- The migration head assertion still expects `a7b8c9d0e1f2` after PR #10 added head `f1a2b3c4d5e6`.
- `main` currently has no code-quality GitHub Actions workflow or branch protection capable of blocking the same integration regression.

The evidence and reproduction details are recorded in `research/frontend-pr-auth-integration-audit.md`.

## Scope

### Included

- Declare the integrated `app/api/app.py` composition as the single canonical browser Web API.
- Provide one email-code browser contract for challenge request, verification, current session, logout, safe errors, cookies, and CSRF.
- Remove duplicate authentication ownership from `app/web_api.py`; retain any still-required conversation or link-token surface only by mounting/refactoring it through the canonical application and shared authentication dependency.
- Ensure browser session projections contain only browser-required fields and never expose internal tenant or database IDs.
- Generate OpenAPI from the same email-enabled composition used in production and regenerate the tracked TypeScript declarations.
- Replace the legacy-only login experience with an accessible email challenge and six-digit verification flow that responds to server capability.
- Preserve private query-cache rotation on authentication, logout, and HTTP 401.
- Correct the stale Alembic-head regression test and keep the repository at one head.
- Align authentication and conversation API documentation with the canonical production paths, cookies, CSRF rule, and error envelope.
- Add deterministic backend, frontend, contract, and production-composition tests plus a repository CI workflow that runs the required checks.

### Excluded

- Deploying to a real public host, changing DNS/TLS, or provisioning SMTP/Resend credentials.
- Choosing the team's final production email provider.
- Passwords, OAuth, magic links, account splitting, workspace/multi-user product features, or device-management UI.
- A chat interface or cross-channel-linking UI in the React video library.
- Visual redesign of Showcase, Library, Video Detail, or the established frontend design system.
- Broad cleanup of unrelated backend, Agent, ingestion, or deployment failures.
- Enabling GitHub branch protection through the external GitHub settings API; maintainers perform that operational step after the workflow lands.

## Requirements

### Canonical API and contract

- `app/api/app.py` and its routers must be the only owners of public browser authentication/session semantics.
- The production email endpoints must be:
  - `POST /api/v1/auth/challenges` with `{email}`;
  - `POST /api/v1/auth/verify` with `{email, code}`;
  - `GET /api/v1/auth/session`;
  - `DELETE /api/v1/auth/session` with exact-origin and CSRF validation.
- All public errors must use the existing safe browser envelope `{code, message}`. Provider bodies, exception text, email existence, raw codes, raw tokens, and internal IDs must never be returned or logged.
- The browser session projection must contain `authenticated`, `login_channel="email"`, and `expires_at`; it must not expose `tenant.id`, `app_user_id`, `session_id`, or another internal identifier.
- Session and CSRF cookies must retain the canonical `__Host-kb_session` and `__Host-kb_csrf` names and their existing Secure/HttpOnly/SameSite/path rules.
- Existing MCP bearer authentication and routing must remain separate and behaviorally unchanged.
- If legacy channel-auth construction remains for non-production embedders, it must be explicitly isolated and must not determine the production browser OpenAPI document.

### Frontend login behavior

- When capabilities advertise `email`, the login route must render a labeled email field and a two-step email-code flow rather than disabled Telegram/WeChat controls.
- Challenge submission must show the same accepted state whether or not the address already exists or a rate limit was hit; client copy must not create an enumeration oracle.
- Verification must accept exactly six digits, support correction and restarting with another email, expose bounded pending/error states, and prevent duplicate submissions.
- Successful verification must rotate the private QueryClient, seed the returned session, and replace-navigate to `/library`.
- Logout and any 401 must clear all tenant-private cached data before returning to `/login`.
- Raw codes are limited to the local form state required to submit verification. Email, codes, sessions, CSRF values, and private query data must not be stored in Local Storage, Session Storage, IndexedDB, query strings, or logs.
- Existing accessibility, reduced-motion, mobile-first, and 390x844 layout requirements remain in force.

### OpenAPI, compatibility, and documentation

- `scripts/export_web_openapi.py` must build the email-enabled production contract without opening a database, queue, object store, or network connection.
- Pydantic request/response models are canonical; tracked `openapi.json` and `schema.d.ts` are generated and never manually edited.
- The frontend API client must consume only generated DTO aliases and the canonical routes/error envelope.
- `app/web_api.py` must not retain a second copy of challenge, verification, session, cookie, origin, or error behavior. Compatibility exports must delegate to canonical composition.
- Documentation and tests must describe the same paths, response bodies, cookies, CSRF behavior, and production composition.

### Validation and delivery safety

- The repository must still have exactly one Alembic head, `f1a2b3c4d5e6`, unless a new migration is demonstrably required by the implementation.
- No new migration is expected for a contract/UI repair. If one becomes necessary, `vercel.json` and head-derived tests must change in the same commit.
- A GitHub Actions workflow must use Node 22.22.2 and pnpm 11.16.0 and run the frontend contract, lint, type, test, and build gates plus focused Web/Auth backend tests.
- The workflow must not require real email, Redis, object-store, model-provider, or database credentials for its deterministic checks.

## Acceptance criteria

- [x] With the production composition, `/api/v1/capabilities` advertises `web_login_channels=["email"]`, and `/login` presents a usable email-code flow.
- [x] A deterministic browser/API test completes challenge request, verification, session establishment, authenticated `/library` access, CSRF-protected logout, and return to `/login`.
- [x] Email verification returns the canonical browser session DTO with `login_channel="email"` and no tenant, user, identity, or database ID.
- [x] Invalid origin, invalid email, unavailable delivery, failed verification, invalid/expired session, and invalid CSRF use bounded `{code, message}` responses without secret/provider detail.
- [x] The email request path remains non-enumerating for unknown/existing/limited addresses.
- [x] No authentication value or private query cache is persisted in browser storage or query parameters.
- [x] `app/web_api.py` contains no parallel authentication/session implementation; compatibility imports delegate to the canonical application or the obsolete surface is removed with its tests/docs migrated.
- [x] `pnpm check:api` passes against an OpenAPI document exported from the email-enabled production composition.
- [x] TypeScript strict checking, ESLint, frontend tests, and the production Vite build pass under the pinned Node/pnpm versions.
- [x] Focused Web/Auth backend tests pass with developer `.env` values neutralized by explicit test settings.
- [x] `alembic heads` reports one head and the migration-head regression test expects the current graph rather than a stale copied value.
- [x] Existing Telegram/WeChat identity behavior and MCP bearer/session isolation retain focused regression coverage.
- [x] A repository CI workflow runs these checks on pull requests and pushes to `main`.
- [x] A 390x844 browser smoke shows no clipped controls, horizontal overflow, inaccessible form controls, or console errors during the email login flow.

## Planning decisions

- This is one implementation task rather than a parent with children because canonical API, generated contract, UI, and end-to-end verification cannot be safely merged or accepted independently.
- The implementation PR targets `main` and must not be merged while any required check is missing or red.
- Activation remains gated on user review of `prd.md`, `design.md`, and `implement.md`.
