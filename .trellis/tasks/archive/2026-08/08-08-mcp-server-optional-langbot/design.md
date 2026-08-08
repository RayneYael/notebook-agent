# Design: LLM-backed MCP facade with pluggable LangBot

## 1. Problem statement

The competition needs a deterministic way to measure Notebook Agent
connectivity and response time. The current externally reachable chat path
requires a manually patched LangBot installation, even though LangBot is only
a channel adapter and Notebook Agent already owns the Agent, retrieval,
identity, conversation, and persistence layers.

An MCP server is useful only if the evaluated operation invokes Notebook
Agent's own LLM-backed workflow. Publishing raw search or ingestion tools would
let an evaluator-owned Agent bypass that workflow and would not demonstrate
Notebook Agent connectivity.

## 2. Design principles

1. **The evaluated conversational operation uses the real Agent path.** A
   successful `ask_notebook_agent` call always reaches `KnowledgeAgent.run()`
   and at least attempts the configured model provider. Additional full-profile
   product tools do not replace this evaluation path.
2. **Protocol adapter, not a second application.** MCP translates typed input
   into `ChannelEnvelope` and projects `AgentAnswer`; it does not implement
   retrieval, prompting, citations, history, or provider behavior.
3. **Server-owned identity.** The caller cannot select an application user,
   model, provider, request ID, account ID, or retrieval limits.
4. **Conversation state belongs in PostgreSQL.** MCP transport sessions do not
   own product conversation history.
5. **Transport does not change product semantics.** stdio and Streamable HTTP
   use the same tool definitions; the resolved grant scope, not the transport,
   determines which tools are discoverable and callable.
6. **LangBot remains a pluggable sibling adapter.** It is installed and run
   out of process, and is not imported or started by the MCP/CLI core path.

## 3. Architecture and data flow

```text
Local evaluator                         Hosted evaluator / MiXer
      | stdio grant                         | Bearer header or /mcp/c/<token>
      +-------------------+-----------------+
                          v
               access-grant resolver
                  | AppUser + scope
                          v
                  MCPServer (official SDK)
              /                               \
   ask_notebook_agent                 typed product tools
              |                         save/list/update/
      ChannelService.handle             delete/restore/retry
              |                               |
      KnowledgeAgent.run             tenant-scoped services
              \                               /
                structured safe results

Optional channel path, unchanged:
WeChat/Telegram -> LangBot -> bridge -> HTTP gateway -> ChannelService
```

### Boundary ownership

| Boundary | Owner | Responsibility |
| --- | --- | --- |
| MCP JSON-RPC/schema/transport | official `mcp==2.0.0` SDK | protocol negotiation, validation, tool discovery |
| MCP product contract | new `app.mcp_server` module | tool definition, bounded input, trusted envelope, safe output |
| identity/thread semantics | existing channel/identity/conversation modules | tenant mapping and durable bounded history |
| Agent/model/retrieval | existing `ChannelService` and `KnowledgeAgent` | full LLM-backed execution and failure semantics |
| optional chat platforms | existing `integrations/langbot_*` | personal-WeChat/Telegram transport only |

### LangBot plugin boundary

The existing process boundary is the plugin mechanism. Notebook Agent owns the
typed `ChannelEnvelope`/`AgentAnswer` application contract and the authenticated
loopback gateway. The LangBot package owns LangBot SDK imports, platform-event
translation, credentials, login state, and its own lifecycle. Neither side
reaches into the other's model, retrieval, identity, or persistence internals.

This task deliberately does not add Python entry-point discovery or an
in-process plugin registry. Such a registry would not remove the external
LangBot runtime or its plugin worker, and `ChannelAdapter` plus the existing
gateway already provide the transport-neutral seam. A future channel can
either implement `ChannelAdapter` in process or bridge the same bounded
application contract out of process without changing the Agent core.

### Access profiles

