# Second live failure: retrieval converged but answer generation exhausted cumulative output tokens

## Evidence inspected

- User-provided structured runtime log containing the original failing trace and a second development-mode trace.
- Current `app/agent/runtime.py`, `app/agent/services.py`, and `app/retrieval/search.py` at `HEAD`.
- PydanticAI 2.15.0 installed source for `UsageLimits`, tool preparation, and tool execution.
- Current runtime model selection: `openai:deepseek-v4-flash`.
- Existing regression tests in `tests/test_agent_runtime.py` and `tests/test_knowledge_services.py`.

The analysis uses only the already user-provided diagnostic data. It does not add model output, prompts, secrets,
external identities, or provider payloads to repository artifacts.

## Reconstructed second trace

The second request did not repeat the original tool-call-limit failure. Its observed path was:

| Model attempt | Model-emitted calls or result | Backend retrieval calls after step | Outcome |
| ---: | --- | ---: | --- |
| 1 | 2 × `search_segments` in one response | 2 | both succeeded, 6 results each |
| 2 | 2 × `get_neighbors` + 1 × `get_item` in one response | 5 | all three succeeded |
| 3 | answer draft | 5 | output validator did not accept the draft |
| 4 | retry response | 5 | run stopped at cumulative output tokens 2066 > 2000 |

No `citation_validated` event occurred. All retrieved candidates belonged to one video. Because a Top-5 violation is
impossible with one `item_id`, the transition from attempt 3 to attempt 4 is consistent with the only remaining
validator branch: missing or unknown citation markers. The private model draft was correctly not logged, so the exact
text and exact invalid marker are intentionally unavailable.

The terminal diagnostic was:

```text
error_class=UsageLimitExceeded
limit_kind=output_tokens
limit_value=2000
used_value=2066
```

The user still saw the retrieval-limit wording because the runtime maps every `UsageLimitExceeded` kind to the same
text: `检索步骤已达到上限，请缩小问题范围后重试。`

## Root causes and invalidated assumptions

### 1. `parallel_tool_calls=False` is not an application boundary

The current callback did pass `{"parallel_tool_calls": False}` on every model request. The live
OpenAI-compatible DeepSeek path nevertheless returned batches of two and three tool calls. Therefore the setting is
only a provider request preference for this deployment, not a server-enforced invariant.

PydanticAI prepares visible tool definitions before the model response. A tool `prepare` callback cannot re-evaluate
dependency counters between calls already present in the same response. PydanticAI also executes non-sequential tools
in a batch concurrently by default. The framework supports local sequential execution, but sequential execution alone
still runs every call in the batch; it does not reduce a batch to one backend retrieval.

This invalidates the design claim that provider settings make five model rounds and five backend retrieval calls map
one-to-one.

### 2. The 2000 output-token limit is cumulative across the entire Agent run

PydanticAI's `UsageLimits.output_tokens_limit` checks `RunUsage.output_tokens` after each response. It is not a
per-response maximum reserved for the final answer. Tool-planning responses, the first answer draft, and citation
retries all consume the same 2000-token pool. A longer multi-step run can therefore exhaust the final-answer budget
even when backend retrieval has converged normally.

The existing tests use `FunctionModel` responses with minimal/default usage and do not reproduce cumulative provider
usage. They prove tool visibility under a cooperative one-call-per-response fake, not the real batch-plus-token path.

### 3. Citation formatting repair is coupled to another search

After evidence already exists, any missing or unknown `[S…]` marker starts a repair mode that requires a fresh
`search_segments`. The live request already held useful evidence, including a neighboring segment containing a
definition, but a formatting/selection failure still required another retrieval. The fourth response ignored that
instruction and hit the cumulative output-token limit before a fresh search or validated answer.

Evidence refresh and answer/citation-format repair are different problems. Coupling them adds model requests, provider
output tokens, embeddings, and duplicate retrieval without proving the evidence itself was insufficient.

### 4. Segment-level top-k does not provide Top-5 video coverage

Both live searches returned six segments from the same video. `KnowledgeServices.search_segments()` asks BM25 and
vector search for `k=limit`, merges by segment ID, sorts raw hit scores, and stops after `limit` segments. It performs
no per-`item_id` diversification or over-fetching. One video with many high-scoring segments can crowd every other
video out of the candidate set, so the Agent cannot compare sources it never receives.

Final output grouping by `item_id` prevents duplicate display rows, but it cannot recover candidate diversity after
segment-level truncation.

## Test gaps

- No fake model emits multiple retrieval calls in one response while `parallel_tool_calls=False` is present.
- No test asserts an application-enforced per-step reservation when the provider ignores that setting.
- No model response supplies realistic non-zero `RequestUsage.output_tokens` across tool planning and retries.
- No test proves output-token exhaustion is classified separately from retrieval exhaustion.
- No retrieval-service test creates many strong segments from one item plus weaker relevant segments from other items
  and asserts diversified video coverage.
- The citation repair test assumes every invalid draft should trigger a fresh search rather than an answer-only retry
  against the existing allow-list.

## Design implications

The next design must not depend on provider compliance for batching and must not treat a cumulative run token limit as
the final answer's generation budget. The strongest candidate is a two-stage knowledge path:

1. A server-bounded retrieval/selection stage with atomic per-step/backend budgets and diversified candidates.
2. A tool-free answer composer with a fresh, explicit generation budget and structured citation IDs validated against
   the selected evidence.

If the composer still fails, the product needs one explicit decision: return a deterministic evidence-only fallback,
or keep a generic `answer_unavailable` failure. Merely increasing `AGENT_OUTPUT_TOKEN_LIMIT` is a mitigation, not a
complete convergence fix.
