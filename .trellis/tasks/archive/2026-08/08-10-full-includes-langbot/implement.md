# Implementation plan: include gateway in full

1. Extend the full immutable component plan with `gateway`.
2. Generalize listener target derivation and use it for startup, state, status,
   and target fingerprinting.
3. Apply gateway secret generation, preservation, required-variable checks,
   loopback validation, and port validation to full as well as langbot.
4. Update focused tests for composition, initialization, validation, dual
   listener readiness/status, and supervisor launch order.
5. Update the deployment spec and operator documentation in English and
   Chinese.
6. Run the required deployment/MCP/worker regressions, Python and shell syntax
   checks, Trellis validation, and `git diff --check`; inspect staged paths for
   runtime artifacts or secrets.
7. Commit on the isolated branch, rebase onto current `origin/dev` if needed,
   archive the task, and fast-forward push to `dev` only.

## Rollback

Reverting the component-plan and listener-target changes restores the previous
mutually exclusive MCP/gateway profiles without changing operator data or
Compose volumes.

## Validation results

- Affected deployment, task, ingestion notification, LangBot bridge, and HTTP
  gateway suites: `105 passed`.
- Deployment CLI after independent review: `45 passed`.
- Broader regression excluding the known fixed-five-second MCP stdio cold-start
  case: `111 passed, 1 deselected`.
- The excluded MCP stdio case also times out on the unmodified `dev` baseline;
  it is unrelated to this profile change and was not broadened into this task.
- Python compile checks, shell syntax, `git diff --check`, and Trellis context
  validation passed.
- Independent Trellis review found and fixed a full-profile listener-port
  collision race; no high- or medium-priority findings remain.
