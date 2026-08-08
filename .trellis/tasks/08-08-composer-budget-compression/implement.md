# Implementation Plan

## 1. Configuration and provider request contract

- [x] Add `Settings.agent_composer_max_tokens` from
      `AGENT_COMPOSER_MAX_TOKENS` with default 1000.
- [x] Validate positivity and the two-request answer-stage budget invariant.
- [x] Update `.env.example` and deployment documentation.
- [x] Apply the PydanticAI DeepSeek profile to configured DeepSeek model names
      and force the `max_tokens` Chat Completions field mapping.
- [x] Add a mocked-transport test that asserts exact outbound DeepSeek fields:
      `max_tokens`, `thinking.type=disabled`, no `max_completion_tokens`, and
      no `reasoning_effort=none`.

## 2. Composer policy and compressed evidence view

- [x] Add one provider-aware Composer model-settings helper; keep retrieval
      model settings unchanged.
- [x] Extend `ComposerDeps` with an excerpt projection bound.
- [x] Implement a pure coverage-first compression helper capped at eight
      citations and 180 excerpt characters.
- [x] Test deterministic order, item coverage, no duplicates, immutability, and
      the no-op case where compression cannot reduce context.

## 3. Bounded retry flow

- [x] Refactor answer composition into a single-attempt helper returning the
      validated draft and attempt metadata.
- [x] Keep full and compressed attempts inside one answer-stage timeout.
- [x] Retry exactly once after typed token-limit or exhausted answer-output
      handling, each time with a fresh `RunUsage`.
- [x] Ensure compressed validation cannot cite omitted IDs.
- [x] On second failure, preserve the original deterministic evidence fallback
      and discard every partial/invalid draft.

## 4. Diagnostics and specification

- [x] Add the safe `context_compressed` diagnostic stage and tests.
- [x] Keep the recovered first attempt out of terminal `agent_failed` logs.
- [x] Update `.trellis/spec/backend/agent-retrieval-convergence.md` with the
      real generation cap, DeepSeek non-thinking Composer, and compression
      retry contract.

## 5. Validation

- [x] Run focused tests:

      ```bash
      .venv/bin/pytest tests/test_agent_runtime.py \
        tests/test_provider_and_explicit_user.py tests/test_diagnostics.py
      ```

- [x] Run the complete suite:

      ```bash
      .venv/bin/pytest
      ```

- [x] Review the diff for secret leakage, unrelated worktree changes, and
      provider-generic regressions.
- [x] Confirm `.trellis` context manifests and task validation before starting
      implementation.

Focused validation: `63 passed`. The complete suite reached `161 passed, 21
skipped, 1 failed, 9 errors`; the remaining cases require a local TCP listener
or PostgreSQL on `localhost:5432`, both denied by the current sandbox rather
than failing in the changed Composer/provider paths.

## Risk and Rollback Points

- Provider profile changes are isolated in `app/agent/provider.py`; revert that
  unit if a non-DeepSeek compatible endpoint regresses.
- Retry orchestration is isolated around `_compose_or_fallback`; the existing
  fallback remains the terminal behavior throughout implementation.
- Do not raise global usage limits to make tests pass.
