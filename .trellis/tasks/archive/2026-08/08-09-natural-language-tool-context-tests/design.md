# Design: Real-model natural-language tool and context evaluation

## 1. Architecture and boundary

The evaluator is an opt-in developer tool, not part of normal offline pytest and not a production endpoint.

```text
catalog + eval config
        |
        v
live-eval runner ---- readiness probes ---- existing full local stack
        |                                      |
        | official MCP v2 client               | PostgreSQL/pgvector
        v                                      | Redis + Celery
full-scope stdio MCP subprocess                | MinIO
        |                                      | connector + embedding
        v                                      v
McpToolFacade -> ChannelService -> real KnowledgeAgent -> real tools
        |
        +---- safe runtime diagnostics (stderr JSONL) -> correlated tool trace
        +---- typed MCP responses --------------------> assertions/report
```

The runner starts a stdio MCP subprocess with an in-memory raw bearer issued for the configured evaluation user. It uses the official MCP client for `initialize`, `tools/list`, and calls. The subprocess inherits the existing full-stack and provider configuration. A successful preflight requires exactly the ten full-scope public MCP tools and real worker/object-store/broker readiness.

Notebook Agent model-routing cases enter through `ask_notebook_agent`. Direct MCP management calls used for fixture setup are recorded separately as `setup` or `deterministic` activity and never count as model-routing coverage. Likewise, the bare-URL server pre-route is not counted as a model tool choice.

## 2. Files and responsibilities

Proposed structure:

```text
evals/
└── natural_language/
    ├── __init__.py
    ├── __main__.py          # command entry point
    ├── catalog.yaml         # reviewed natural-language scenarios
    ├── schema.py            # catalog and report models
    ├── runner.py            # orchestration, repeats, assertions
    ├── mcp_runtime.py       # grant/subprocess/client lifecycle and trace capture
    ├── fixtures.py          # persistent eval-user fixture discovery/provisioning
    └── README.md            # setup, safety, execution and interpretation
```

Generated reports go to a gitignored operator-selected directory, defaulting to `.eval-results/natural-language/<run-id>/`. No API keys or raw tokens are serialized.

Small offline tests may validate evaluator-owned parsing/assertion code, but they are support tests only and do not count toward the task's real-model acceptance. Existing Agent contract tests are not duplicated.

## 3. Configuration contract

The runner reuses application settings for model and infrastructure. Evaluation-only inputs are separate and explicit:

```text
NATURAL_LANGUAGE_EVAL_ENABLED=true
NATURAL_LANGUAGE_EVAL_USER_ID=<dedicated non-production AppUser id>
NATURAL_LANGUAGE_EVAL_CATALOG=<optional path override>
NATURAL_LANGUAGE_EVAL_RESULTS_DIR=<optional output directory>
NATURAL_LANGUAGE_EVAL_REPEAT=1
NATURAL_LANGUAGE_EVAL_INGEST_TIMEOUT_SECONDS=<bounded positive value>
```

`AGENT_MODEL`, `AGENT_API_KEY`, `AGENT_BASE_URL`, database, embedding, Redis, MinIO and Celery settings remain authoritative. The runner refuses obvious production environments and requires the operator to explicitly enable evaluation. It verifies the configured user exists and is active, then issues a short-lived full grant labeled with the run ID. The raw token remains only in runner/subprocess memory and the grant is revoked in `finally`; persistent evaluation data is retained.

## 4. Catalog contract

The YAML catalog has a version and named fixtures. Each scenario contains:

```yaml
id: context.pending-unrelated-question
category: context
description: Pending save must survive an unrelated knowledge question.
requires: [ready_item, full_management]
repeat: default
turns:
  - input: "{new_video_url}"
    route: deterministic
    expect:
      error_code: save_confirmation_required
  - input: "我的知识库里谁讲过 {known_topic}？"
    route: model
    expect:
      required_tools: [search_segments]
      forbidden_tools: [confirm_video_save, cancel_video_save]
  - input: "需要，保存吧"
    route: model
    expect:
      required_tools: [confirm_video_save]
```

Supported expectations include required/allowed/forbidden tool names, acceptable status/error codes, citation presence/absence, source scope, response-safe substring/regex checks, and context relations. Template values can come only from catalog fixtures or typed outputs of earlier turns. Confirmation codes, cursors and IDs are captured from server-owned results rather than fabricated.

The catalog loader validates unique IDs, valid tool names, valid template dependencies, ordered turns and coverage tags before any paid model call.

## 5. Persistent fixture strategy

The dedicated evaluation user is stable across runs and owns all retained data.

