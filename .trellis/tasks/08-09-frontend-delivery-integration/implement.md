# Implementation plan

## Gate 0 - Ownership and source completion

- [x] Fetch `origin` and `upstream`; confirm `upstream/main@a5d244e`.
- [x] Create isolated `codex/frontend-delivery-integration` from the clean
  collection branch; leave dirty root main and source worktrees untouched.
- [x] Confirm collection branch `5b81485` and Showcase branch `b123d0f` have
  committed handoffs.
- [x] Receive the active Web task's final committed handoff and residual-WIP
  ownership report.

## Gate 1 - Independent delivery contract

- [x] RED: prove production composition cannot select API-only mode from
  settings and expects static assets by default.
- [x] GREEN: add strict `WEB_SERVE_STATIC` configuration with backward-compatible
  bundled default and API-only composition.
- [x] Document bundled and split-service same-origin topologies, proxy rules,
  health checks, caching, rollback, and unsupported cross-origin behavior.

## Gate 2 - Source integration and review

- [x] Integrate one source commit at a time, resolve shared frontend files by
  behavior, and run the matching focused tests after each commit.
- [x] Review combined code for correctness, accessibility, product copy,
  responsive behavior, security boundaries, duplication, and simpler designs.
- [x] Fix only reproducible blockers or narrow maintainability defects.

## Gate 3 - Full verification

- [x] Run relevant Python config/API/CLI tests and compilation.
- [x] As sole owner, run frontend test, typecheck, lint, OpenAPI stale check,
  and build serially in the integration worktree.
- [x] Run desktop and exact 390x844 browser smoke for Showcase, login, library,
  add dialog, and detail; record console and overflow evidence.
- [x] Validate Trellis records and Git diff/commit boundaries.

## Gate 4 - Handoff

- [x] Create Lore commits with source integration and delivery-boundary intent.
- [x] Fast-forward the existing fork PR branch from the verified integration
  head; do not push or update `main`.
- [x] Update the existing upstream PR without merging; include architecture decision,
  verification, and external deployment gates.

## Gate 5 - Final residual frontend integration

- [ ] Create a narrow recovery commit for each residual source worktree while
  excluding runtime/build output, machine-local QA paths, and unrelated WIP.
- [ ] Integrate the collection/progress/transcript commit and the
  brand/login/Showcase commit one at a time, preserving both sides of shared
  stylesheet changes.
- [ ] Run full frontend tests, frozen OpenAPI check, typecheck, lint, production
  build, deployment contract tests, and a final independent code/architecture
  review on the integrated head.
- [ ] Refresh `upstream/main`, preserve a fast-forward fork push, update PR 2
  with completed frontend work plus deployment-ready and external-gate status,
  and do not merge it.
