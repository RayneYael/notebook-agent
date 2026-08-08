# Agent Retrieval Convergence and Multi-Source Answers

## 1. Scope / Trigger

Use this contract when changing PydanticAI knowledge tools, retrieval budgets,
candidate selection, citations, source rendering, Agent usage limits, or the
knowledge-answer persistence path. It applies only to tenant-scoped knowledge
answers. Video save and confirmation actions retain their existing terminal
`ActionOutcome` behavior and do not consume retrieval budget.

The runtime has two distinct model stages:

```text
trusted request -> retrieval/action planner -> trusted Citation cache
                -> tool-free answer composer -> validated answer
                -> deterministic evidence fallback on composer failure
```

The planner's text is only a stop signal. It is never a user-visible answer,
is never citation-validated, and is never persisted.

## 2. Signatures

```python
NORMAL_RETRIEVAL_CALLS_LIMIT = 5
NORMAL_SEARCH_CALLS_LIMIT = 2
NORMAL_EXPANSION_CALLS_LIMIT = 3
MAX_SOURCE_ITEMS = 5
SEARCH_RESULT_LIMIT = 10
SEARCH_CANDIDATE_POOL_LIMIT = 50
ANSWER_REQUEST_LIMIT = 2
COMPRESSED_EVIDENCE_LIMIT = 8
COMPOSER_EVIDENCE_EXCERPT_CHARS = 360
COMPRESSED_EVIDENCE_EXCERPT_CHARS = 180

class AgentDeps:
    citations: dict[int, Citation]       # keyed by segment_id, insertion order
    last_retrieval_run_step: int | None
    def reserve_retrieval(
        self, *, run_step: int, kind: RetrievalKind
    ) -> ReservationResult: ...

class RetrievalToolPayload(TypedDict):
    status: Literal["ok", "skipped"]
    evidence: list[dict]
    reason: Literal["same_model_step", "budget_exhausted"] | None

class AnswerSection(BaseModel):
    text: str
    citation_ids: list[int]

class AnswerDraft(BaseModel):
    sections: list[AnswerSection]

class ComposerDeps:
    citations: dict[int, Citation]       # prompt rows and validator allow-list
    excerpt_chars: int
```

`AGENT_REQUEST_LIMIT`, `AGENT_TOOL_CALLS_LIMIT`, and
`AGENT_OUTPUT_TOKEN_LIMIT` remain deployment safety limits. Retrieval and
composer each receive a new `RunUsage`; the configured output-token limit is
therefore per stage, not a cumulative allowance shared by planning and answer
generation.

`AGENT_COMPOSER_MAX_TOKENS` defaults to 1000 and is the real provider-side cap
for each Composer request. It must be positive, and multiplied by
`ANSWER_REQUEST_LIMIT` it must not exceed `AGENT_OUTPUT_TOKEN_LIMIT`. A full
attempt and its optional compressed attempt each receive fresh `RunUsage`, but
both remain inside one answer-stage wall-clock timeout. Because each attempt
may perform one structured-output repair, the optional two-attempt workflow can
make at most four provider requests (4000 capped output tokens at the default).

## 3. Contracts

- Every provider request includes `parallel_tool_calls=False`, but this is an
  advisory provider hint, never a correctness boundary.
- The retrieval Agent uses local sequential tool execution. Before a retrieval
  tool reaches a service, `AgentDeps.reserve_retrieval()` holds one lock and
  atomically checks the current `run_step`, total 5-call budget, search 2-call
  budget, and expansion 3-call budget. Only its first successful reservation
  in a model step invokes a backend service.
- Other retrieval calls in the same provider batch return a typed
  `skipped/same_model_step` payload. Calls after a exhausted stage budget
  return `skipped/budget_exhausted`. Neither kind performs embedding, SQL, or
  storage work, records a Citation, or pretends that a search found no hits.
