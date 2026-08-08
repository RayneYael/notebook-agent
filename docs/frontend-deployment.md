# Frontend package and split deployment

## What `web/` is

`web/` is the Notebook Agent browser application. It is already an independent,
private package with its own dependency lock, tests, lint, typecheck, OpenAPI
snapshot, and Vite build. Its deployable artifact is `web/dist`.

It is not a reusable component library. The package owns application routes,
authentication, server-state queries, CSRF handling, and product pages, and
there is currently no second application that would consume a shared UI API.
Keep it in this repository so changes to `/api/v1` and the generated frontend
contract can be reviewed atomically.

## Supported deployment shapes

### Bundled mode

Bundled mode is backward-compatible and remains the default:

```text
Browser -> https://kb.example.com -> Python web-server
                                   |-- /api/v1/*
                                   `-- web/dist
```

```dotenv
WEB_ORIGIN=https://kb.example.com
WEB_SERVE_STATIC=true
WEB_STATIC_DIR=web/dist
```

Build the frontend before starting `web-server`:

```bash
corepack pnpm --dir web install --frozen-lockfile
corepack pnpm --dir web check:api
corepack pnpm --dir web test
corepack pnpm --dir web typecheck
corepack pnpm --dir web lint
corepack pnpm --dir web build
.venv/bin/python -m app.cli web-server
```

### Split services behind one public origin

The static frontend and Python API may run on different services:

```text
Browser -> https://kb.example.com
           |-- /*         -> static service containing web/dist
           `-- /api/v1/*  -> Python web-server (API-only)
```

Backend configuration:

```dotenv
WEB_ORIGIN=https://kb.example.com
WEB_SERVE_STATIC=false
WEB_STATIC_DIR=web/dist
```

`WEB_STATIC_DIR` stays configured so switching back to bundled mode is
deterministic, but API-only startup does not access the directory.

The public reverse proxy must:

- forward `/api/v1/*`, including methods, query strings, request bodies,
  `Origin`, `Sec-Fetch-Site`, cookies, CSRF headers, and `Set-Cookie` responses;
- serve `index.html` for frontend routes such as `/login`, `/library`, and
  `/videos/<public-id>`;
- return the backend JSON response for unknown `/api/*` paths instead of the
  SPA shell;
- disable CDN caching for `/api/v1/*` and HTML, while allowing immutable caching
  for fingerprinted `/assets/*` files;
- keep the channel gateway private and never expose its loopback port.

Do not put the frontend at one browser origin and call a second public API
origin directly. The current security model intentionally requires exact
`Origin`, `Sec-Fetch-Site: same-origin`, host-only `__Host-kb_session` and
`__Host-kb_csrf` cookies, and `X-CSRF-Token`. Adding wildcard CORS, domain
cookies, browser storage tokens, or a permissive fallback would weaken that
model and is not supported.

## Vercel frontend project

Vercel supports selecting `web/` as the Root Directory of a project in a
monorepo. Configure that project as a Vite application with:

- install command: `corepack pnpm install --frozen-lockfile`;
- build command: `corepack pnpm build`;
- output directory: `dist`;
- a SPA fallback to `/index.html` after the API rule;
- an external rewrite from `/api/v1/:path*` to the concrete backend HTTPS
  origin, preserving the `/api/v1/` prefix;
- no caching for the proxied authenticated API.

Do not commit a placeholder external destination. Add the rewrite only after
the team has selected the actual backend origin, then validate it in a preview
deployment before production. Vercel documents both the
[monorepo Root Directory workflow](https://vercel.com/docs/monorepos),
[Vite SPA fallback](https://vercel.com/docs/frameworks/frontend/vite), and
[external-origin rewrites](https://vercel.com/docs/routing/rewrites).

The repository-root Vercel project described in `docs/vercel-neon.md` is a
separate competition health deployment. Pointing a new frontend project at
`web/` must not replace or broaden the root project's strict health-only route
allowlist.

## Verification

Before routing traffic, verify the same public origin:

```text
GET  /                      -> SPA index
GET  /login                 -> SPA index
GET  /library               -> SPA index
GET  /videos/<public-id>    -> SPA index
GET  /api/v1/health         -> 200 JSON
GET  /api/v1/capabilities   -> 200 JSON
GET  /api/v1/does-not-exist -> JSON 404, never SPA HTML
```

Then complete a real login challenge, confirm both `__Host-` cookies are scoped
to the public origin, load the library, and exercise one CSRF-protected mutation.
Browser developer tools must show requests to relative `/api/v1/*` URLs and no
cross-origin preflight.

## Rollback

- Frontend rollback: redeploy the previous known-good `web/dist` artifact.
- API rollback: redeploy the previous backend while keeping the same public
  origin and route split.
- Routing rollback: switch `WEB_SERVE_STATIC=true`, restore the built
  `WEB_STATIC_DIR`, point all public paths back to `web-server`, and re-run the
  verification list above.

Never change cookie or CORS rules as an emergency routing workaround.
