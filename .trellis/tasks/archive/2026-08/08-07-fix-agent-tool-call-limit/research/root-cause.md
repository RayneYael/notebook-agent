# Root-cause research: concept query exhausts tool-call limit

## Evidence inspected

- User-provided redacted runtime log, 47 JSONL events, trace
  `a0d1a1acac49481484ce8d5a18f6ec6e`.
- `app/agent/runtime.py` current worktree and `HEAD` version.
- `app/config.py` defaults and `.env.example`.
- PydanticAI 2.15.0 installed source for `UsageLimits`.
- Existing Agent requirements/design in:
  - `.trellis/tasks/08-04-video-text-kb/design.md`
  - `.trellis/tasks/08-06-connect-agent-embedding/prd.md`
  - `.trellis/tasks/08-06-connect-agent-embedding/design.md`
  - `.trellis/tasks/08-07-initial-logging-setup/prd.md`

No prompt, query, tool arguments/results, evidence text, secrets, provider payloads, or external identities were
read or persisted during this analysis.

## Reconstructed execution

The request reached the Agent, embedding and pgvector retrieval completed successfully, and every backend tool
boundary shown before the failure succeeded. The trace reconstructs as follows:

| Model attempt | Requested tools | Successful calls in round | Cumulative successful calls |
| --- | --- | ---: | ---: |
| 1 | 2 × `search_segments` | 2 | 2 |
| 2 | 3 × `get_neighbors` | 3 | 5 |
| 3 | 2 × `get_neighbors`, 1 × `get_item` | 3 | 8 |
| 4 | 1 × `search_segments`, 1 × `get_neighbors` | 2 | 10 |
| 5 | next parallel batch (not executed) | 0 | projected 12 |

The final event was:

```text
error_class=UsageLimitExceeded
limit_kind=tool_calls
limit_value=10
used_value=12
```

This is not an embedding or retrieval outage. Both `embedding_completed` and `retrieval_completed` precede each
successful `search_segments`, and no provider/database failure event occurs.

## Why `used_value` is 12 when only 10 calls ran

PydanticAI 2.15.0 implements the check as:

```python
def check_before_tool_call(self, projected_usage: RunUsage) -> None:
    tool_calls = projected_usage.tool_calls
    if tool_calls_limit is not None and tool_calls > tool_calls_limit:
        raise UsageLimitExceeded(...)
```

The framework validates the whole tool-call batch before executing it. The model had already completed 10 calls
and proposed 2 more in one response, so the projected count was 12. The rejected pair did not enter the backend.

## Root cause

The system has a hard raw-call limit but no normal retrieval convergence control:

1. `INSTRUCTIONS` permits repeat search and optional expansion without an ordered budget.
2. All four retrieval tools stay visible on every model request.
3. Provider-level parallel tool calls are enabled, allowing 2–3 calls per model response.
4. `UsageLimits(tool_calls_limit=10)` is therefore the first deterministic stop condition.
5. The catch block maps that internal stop to user-facing `failed/limit` and tells the user to narrow the question,
   even when the initial question is a simple concept explanation.

This violates the original design requirement that the Agent use a bounded number of tool *rounds* and terminate
with an evidence/no-evidence result.

The repeated `call_index` values on success events are an observability artifact of the in-progress logging change:
the success event reads the shared cumulative counter after a parallel batch has started. It does not explain the
limit. Serializing model tool calls as part of this fix also makes each started/succeeded pair stable, but the wider
logging implementation remains owned by `08-07-initial-logging-setup`.

## Options considered

### A. Increase `AGENT_TOOL_CALLS_LIMIT`

Rejected as the primary fix. It postpones the failure but does not create convergence; a looping model can consume
the new budget as well. It also increases latency and provider cost for simple questions.

### B. Add prompt wording only

Rejected as insufficient. Prompt guidance is useful, but the acceptance test must include a model that keeps calling
every tool it can see. The runtime needs to remove retrieval tools once the normal budget is exhausted.

### C. Disable parallel tool calls and dynamically omit retrieval tools after a staged budget

Selected. PydanticAI 2.15.0 supports both `ModelSettings.parallel_tool_calls` and per-tool `prepare` callbacks that
return `None` to hide a tool for a model step. A local prototype confirmed that a prepared tool is present for the
first two steps and absent on the next step after dependency state reaches its budget.

The initial three-round proposal was revised after the product requirement was clarified: answers may span multiple
videos or chapters, and the Agent must judge candidate relevance and return a grouped summary list. The selected
normal budget is therefore five ordered calls: at most two searches plus at most three selective context/metadata
expansions. One extra search remains reserved for citation repair.

The user selected a ranked Top 5 video list rather than exhaustive retrieval. Deduplication is hierarchical: exact
or adjacent-overlapping segment evidence may merge, while distinct chapter/time evidence remains nested under one
video-level `item_id` entry. Current Citations expose timestamps but not chapter titles, so the first version must not
invent chapter labels.

This produces an ordered normal path:

```text
model → retrieval tool 1..5 (stop early when evidence is sufficient)
model → final cited answer or explicit no-evidence result
```

If the last draft fails citation validation, expose only one fresh `search_segments` call, then hide retrieval again:

```text
... → invalid draft → repair search → final repaired answer
```

The repair worst case uses eight model requests and six tool calls, so the default request limit changes from six to
eight while the raw tool-call hard limit remains ten.

### D. Catch the limit and run a second answer-only Agent

Rejected for now. It adds a second model execution path, makes message/citation persistence harder to reason about,
and treats the symptom after excessive work instead of preventing it.

## Validation implications

- Test tool visibility per step, not merely constants or prompt text.
- Use a `FunctionModel` that deliberately keeps calling while any retrieval tool is exposed.
- Assert backend retrieval attempts, model request count, final status/citations, and no `limit` outcome.
- Preserve a dedicated hard-limit test so PydanticAI budget exceptions remain fail closed.
- Re-run action/persistence/integration tests because all tools share one Agent and model settings apply to action
  calls as well.