- `search_segments` is public-limit bounded to 10. It obtains a bounded
  over-fetch pool (`min(50, max(20, limit * 5))`) from each hybrid retrieval
  backend, removes exact duplicate segment IDs using the best score, ranks
  item groups by their best hit, chooses at most five items, emits one best
  representative for each, then fills remaining slots by score with distinct
  segments from those selected items. All database hydration remains tenant
  scoped.
- The planner must call `search_segments` before a knowledge answer may exist.
  Zero trusted citations after search returns `not_found/no_evidence` and does
  not invoke composer. Embedding and retrieval failures remain
  `embedding_unavailable` and `retrieval_unavailable` rather than evidence
  fallback.
- Planner usage-limit or timeout failures with trusted citations continue to
  answer composition. Without citations they use phase-accurate failed-limit
  or timeout behavior. The raw hard limits remain defense in depth; increasing
  them is not a convergence fix.
- The composer has no retrieval or action tools. It receives only the user
  question and bounded Citation title, excerpt, timestamp, and segment-ID
  allow-list. It uses `PromptedOutput(AnswerDraft)` to parse schema-prompted
  JSON text without an output tool or `tool_choice=required`. `AnswerDraft`
  validation requires every cited ID to be allowed, every section to cite
  evidence, and at most five distinct cited item IDs. PydanticAI performs at
  most one output retry, against the same allow-list; it never starts a fresh
  search.
- Every Composer request sends `AGENT_COMPOSER_MAX_TOKENS` as the provider's
  actual `max_tokens` generation cap. For DeepSeek Chat Completions, the model
  profile must retain DeepSeek response/tool semantics, map the field to
  `max_tokens` rather than `max_completion_tokens`, and send
  `thinking: {"type": "disabled"}` without `reasoning_effort=none`.
  Other compatible Composer models request provider-neutral `thinking=False`
  when supported. Retrieval model settings remain unchanged.
- If a full Composer attempt exceeds its output-token usage limit, or captured
  response messages prove provider truncation with `finish_reason=length`, the
  server may retry exactly once with a local deterministic evidence view. The
  view selects at most eight segments, gives each retained item one segment
  before filling in retrieval order, and truncates prompt excerpts to 180
  characters. The compressed prompt rows are also its entire citation
  allow-list. Ordinary invalid citations, provider failures, and timeouts do
  not trigger compression; already compact evidence skips a useless retry.
- The application appends `[S<segment_id>]` markers after validating the
  structured draft, and source rendering owns titles and real URLs. Sources
  are grouped once per item in retrieval order, retain distinct timestamp
  evidence under the item, and never infer chapter titles.
- Composer retry exhaustion, timeout, provider failure, or a terminal
  usage-limit failure after the optional compressed attempt discards every
  draft and returns `status=ok` evidence fallback. The
  fallback begins with `自动总结未完成，以下是知识库中最相关的证据：` and contains only
  real grouped sources, timestamp links, and bounded excerpts.
- Knowledge success and fallback persist only normalized user question plus
  final visible answer, while the conversation turn keeps public Citation
  sources. Tool payloads, planner text, composer retry prompts, and invalid
  drafts are never persisted.
- Diagnostics use only fixed safe fields. Retrieval events carry
  `agent_phase=retrieval`; composer events carry `agent_phase=answer`.
  `context_compressed` records only before/after counts, retry count, and a
  fixed limit classification; a recovered full attempt is not terminal
  `agent_failed`.
  `tool_outcome=skipped` is allowed. `ModelHTTPError` additionally projects
  its validated integer `http_status`. Production forbids its body and message;
  explicit development records its complete message/model/body for diagnosis.
  Production logs never include questions, tool arguments/results, excerpts,
  IDs, drafts, URLs, or exception messages.

