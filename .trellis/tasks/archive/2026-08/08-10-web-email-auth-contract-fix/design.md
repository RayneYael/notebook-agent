# Web email authentication integration repair: technical design

## 1. Desired architecture

The browser must have one contract owner and one runtime path:

```text
React /login
  -> generated client DTOs
  -> same-origin /api/v1/*
  -> app.api.app.create_app
       -> email auth router
       -> session dependency
       -> library routers
       -> optional conversation/link routers
  -> WebAuthService / tenant-scoped services

MCP /mcp
  -> existing bearer middleware and official MCP app
```

`app/web_runtime.py` remains the path dispatcher that keeps MCP bearer authentication outside the browser cookie boundary. `app/api/app.py` is the single FastAPI browser application. No second module may independently choose browser cookie names, authentication paths, error bodies, or session projections.

## 2. Canonical browser authentication protocol

### 2.1 DTOs

Add or consolidate strict Pydantic DTOs under `app/api/`:

```text
EmailChallengeRequest  { email: str }
AcceptedResponse       { status: "accepted" }
EmailVerifyRequest     { email: str, code: str }
SessionResponse        {
  authenticated: true,
  login_channel: "email" | "telegram" | "wechat",
  expires_at: datetime
}
ErrorResponse          { code: str, message: str }
```

Production email responses always use `login_channel="email"`. Internal `app_user_id`, tenant ID, channel-identity ID, raw session token, session database ID, and email address are not browser DTO fields.

### 2.2 Routes and security

| Method | Path | Input | Security | Success |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/auth/challenges` | `{email}` | exact Origin; JSON body | accepted |
| POST | `/api/v1/auth/verify` | `{email, code}` | exact Origin; JSON body | session DTO + session/CSRF cookies |
| GET | `/api/v1/auth/session` | none | session cookie | session DTO |
| DELETE | `/api/v1/auth/session` | none | exact Origin + session + double-submit CSRF | 204 + cookie deletion |

The canonical cookie names remain those already used by the private library:

```text
__Host-kb_session  Secure; HttpOnly; SameSite=Lax; Path=/
__Host-kb_csrf     Secure; SameSite=Lax; Path=/
```

The existing `requestJson` CSRF behavior remains the only browser implementation. The email router maps all expected domain exceptions through the same safe `{code, message}` catalog used by the rest of the Web API.

Challenge acceptance stays deliberately non-enumerating. Input-shape errors may be rejected, but account existence and rate-limit state must not be distinguishable from the public accepted response.

## 3. Eliminate parallel authentication ownership

`app/web_api.py` currently defines a second application with different routes, cookie name, error envelope, and session projection. The repair will:

1. move any still-required conversation/link-token routers behind the canonical `app/api/app.py` session dependency;
2. remove challenge/verify/session/cookie/origin implementations from `app/web_api.py`;
3. keep only a narrow compatibility factory/import shim when an in-repository caller still needs the old module spelling;
4. update its tests to exercise the canonical production composition rather than a separate FastAPI app;
5. update or replace `docs/web-conversation-api.md` so it documents the mounted canonical routes.

If code discovery proves the conversation/link surface has no supported caller and no acceptance owner, deletion is preferred over preserving unreachable API. That decision must be recorded in the implementation review without reintroducing another auth boundary.

## 4. OpenAPI as an executable production contract

`scripts/export_web_openapi.py` must instantiate `create_app` with:

- explicit placeholder domain services;
- an explicit email-auth placeholder;
- `web_login_channels=("email",)`;
- no database/session factory construction;
- no queues, object store, email network, Redis, or provider credentials.

All email routes declare request, success, and safe error response models so OpenAPI contains their real shapes. `web/src/api/openapi.json` is regenerated from that app, followed by `openapi-typescript` generation of `schema.d.ts`.

`web/src/api/contracts.ts` aliases the generated email request, accepted, verify, session, capability, and error types. It does not hand-write a parallel union.

The contract check compares a fresh deterministic render against the tracked JSON. CI runs it before TypeScript/build so drift fails early.

## 5. Frontend email state machine

`LoginPage` becomes an explicit three-state flow:

```text
loading-capabilities
  -> enter-email
       submit -> requesting
       accepted -> enter-code(email retained in component memory)
  -> enter-code
       submit -> verifying
       success -> rotate QueryClient -> /library
       safe error -> editable/retryable code state
       change email -> enter-email and clear code/error
