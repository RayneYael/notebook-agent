# Web email authentication integration repair: implementation plan

## Preconditions

- Work on `codex/web-email-auth-contract-fix` from the latest `main`.
- Preserve unrelated user changes and do not start implementation until the user approves all planning artifacts and the Trellis task is activated.
- Reproduce the baseline failures before editing:
  - email-only capabilities leave `/login` with no usable method;
  - `pnpm check:api` reports stale OpenAPI;
  - the focused migration-head test expects the previous head.

## Ordered implementation checklist

### 1. Pin failing integration tests first

- [x] Add a production-composition test for `build_web_app` that asserts email-only capability and the canonical auth/session routes.
- [x] Add ASGI tests for canonical challenge, verify, session, CSRF logout, and safe error bodies.
- [x] Add a frontend regression test where capabilities contain only `email`; assert an enabled email flow and no disabled-only dead end.
- [x] Update the Alembic head regression expectation to cover `f1a2b3c4d5e6` and its parent.
- [x] Confirm these new/updated tests fail for the expected pre-fix reasons.

Rollback point: test-only changes can be dropped without changing runtime behavior.

### 2. Canonicalize backend auth DTOs and routes

- [x] Define strict canonical email request, accepted, session, and safe error schemas under `app/api/`.
- [x] Change the production email router to return `{code, message}` errors and the ID-free session projection with `login_channel="email"`.
- [x] Preserve the existing `__Host-kb_session` and `__Host-kb_csrf` cookies, exact Origin check, double-submit CSRF logout, fixed session expiry, and non-enumerating challenge semantics.
- [x] Declare OpenAPI response models for success and bounded failure cases.
- [x] Verify authenticated library dependencies still derive tenant exclusively from the resolved server session.

Rollback point: revert router/DTO changes together; do not leave mixed response shapes.

### 3. Remove the second authentication implementation

- [x] Inventory every in-repository consumer of `app/web_api.py` and its documented conversation/link endpoints.
- [x] Move supported non-auth routers behind the canonical app/session dependency, or remove unreachable surfaces when no supported caller owns them.
- [x] Replace `app/web_api.py` with a narrow compatibility delegate if an import spelling must remain; otherwise delete it.
- [x] Migrate its tests to the production composition.
- [x] Assert one cookie name, one session path, one Origin/CSRF implementation, and one error envelope across the public browser API.

Review gate: pause for focused diff review because this step changes module ownership and compatibility boundaries.

### 4. Make OpenAPI represent production

- [x] Update `scripts/export_web_openapi.py` to construct an email-enabled canonical app with inert placeholders and no external side effects.
- [x] Regenerate `web/src/api/openapi.json` through the script.
- [x] Regenerate `web/src/api/schema.d.ts` through `openapi-typescript`.
- [x] Update only semantic aliases in `web/src/api/contracts.ts`; do not hand-edit generated files or duplicate DTOs.
- [x] Run `pnpm check:api` and inspect the generated document for email routes, `login_channel="email"`, safe errors, and absence of internal IDs.

Rollback point: generated files and exporter change revert as one unit.

### 5. Implement the email-code login UI

- [x] Add generated-type API client functions for challenge request and verification.
- [x] Refactor `LoginPage` into capability, email-entry, and code-entry states.
- [x] Preserve accessible labels, pending and alert semantics, recovery/change-email behavior, and duplicate-submit prevention.
- [x] On verification success, pass the canonical session to `onAuthenticated`, rotate the QueryClient, and replace-navigate to `/library`.
- [x] Remove production reliance on channel challenge polling/exchange and delete unused legacy UI code when no supported consumer remains.
- [x] Keep all authentication state in component memory/cookies and assert Web Storage remains empty.
- [x] Add focused CSS within the existing stylesheet and verify 390x844 without redesigning unrelated pages.

Rollback point: frontend API/client/login/CSS changes revert together while the backend remains backward-compatible until final integration.

### 6. Align docs, migration assertion, and CI

- [x] Update `docs/web-conversation-api.md`, deployment documentation, and examples to the canonical paths, cookie names, CSRF behavior, DTOs, and error envelope.
- [x] Confirm `vercel.json` expects the actual Alembic head and no duplicate copied constant remains in tests.
- [x] Add a GitHub Actions workflow with pinned Python, Node 22.22.2, and pnpm 11.16.0.
- [x] Run deterministic focused backend tests plus all required frontend gates without real credentials.
- [x] Document the post-merge maintainer step to enable branch protection and remove/repair the unrelated failing Vercel authorization check.

### 7. Integrated verification and review

- [x] Run focused backend Web/Auth/MCP-isolation tests with explicit test settings.
- [x] Run the full Python suite and classify any unrelated environment/infrastructure skips separately.
- [x] Run `alembic heads` and the migration graph tests.
- [x] From `web/`, run `pnpm check:api`, `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` under the pinned runtime.
- [x] Browser-smoke email challenge, verification, authenticated library, logout, expired/401 recovery, keyboard use, mobile layout, and console/network errors.
- [x] Run `git diff --check` and verify no secrets, generated caches, build output, or browser-auth state are tracked.
- [x] Obtain an independent code/security review before merge.

## Expected validation commands

```bash
NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=false \
  .venv/bin/pytest -q \
  tests/test_web_api.py \
  tests/test_web_api_public.py \
  tests/test_web_api_auth.py \
  tests/test_web_auth.py \
  tests/test_web_auth_migration.py \
  tests/test_multiuser_integration.py \
  tests/test_mcp_server.py

.venv/bin/pytest -q
.venv/bin/alembic heads

cd web
pnpm check:api
pnpm lint
pnpm typecheck
pnpm test
pnpm build

git diff --check
```

## Completion gate

Do not call the task complete or merge the implementation PR until:

- the production composition and frontend complete one email login/logout flow;
- OpenAPI is generated from that production composition;
- no parallel auth/session implementation remains;
- all acceptance criteria in `prd.md` are checked with evidence;
- required CI is green and an independent review has no open P0/P1 findings.

## Completion evidence

- Independent implementation review completed after three remediation passes;
  final verdict: no open P0/P1 findings.
- Focused credential-free backend workflow: `77 passed, 18 skipped`.
- Full Python suite with loopback HTTP and a test-only model key:
  `542 passed, 74 skipped`.
- Alembic graph: exactly `f1a2b3c4d5e6 (head)`.
- Frontend bundled Node 24 / pnpm 11.16.0 gates: OpenAPI check, ESLint,
  strict TypeScript, and production build passed; Vitest passed `79/79`.
- `git diff --check` and changed-Python compilation passed; package and lock
  files were unchanged.
- A real 390×844 Chromium smoke completed email challenge, six-digit
  verification, authenticated library access, CSRF logout, and unauthenticated
  recovery. It confirmed no horizontal overflow, empty Web Storage, and clean
  page-error/console buffers after the View Transition abort regression was
  fixed.
