# Review Findings and Resolution

## Independent review gate

Implementation and tests were assigned to the worker subagent. Review was
performed independently by the reviewer subagent over the Trellis artifacts,
context manifests, complete diff, official MCP SDK behavior, and test suites.

## Release blockers found and closed

1. The first implementation used the obsolete `FastMCP` import and a fallback
   registry. It was replaced with the official `mcp==2.0.0` `MCPServer`, real
   stdio/Streamable HTTP runners, and official client tests.
2. The executable HTTP path bypassed authentication middleware. Startup now
   serves the middleware-wrapped ASGI application and tests Bearer/path-token
   parity, scope discovery, query rejection, revocation, and calls.
3. The dependency declaration and lock graph diverged. `uv.lock` now contains
   the complete `mcp==2.0.0` graph and passes `uv lock --check`.
4. Scope discovery, fresh deletion confirmation, bounded wire schemas, and
   grant lifecycle behavior lacked protocol-level proof. Repository tests now
   cover official `initialize -> tools/list -> tools/call`, a real
   `ChannelService -> KnowledgeAgent -> FunctionModel` call, stdio subprocess
   stdout purity, HTTP authentication, grant lifecycle, and marker safety.
5. Mutation readiness initially treated an absent Celery worker probe as
   healthy. Production stdio and HTTP now run a bounded, fail-closed worker
   probe requiring pong plus the `ingest` and `maintenance` queues.
6. Empty management markers could consume the bounded model-history window.
   Marker rows are excluded before applying the history turn limit, and the
   regression is covered with persisted SQLite turns.

## Final reviewer result

The final reviewer pass reported no release-blocking findings. Its last
non-blocking test concern was closed by replacing the mocked fresh MCP delete
test with SQLite conversation/pending-action persistence and the real
`PendingConfirmationService`.

## Final validation

- MCP-focused test file: 18 passed.
- MCP/diagnostics/provider/item-management focused suite: 88 passed.
- Full suite outside the sandbox with the documented clean feature flag:
  251 passed, 1 skipped.
- `mcp==2.0.0` installed and exercised through official client and transport
  APIs.
- `uv lock --check`: resolved 97 packages successfully.
- Python compilation and `git diff --check`: passed.

External deployment checks remain operational rather than code blockers:
real MiXer capability-URL validation, a live provider call, and a deployment
smoke against Redis, MinIO, Celery workers, PostgreSQL, and reverse-proxy log
redaction.
