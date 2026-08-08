# Context

## 2026-08-09

- Owner: `/root` (integration owner and sole live-process owner for this task).
- Source requirement: browser comment on the Add Video dialog plus follow-up to
  check upstream and prefer reuse of `why_saved`.
- Upstream evidence: `upstream/main@a5d244e` has no Web folder/collection API;
  its `ContentItem.tags` is connector metadata and its management service limits
  `why_saved` to 500 characters.
- Isolation: implementation worktree is
  `C:/Users/raede/.codex/worktrees/why-saved-collections` on
  `codex/why-saved-collections`, based on Web MVP HEAD `f29b982`.
- Existing live previews remain owned by `/root`: Showcase on 5173 and the
  authenticated Web fixture on 5174. This task will use a separate port before
  changing either preview.
- TDD evidence: pure parser, add-dialog, library filter, card, and detail tests
  all failed for the intended missing behavior before the minimal implementation;
  the focused suite now passes 30 tests.
- Live validation owner: `/root` only. Commands run serially from `web/`:
  `pnpm test`, `pnpm typecheck`, `pnpm lint`, `pnpm check:api`, and `pnpm build`.
  Build output is isolated to this worktree's `web/dist`.
- Preview plan: port 5175 only, with logs and PID under this worktree's
  `.runtime/why-saved-collections/`. Ports 5173 and 5174 remain untouched.
- Success: all frontend checks exit 0 and desktop plus 390x844 browser smoke
  show no horizontal overflow. Stop on a repeatable product failure; retry at
  most after collecting new evidence.
- Final verification: 13 frontend test files / 51 tests passed; TypeScript,
  ESLint, OpenAPI stale check, Vite production build, and `git diff --check`
  passed. The OpenAPI check reused the project virtual environment with a
  one-command `PYTHONPATH` pointed at this worktree; no API files changed.
- Browser evidence: desktop filtering reduced `#产品调研` to one item while
  retaining the other chips; the Add Video dialog exposed all discovered
  collections, inline invalid-name guidance, a selected new collection, and a
  vertically resizable reason area. Detail displayed `#产品调研` separately and
  the editor contained only human-readable reason text. A calibrated 391x844
  viewport (the browser's nearest integer representation of 390x844) had no
  horizontal overflow; the bottom-sheet dialog stayed within the viewport and
  became internally scrollable.
- Preview: `http://127.0.0.1:5175/library`, local fixture only. Listener PID
  observed as 47536 (venv launcher PID 72196); logs are under
  `.runtime/why-saved-collections/`. Leave running for user review.
- Remaining integration boundary: commit this isolated branch, then integrate
  it into `codex/web-video-library-mvp` only after that shared worktree's
  unrelated Showcase/chapter WIP is cleanly separated. Do not auto-merge.
