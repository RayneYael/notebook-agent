# Add an MCP core entry point and make LangBot pluggable

## Goal

Provide a standards-based MCP entry point that lets the competition evaluator
connect to and exercise Notebook Agent without installing LangBot. Treat the
existing LangBot bridge as an independently installable and removable
personal-WeChat/Telegram channel adapter, rather than a prerequisite for
running, evaluating, or importing the Agent core.

## Background and Confirmed Facts

- The preliminary-round rules shown by the user allow dynamic evaluation by
  parsing the source ZIP or by calling a contestant-provided MCP interface.
- The repository does not currently contain an MCP server or an MCP SDK
  dependency.
- `app.bootstrap.build_channel_service()` is the existing composition root for
  the Agent, retrieval, identity, and conversation services.
- `app.channels.types.ChannelEnvelope` is the framework-neutral inbound message
  contract, and `app.channels.service.ChannelService` owns the user-facing
  conversation behavior.
- The CLI already demonstrates three stable core workflows: create a local
  user, submit a URL for asynchronous ingestion, and ask a conversational
  knowledge-base question.
- `app.channels.supervisor.ChannelAdapter` already keeps channel transports
  separate from Agent behavior.
- No module under `app/` imports the LangBot SDK. LangBot-specific imports and
  dependencies are already confined to `integrations/langbot_kb_plugin/`, and
  the integration communicates with the core through the authenticated
  loopback channel-gateway contract.
- The current `docker-compose.yml` starts only PostgreSQL, Redis, and MinIO.
  LangBot installation, patching, plugin configuration, the Celery worker, and
  the Notebook Agent gateway are currently manual deployment steps.
- LangBot remains valuable for the current personal-WeChat OpenClaw/iLink path,
  but it is not required by the Agent, retrieval, ingestion, database, or CLI
  layers.
- MCP is a protocol for exposing tools, resources, and prompts to LLM hosts; a
  generic MCP tool does not by itself prove that Notebook Agent's own model was
  invoked.
- The competition wording emphasizes Agent connectivity and response speed.
  The user therefore wants the evaluated MCP operation to execute Notebook
  Agent's full LLM-backed request path, not merely expose raw retrieval or
  ingestion utilities to an evaluator-owned Agent.
- A non-command message handled by `ChannelService` is converted to an
  `AgentRequest` and passed to `KnowledgeAgent.run()`, which performs the
  provider model call and server-owned retrieval workflow. Deterministic slash
  commands intentionally bypass that path.
- The current MCP specification defines stdio and Streamable HTTP as standard
  transports. The official Python SDK v2 supports both and can be tested with
  an in-memory client.
- MiXer can parse uploaded code with an LLM, extract MCP tool definitions, and
  generate a local or platform-hosted MCP proxy. The generated proxy still
  requires a runnable local function or real business HTTP API; it does not
  supply Notebook Agent's database, provider credentials, migrations, or
  knowledge data.
- MiXer supports two separate evaluation modes: direct MCP tool evaluation and
  an Agent end-to-end mode where MiXer runs its own outer ReAct Agent over MCP
  tools.
- The competition submission UI makes the source ZIP and original experience
  page mandatory. A self-hosted public Streamable HTTP MCP is optional, but a
  validated URL adds five points. Without it, the uploaded source must still
  yield a runnable Agent backend for dynamic scoring or the dynamic score is
  zero.
- The repository currently has no browser UI. Its HTTP gateway is a private,
  loopback-only LangBot bridge rather than a public human-facing chat API, so
  the mandatory public HTTPS experience page is not satisfied by the current
  codebase or by an MCP endpoint alone.
- A competition read-only runtime can keep the model and embedding providers
  remote and omit LangBot, Redis, MinIO, Celery worker, and ingestion features.
  It still needs the Notebook Agent process, PostgreSQL/pgvector with prepared
  demo data, TLS/reverse proxying, and a small human-facing experience page.
- The user's existing Tencent Cloud host is 4 vCPU / 4 GB with a working
  ICP-filed and Tencent-accessed domain. Hermes Agent currently consumes about
  half of memory, leaving roughly 2 GB apparent headroom; an additional 50 GB
  data disk is affordable, but it does not relieve memory pressure. The local
  deployment option is acceptable only if the read-only profile and measured
  memory/load gates in `research/demo-hosting-options.md` pass.
