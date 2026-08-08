# Improve deployment environment configuration docs

## Goal

Make environment configuration understandable and executable for developers
who do not yet know Notebook Agent's process boundaries. A developer should be
able to choose a supported runtime profile, copy the smallest relevant config,
identify secrets, and know which processes must receive each value without
reading the entire deployment manual.

## Background

- The root `.env.example` is a valid local superset but presents variables in
  implementation order rather than by developer outcome.
- `docs/deployment.md` is 817 lines and mixes environment reference material,
  topology, rollout, LangBot operations, logging, backup, and troubleshooting.
- Environment guidance is duplicated across the English/Chinese README,
  deployment manual, root `.env.example`, and the LangBot plugin's private
  `.env.example`.
- The deployment manual still names migration `d4e5f6a7b8c9` as head even
  though MCP grants add `e5f6a7b8c9d0`.
- The Vercel/Neon task and `docs/vercel-neon.md` have unrelated uncommitted
  work and must not be modified or included.

## In Scope

1. Add `docs/environment-configuration.md` as the canonical developer-facing
   environment guide.
2. Organize the guide by supported runtime profile:
   - read-only local/stdio MCP;
   - full local MCP with ingestion and item management;
   - Streamable HTTP/MiXer deployment;
   - optional LangBot gateway and plugin runtime.
3. Give each profile a minimal copyable dotenv block, required processes, a
   startup command, and a short readiness check.
4. Add a grouped variable reference that states purpose, default, required
   profile/process, secret classification, and restart implications.
5. Rework comments and ordering in the root `.env.example` so developers can
   distinguish infrastructure values, application/provider secrets, optional
   feature flags, MCP transport settings, and optional LangBot bridge values.
6. Simplify the environment section in `docs/deployment.md` to link to the
   canonical guide, preserve operational detail, and correct the migration
   head to `e5f6a7b8c9d0`.
7. Update the English and Chinese README quick-start wording and links without
   duplicating the full variable reference.

## Out of Scope

- No change to `app/config.py`, runtime defaults, feature behavior, migration
  code, Docker Compose behavior, secret handling, or deployment topology.
- No real provider, MiXer, LangBot, Vercel, Neon, or infrastructure deployment.
- No edits to `docs/vercel-neon.md` or the active Vercel/Neon Trellis task.
- No generated secrets or real credential examples.

## Requirements

- `app/config.py`, `docker-compose.yml`, `app/ingest/tasks.py`,
  `app/mcp_server.py`, and the LangBot plugin `.env.example` remain the
  authoritative evidence for consumers and defaults.
- The root `.env.example` remains a syntactically valid, copyable local
  superset. Placeholder values must be visibly non-production and no secret
  may be introduced.
- The guide must explain the distinction between root `.env`, stdio-only
  `MCP_TOKEN`, and the installed LangBot plugin's private `.env`.
- The guide must state that read-only MCP does not require Redis, MinIO, or a
  Celery worker, while the full mutation surface is withheld until database,
  broker, object store, maintenance, and worker readiness pass.
- Bearer auth is the normal HTTP path. URL-token mode is opt-in, HTTPS-only,
  rejects query tokens, and requires URI redaction.
- Long explanations stay in the canonical guide or deployment operations
  section. README quick starts link instead of copying the same matrix.

## Acceptance Criteria

- [x] The first screen of the environment guide lets a developer select one
      of the four supported profiles and links to its minimal configuration.
- [x] Every variable in the root `.env.example` appears in a grouped reference
      or is explicitly identified as Compose-only/process-only.
- [x] Each reference row identifies its consumer, default/placeholder,
      required scenario, secret status, and whether restart is required.
- [x] Copyable snippets use safe placeholders and clearly separate required
      values from optional tuning.
- [x] Root application `.env`, process-only `MCP_TOKEN`, and LangBot plugin
      private `.env` are not conflated.
- [x] `docs/deployment.md` links the canonical guide and consistently names
      `e5f6a7b8c9d0` as the current migration head.
- [x] README quick starts point developers to the canonical guide in English
      and Chinese.
- [x] Markdown links and dotenv variable names are checked against repository
      files; existing focused config/MCP tests remain green.
- [x] No Vercel/Neon task file or `docs/vercel-neon.md` is changed or staged.

## Key Decisions

- Use one dedicated environment guide rather than expanding the already long
  deployment manual.
- Organize by developer task first and provide the exhaustive variable matrix
  second.
- Keep `.env.example` as a safe superset, while minimal profile snippets live
  in documentation and are not additional committed dotenv templates.

## Risks and Deferred Items

- Documentation can drift from runtime defaults. Validation will compare the
  documented/root-example variable set with current config consumers, but no
  new runtime validation code is added in this lightweight task.
- Live deployment screenshots and provider-specific secret-manager tutorials
  remain future operational work.
