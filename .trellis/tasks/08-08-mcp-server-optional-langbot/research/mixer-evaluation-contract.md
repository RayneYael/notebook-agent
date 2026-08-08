# MiXer competition and evaluation contract research

Research date: 2026-08-08

## First-party sources

- MiXer user guide: https://open.hirebox.cn/docs/user-guide
- MiXer automated evaluation guide: https://open.hirebox.cn/docs/evaluation
- Competition submission UI and the screenshots supplied by the user on
  2026-08-08.

## Confirmed submission rules visible in the competition UI

- The Agent usage instructions and a public HTTPS original-experience page are
  required.
- The source ZIP is always required and remains the basis for static review.
- A self-hosted public Streamable HTTP MCP URL is optional.
- A self-hosted MCP URL that passes validation receives an additional five
  points and is included in the overall score.
- The UI explicitly warns that, without a self-hosted MCP URL, dynamic scoring
  still needs a runnable Agent backend from the source submission; otherwise
  the dynamic score is zero.
- Submission enters an automated parse, static-score, and dynamic-score state
  machine. Visible failure states include parse, provisioning, static, and
  dynamic failures.

## What MiXer can generate

The user guide describes a separate code-to-MCP developer workflow:

1. Upload a source file or ZIP.
2. MiXer uses an LLM to identify language and callable functions and produces
   MCP tool definitions (`name`, `description`, and `inputSchema`).
3. MiXer generates a runnable MCP server package.
4. The package can run locally over stdio or be hosted by MiXer over
   Streamable HTTP.

The guide describes the generated server as a proxy. For a hosted HTTP path it
translates an MCP tool call into a call to the contestant's real business HTTP
API, optionally using `X-API-Key`, then projects the result back to MCP. This
removes protocol glue but does not create or operate the real Agent backend,
database, model credentials, embedding provider, or knowledge data.

## What MiXer can evaluate

The evaluation guide has two distinct target kinds:

1. **MCP tool evaluation**: MiXer discovers `tools/list`, calls a named tool
   directly with test input, and evaluates the raw tool result.
2. **Agent end-to-end evaluation**: MiXer starts its own outer Agent/ReAct loop;
   that Agent chooses among the target MCP tools and MiXer judges the final
   answer and tool trace.

Cases can be created from `tools/list` or by LLM suggestions. Judges include
exact assertions, JSON Schema validation, LLM-as-judge, and performance
thresholds such as p50/p95/max/average latency and success rate.

## Implications for Notebook Agent

- MiXer can help generate MCP glue, but it does not make Notebook Agent's
  operational dependencies disappear.
- Relying only on ZIP parsing is risky for the current repository because the
  runtime needs PostgreSQL/pgvector, model and embedding credentials, schema
  migration, and preloaded tenant knowledge. The present manual LangBot path
  makes automatic provisioning even less likely to succeed.
- A MiXer-generated hosted proxy would still require a public, authenticated
  Notebook Agent HTTP endpoint. The current LangBot gateway is intentionally
  loopback-only and HMAC-bound and must not be exposed as that API.
- A native self-hosted `ask_notebook_agent` MCP endpoint gives the team control
  over identity, model invocation, result schema, privacy, timeout, and test
  data, avoids LangBot, and targets the optional +5 validation path.
- Because MiXer supports both direct MCP-tool and outer-Agent evaluation, the
  tool description and output must be usable in either mode. The tool must
  still invoke Notebook Agent's own LLM so direct tool evaluation measures the
  actual product rather than raw retrieval.

## Remaining competition-specific unknown

The public docs do not state which MiXer target kind and exact cases the
competition's automatic dynamic-scoring pipeline chooses for submitted Agents.
The submission UI establishes the required artifacts and +5 path, but the
organizer still needs to confirm whether competition scoring calls the MCP tool
directly or wraps it in MiXer's outer ReAct Agent.

The available material also does not establish how the competition validator
attaches credentials to a contestant-supplied self-hosted MCP URL. MiXer's
generated proxy can optionally send `X-API-Key` to a separate business API,
but that is not evidence that the self-hosted MCP submission field supports a
custom header. Before choosing remote authentication, test the real validator's
initialization, `tools/list`, and `tools/call` behavior. If it cannot send a
header, a token-bearing URL path is the available compatibility mechanism; it
authenticates by possession but has higher storage/logging exposure than a
standard Authorization header.

## URL-only asset form evidence

The user supplied a 2026-08-08 screenshot of MiXer's “添加 Agent/MCP 资产”
dialog. For asset type “MCP Server” it shows required asset name and MCP URL
fields plus a description field, with no visible header, API-key, OAuth, or
advanced authentication input. The placeholder `https://example.com/mcp/...`
suggests that a path-suffixed endpoint may be accepted, but only an actual
connection probe can prove whether MiXer preserves a dynamic path across MCP
initialization and subsequent requests.

If a URL path must carry an opaque bearer capability, it is not anonymous: the
secret maps to an MCP grant and application user. It is nevertheless more
leak-prone than an Authorization header because MiXer and HTTP infrastructure
store or observe the full URL. The compatibility design therefore requires
HTTPS, at least 256 random bits, hash-only storage, revocation/rotation,
URI-log redaction, no query-string token, and optional operator-selected expiry.
Normal MiXer grants default to no expiry because the future invocation time is
unknown; operators rotate or revoke them manually when access should end.
