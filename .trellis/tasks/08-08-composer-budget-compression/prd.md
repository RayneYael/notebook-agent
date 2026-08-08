# Composer Output Budget and Automatic Evidence Compression

## Goal

Make the answer Composer reliably produce a grounded summary under the configured
token budget by enforcing a real provider-side generation cap, disabling reasoning
for summary composition, and automatically retrying once with a smaller trusted
evidence context when the first composition attempt exhausts its limit.

## Background and Confirmed Facts

- The latest failing request completed retrieval, then exceeded the retrieval
  stage output budget at 2,153/2,000 tokens and the fresh answer-stage budget at
  3,022/2,000 tokens (`.runtime/logs/notebook-agent-2026-08-08.log:256,258`).
- `UsageLimits.output_tokens_limit` is an after-response safety check, not a
  provider generation cap. The current Composer supplies no `max_tokens`
  model setting (`app/agent/runtime.py:683-701`).
- The deployment uses `deepseek-v4-flash` through the OpenAI-compatible Chat
  Completions API. DeepSeek V4 enables thinking by default.
- DeepSeek's official Chat Completions contract uses `max_tokens` for the real
  generation cap and `thinking: {"type": "disabled"}` to disable thinking.
  PydanticAI's generic `thinking=False` maps to `reasoning_effort="none"`, which
  is not DeepSeek's documented Chat Completions toggle.
- The Composer currently receives all retained segments from the top five
  source items. The item cap does not cap segments within an item, so one video
  can contribute roughly twenty evidence rows after two searches.
- The deterministic evidence fallback is an intentional final safety net and
  must remain available if both full and compressed composition fail.

## Requirements

### R1. Real Composer generation cap

- Add a separately configurable Composer generation limit named
  `AGENT_COMPOSER_MAX_TOKENS`, defaulting to 1000.
- Send that value as a real provider request limit for every Composer request;
  do not treat `UsageLimits` as the provider cap.
- For DeepSeek Chat Completions, ensure PydanticAI serializes the setting as
  `max_tokens`, not `max_completion_tokens`.
- Validate configuration so the value is positive and the maximum output of
  the Composer's existing two-request validation run cannot exceed the
  answer-stage `AGENT_OUTPUT_TOKEN_LIMIT`.

### R2. Disable thinking only for summary composition

- Every DeepSeek Composer request must include
  `thinking: {"type": "disabled"}`.
- Non-DeepSeek models should receive the provider-neutral `thinking=False`
  setting when supported.
- Retrieval planning behavior is unchanged; this task must not disable
  reasoning for the tool-using retrieval stage.

### R3. One bounded automatic compression retry

- The first Composer run uses the current trusted, top-five-item evidence set.
- If the answer phase raises a token `UsageLimitExceeded`, or exhausts structured
  output handling in a way consistent with a provider generation cutoff, retry
  composition once with a deterministically compressed evidence view.
- Compression must be local and non-generative: select at most eight segments,
  preserve item coverage before filling additional slots in retrieval order,
  and truncate each evidence excerpt to at most 180 characters.
- The compressed Composer allow-list must contain only evidence that is actually
  presented in its prompt. It may never cite a dropped segment.
- Full trusted citations remain unchanged outside the Composer attempt. If the
  compressed retry fails, the existing evidence fallback uses the original
  bounded citation set.
- Do not retry when compression would not make the context smaller.
- Both Composer runs share the existing answer-stage wall-clock timeout; the
  retry must not silently double worst-case latency.

### R4. Safe diagnostics

- Add an allow-listed `context_compressed` answer-stage diagnostic with only
  safe numeric fields such as before/after evidence counts, retry count, and
  limit classification.
- A recovered first attempt must not be recorded as the final request failure.
- If the compressed retry fails, emit the existing final `agent_failed` event
  and return deterministic evidence fallback.
- Production diagnostics must not contain questions, excerpts, titles, URLs,
  segment IDs, provider bodies, or draft text.

### R5. Compatibility and documentation

- Preserve action behavior, retrieval budgets, tenant isolation, citation
  validation, canonical history, grouped source rendering, and fallback status.
- Document the new environment variable and update the Agent retrieval/
  composition contract.
- Verify the exact outbound DeepSeek request body with a mocked HTTP transport;
  no paid live provider call is required for automated tests.

## Acceptance Criteria

- [ ] A DeepSeek Composer request contains `max_tokens=1000` (or the configured
      value), contains `thinking.type=disabled`, and does not contain
      `max_completion_tokens` or `reasoning_effort=none`.
- [ ] A non-DeepSeek Composer receives a real `max_tokens` model setting and a
      provider-neutral request to disable thinking without changing retrieval
      model settings.
- [ ] Invalid Composer budget configuration fails at startup with a clear,
      secret-free error.
- [ ] A simulated first-run output-token limit causes exactly one compressed
      retry whose evidence count and/or rendered evidence size is smaller.
- [ ] A successful compressed retry returns `status=ok`, validated citations,
      and a normal generated answer rather than the fallback introduction.
- [ ] A second limit/failure returns the original deterministic evidence
      fallback and never exposes a partial or invalid model draft.
- [ ] Already-compact evidence does not cause a useless second model run.
- [ ] Compression keeps at least one segment per retained item when the
      eight-segment cap permits it, and no output cites an omitted segment.
- [ ] Diagnostics record compression with safe counts only and preserve
      production redaction.
- [ ] Targeted Agent/provider/diagnostic tests and the full test suite pass.

## Out of Scope

- Raising the global retrieval/answer `AGENT_OUTPUT_TOKEN_LIMIT` as the fix.
- Disabling thinking for retrieval planning or action handling.
- Compressing stored conversation history; the Composer receives no message
  history, so this task compresses only its trusted evidence prompt.
- A model-generated compression pass, unbounded retries, provider failover, or
  changing the public answer/source format.

