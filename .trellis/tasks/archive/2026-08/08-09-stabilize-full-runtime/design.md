# Design: launch first, diagnose separately

## Lifecycle boundary

`_prepare` remains responsible for deterministic gates: configuration safety,
owned local Compose services, and the database migration. Once it succeeds,
the supervisor launches every component in the selected immutable plan.

For `full`, the launch order remains worker, Beat, MCP, but there is no worker
inspection between those launches. The supervisor waits only for the selected
application listener while also checking that every child remains alive. This
makes `start` mean "all required processes were launched and the application
endpoint is listening," rather than "every external diagnostic returned true
in one synchronized snapshot."

## Health boundary

The runtime state records process ownership, the proven listener, and locally
managed Compose ownership. `status` performs database, broker, object store,
maintenance, worker, Compose, listener, and process checks on demand. Deep
probes never occupy the supervisor loop. The supervisor stops the runtime only
on an explicit signal or a real child exit.

The supervisor stores a hash of non-secret dependency targets. Before probing,
`status` hashes its current targets and refuses the deep check on a mismatch.
This prevents a later shell without the original one-shot environment override
from checking a different database or service while never persisting a
credential.

MCP keeps its own bounded mutation-readiness decision. Its Celery inspection
budget must allow both `ping` and `active_queues` to complete on the supported
single-worker setup now that worker and MCP begin concurrently.

## Evaluation teardown

Replace `asyncio.wait_for(runtime.stop())`, which creates a second task, with
`asyncio.timeout()` around a direct `await runtime.stop()`. The timeout remains
bounded while AnyIO exits the stdio client's cancel scope in its owning task.

## Compatibility and rollback

Profiles, commands, environment precedence, state format, log paths, manual
commands, and stop ownership remain compatible. Reverting this task restores
the earlier readiness-gated startup without modifying operator data or volumes.
