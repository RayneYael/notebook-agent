# Pre-existing working-tree boundary

Recorded before deployment implementation on 2026-08-08.

- Base commit: `3989dee916e6420877edc988fc51adfe7f24e5ac`
- Deployment branch: `codex/vercel-neon-deploy`
- Modified files owned by earlier work:
  - `.env.example`
  - `README.md`
  - `README.zh-CN.md`
  - `app/bootstrap.py`
  - `app/channels/identity.py`
  - `app/cli.py`
  - `app/config.py`
  - `app/diagnostics.py`
  - `app/models.py`
  - `docs/deployment.md`
  - `pyproject.toml`
  - `uv.lock`
- Untracked files/directories owned by earlier work:
  - `.trellis/tasks/08-08-mcp-server-optional-langbot/`
  - `app/mcp_auth.py`
  - `app/mcp_grant.py`
  - `app/mcp_grants.py`
  - `app/mcp_server.py`
  - `migrations/versions/e5f6a7b8c9d0_mcp_access_grants.py`
  - `tests/test_mcp_server.py`

These paths must remain unstaged and absent from the deployment commit.
