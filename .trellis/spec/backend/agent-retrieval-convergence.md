# Agent Retrieval Convergence and Multi-Source Answers

## Scenario: bounded retrieval with ranked video-level source groups

### 1. Scope / Trigger

Use this contract whenever changing the PydanticAI knowledge tools, their per-run visibility, citation validation,
multi-source answer rendering, or the Agent request/tool usage limits. It prevents a model from repeatedly searching
and expanding every candidate until the framework hard limit becomes the normal user-visible stop condition.

The contract covers tenant-scoped knowledge retrieval only. Video save/confirmation action tools do not consume the
retrieval budget and remain governed by their own terminal action outcome.

### 2. Signatures

Runtime constants:

```python
NORMAL_RETRIEVAL_CALLS_LIMIT = 5
NORMAL_SEARCH_CALLS_LIMIT = 2
NORMAL_EXPANSION_CALLS_LIMIT = 3
MAX_SOURCE_ITEMS = 5
```

Per-run state:

```python
class AgentDeps:
    search_calls: int
    retrieval_calls: int
    expansion_calls: int
    citations: dict[int, Citation]       # keyed by segment_id
    citation_repair_search_calls: int | None
```

Provider request setting and deployment limits:

```python
{"parallel_tool_calls": False}

AGENT_REQUEST_LIMIT=8
AGENT_TOOL_CALLS_LIMIT=10
```

Source output shape remains `AgentAnswer.text` plus `AgentAnswer.citations`. One top-level source row represents one
`Citation.item_id`; distinct cited segment timestamps remain nested beneath that row.

### 3. Contracts

- Every model request sets `parallel_tool_calls=False`; one model step cannot fan out several retrieval calls.
- Normal retrieval permits at most five calls total: at most two `search_segments` calls and at most three calls among
  `get_neighbors`, `get_item`, and `open_at`.
- Expansion tools are hidden until at least one trusted Citation exists. Search/expansion tools are dynamically omitted
  when either their stage budget or the total budget is exhausted.
- The model may stop before consuming the budget. Evidence sufficiency, not budget exhaustion, is the preferred normal
  stop condition.
- Once normal retrieval is unavailable, instructions require an answer from existing evidence or the stable
  no-evidence result; the model must not use its memory to fill gaps.
- A citation mismatch snapshots `search_calls` and exposes only one fresh `search_segments`. After that search, all
  retrieval tools are hidden again. A repaired draft may cite only IDs returned by the fresh search.
- A draft may cite at most five distinct `item_id` values. More than five follows the same single fresh-search repair
  path and must return a Top-5 draft.
- Source rendering preserves citation/retrieval order as the available relevance signal. It groups by `item_id`, emits
  each video once, and keeps every distinct cited timestamp beneath it. It never invents chapter titles because the
  public Citation contract does not contain one.
- Exact duplicate segment IDs collapse at evidence recording. Distinct segment IDs—including distant chapters in the
  same video—remain independently citable.
- Raw `UsageLimits` remain installed as defense in depth. Raising the hard tool limit is not a convergence fix.
- Query text, excerpts, URLs, model output, and retrieval scores must continue to follow the active diagnostics privacy
  policy; convergence logic must not add a new logging path.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| evidence is sufficient before budget exhaustion | model returns a valid cited answer immediately |
| two normal searches used, citations exist | search hidden; remaining expansion budget may still be used |
| three expansions used, a normal search remains | expansion tools hidden; remaining search may still be used |
| total five normal retrieval calls used | all retrieval tools hidden; answer or stable no-evidence result |
| retrieval succeeds with no citations | `not_found/no_evidence`, never `limit` |
| draft contains an unknown/missing citation | discard draft; expose only one fresh search |
| draft cites more than five videos | discard draft; request a grouped Top-5 answer through the repair path |
| repaired draft still invalid | `failed/answer_unavailable`; invalid draft is not persisted |
| request/tool/token hard limit still fires | fail closed with stable `limit` diagnostics and no untrusted draft |
| action tool completes | canonical action outcome wins; retrieval/citation repair does not run |

### 5. Good / Base / Bad Cases

- Good: two searches find evidence across several videos, the model selectively expands only ambiguous candidates,
  cites at most five videos, and the renderer groups distant timestamps under their owning video.
- Base: one search returns enough evidence for a simple definition; the model answers on the next request without using
  the remaining budget.
- Bad: enable parallel tool calls, expand every search hit, increase `AGENT_TOOL_CALLS_LIMIT`, flatten each segment into
  a separate video row, drop distant timestamps during item grouping, or invent chapter labels from transcript text.

### 6. Tests Required

- A looping `FunctionModel` keeps calling visible tools; assert at most five normal retrieval calls, two searches, three
  expansions, `parallel_tool_calls is False`, and no retrieval tools on the final request.
- A zero-hit looping model performs at most the search budget and returns `not_found/no_evidence` rather than `limit`.
- Exhaust the normal budget, emit a bad citation, verify only one repair search is visible, then accept a valid final
  answer within eight model requests.
- Cite six distinct videos, verify the draft is rejected, then return five and assert only those five item IDs survive.
- Render two distant segments from one item plus at least five other items; assert the video appears once, both timestamp
  links remain, the sixth video is omitted, and no chapter label is invented.
- Run action/pending-confirmation regressions to prove retrieval preparation does not hide action tools.
- Run the complete suite because Citation equality, persistence, channel rendering, diagnostics, and tenant isolation
  share these contracts.

### 7. Wrong vs Correct

#### Wrong

```python
# The model can emit a batch that jumps from 8 to 12 projected calls.
result = await agent.run(..., model_settings=None)

# Grouping accidentally keeps only one chapter from each video.
sources = {citation.item_id: citation for citation in citations}
```

#### Correct

```python
result = await agent.run(
    ...,
    model_settings=lambda _ctx: {"parallel_tool_calls": False},
)

groups: dict[int, list[Citation]] = {}
for citation in citations:
    groups.setdefault(citation.item_id, []).append(citation)
```

The tool `prepare` callbacks, not prompt wording alone, own the deterministic stop boundary. Prompt instructions explain
how to use the available budget; dynamic tool omission enforces it.