The browser experience and full MCP surface use separately issued grants. A
grant selects both the `AppUser` and the permitted product capability scope:

| Profile | Capability | Trust boundary |
| --- | --- | --- |
| browser demo | bounded conversational question only; no mutations | read-scoped grant plus isolated conversation IDs |
| MCP stdio | complete reviewed product capability set | local grant/configuration resolved to an AppUser |
| MCP HTTP | scope-selected typed product capability set | bearer grant resolved per request; header preferred, URL-path compatibility for MiXer |

The browser backend must call only the restricted facade and must not embed,
forward, or reveal a credential for the full MCP profile. Full MCP exposes
product services, not raw retrieval, database, storage, provider, tenant, or
background-purge internals.

The full MCP tool set is `ask_notebook_agent`, `submit_knowledge_urls`,
`list_saved_items`, `get_saved_item`, `update_saved_item`,
`request_delete_saved_items`, `confirm_item_deletion`,
`cancel_item_deletion`, `restore_saved_items`, and
`retry_item_ingestion`. The adapter delegates to tenant-scoped application
services; it does not expose internal retrieval tools or infrastructure IDs.

### Access-grant model

Add a durable MCP access-grant record with a stable non-secret principal ID,
`app_user_id`, token hash, scope, optional expiry, revocation state, and audit
timestamps. The raw 256-bit-or-stronger token is returned only at issue/rotate
time and is never stored. Rotation replaces the hash while retaining the grant
ID, user binding, scope, and conversation identity; revocation disables it.

`expires_at` is nullable and defaults to `NULL`. A normal MiXer grant has no
automatic or inactivity expiry because its next invocation time is unknown. It
remains valid across restarts and idle periods until an operator revokes or
rotates it, the grant is disabled, or the bound `AppUser` is disabled. Operators
may explicitly request an expiry for temporary grants without changing the
default lifetime contract.

Each grant owns or references one `ChannelIdentity` whose external identity is
the stable grant ID rather than the raw secret. Token resolution therefore
produces the existing `TenantContext` without accepting a tenant ID from an MCP
tool. Different grants can map to different users, and read/full grants can
intentionally map to the same user.

Preferred HTTP authentication is `Authorization: Bearer <token>`. MiXer's
current URL-only form uses an explicitly enabled compatibility path:

```text
https://host.example/mcp/c/<opaque-token>
```

ASGI middleware extracts and hashes the final path component, resolves the
grant, replaces the visible request path with canonical `/mcp`, and passes the
resolved principal/tenant context to the MCP application. Query-string tokens
are rejected. HTTPS protects transit, but the full URL remains bearer material
inside MiXer and server infrastructure, so proxy/application access logging
must redact or omit the request URI.

## 4. MCP tool contract

### `ask_notebook_agent`

Input:

```text
question:        required string, stripped, 1..4000 characters
conversation_id: optional ASCII opaque identifier, default "default",
                 1..128 characters, restricted to a safe documented pattern
```

The tool must reject:

- empty or oversized questions;
- questions whose normalized text starts with `/`, because deterministic slash
  commands intentionally bypass the model;
- malformed or oversized conversation identifiers;
- extra fields through the SDK/Pydantic schema.

The caller cannot supply `user_id`, `account_id`, `external_user_id`,
`message_id`, `request_id`, model name, provider URL, tool budget, or retrieval
limit.

For each call the facade creates:

```text
channel          = "mcp"
account_id       = server-owned constant/configuration
external_user_id = server-owned principal
conversation_id  = validated tool argument
message_id       = fresh UUID
request_id       = fresh UUID
text             = normalized question
```

It awaits `ChannelService.handle()` directly. It does not call
`KnowledgeServices`, retrieval functions, the database, or PydanticAI model
objects itself.

Structured result:

