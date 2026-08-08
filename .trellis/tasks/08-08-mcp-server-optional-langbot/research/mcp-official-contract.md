# MCP official contract research

Research date: 2026-08-08

## Sources

- MCP transport overview:
  https://modelcontextprotocol.io/specification/latest/basic/transports
- MCP Streamable HTTP transport:
  https://modelcontextprotocol.io/specification/latest/basic/transports/streamable-http
- MCP authorization:
  https://modelcontextprotocol.io/specification/latest/basic/authorization
- Official Python SDK repository:
  https://github.com/modelcontextprotocol/python-sdk
- Official Python SDK server runner documentation:
  https://py.sdk.modelcontextprotocol.io/run/
- Official Python SDK tool documentation:
  https://py.sdk.modelcontextprotocol.io/servers/tools/
- PyPI package metadata:
  https://pypi.org/project/mcp/

## Verified facts

1. MCP standardizes how an MCP host discovers and calls tools, resources, and
   prompts. MCP does not require a tool implementation to invoke a model. A raw
   retrieval tool can therefore let the host's Agent bypass Notebook Agent's
   own LLM orchestration.
2. The current MCP specification revision is `2026-07-28`. The standard
   transports are stdio and Streamable HTTP. The older HTTP+SSE transport is
   retained only for compatibility and should not be used for a new server.
3. In stdio mode, stdout is the MCP protocol wire. Application diagnostics
   must not write ordinary logs to stdout while the server is running.
4. Streamable HTTP uses one MCP endpoint, normally `/mcp`. The official Python
   SDK can use JSON responses and stateless HTTP when server-to-client callbacks
   and MCP session state are unnecessary.
5. Streamable HTTP servers must validate `Origin` when present, should bind to
   localhost for local use, and should authenticate remote connections. Tokens
   must not be placed in query strings.
6. The official Python SDK v2 is the current stable line. PyPI reports
   `mcp==2.0.0`, released 2026-07-28, requiring Python 3.10 or later. This
   repository requires Python 3.11 or later, so the Python floor is compatible.
7. The SDK derives input schemas from Python/Pydantic type annotations,
   supports async tool functions, produces structured tool results, and
   provides an in-memory client for protocol tests without a port or subprocess.

## Consequences for this task

- Expose one `ask_notebook_agent` tool that calls the existing full Agent path;
  do not expose raw retrieval tools in the MVP.
- Test model invocation explicitly with a controlled PydanticAI model. Tool
  discovery or a transport health check is not sufficient evidence.
- Use the same MCP server definition for stdio and Streamable HTTP.
- Use stdio for local/source evaluation and stateless JSON Streamable HTTP for
  a hosted evaluator endpoint.
- Keep stdout protocol-clean in stdio mode by directing runtime diagnostics to
  stderr plus the existing bounded private file sink.
- Bind HTTP to loopback by default. Put any public endpoint behind TLS and an
  organizer-compatible authentication/reverse-proxy boundary; do not invent a
  query-token convention before the organizer publishes its connection
  contract.
