# Design: profile-aware one-command runtime

## Scope boundary

The feature is a repository-level deployment convenience layer. It selects a
supported runtime profile, resolves only the configuration that profile needs,
starts optional local Compose dependencies, applies migrations, and supervises
the required application child processes. Host-specific production policy
remains outside this layer.

## Operator interface

Provide one executable entry point, provisionally:

```text
./scripts/notebook-agent init [--profile read|full|langbot]
./scripts/notebook-agent start [--profile ...] [--foreground]
./scripts/notebook-agent stop
./scripts/notebook-agent restart
./scripts/notebook-agent status
./scripts/notebook-agent logs [component]
```

`start` performs `init` automatically when the managed configuration does not
exist and stdin is interactive. In a non-interactive environment it fails with
the exact missing variable names and accepts those values from existing
environment variables or explicit file/options.

The shell entry point stays thin. Profile selection, validation, configuration
planning, PID ownership, and redacted status are implemented in a testable
Python module. Shell is used only to locate the repository interpreter and
replace itself with that module.

## Configuration model

Configuration has three layers, highest precedence first:

1. the invoking process environment;
2. an existing operator-owned root `.env`;
3. a generated ignored minimal file containing profile and secret values.

The runtime must preserve the application's existing `load_dotenv` behavior.
It must not silently rewrite an operator-owned `.env`. If a separate generated
file is used, the supervisor passes its resolved values to children without
printing them.

Defaults continue to live in `app.config.Settings`. The deployment layer owns
only profile membership and preflight validation; it must not create a second
copy of every default. `.env.example` remains the exhaustive documented
catalog.

For bundled local Compose, database and MinIO credentials are generated using
a cryptographically secure source. Provider credentials are supplied by the
operator. Remote URLs select externally managed dependencies, which are never
started or stopped by this command.

## Profile plans

| Profile | Infrastructure | Application children |
| --- | --- | --- |
| `read` | PostgreSQL only (or remote database) | Streamable HTTP MCP |
| `full` | PostgreSQL, Redis, MinIO (or remote equivalents) | MCP, Celery worker on `ingest,maintenance`, Celery Beat |
| `langbot` | Same as `full` | Celery worker, Beat, loopback LangBot gateway; optional MCP switch |

Compose gains profile-aware service selection only where needed. Existing
plain `docker compose up -d` behavior remains compatible unless the final
implementation can prove an intentional migration path in documentation and
tests.

## Lifecycle and ownership

Runtime state is stored below an ignored `.runtime/` directory:

- one lock guards startup and lifecycle mutations;
- one metadata file records the supervisor PID, child PIDs, profile, start
  time, and non-secret component names;
- each component writes to a separate rotating or bounded log destination;
- PID checks validate both liveness and expected command identity before any
  signal is sent.

In foreground mode the supervisor owns all child process groups, forwards
SIGINT/SIGTERM, and exits non-zero if a required child exits unexpectedly. In
background mode the same supervisor is detached and lifecycle commands talk
only to its validated PID. `stop` signals the supervisor and waits for bounded
cleanup; it never kills processes found only by name or port.

Worker and Beat remain separate children. This avoids Celery's embedded Beat
production caveats while presenting a single operator lifecycle. The lock and
metadata contract prevent a second managed Beat. Readiness still proves a
worker serves both mutation queues.

## Startup sequence

```text
parse profile/options
  -> lock and reject conflicting owner
  -> resolve config without logging values
  -> validate profile requirements and listener safety
  -> start only owned local Compose services
  -> wait for bounded dependency readiness
  -> alembic upgrade head + verify single head
  -> start worker, then Beat when required
  -> verify worker pong and active queues
  -> start MCP and/or private LangBot gateway
  -> publish redacted status
```

Feature flags continue to fail closed. The command must not silently enable
mutation flags merely because the `full` profile was selected; initialization
can propose explicit values, and startup must surface when full readiness is
intentionally disabled.

## Failure and rollback behavior

- Preflight failures make no application-process changes.
- Dependency or migration failures stop only services started during the
  current attempt when doing so cannot affect pre-existing containers.
- Child startup failures terminate siblings started by the supervisor.
- User-authored environment files and persistent Compose volumes are never
  deleted by rollback or `stop`.
- Logs and state remain for diagnosis, but stale state is recognized and can be
  replaced only after command-identity validation.

## Security

- Secret prompts do not echo input.
- Generated files are created with owner-only permissions.
- Status and exceptions use variable names and component names, never values or
  connection URLs.
- MCP remains loopback by default; a non-loopback bind requires an explicit
  acknowledgement and documentation of TLS/reverse-proxy requirements.
- LangBot gateway continues to require loopback and a shared secret of the
  existing minimum length.

## Test strategy

Unit tests exercise profile plans, precedence, minimal serialization,
permissions, redaction, lock/PID validation, startup order, cleanup, and
dependency failure using injected subprocess and filesystem adapters. A small
CLI integration test uses fake child commands and temporary state. Existing
MCP readiness, configuration, deployment health, and ingestion routing tests
guard the runtime contracts.