- A small catalog-defined baseline contains at least two publicly accessible videos with known, distinct topics and one mutable video for delete/restore sequences.
- Preflight lists the evaluation user's inventory. Missing baseline URLs are submitted through the real full MCP tool and polled through real inventory/detail projections until PostgreSQL reaches a searchable terminal state or a bounded deadline expires.
- Ready items are reused on later runs, avoiding unnecessary downloads and embeddings while retaining a genuine first-provision ingestion proof in the run that creates them.
- Save-routing scenarios may use an already known URL; their purpose is to prove the real model selects `save_videos`. The report distinguishes `queued`, `already_exists`, and restored outcomes.
- Delete and restore run as one explicit scenario so the retained item ends in a reusable library state. This is scenario behavior, not an evaluator rollback.
- Retry requires a catalog fixture that is genuinely in an allowed failed state. If the fixture cannot be established through the real stack, the case fails as `fixture_unavailable`, rather than modifying database state directly.
- Every conversation ID and management marker includes a run-scoped opaque suffix. Historical rows are retained but do not enter a new run's context.

## 6. Tool-trace collection

Runtime diagnostics already emit allow-listed JSON events with `request_id`, `tool_name`, `call_index`, outcome and phase, without tool arguments/results. The stdio server writes diagnostics to stderr while stdout remains MCP protocol-only.

The runner captures stderr JSONL, accepts only known diagnostic fields, and indexes events by the `request_id` returned in `AskNotebookAgentOutput`. Started/succeeded/skipped/failed events for the same `(request_id, call_index, tool_name)` become one trace record. Unknown or malformed lines are retained only as bounded diagnostic counters, never copied wholesale into the report.

For each model turn the report proves at least one `model_attempt` event and records the configured model identifier. Missing model-attempt or uncorrelated trace events fail the case; they cannot silently become a pass.

## 7. Context execution

- Same-conversation turns reuse the same MCP `conversation_id` and are sent sequentially.
- Isolation scenarios use distinct run-scoped conversation IDs under the same evaluation grant/user.
- Restart recovery stops and recreates only the MCP/Agent subprocess, preserving the same grant and conversation ID; PostgreSQL remains running. The follow-up must use restored canonical model history.
- Pending save/delete scenarios use the real durable pending tables. Unrelated turns are executed before confirmation to prove the model does not consume the pending action.
- Slash commands are excluded because MCP deliberately rejects them before the planner; testing `/new` would not measure real-model routing.

## 8. Scoring and exit behavior

- Infrastructure/setup failures are reported separately and terminate affected cases without scoring them as model failures.
- A single invocation passes only when all required tools appear, no forbidden tool appears, every actual tool is allowed, and response/status constraints hold.
- Forbidden destructive or cross-tenant behavior is zero-tolerance across repeats.
- The CLI defaults to one repeat for smoke. `--repeat N` retains each attempt and computes a pass rate; a catalog or CLI threshold controls the aggregate result.
- The command exits non-zero for preflight failure, fixture failure, privacy/safety violation, or an aggregate case below threshold. Skips require an explicit catalog capability condition and are visible in the summary.

## 9. Reporting and privacy

Write both `report.json` and a concise `report.md` containing run metadata, sanitized readiness, model ID, case/turn results, tool traces, timing and coverage. Do not store bearer tokens, provider keys, tenant IDs, storage keys, tool arguments/results, transcript excerpts, raw diagnostics or unrelated inventory rows.

The runner prints the result directory and compact summary. Detailed provider bodies remain governed by existing diagnostics settings and are not copied into evaluation artifacts.

## 10. Compatibility and rollback

This feature adds an opt-in evaluator and does not change public tool schemas or production behavior. Removing `evals/natural_language/` and its documentation disables it. No database migration is planned.

Evaluation data is intentionally retained. Operational cleanup, if later desired, must be a separately authorized user/grant lifecycle action; the runner never bulk-deletes retained knowledge or storage objects.

## 11. Risks and mitigations

- **Cost and latency:** selection, category filters, repeats and baseline reuse keep paid calls bounded.
- **External video drift:** catalog fixtures are explicit and preflight reports terminal ingestion failures separately.
- **Model nondeterminism:** retain each repeat; use constraint-based assertions rather than exact prose/tool-count matching.
- **Trace misattribution:** run model turns sequentially and correlate by response request ID.
- **Persistent-state contamination:** use a dedicated user plus run-scoped conversations; discover fixtures by normalized URL, not list position.
- **Accidental production use:** require an explicit enable flag, dedicated user ID and non-production configuration checks.
