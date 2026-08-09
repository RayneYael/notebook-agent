# Implementation plan: stabilize the managed runtime

1. Remove deep full-runtime readiness from the supervisor's component launch
   sequence and spawn all selected children first.
2. Keep the bounded listener/liveness wait as the only application startup
   gate, then publish a minimal initial status snapshot.
3. Move deep dependency checks to on-demand `status`, leaving the supervisor
   loop responsible only for signals and child-exit sibling cleanup.
4. Increase the MCP worker-inspection budget enough for both Celery broadcast
   operations without creating an unbounded startup.
5. Preserve same-task evaluation teardown with a regression test.
6. Update focused lifecycle tests and deployment documentation/specification.
7. Run focused and combined regressions, syntax checks, `git diff --check`, and
   a no-cost real full-stack preflight. Review the final diff for generated or
   secret files.
8. Commit on the isolated fix branch, rebase onto current `origin/dev` if
   needed, and push the commit to `dev` only.

## Rollback points

- The supervisor sequencing change is isolated to `app/deployment.py` and its
  focused tests.
- The evaluation teardown change is independent and can be reverted without
  changing deployment behavior.
- No persistent volumes or operator-authored environment files are mutated by
  the code changes.

## Validation result

- Relevant combined regression: `125 passed`.
- Python compilation, shell syntax, Trellis context validation, and
  `git diff --check` passed.
- A real full-stack preflight completed cleanly after the same-task teardown
  fix, with no AnyIO cancel-scope error.
- A final local full-launch repetition was not stacked on top of seven foreign,
  orphaned ingest-only Celery processes (PPID 1); those processes are not owned
  by this launcher and were intentionally left untouched. Component launch
  order and child-exit cleanup are covered by focused supervisor tests.
- Generated `.env.runtime`, `.runtime/`, and evaluation artifacts remain
  ignored and unstaged.
