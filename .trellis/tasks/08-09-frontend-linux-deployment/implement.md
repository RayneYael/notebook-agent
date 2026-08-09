# Implementation plan

## Gate 0 - Ownership and evidence

- [x] Confirm integration ownership, fork-only branch, remote roles, and dirty
  root-main protection.
- [x] Fetch the latest upstream and inspect repository/GitHub/server evidence.
- [x] Confirm no concrete SSH host, domain, deployment workflow, repository
  secret, or local SSH alias is available.

## Gate 1 - Upstream convergence

- [ ] Merge `upstream/main@6539f3b` into the integration branch.
- [ ] Resolve code conflicts by preserving both Web tenant/archive/deleted
  filters and upstream reference-scoped routing/completion behavior.
- [ ] Replace the duplicate Web merge revision with one new unique head and
  update deployment revision references.
- [ ] Run focused routing, ingestion completion, Web, migration-graph, and
  deployment tests.

## Gate 2 - Linux deployment surface

- [ ] Add a reviewed Nginx static + same-origin API proxy configuration.
- [ ] Add a hardened systemd unit for the API-only Web service.
- [ ] Document exact install, build, configuration, TLS, rollout, rollback, and
  smoke commands without embedding a real host or secret.
- [ ] Add structural regression tests for the deployment artifacts.

## Gate 3 - Validation

- [ ] Run frontend frozen install, API contract check, tests, typecheck, lint,
  and production build serially as the single live-test owner.
- [ ] Run Python compile, focused backend/deployment tests, Alembic head/history,
  and diff checks.
- [ ] Run a local production-shape smoke with a task-owned loopback port and
  record logs/process cleanup.

## Gate 4 - Remote and PR handoff

- [ ] If an explicit authorized host/domain exists, deploy and verify the exact
  candidate; otherwise record the missing target as the only remote blocker.
- [ ] Create Lore commits, fast-forward the user's existing fork PR branch, and
  update PR 2 without merging.
- [ ] Leave Trellis status at `review` until external server and live-channel
  acceptance are complete.