```text
status:          "ok" | "not_found" | "failed"
answer:          final visible Agent text
citations:       existing Citation projections, including timestamps
conversation_id: validated caller token to reuse on the next MCP call
thread_id:       public durable thread ID returned by ChannelService, if any
request_id:      server-generated diagnostic correlation ID
elapsed_ms:      non-negative server-observed duration
error_code:      existing stable public error code or null
```

`elapsed_ms` is diagnostic only. The evaluator's end-to-end wall time is the
authoritative speed measurement. The result must not include prompts, history,
planner text, tool payloads, embeddings, provider messages, exception text,
credentials, or internal database identity values.

The client continues a conversation by reusing its original
`conversation_id`; `thread_id` is an informational public Agent result and is
not silently substituted for the caller's conversation key.

Tool annotations must describe that the call is non-destructive but not
idempotent: it consumes provider capacity and persists a conversation turn.

## 5. Proving that the model was invoked

MCP protocol success is separated from Agent success:

1. `tools/list` proves only MCP protocol connectivity.
2. `ask_notebook_agent` input validation proves only the adapter boundary.
3. An in-memory MCP client calling the tool through a controlled
   `FunctionModel` must observe at least one planner model invocation. This is
   the automated proof that the tool does not bypass Notebook Agent.
4. A live smoke uses a natural-language knowledge question, never a slash
   command, and records only status, safe error code, citation count, and
   coarse duration.

The production result does not expose a self-asserted `model_invoked=true`
field; that would not be trustworthy evidence and would add no value to the
evaluator's own timing and result checks.

## 6. Identity and tenancy

The MCP server has no fixed application user. Each valid access grant resolves
to one enabled `AppUser` and one enabled MCP `ChannelIdentity`; missing,
expired, revoked, malformed, or wrong-scoped grants fail before invoking an
Agent or application service.

This is a grant-to-user and channel-identity-to-user binding, not an
identity-to-identity link. A grant may intentionally share an `AppUser` with
desired WeChat/Telegram identities, giving that token access to the same
tenant-scoped knowledge while preserving a separate MCP conversation identity.

All visitors routed through a future competition web experience use the same
read-only web-demo `AppUser`. The web proxy must generate a high-entropy opaque
`conversation_id` per browser session so `ConversationThread` records remain
isolated even though their `app_user_id` is the same. The public demo profile
must keep save, ingestion, deletion, and item-management feature flags disabled.
Conversation IDs isolate context; they do not authenticate callers.

Extract the existing explicit identity setup into a transaction-scoped helper
and reuse it when issuing an MCP grant. Do not let the MCP client pass an
arbitrary user ID.

This design lets operators issue multiple principals and preload knowledge for
known users while preserving tenant predicates in all existing retrieval code.
Interactive OAuth login, organization membership and delegated authorization
remain outside this competition MVP.

## 7. Transports and runtime

### stdio

- Default local/source-evaluation transport.
- stdout is reserved exclusively for MCP protocol bytes.
- Extend runtime logging configuration with an explicit console stream choice;
  MCP stdio selects stderr while retaining the bounded private file sink.
- No network authentication is needed because the MCP host launches the local
  subprocess under the operator's account.

### Streamable HTTP

- Same MCP server and tool contract at `/mcp`.
- Use JSON responses and stateless HTTP because product history is keyed by the
  explicit conversation ID in PostgreSQL and the tool needs no sampling,
  elicitation, progress, or other server-to-client callback.
- Bind to `127.0.0.1` by default and retain SDK transport-security/Origin
  validation.
- A public competition endpoint must use TLS. First probe the actual MiXer
  validator to learn whether it supports headers/OAuth; do not assume a scheme
  and do not put tokens in query strings.
- If the validator supports authentication headers, use the standard Bearer
  mode.
- If it accepts only a URL, enable the path-capability compatibility route. The
  opaque path component is a bearer credential by possession, not an anonymous
  endpoint; it must be revocable, rotatable, hashed at rest, and redacted from
  every controlled log. MiXer account access reduces casual exposure but does
  not remove the need to treat the stored URL as a secret.

