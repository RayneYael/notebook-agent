# Agent 检索与回答两阶段收敛设计

## 1. Boundary

本轮修改限定在：

- `app/agent/runtime.py`：provider-independent retrieval gate、两阶段运行、结构化 composer、fallback、历史；
- `app/agent/services.py` / `app/retrieval/search.py`：有界候选 over-fetch 与按视频多样化；
- `app/agent/types.py`：内部 answer draft/section 类型（公开 `AgentAnswer`/`Citation` 兼容）；
- `app/diagnostics.py`：固定 phase/outcome 诊断字段；
- `app/config.py`、`.env.example`、`docs/deployment.md`：澄清 output limit 的 per-stage 语义；
- 对应 Agent、service、diagnostics、channel/persistence 测试。

不修改数据库 schema、embedding 维度/provider、字幕 chunking、公开 channel payload 或正式章节元数据。

## 2. End-to-end data flow

```text
trusted AgentRequest
  -> retrieval/action Agent
       -> sequential provider batch handling
       -> atomic one-backend-call-per-model-step reservation
       -> diversified tenant-scoped Citations
       -> terminal ActionOutcome (action path ends here)
  -> bounded evidence projection
  -> tool-free structured answer composer with fresh RunUsage
       -> valid AnswerDraft -> deterministic marker/source rendering
       -> invalid once -> answer-only retry against same allow-list
       -> invalid/timeout/limit -> deterministic evidence fallback
  -> AgentAnswer
  -> canonical user/final-answer history + public sources
```

The retrieval Agent's text output is a stop signal only. It is never returned to the user and never needs citation
validation. Relevance judgment moves to the composer, which sees bounded excerpts/titles/timestamps across candidates.

## 3. Runtime contracts

### 3.1 Fixed budgets

```python
NORMAL_RETRIEVAL_CALLS_LIMIT = 5
NORMAL_SEARCH_CALLS_LIMIT = 2
NORMAL_EXPANSION_CALLS_LIMIT = 3
MAX_SOURCE_ITEMS = 5
SEARCH_RESULT_LIMIT = 10
SEARCH_CANDIDATE_POOL_LIMIT = 50
ANSWER_REQUEST_LIMIT = 2
```

`AGENT_REQUEST_LIMIT`, `AGENT_TOOL_CALLS_LIMIT`, and `AGENT_OUTPUT_TOKEN_LIMIT` remain deployment safety settings.
Retrieval and composer runs each create their own `RunUsage`; the configured output-token value therefore applies
independently to each stage rather than being silently shared.

### 3.2 Atomic reservation

Conceptual internal contract:

```python
class RetrievalKind(Enum):
    SEARCH = "search"
    EXPANSION = "expansion"

class ReservationResult(Enum):
    EXECUTE = "execute"
    SAME_STEP_SKIPPED = "same_step_skipped"
    STAGE_BUDGET_EXHAUSTED = "stage_budget_exhausted"

@dataclass
class AgentDeps:
    retrieval_calls: int
    search_calls: int
    expansion_calls: int
    last_retrieval_run_step: int | None
    citations: dict[int, Citation]
    def reserve_retrieval(self, *, run_step: int, kind: RetrievalKind) -> ReservationResult: ...
```

`reserve_retrieval()` holds one lock while it checks the model step and all budgets, then increments counters only for
`EXECUTE`. Every Agent tool runs under `ToolManager.parallel_execution_mode("sequential")`; the provider may still
emit a batch, but only the first retrieval call for `ctx.run_step` reaches services.

Retrieval tools return a typed envelope:

```python
class RetrievalToolPayload(TypedDict):
    status: Literal["ok", "skipped"]
    evidence: list[dict]
    reason: Literal["same_model_step", "budget_exhausted"] | None
```

Skipped calls contain no Citation and are logged with `tool_outcome="skipped"`. They count as provider/Pydantic tool
proposals but not as backend retrieval attempts. `parallel_tool_calls=false` remains in model settings as an advisory.

### 3.3 Tool visibility

- Before any citation: `search_segments` visible while search budget remains.
- After citations: remaining search and expansion tools are visible according to stage budgets.
- After five executed retrievals or a stage budget is exhausted: corresponding tools are omitted.
- No fresh-search citation-repair state exists. Once the retrieval Agent stops, later repair happens only in composer.
- Save/confirmation tools remain visible under their existing rules and never consume retrieval budgets.

## 4. Candidate diversification

`KnowledgeServices.search_segments(query, limit=10)` clamps the public result count to 10. It requests an internal
pool of `min(50, max(20, limit * 5))` hits from each existing retrieval path, then:

1. merges exact duplicate `segment_id` hits using the current best-score behavior;
2. groups candidates by `item_id` and ranks each group by its strongest segment;
3. chooses at most five item groups;
4. emits the strongest segment from each selected group first;
5. fills remaining slots, in score order, with other distinct segments from selected groups.

