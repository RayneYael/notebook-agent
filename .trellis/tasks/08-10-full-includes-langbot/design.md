# Design: full is the application-runtime union

## Profile composition

The immutable profile plans become:

| Profile | Components |
| --- | --- |
| `read` | MCP |
| `langbot` | worker, Beat, gateway |
| `full` | worker, Beat, MCP, gateway |

Infrastructure selection remains unchanged: both mutation-capable profiles use
PostgreSQL, Redis, and object storage.

## Listener contract

Introduce a single listener-target function derived from the profile. `read`
has the MCP target, `langbot` has the gateway target, and `full` has both. The
same target list drives startup readiness, status checks, initial state labels,
and the non-secret runtime target fingerprint so those paths cannot drift.

For compatibility, single-listener profiles continue to display `listener`.
The full profile displays `listener.mcp` and `listener.gateway` independently.

## Configuration

Any plan containing `gateway` must require a minimum 32-character
`CHANNEL_GATEWAY_SECRET`, loopback host, and valid port. Full initialization
uses the same generate/preserve behavior already used by `langbot`.

The gateway is a Notebook Agent child. LangBot core, its bridge plugin runtime,
and platform adapters remain externally managed and are not added to the
supervisor.
