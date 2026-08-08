# Design: Composer Budget Enforcement and Evidence Compression

## 1. Boundaries

The change stays inside the existing two-stage knowledge path:

```text
retrieval planner -> trusted Citation cache
                  -> full Composer attempt
                  -> compressed Composer attempt (limit/output exhaustion only)
                  -> deterministic evidence fallback
```

The retrieval planner and save/action paths do not change. Compression is a
server-owned projection of already trusted `Citation` objects, not a new model
stage and not a new retrieval call.

## 2. Provider Contract

### 2.1 DeepSeek model profile

`app/agent/provider.py` currently constructs every configured custom base URL
with a generic `OpenAIProvider`. For model names beginning with `deepseek-`,
compose the bundled PydanticAI DeepSeek profile into the `OpenAIChatModel`
profile while retaining the configured base URL. Override
`openai_chat_supports_max_completion_tokens=False`, because DeepSeek's official
Chat Completions field is `max_tokens`.

This keeps custom/loopback endpoint support while gaining DeepSeek's
`reasoning_content` and tool-choice compatibility profile. Non-DeepSeek
OpenAI-compatible models retain their current profile.

### 2.2 Composer request settings

Each Composer request receives:

```python
{
    "parallel_tool_calls": False,
    "max_tokens": settings.agent_composer_max_tokens,
    # DeepSeek:
    "extra_body": {"thinking": {"type": "disabled"}},
    # Other providers instead use:
    "thinking": False,
}
```

The DeepSeek path intentionally does not set unified `thinking=False`, because
PydanticAI 2.15.0 translates that value to `reasoning_effort="none"`; DeepSeek
documents only `low`, `high`, and `max` for `reasoning_effort`, with the mode
toggle carried in `thinking.type`.

`UsageLimits(output_tokens_limit=...)` remains as defense in depth. It is not
removed and is not represented as the provider cap.

### 2.3 Budget invariant

The existing `ANSWER_REQUEST_LIMIT=2` allows one structured-output repair in a
single Composer run. Configuration validates:

```text
AGENT_COMPOSER_MAX_TOKENS > 0
AGENT_COMPOSER_MAX_TOKENS * ANSWER_REQUEST_LIMIT
    <= AGENT_OUTPUT_TOKEN_LIMIT
```

The default is `1000 * 2 <= 2000`.

## 3. Evidence Views

Keep original trusted citations immutable. A Composer attempt gets a view:

```python
@dataclass
class ComposerDeps:
    citations: dict[int, Citation]  # both prompt rows and validation allow-list
    excerpt_chars: int
    diagnostics: RequestDiagnostics | None
    invalid_draft_count: int
```

The full view retains the current selected top-five-item citations and uses the
current 360-character excerpt projection.

The compressed view is deterministic:

1. Group citations by `item_id` while preserving retrieval order.
2. Select the first citation from each item, up to eight total.
3. Fill remaining slots by original retrieval order without duplicates.
4. Render at most 180 characters from each excerpt.

The view's citation dictionary is also the output validator's allow-list. This
prevents a model from citing evidence omitted during compression. Successful
rendering uses the selected original `Citation` objects, so public URLs and
source excerpts are not mutated.

Compression is useful only if either the selected citation count or rendered
evidence character count decreases. Otherwise the retry is skipped.

## 4. Retry State Machine

Run both possible attempts under one outer `asyncio.timeout` using the existing
`AGENT_TIMEOUT_SECONDS` value.

```text
full attempt
  success -> validate/render/persist
  token UsageLimitExceeded -> compressed attempt
  exhausted structured output / provider length -> compressed attempt
  timeout or unrelated provider/runtime failure -> fallback

compressed attempt
  success -> validate/render/persist
  any failure -> log final failure -> fallback(original citations)
```

Each attempt gets a fresh `RunUsage`, because it is a separately bounded model
run. Each still has `ANSWER_REQUEST_LIMIT=2` and the configured post-response
output safety limit. There is at most one compressed attempt. Therefore the
whole recovery workflow can theoretically make four provider requests and
generate up to 4,000 output tokens with the default configuration, while the
shared wall-clock timeout still bounds total latency.

PydanticAI may surface a provider `finish_reason=length` as
`UnexpectedModelBehavior` after structured-output handling. Therefore an
exhausted answer-only structured-output run is eligible for the same one-time
compression retry. Model HTTP failures and timeouts are not retried unless they
already arrive through the typed limit/output-exhaustion paths.

## 5. Diagnostics

Add `context_compressed` to the diagnostic stage allow-list. Reuse safe numeric
fields:

- `agent_phase=answer`
- `retry_count=1`
- `result_count=<after evidence count>`
- `projected_value=<before evidence count>`
- `limit_kind=<classified limit or unknown>`

Do not log IDs, evidence text, titles, questions, drafts, or exception messages
in production. The first recoverable event is not `agent_failed`; only terminal
failure after the compressed attempt uses that stage.

## 6. Compatibility and Rollback

- Public `AgentAnswer`, citations, answer history, and source rendering do not
  change.
- Existing deterministic fallback remains the rollback boundary.
- Removing the new Composer settings and retry helper returns to current
  behavior without data migration.
- Configuration is additive. Deployments that do not set the new variable use
  the validated default of 1000.

## 7. Test Strategy

- Mock the OpenAI client transport and inspect the exact DeepSeek JSON request.
- Assert generic provider settings separately from DeepSeek settings.
- Use `FunctionModel`/test models to force first-attempt usage and output
  exhaustion, inspect compressed prompt size, and return a valid second answer.
- Cover second failure, already-compact input, coverage-first selection,
  citation allow-list enforcement, shared timeout, and diagnostics redaction.
- Re-run all existing retrieval convergence, action, persistence, and
  multi-user tests.