- The working tree contains a separate in-progress knowledge-item-management
  task. This MCP task must not depend on or absorb that unfinished scope.
- The user confirmed that the competition/web-facing MVP may represent every
  visitor as one shared, preconfigured demo `AppUser`; individual visitors do
  not need their own knowledge tenant in this phase.
- The user clarified that the browser experience is intentionally restricted,
  while the trusted MCP surface is expected to carry the complete product
  capability set rather than being limited to the browser's read-only policy.
- The user selected separate typed MCP tools rather than hiding the complete
  capability set behind natural-language `ask_notebook_agent` routing.
- MiXer's public material confirms optional `X-API-Key` forwarding for its
  generated business-API proxy, but the available competition submission
  contract only establishes a self-hosted MCP URL and does not establish that
  the validator can send a custom authorization header. Remote authentication
  therefore cannot be hard-coded before an actual MiXer connection probe.
- The user rejected a server-wide fixed MCP user. Each MCP bearer capability
  must resolve to an `AppUser`, so one server can safely serve multiple users
  and tokens with different scopes.
- The supplied MiXer asset form exposes an MCP URL field but no visible header
  or OAuth configuration. The user accepts a token-bearing URL for this
  compatibility case. Use an opaque path capability, never a query parameter,
  and treat the full URL as a secret stored by MiXer.
- The user accepted operator CLI issuance for the MVP and requires tokens to
  remain valid for an unknown future MCP call time. Token expiry is therefore
  optional and disabled by default; normal lifetime ends only through manual
  revocation/rotation or disabling the bound user/grant.

## Requirements

### R1. MCP evaluation boundary

- Add an MCP server layer that reuses application services instead of
  duplicating Agent, retrieval, ingestion, identity, or conversation logic.
- The MCP surface must retain `ask_notebook_agent` as the primary conversational
  operation. Calling it with a valid natural-language question must execute the
  existing LLM-backed `ChannelService` -> `KnowledgeAgent` path.
- The trusted full MCP profile must cover the product-level save, ingestion,
  inventory, item detail/update, recoverable delete/confirmation, restore, and
  failed-ingestion retry capabilities implemented by the Agent services.
- Expose those capabilities as separate typed product tools:
  `ask_notebook_agent`, `submit_knowledge_urls`, `list_saved_items`,
  `get_saved_item`, `update_saved_item`, `request_delete_saved_items`,
  `confirm_item_deletion`, `cancel_item_deletion`, `restore_saved_items`, and
  `retry_item_ingestion`. Direct delete confirmation consumes a server-owned,
  thread-bound pending target and never accepts replacement item IDs.
- Do not expose raw database access or low-level Agent retrieval primitives
  such as segment search, neighbor expansion, citation hydration, model
  configuration, tenant IDs, dispatch IDs, or storage keys. Those remain
  internal orchestration details even in the full MCP profile.
- Reject deterministic slash commands at the MCP boundary so a successful
  `ask_notebook_agent` call cannot silently bypass the model invocation being
  evaluated.
- MCP tool inputs and outputs must be typed, bounded, machine-readable, and
  free of secrets or private diagnostic payloads.
- The MCP boundary must preserve tenant isolation and must not accept an
  arbitrary caller-selected application user without an explicit trusted
  configuration or authentication decision.
- Resolve every MCP request through a revocable access grant. Each grant maps a
  cryptographically random bearer token to one `AppUser`, one stable MCP
  principal/channel identity, and an allow-listed scope such as `read` or
  `full`. MCP tools never accept an `app_user_id` argument.
- Multiple tokens may point to the same `AppUser` with different scopes, while
  different tokens may point to different users. The server is multi-tenant;
  it has no global application-user setting for HTTP requests.
- Sharing the demo user must not merge visitor chat history. A web-facing
  proxy must issue each browser session a high-entropy opaque conversation
  identifier; callers cannot select another tenant, and conversation IDs must
  not be treated as authentication credentials.
- The browser-demo facade uses a read-scoped token and cannot invoke mutation
  tools. MiXer may use a full-scoped token mapped to the intended evaluation or
  personal user. Whether two tokens share one user is an operator choice made
  when issuing them, not a server-wide constant.
