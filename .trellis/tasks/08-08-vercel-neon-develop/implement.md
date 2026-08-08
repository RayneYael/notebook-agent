# Implementation plan: Vercel + Neon develop environment

## 1. Establish a clean Git deployment boundary

- Record the current committed base SHA and the complete unstaged/untracked
  file list.
- Create `codex/vercel-neon-deploy` from the committed HEAD and set it as the
  task branch.
- Never stage or commit files owned by the existing MCP task.
- Gate: staged diff and `base..HEAD` diff contain only this task's files.

## 2. Add the minimal Vercel runtime probe

- Add a Python `BaseHTTPRequestHandler` entrypoint for the health endpoint.
- Add bounded Neon connection/query behavior and redacted 200/503 responses.
- Add Vercel routing, Python version, and bundle-exclusion configuration.
- Add unit tests for success, database failure, missing configuration, response
  shape, and secret redaction.
- Add a deployment guide covering environment variables, migration, rollback,
  and teardown.

Validation:

```bash
pytest -q
python -m compileall api app
git diff --check
```

## 3. Create and migrate the isolated Neon environment

- Authenticate to Neon through an existing session or a one-time user login.
- Create `notebook-agent` in a suitable region; record only public
  project/branch identifiers.
- Obtain pooled and direct URLs without printing them into logs or task files.
- Run `alembic upgrade head` against the direct URL.
- Verify `alembic current`, `vector`, and `pg_trgm`.
- Gate: schema revision equals the committed repository head before Vercel is
  allowed to report ready.

## 4. Commit, push, and connect Vercel to Git

- Review and commit only the deployment task files.
- Push `codex/vercel-neon-deploy` to GitHub.
- Create `notebook-agent` in Vercel and link the GitHub repository.
- Configure the selected branch as the stable branch for this dedicated
  develop-only project.
- Add `DATABASE_URL` and non-secret environment markers to Vercel without
  echoing values.
- Start the first Git-sourced deployment and capture its project, deployment,
  commit, and public URL identifiers.

## 5. Verify the live environment

- Request the public health URL and require HTTP 200.
- Confirm the response says `competition`, database `ok`, and the expected Alembic
  revision, with no host, username, password, DSN, exception, or stack trace.
- Inspect the Vercel build for Python version, dependency bundle success, Git
  source SHA, and function duration.
- Confirm Git integration is active for subsequent pushes to the branch.
- Gate: do not claim the environment is deployed if only a CLI/local upload
  exists or the endpoint cannot reach Neon.

## 6. Final review and handoff

- Run the full local test suite and a deployment-specific review.
- Re-check the original dirty-file inventory to prove unrelated work is intact.
- Update the deployment guide with the actual non-secret resource identifiers.
- Commit and push final documentation changes, then verify the resulting Git
  deployment.
- Record rollback and teardown commands without executing teardown.

## Rollback points

- Before cloud creation: delete only local task changes if the user cancels.
- After Neon creation but before Vercel: leave the isolated empty database for
  retry, or delete it only on explicit request.
- After Vercel deployment: redeploy the previous Git commit; do not downgrade
  the database automatically.
- Never modify, restart, or remove Tencent Cloud/Hermes resources in this task.
