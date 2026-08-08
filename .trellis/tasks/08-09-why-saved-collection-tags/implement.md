# Implementation Plan

## Gate 0 - Isolation and contract

- [x] Fetch and inspect `upstream/main`; confirm no Web collection/folder API.
- [x] Confirm connector `tags` are YouTube metadata and must remain unchanged.
- [x] Create `codex/why-saved-collections` worktree from Web MVP HEAD to avoid
  the Showcase and chapter-style WIP in `web-mvp-final`.
- [x] Record the `why_saved` hashtag grammar, 500-character limit, and non-goals.

## Gate 1 - Pure tag behavior

- [x] RED: parsing, de-duplication, validation, reason separation, formatting,
  and combined-length tests.
- [x] GREEN: implement the pure collection-tag module.

## Gate 2 - Add dialog

- [x] RED: existing tag selection, create/select validation, unclassified
  selection, textarea resize affordance, and unchanged request DTO tests.
- [x] GREEN: implement picker composition and add-dialog behavior.

## Gate 3 - Existing library/detail UI

- [x] RED: library filter chips, card tag/reason separation, and detail tag
  display plus reason-edit preservation.
- [x] GREEN: implement shared tag presentation and integrate each surface.

## Gate 4 - Verification and integration handoff

- [x] Targeted tests after each RED/GREEN cycle.
- [x] Full frontend test, typecheck, lint, build, and API stale check.
- [x] Desktop and 390x844 browser smoke in an isolated preview port.
- [x] Review for accessibility, mobile overflow, privacy, and simpler designs.
- [x] Prepare a clean commit/patch for integration into
  `codex/web-video-library-mvp`; do not merge the PR automatically.

## Gate 5 - Compact URL tags follow-up

- [x] RED: compact one-row URL input and per-link removable tag behavior.
- [x] GREEN: split URL draft state from confirmed URLs while preserving the
  existing `{urls, why_saved}` submission contract.
- [x] Verify multiline paste, link wrapping/growth, desktop/mobile overflow,
  full frontend checks, and the refreshed isolated preview.

## Gate 6 - Account-menu click-away follow-up

- [x] RED: opening the native details menu and clicking a control outside it
  leaves the old implementation incorrectly expanded.
- [x] GREEN: close only when document pointerdown falls outside the menu ref.
- [x] Run the shell regression test, full frontend checks, rebuild 5175, and
  verify outside/inside clicks in the browser before committing.

## Validation Commands

```powershell
corepack pnpm vitest run src/library/collections.test.ts
corepack pnpm test
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm build
corepack pnpm check:api
git diff --check
```