- Prefer `Authorization: Bearer` when a client can send headers. For MiXer's
  URL-only form, support an explicitly enabled compatibility route such as
  `/mcp/c/<opaque-token>` and internally rewrite it to the canonical `/mcp`
  transport after authentication. Do not support `?token=...`.
- Generate at least 256 bits of random token material, display the raw token
  only when issued, store only a cryptographic hash, and support revocation,
  rotation, and operator-selected optional expiry. `expires_at` defaults to
  `NULL`; there is no inactivity timeout or automatic expiry for normal MiXer
  grants. Derive the MCP external principal from a stable non-secret grant ID,
  never from the raw token.
- Raw bearer values and token-bearing paths must not enter application,
  reverse-proxy, access, error, analytics, or diagnostic logs. Deployment docs
  must show a redacted/disabled request-URI log configuration and require token
  rotation after a competition or suspected disclosure.
- Agent answers must retain their structured status, public conversation
  identifier, citations, source URLs, and timestamp information where present.
- The response may include safe server-observed elapsed time and a correlation
  identifier for diagnostics, but the evaluator's end-to-end wall time remains
  the authoritative response-speed measurement.

### R2. Runtime and transport

- The MCP server must have a documented local/source-evaluation launch command.
- The design must support a competition-provided remote MCP endpoint without
  coupling the Agent core to LangBot.
- Provide both stdio for clean source/local evaluation and Streamable HTTP for
  a remotely hosted competition endpoint from the same tool implementation.
- Run an actual MiXer compatibility probe covering the exact token-bearing URL,
  initialization, `tools/list`, session behavior, and one typed tool call. If
  MiXer later exposes organizer-provided headers/OAuth, prefer the standard
  header mode without changing token-to-user semantics.
- Startup must validate required configuration and fail with safe, actionable
  errors without logging model keys, embedding keys, channel secrets, user
  content, or external identity values.
- Health/readiness documentation must distinguish MCP process availability
  from database, embedding, model, broker, object-store, worker, and maintenance
  readiness. The browser read-only profile can omit Redis, MinIO, Celery, and
  beat; the full MCP profile must fail closed or withhold dependent mutating
  tools when their required services are not enabled and ready.

### R3. Optional LangBot integration

- For this task, **pluggable** means an out-of-process channel adapter that can
  be installed, configured, started, stopped, or removed independently of the
  core. It does not mean adding a dynamic Python entry-point registry inside
  Notebook Agent.
- LangBot must not be imported, installed, patched, configured, or started for
  the default MCP/CLI core path.
- The existing bridge plugin and pinned LangBot patch remain in
  `integrations/` as an optional personal-WeChat/channel package.
- LangBot-specific event types, SDK dependencies, login state, and lifecycle
  remain outside `app/`; the core side depends only on the existing bounded
  `ChannelEnvelope`/`AgentAnswer` gateway contract.
- Documentation and deployment commands must clearly separate core startup from
  optional LangBot startup.
- Removing or disabling the LangBot integration must not change MCP or CLI
  behavior.

### R4. Delivery and competition packaging

- The source submission must include all first-party MCP code, pinned Python
  dependencies, migrations, tests, and reproducible startup documentation.
- It must exclude secrets, `.env`, `.runtime`, LangBot login state, databases,
  logs, virtual environments, caches, and other machine-local artifacts.
- Third-party LangBot source must not be treated as first-party Notebook Agent
  source. If an offline competition package is later required, it must remain
  under an explicitly identified third-party boundary with provenance and
  license metadata.

## Acceptance Criteria

- [ ] A clean environment can start and inspect the MCP server without
      installing LangBot.
- [ ] An MCP client can list the supported Notebook Agent tools and their typed
      schemas.
- [ ] `ask_notebook_agent` with a natural-language question performs a real
      provider-model attempt through `KnowledgeAgent` and returns a structured
      Agent answer with citations when evidence is available.
- [ ] `ask_notebook_agent` rejects slash commands and does not offer a raw
      retrieval path that bypasses the model.
- [ ] Reusing the same MCP conversation identifier preserves bounded
      conversation context; a different identifier creates an independent
      thread.
- [ ] Two clients using different high-entropy conversation identifiers share
      the configured demo knowledge tenant but cannot observe or influence each
      other's conversation history.
- [ ] The shared public/demo profile cannot save, ingest, delete, or otherwise
      mutate knowledge through the Agent path.