The command surface will make the choice explicit, for example:

```text
python -m app.cli mcp-server --transport stdio
python -m app.cli mcp-server --transport streamable-http
```

Exact HTTP host/port/path values come from validated MCP-specific settings,
not the LangBot channel-gateway settings.

## 8. Configuration

Add MCP-specific settings without reusing channel bridge configuration:

```text
MCP_HOST            default 127.0.0.1
MCP_PORT            default 8000, valid TCP port
MCP_PATH            default /mcp
MCP_URL_TOKEN_MODE  default false; explicitly enable for MiXer compatibility
```

Do not require `CHANNEL_GATEWAY_SECRET` for MCP startup. Model, embedding,
database, logging, TLS, context, and Agent safety settings retain their existing
meaning.

The read-only browser-demo profile does not require Redis, MinIO, Celery, or
beat to answer questions over already-ingested knowledge. The full MCP profile
requires those components whenever save, ingestion, retry, or maintenance
capabilities are enabled, and must not advertise successful mutation readiness
when a required dependency is unavailable.

The working tree already contains unrelated changes in `app/config.py` and
`.env.example`. Implementation must patch around and preserve those changes.

## 9. Failure and cancellation behavior

| Condition | Result |
| --- | --- |
| invalid MCP schema | SDK tool validation error; application service is not called |
| slash command | stable MCP tool error; model is not claimed as evaluated |
| missing/disabled/conflicting configured user | MCP startup fails safely |
| model/provider failure | existing structured `failed` AgentAnswer and safe error code |
| no tenant evidence | existing `not_found/no_evidence` behavior |
| embedding/database failure | existing distinct safe failure; no lexical-only success |
| Agent timeout | existing timeout answer; no unbounded MCP retry |
| HTTP client cancels | propagate cancellation; do not add an adapter-level retry |

The MCP layer must not translate a structured Agent failure into a protocol
crash. Unexpected adapter defects may become safe tool errors, with exception
class only in allow-listed diagnostics.

## 10. LangBot optionality and documentation

- Keep all LangBot code under `integrations/` and retain its existing tests.
- Keep LangBot SDK packages out of the core dependency set and prevent
  LangBot-specific imports or configuration from entering `app/`.
- Change README architecture/requirements wording so the core requires Python,
  PostgreSQL/pgvector, Redis, MinIO, model, and embedding providers; LangBot is
  listed only under optional personal-WeChat/chat integration.
- Put MCP startup and smoke testing before the optional LangBot deployment
  section.
- Do not delete the bridge, patch, privacy gates, or channel tests.
- Containerizing the entire application and automating LangBot installation is
  a separate deployment task; this task adds a reproducible MCP process and
  clarifies the boundary without absorbing the larger one-command deployment
  overhaul.

## 11. Compatibility, rollout, and rollback

- Add and lock `mcp==2.0.0`; do not use the superseded SSE transport.
- Add one migration for hashed MCP access grants after the active
  knowledge-item-management migration. Reuse existing user, identity,
  conversation, and turn tables for tenant and history semantics.
- CLI and LangBot routes remain unchanged except for sharing the extracted
  explicit-identity helper.
- Rollout starts with stdio/in-memory protocol tests, then loopback Streamable
  HTTP, then a controlled live model smoke, and only then a public reverse
  proxy compatible with organizer instructions.
- Rollback removes the MCP command/module/dependency/settings and restores the
  logging function signature; the existing CLI and LangBot bridge remain
  operational throughout.

## 12. Deferred decision

Before publishing the final competition URL, obtain the organizer's required
tool name/schema, supported protocol revision, timeout, endpoint authentication,
and whether their harness calls an Agent facade or consumes MCP as tools for
its own Agent. If it mandates a different contract, update only the MCP adapter;
do not bypass or duplicate `KnowledgeAgent`.
