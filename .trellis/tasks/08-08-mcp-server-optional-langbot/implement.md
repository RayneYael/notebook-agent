# Implementation plan: LLM-backed MCP facade

## Preconditions

- Preserve all existing uncommitted knowledge-item-management changes.
- Re-read the final PRD and design before editing.
- Confirm the active task is this task and run the relevant Trellis
  before-development context workflow.
- Treat the active `08-08-knowledge-item-management-tools` task as a dependency:
  do not duplicate or absorb its dirty implementation; wrap only its reviewed,
  stable tenant-scoped service contracts.
- Pin the official MCP Python SDK v2 release selected in research and refresh
  `uv.lock` through the normal dependency tooling.

## Phase 1: multi-tenant access grants, identity, and configuration

1. After the active item-management migration, add a migration/model for MCP
   access grants: stable principal ID, `app_user_id`, token hash, scope,
   nullable/default-null expiry, revocation and bounded audit metadata; never
   store the raw token.
2. Add issue, resolve, rotate and revoke services using at least 256 bits of
   randomness and constant-time hash comparison where applicable.
3. Extract a transaction-scoped explicit identity-binding helper and create a
   stable `channel="mcp"` identity for each grant without storing the secret as
   an external identity.
4. Add operator CLI commands to issue/read metadata/rotate/revoke grants; issue
   without expiry by default, allow an explicit optional expiry, print raw
   bearer material only on issue/rotate, and never include it in list output.
5. Add bounded MCP host/path and URL-token-mode settings to `app/config.py` and
   `.env.example`, preserving unrelated dirty changes.
6. Cover missing/disabled users, duplicate hashes, concurrent issuance,
   indefinite idle/restart validity, optional explicit expiry, revocation,
   rotation, scope checks, multiple grants per user and cross-user isolation.

Rollback point: identity tests and existing CLI/multi-user tests are green
before adding the MCP SDK boundary.

## Phase 2: MCP adapter and typed contract

1. Add `mcp==2.0.0` to runtime dependencies and update the lock file.
2. Add a focused `app/mcp_server.py` module with:
   - Pydantic input/result projections;
   - `create_mcp_server(...)` dependency-injection factory;
   - the primary `ask_notebook_agent` tool and the reviewed high-level full
     product tool surface;
   - server-owned envelope identity/request/message fields;
   - slash-command rejection;
   - structured `AgentAnswer` and Citation projection;
   - monotonic safe elapsed-time measurement.
3. Keep service construction lazy/lifespan-owned so importing the module for
   schema inspection and tests does not open database or provider resources.
4. Do not import LangBot, bridge modules, raw retrieval functions, ingestion
   functions, or management services from the MCP module.

Rollback point: an in-memory MCP client can discover the intended profile tool
surface and call it against injected fake application services.

## Phase 3: runtime commands and protocol-safe logging

1. Extend `configure_runtime_logging()` with an explicit stdout/stderr console
   selection whose idempotence key includes the selected stream.
2. Add diagnostics tests proving stdio mode emits no application diagnostics on
   stdout while retaining stderr/file fallback behavior.
3. Add `mcp-server --transport {stdio,streamable-http}` to `app.cli`.
4. Run stdio with protocol-clean stdout.
5. Run Streamable HTTP at validated MCP host/port/path using stateless JSON
   responses and SDK transport-security defaults.
6. Add Bearer-header authentication plus the explicitly enabled MiXer
   URL-path capability middleware; reject query credentials and rewrite only a
   successfully authenticated dynamic path to canonical `/mcp`.
7. Fail startup before serving for missing/conflicting MCP identity or unsafe
   configuration.

Rollback point: CLI ask, gateway, diagnostics rotation/fallback, and MCP
in-memory tests are green before live transport smoke tests.

## Phase 4: verification that MCP reaches the LLM Agent

1. Add an in-memory protocol integration test using a controlled PydanticAI
   `FunctionModel`; assert a natural-language MCP call causes at least one
   planner model invocation.