## 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| provider emits several retrieval calls in one response | exactly one backend retrieval runs; remaining calls are typed skipped results |
| normal search/expansion budgets are exhausted | no further backend retrieval; planner can stop and existing evidence composes |
| successful searches have no evidence | `not_found/no_evidence`, no composer and no limit wording |
| planner timeout or usage limit after evidence | log retrieval phase/kind and compose from existing Citations |
| planner timeout or usage limit without evidence | fail closed with phase-accurate wording |
| answer draft has unknown IDs or six item IDs | one answer-only retry using the original allow-list |
| full answer output-token limit or captured `finish_reason=length` | one compressed attempt when the evidence view is smaller |
| compressed answer succeeds | validate only compressed IDs, render normal `ok` answer, no terminal failure diagnostic |
| answer retry, timeout, provider error, or compressed attempt fails | `ok` deterministic fallback from original evidence, no draft persistence |
| provider HTTP request fails | preserve phase behavior; production logs safe status/class, development also logs full error details |
| valid answer draft | server-rendered markers and grouped real sources, at most five items |
| action succeeds, including a mixed tool batch | canonical action result wins and composer does not run |
| embedding/database failure | `failed/embedding_unavailable` or `failed/retrieval_unavailable`, never fallback |

## 5. Good / Base / Bad Cases

- Good: a provider ignores its parallel-tool-call hint and emits two searches;
  the first executes, the second gets `same_model_step`, and a later
  composer generates a validated structured answer using only the cached
  source IDs.
- Good: one video dominates raw segment scores but bounded over-fetch exposes
  five relevant item groups. The answer shows one top-level row per video and
  preserves two distant links for the selected first video.
- Base: one search provides sufficient evidence. The planner stops, the
  composer uses a fresh output-token budget, and canonical history contains
  only the normalized question and final answer.
- Bad: rely on `parallel_tool_calls=False` alone, treat skipped tools as zero
  results, rerun search to fix citation formatting, return a raw planner
  draft, fabricate chapter names, or log private evidence/exception text.

## 6. Tests Required

- A batched `FunctionModel` returns two searches, then two neighbor calls and
  one metadata call with non-zero `RequestUsage.output_tokens` totaling 2066.
  Assert one backend retrieval per model step, typed skipped payloads, no
  extra embedding/SQL work, and a successful composer run with a fresh budget.
- Cover normal 5/2/3 convergence, zero-hit exit, hard request/tool limits,
  phase-correct output-token diagnostics, and retrieval embedding/database
  failures.
- Cover valid composer answers, unknown-ID repair, over-five-item repair,
  second invalid draft fallback, timeout fallback, provider-error fallback,
  provider-cap request serialization, output-token compression recovery,
  captured-length recovery, compressed allow-list enforcement, shared timeout,
  no-op compression, and second-limit fallback. Assert no repair starts
  retrieval and no invalid model content reaches history.
- Cover hybrid duplicate collapse, one-item crowding, six-item selection,
  distant same-item segments, public limit clamping, bounded candidate pool,
  and PostgreSQL tenant predicates during hydration.
- Re-run action/pending-confirmation, persistence, duplicate message,
  multi-user tenant isolation, source grouping, diagnostics privacy, and the
  complete test suite.

## 7. Wrong vs Correct

#### Wrong

```python
# A provider can ignore this preference and execute an entire batch.
result = await planner.run(..., model_settings={"parallel_tool_calls": False})

# Formatting failure wastes an embedding request and loses the original budget.
if invalid_citation:
    return await planner.run(question_again)
```

#### Correct

```python
with planner.parallel_tool_call_execution_mode("sequential"):
    await planner.run(...)

# The locked reservation decides whether a retrieval backend may run.
if deps.reserve_retrieval(run_step=ctx.run_step, kind=kind) is not EXECUTE:
    return {"status": "skipped", "evidence": [], "reason": "same_model_step"}

# A fresh, tool-free composer may retry only against trusted cached evidence.
answer = await composer.run(question, deps=ComposerDeps(allowed_citations))
```