```

Rules:

- Render email only when advertised by capability; do not show disabled legacy methods as the terminal production state.
- Use native labeled `input type="email"`, an input suitable for a six-digit numeric code, and native buttons.
- Disable only the mutation currently in flight; do not dead-end the form after a recoverable error.
- Use `aria-live`/`role="alert"` for accepted, pending, and failure feedback.
- Do not reveal whether the email exists or whether a challenge was actually sent.
- Do not persist email, code, session, or query data in Web Storage.
- Preserve `onAuthenticated`, QueryClient rotation, 401 teardown, and replace navigation semantics.
- Keep the current visual system and mobile-first layout; no Showcase or Library redesign.

The frontend API boundary adds generated-type functions for `requestEmailChallenge` and `verifyEmailChallenge`. Legacy channel challenge polling/exchange functions are removed from the production login page. Compatibility code is retained only if a supported non-production consumer is proven by tests.

## 6. Migration and configuration consistency

The repair should not require a database migration. Update the stale migration test to derive/assert the actual single head and the expected parent relationship for `f1a2b3c4d5e6`. `vercel.json` already expects that head and remains unchanged unless the Alembic graph changes.

Tests must construct `Settings` with explicit email/log/provider values rather than inherit developer `.env` values. Production settings still fail closed without a configured email provider; deterministic tests use the in-memory sender and limiter.

## 7. Test strategy

### Backend

- DTO and error-envelope tests for every email route outcome.
- Production `build_web_app` composition test asserting email capability and mounted route set.
- Session cookie/CSRF/origin lifecycle test through one ASGI client.
- Authenticated library request after verification, proving session tenant resolution.
- Regression tests that MCP Bearer routing is not interpreted as browser session auth.
- Canonical conversation/link compatibility tests if those routers remain supported.
- Single Alembic-head assertion.

### Frontend

- Capability loading and email-method rendering.
- Accepted challenge state without enumeration copy.
- Six-digit validation, duplicate-submit prevention, correction, change-email, safe failure, and success.
- Successful session activation and `/library` navigation.
- Logout/401 private-cache teardown.
- No Local/Session Storage writes.
- Contract-generated types compile without casts or duplicated DTOs.

### Browser

- 390x844 email request and verification flow using deterministic network responses.
- Keyboard focus order, labels, live/error announcements, retry behavior, no overflow, and clean console.

## 8. CI and merge gate

Add a GitHub Actions workflow with pinned runtimes:

```text
Python 3.11 + project dev dependencies
Node 22.22.2
pnpm 11.16.0
```

Required jobs run focused backend Web/Auth/MCP-isolation tests and, from `web/`, `pnpm check:api`, `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build`. No provider or infrastructure secrets are required.

After the workflow is merged, a maintainer enables branch protection requiring the workflow and at least one review. The external Vercel authorization check is not treated as a substitute for code-quality CI.

## 9. Rollback

- Before merge: revert the repair branch; production remains in the known blocked state.
- After merge but before public deployment: revert the application commit; no schema rollback is needed.
- After deployment: disable the public Web route or roll back the application artifact while keeping the existing database head. Do not downgrade production schema for this code-only repair.
- Email/Redis/provider failure continues to fail Web login closed without weakening Telegram, WeChat, or MCP authentication.

## 10. Review risks

- Accidentally exporting the legacy channel app again.
- Preserving `app/web_api.py` as a hidden second auth owner.
- Leaking internal tenant/session IDs in a convenience response.
- Adding a handwritten TypeScript DTO to bypass stale generated types.
- Weakening Origin/CSRF because email verification appears unauthenticated.
- Allowing a developer `.env` to determine deterministic test behavior.
- Treating a passing build as proof of a usable end-to-end login flow.
