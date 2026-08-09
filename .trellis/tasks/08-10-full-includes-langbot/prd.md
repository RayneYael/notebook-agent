# 让 full 包含 LangBot gateway

## Goal

Define full as worker, Beat, MCP, and LangBot gateway; align init, required configuration, status, tests, and deployment docs.

## Requirements

- Redefine `full` as the union of the MCP and LangBot application runtimes:
  one worker, one Beat scheduler, Streamable HTTP MCP, and the loopback channel
  gateway.
- Keep `langbot` as the channel-only application profile: worker, Beat, and
  gateway without the public MCP listener.
- Make `CHANNEL_GATEWAY_SECRET` required, generated, preserved, validated, and
  redacted for both `full` and `langbot`.
- A `full` start must wait for both MCP and gateway listeners while continuing
  to treat real child exit as a lifecycle failure.
- `status` must report both listeners for `full` and preserve one-listener
  compatibility for `read` and `langbot`.
- The runtime target fingerprint must cover both `full` listeners without
  storing credentials.
- Update the English/Chinese quick starts, environment guide, deployment guide,
  and stable deployment specification so `full` is no longer described as MCP
  plus background workers only.
- Implement in an isolated worktree based on `dev`, then test and push only to
  `dev`; do not modify the main worktree.

## Acceptance Criteria

- [x] `build_plan("full")` contains exactly worker, Beat, MCP, and gateway.
- [x] `init --profile full` creates or preserves a private gateway secret.
- [x] Missing, short, or unsafe gateway configuration fails before side
      effects for both profiles that contain the gateway.
- [x] Full startup and status cover ports 8000 and 8765 independently.
- [x] Focused deployment and affected regression tests pass.
- [x] Generated configuration, logs, runtime state, and secrets remain ignored
      and unstaged.

## Constraints

- This launcher manages the Notebook Agent gateway process, not the external
  LangBot core, plugin runtime, or WeChat adapter.
- Worker and Beat remain separate processes and only one managed Beat may run.