This changes candidate diversity, not the embedding model or vector schema. It preserves tenant predicates in the
BM25/vector queries and hydration query. Distant segments from one selected video remain eligible; exact duplicates
collapse. Adjacent semantic merging remains an answer-selection concern because the public Citation has no chapter
boundary metadata.

`AgentDeps.citations` remains keyed by `segment_id`, so duplicate hits across two rewritten queries do not grow the
evidence set. Insertion order is preserved as the fallback relevance order.

## 5. Two-stage answer composition

### 5.1 Retrieval stage termination

The retrieval Agent no longer has an output validator. Its text is discarded. After it stops:

- terminal action outcome -> return canonical action result; do not compose;
- zero search calls -> existing `search_required` failure;
- no citations after successful searches -> `not_found/no_evidence`;
- citations exist -> project bounded evidence and invoke composer;
- retrieval `UsageLimitExceeded` with citations -> log phase/kind and invoke composer from existing trusted evidence;
- embedding/retrieval exception -> keep the existing distinct failure; do not fallback.

### 5.2 Composer schema

```python
class AnswerSection(BaseModel):
    text: str = Field(min_length=1)
    citation_ids: list[int] = Field(min_length=1)

class AnswerDraft(BaseModel):
    sections: list[AnswerSection] = Field(min_length=1, max_length=8)
```

The composer has no tools. It uses `PromptedOutput(AnswerDraft)`, placing the JSON schema in the prompt and parsing the
model's JSON text without creating an output tool or sending `tool_choice=required`. Its prompt contains the current
question plus bounded Citation fields only. The validator requires every ID to exist in the supplied allow-list and
the union of IDs to cover no more than five `item_id` values. One invalid output produces one composer-only retry that
includes allowed IDs but no new search instruction.

The renderer appends validated `[S<segment_id>]` markers to each section and then calls the existing video-level source
grouping. The model cannot supply titles, URLs or final source rows.

### 5.3 Independent usage and fallback

Composer uses a new `RunUsage` with:

```python
UsageLimits(
    request_limit=ANSWER_REQUEST_LIMIT,
    output_tokens_limit=settings.agent_output_token_limit,
)
```

It has no function-tool limit because no retrieval/action tools are exposed. Any composer timeout, provider error,
`UsageLimitExceeded`, or exhausted structured-output retry discards all drafts and returns:

```text
status = "ok"
error_code = None
text starts with "自动总结未完成，以下是知识库中最相关的证据："
citations = deterministic top-five video groups from trusted evidence
```

The fallback renders only title, real timestamp URL and bounded excerpt. It does not infer facts or chapter names.

## 6. Conversation and action compatibility

Knowledge answers persist a canonical two-message history built from the original user question and final rendered
answer. Retrieval tool calls/results, discarded retrieval text, composer schema retries and invalid drafts are omitted.
The conversation turn continues to store public sources separately. This preserves future conversational context
without replaying stale evidence or bloating the model history.

Action and pending-confirmation paths retain their canonical `ActionOutcome` and existing empty provider-message
history. If a provider batch mixes retrieval and a terminal action, local sequential execution preserves order and the
terminal action outcome wins; composer is never invoked after an action outcome.

## 7. Diagnostics and failure matrix

Add allow-listed `agent_phase=retrieval|answer`, `tool_outcome=skipped`, and an optional integer `http_status`.
`http_status` is emitted only when it is an actual integer from 100 through 599. Runtime catches
`ModelHTTPError` explicitly and passes `exc.status_code`; diagnostics remain the only serialization owner. Production
continues to omit questions, evidence, IDs, drafts, exception messages, `ModelHTTPError.body`, provider response bodies
and schemas. Explicit `development` diagnostics additionally serialize the complete exception message, provider model
and raw response body so a local 400 can be diagnosed. Authentication headers and API keys are never added explicitly.

| Condition | Result |
| --- | --- |
| search succeeds with zero evidence | `not_found/no_evidence` |
| retrieval provider request/tool/output limit with evidence | continue to composer; log retrieval phase limit |
| retrieval limit without evidence | stage-accurate `failed/limit` wording |
| embedding failure | `failed/embedding_unavailable` |
| database retrieval failure | `failed/retrieval_unavailable` |
| valid composer draft | `ok` with structured citations |
| first invalid composer draft | one answer-only retry, no retrieval |
| provider `ModelHTTPError` | always log phase/class/status; development also logs full message/model/body; preserve existing failed/fallback behavior |
| composer retry/timeout/provider/output limit exhausted | `ok` evidence fallback |
| action completes | canonical action result; no composer |

## 8. Validation and rollback

Automated validation must include real `RequestUsage` values, provider batches, service-level crowding, PostgreSQL
tenant integration, canonical history, action regressions, diagnostics privacy and the full suite. Deployment smoke
must repeat the original query and a multi-video/multi-chapter query with development retrieval logging temporarily
enabled, then restore production-safe logging.

Rollback can disable the composer and diversified candidate selection independently, but must never restore reliance
on provider-side `parallel_tool_calls=false` as the only enforcement or expose unvalidated drafts. Existing hard limits
and tenant predicates remain installed throughout rollback.