2. Assert slash commands and invalid schemas do not call the model.
3. Assert conversation reuse and isolation via `conversation_id`.
4. Assert the shared public/demo profile cannot invoke save, ingestion,
   deletion, or item-management actions.
5. Assert citations/timestamps/status/error/thread data survive projection.
6. Cover model failure, no evidence, embedding failure, retrieval failure, and
   timeout without protocol crashes or sensitive error content.
7. Add stdio subprocess and loopback Streamable HTTP smoke tests for
   `tools/list` and `tools/call` without a real provider.
8. Test every separate typed product tool against tenant-scoped fake/real
   services, including two-step delete confirmation and dependency failures.
9. Test header/path authentication parity, scope enforcement, token log
   redaction, rotation/revocation, multi-user tenant separation, and exact MiXer
   session behavior.
10. Add static/import coverage showing the MCP core path has no LangBot
   dependency.

Rollback point: all new tests pass with no live provider or network access.

## Phase 5: documentation and optional LangBot boundary

1. Update English and Chinese README quick starts so MCP/CLI are the core
   evaluation path and LangBot is optional.
2. Document the existing out-of-process gateway as the LangBot plugin boundary
   and make clear that no LangBot SDK belongs in the core dependency set.
3. Add MCP configuration, stdio launch, Streamable HTTP launch, client smoke,
   readiness distinctions, secure hosting caveats, and live latency smoke to
   `docs/deployment.md`.
4. Keep the existing LangBot deployment and privacy/readiness instructions,
   but label them as optional personal-WeChat/channel integration.
5. Document that the evaluator must use a natural-language question and that
   `tools/list` alone does not test the Agent model.
6. Record the organizer contract fields that still require confirmation before
   exposing the public endpoint.
7. Document read/full grants, token issuance/rotation/revocation, URL-path
   compatibility risk, proxy/application URI redaction, and the rule that raw
   tokens are shown only once.
8. Before submission, run the actual MiXer URL validator and record whether it
   supports credentials, plus initialization, discovery, and representative
   call results without recording secrets or content.

## Validation commands

Run focused checks first, then the full suite:

```bash
.venv/bin/python -m pytest -q tests/test_mcp_server.py
.venv/bin/python -m pytest -q tests/test_diagnostics.py
.venv/bin/python -m pytest -q tests/test_multiuser_integration.py
.venv/bin/python -m pytest -q tests/test_agent_runtime.py
.venv/bin/python -m pytest -q tests/test_langbot_bridge_plugin.py
.venv/bin/python -m pytest -q tests/test_langbot_startup_patch.py
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app tests
```

Protocol smoke checks:

```bash
# In-memory/stdio smoke is automated in tests/test_mcp_server.py.
.venv/bin/python -m app.cli mcp-server --transport streamable-http
# In another process, use the official MCP client/Inspector against
# http://127.0.0.1:8000/mcp and call ask_notebook_agent.
```

Live-provider validation is manual and safe-output only:

```text
- perform one warm-up natural-language call;
- perform three measured natural-language calls against preloaded evidence;
- record only status, stable error code, citation count, and end-to-end ms;
- verify diagnostics contain a model_attempt event and no content/secret
  sentinels;
- do not set an artificial latency acceptance threshold not published by the
  organizer.
```

## Review gates

- Tool discovery exposes only the tools allowed by the selected trust profile.
- The tool cannot select a tenant or bypass the model with slash commands.
- A controlled test proves the planner model was invoked.
- stdio stdout is protocol-clean.
- HTTP defaults to loopback, prefers Bearer headers, and accepts URL-path
  tokens only when explicitly enabled; query-string tokens are rejected.
- The server selects tenant and scope from a revocable hashed grant on every
  request; no tool or global server setting selects the application user.
- Production diagnostics preserve the existing privacy contract.
- Exactly one MCP grant migration is added after the active item-management
  migration; no LangBot dependency enters the core path.
- No in-process plugin registry is added; the existing process/gateway boundary
  remains the LangBot plugin contract.
- Existing CLI and optional LangBot channel regressions remain green.
- The unrelated dirty task files remain intact and are not included in this
  task's eventual commit unless their owner has completed them separately.
