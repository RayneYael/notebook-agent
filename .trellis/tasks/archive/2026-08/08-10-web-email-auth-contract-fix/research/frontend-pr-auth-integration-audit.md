# Frontend PR and Web email authentication integration audit

## Audit context

- Date: 2026-08-10 (Asia/Singapore)
- Repository: `deequoique/notebook-agent`
- Reviewed current branch: `main` at/after merge `908bcc0`
- Relevant PRs: #2, #4, #6, #9, #10

## PR lineage

- PR #2: closed without merge; initial Web library delivery, 161 files, no GitHub review, Vercel authorization check failed.
- PR #4: closed without merge; explicitly replaced #2, 172 files, no GitHub review, Vercel authorization check failed.
- PR #6: closed without merge; pointed to the same head as #4 (`3fc9be4`), had an empty body, no GitHub review, Vercel authorization check failed.
- PR #9: merged; final frontend delivery, 174 files, empty body, no GitHub review, Vercel authorization check failed.
- PR #10: merged; email auth and channel linking, 39 files, no `web/` changes, no GitHub review, Vercel authorization check failed.

At audit time, `main` had no branch protection. GitHub reported no code-quality Actions workflow; the only workflow was the dynamic Dependency Graph workflow.

## Reproduced product blocker

Production `app/api/runtime.py` advertises `public_login_channels=("email",)` when Web auth is enabled. `web/src/auth/LoginPage.tsx` only evaluates and renders Telegram/WeChat availability.

Browser reproduction at 390x844 with a valid capabilities response containing `web_login_channels=["email"]` produced:

```text
微信       暂不可用
Telegram  暂不可用
```

There was no email field or verification-code flow and no console exception. The failure is a silent total authentication blocker.

QA evidence from the investigation was stored outside the repository under `/tmp/notebook-agent-frontend-qa/`.

## Contract divergence

Production browser composition:

```text
app/mcp_server.py
  -> app/web_runtime.py
  -> app/api/runtime.py
  -> app/api/app.py
  -> app/api/email_auth_routes.py
```

Parallel PR #10 surface primarily covered by `tests/test_web_api.py` and `docs/web-conversation-api.md`:

```text
app/web_api.py
```

Observed differences:

| Contract | Production integrated API | Parallel documented/test API | Existing frontend |
| --- | --- | --- | --- |
| Session path | `/api/v1/auth/session` | `/api/v1/session` | `/api/v1/auth/session` |
| Session cookie | `__Host-kb_session` | `__Host-notebook-agent-session` | expects canonical cookie behavior |
| CSRF | `__Host-kb_csrf` + header | different Origin-only surface | copies `__Host-kb_csrf` |
| Error body | `{error}` | FastAPI `{detail}` | expects `{code,message}` |
| Session body | authenticated/expires/tenant ID | authenticated/session ID/expires/tenant ID | authenticated/login_channel/expires |

Both new email session projections expose internal numeric tenant/session data that the frontend does not need and that conflicts with the frontend spec's ID privacy boundary.

## OpenAPI divergence

`scripts/export_web_openapi.py` constructs `WebApiServices` without `email_auth` and without email-only capabilities. It therefore exports legacy Telegram/WeChat authentication rather than production email routes. The tracked TypeScript schema still types `web_login_channels` as Telegram/WeChat only.

Observed command result:

```text
pnpm check:api
web/src/api/openapi.json is stale; regenerate it
```

Regeneration alone is insufficient until the exporter constructs the production email composition.

## Test evidence

Frontend under Node 22.22.2 and pnpm 11.16.0:

- ESLint: passed.
- TypeScript + Vite production build: passed.
- Vitest single worker: 74/74 passed.
- OpenAPI stale check: failed.

Focused backend tests with developer retrieval-content logging disabled explicitly:

```text
24 passed, 1 skipped, 1 failed
```

The stable failure is `tests/test_web_auth_migration.py`, which expects Alembic head `a7b8c9d0e1f2`; the actual single head after PR #10 is `f1a2b3c4d5e6`.

## Deployment evidence

The current `vercel.json` exposes only health routes and returns 404 for other paths. PR #9 also states that no real domestic server was modified or deployed. Repository evidence therefore proves code delivery, not a usable public frontend deployment.

## Planning conclusions

1. Repair one canonical production browser API before writing UI against it.
2. Remove the parallel authentication/session implementation rather than documenting both.
3. Export OpenAPI from the actual email-enabled composition.
4. Implement and browser-test the email challenge/verification flow.
5. Add repository CI and then enable branch protection so this cross-PR regression cannot silently merge again.