- [ ] A valid full-scoped MCP token can exercise every supported product-level
      capability: question answering, save/submission, inventory list/detail,
      `why_saved` update, confirmed recoverable deletion, restore, and failed
      ingestion retry.
- [ ] An unauthenticated browser client cannot discover or invoke the full MCP
      mutation surface and cannot reuse a server-side MCP credential.
- [ ] The exact submitted MiXer URL passes initialization, `tools/list`, and a
      representative `tools/call` using the authentication behavior the
      competition harness actually supports.
- [ ] Two valid tokens can map to different `AppUser` tenants without data or
      conversation leakage; two tokens intentionally mapped to the same user
      share tenant data while retaining separate principals and scopes.
- [ ] Revoked, expired, malformed, missing, or wrong-scoped tokens fail before
      any Agent/service call and return no tenant-existence signal.
- [ ] A grant issued without an expiry remains valid across process restarts
      and arbitrary idle periods until it is revoked, rotated, its user is
      disabled, or its grant is disabled; optional explicit expiry still fails
      closed when configured.
- [ ] No database row or normal log contains a raw token or token-bearing URL;
      rotating a token invalidates the old URL without changing its `AppUser`
      or stable MCP principal.
- [ ] Invalid input, unknown/disabled identity, provider failure, retrieval
      failure, and timeout paths return stable safe errors rather than stack
      traces or leaked payloads.
- [ ] Automated tests prove that the core MCP path neither imports nor requires
      LangBot.
- [ ] The core dependency install contains no LangBot SDK/package, and importing
      or launching the MCP/CLI core succeeds when `integrations/` is absent.
- [ ] Existing CLI and optional LangBot bridge behavior remain compatible.
- [ ] Installing and enabling the LangBot integration requires no changes to
      Agent, retrieval, identity, or conversation code under `app/`.
- [ ] Core and optional-channel deployment instructions are independently
      executable and include readiness checks.
- [ ] The test suite and a local MCP protocol smoke test pass.

## Out of Scope

- Reimplementing the personal-WeChat OpenClaw/iLink protocol.
- Replacing or forking LangBot upstream.
- Adding an in-process plugin registry, package discovery mechanism, plugin
  marketplace, or hot-reload framework; the existing process boundary is the
  plugin contract for this integration.
- Building or hosting a browser UI, mobile client, public chat API, or complete
  submission-ready demo deployment.
- Adding new knowledge-item-management behavior from the separate active task.
- Exposing raw segment search, neighbor expansion, citation hydration, direct
  database/storage operations, tenant administration, manual permanent purge,
  or model/provider configuration as public MCP tools.
- Making model or embedding providers optional for real knowledge questions.
- Automating Telegram token provisioning or personal-WeChat QR login.

## Deferred Competition Contract Detail

- The supplied screenshot does not specify a required MCP tool name/schema,
  protocol revision, remote authentication flow, timeout, or whether the
  evaluator treats MCP as an Agent facade or as a tool source for its own
  Agent. The implementation will use the standard protocol and document these
  assumptions, but the public competition endpoint configuration must be
  checked against the organizer's authoritative MCP integration instructions
  before submission.

## Deferred Follow-up

- A submission-ready browser experience and public deployment remain a
  separate task. Hosting research already captured in
  `research/demo-hosting-options.md` can seed that work without expanding this
  MCP/LangBot-boundary task.
- Authenticated multi-user MCP, where each verified web/MCP principal maps to a
  different `AppUser`, is now covered by token-to-user grants. Interactive
  OAuth account login, organization membership, delegated authorization, and
  user self-service token management remain deferred.

## Resolved Product Decisions

- MCP exposes separate typed high-level product tools.
- HTTP MCP is multi-tenant: a revocable bearer grant maps to an `AppUser` and
  scope; the server does not have a fixed user.
- MiXer's URL-only compatibility mode carries the opaque bearer in the URL path,
  not the query string. Standard authorization headers remain preferred.
- MVP token administration is operator-driven through CLI. Grants do not expire
  automatically by default; optional expiry is available only when explicitly
  requested during issuance.
- Do not add a restrictive competition-specific daily quota in this task.
  Existing per-request time, model/tool-call, output-token, request-size,
  concurrency, item/batch, and confirmation bounds remain mandatory safety
  invariants, and token revocation is the abuse kill switch.
