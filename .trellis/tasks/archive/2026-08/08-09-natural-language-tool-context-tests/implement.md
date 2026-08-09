# Implementation Plan

## 1. Evaluator contracts and catalog

- [x] Add typed catalog/report models and strict YAML loading under `evals/natural_language/`.
- [x] Define canonical Agent tool allow-list and distinguish `model`, `deterministic`, and `setup` routes.
- [x] Convert the reviewed Chinese natural-language corpus into versioned single- and multi-turn cases.
- [x] Add catalog validation for IDs, tools, templates, turn dependencies and required category coverage.

Validation:

```bash
.venv/bin/python -m evals.natural_language --validate-catalog
```

## 2. Full-stack preflight and secure grant lifecycle

- [x] Load existing application/provider settings without printing secrets.
- [x] Require the explicit live-eval enable flag and configured dedicated evaluation user.
- [x] Probe database, broker, MinIO, worker queues, migration/readiness and provider/embedding configuration.
- [x] Issue one run-scoped short-lived full grant, start a real stdio MCP subprocess, and verify official client `initialize -> tools/list` returns all ten tools.
- [x] Revoke only the run-scoped grant in `finally`; preserve evaluation user and data.

Validation:

```bash
.venv/bin/python -m evals.natural_language --preflight
```

Rollback point: no catalog model calls occur before preflight succeeds.

## 3. Persistent real-data fixtures

- [x] Add explicit public baseline video fixture definitions and normalized URL lookup.
- [x] Submit missing items through real MCP full tools and poll typed inventory/detail state to a bounded deadline.
- [x] Verify at least one provisioned item traverses real ingestion, embedding, object storage and becomes searchable.
- [x] Implement reusable mutable-item selection for delete/restore and a genuine failed-item prerequisite for retry.
- [x] Keep all fixture operations tenant scoped and refuse manual DB state fabrication.

Validation:

```bash
.venv/bin/python -m evals.natural_language --prepare-fixtures
.venv/bin/python -m app.cli search --user-id "$NATURAL_LANGUAGE_EVAL_USER_ID" "<fixture topic>"
```

Rollback point: fixture failure stops dependent cases and leaves already-created evaluation data intact.

## 4. MCP runner and safe trace collector

- [x] Implement official MCP client calls over the subprocess's protocol-clean stdio.
- [x] Capture and validate stderr diagnostic JSON without copying unknown/raw lines into reports.
- [x] Correlate `AskNotebookAgentOutput.request_id` to real `model_attempt` and `tool_call` events.
- [x] Normalize tool lifecycle events into per-turn traces and distinguish model calls from pre-routing/setup activity.
- [x] Support subprocess restart while retaining grant and conversation ID for recovery scenarios.

Validation:

```bash
.venv/bin/python -m evals.natural_language --case retrieval.search --repeat 1
```

## 5. Assertions, multi-turn execution and scoring

- [x] Implement required/allowed/forbidden tool assertions plus status, error, citation and bounded response checks.
- [x] Resolve typed outputs from earlier turns into later templates for IDs, cursors and confirmation codes.
- [x] Execute same-conversation, isolated-conversation, pending-action and restart-recovery scenarios sequentially.
- [x] Add repeat/threshold aggregation with zero tolerance for forbidden destructive or cross-tenant behavior.
- [x] Separate infrastructure, fixture, model-routing, response and privacy failures in exit status/reporting.

Validation:

```bash
.venv/bin/python -m evals.natural_language --category context --repeat 1
.venv/bin/python -m evals.natural_language --all --repeat 3
```

## 6. Reports, docs and focused support tests

- [x] Write sanitized JSON and Markdown reports to the configured gitignored results directory.
- [x] Add compact terminal summaries and coverage by tool/category.
- [x] Document environment setup, safety boundary, costs, fixture retention, commands, case authoring and failure interpretation.
- [x] Add focused offline support tests only for evaluator schema, template resolution, trace correlation, scoring and redaction; do not duplicate Agent business-contract tests.
- [x] Update `.gitignore` for generated evaluation artifacts if required.

Validation:

```bash
.venv/bin/pytest -q
.venv/bin/python -m evals.natural_language --validate-catalog
```

## 7. Final live verification

- [x] Run full preflight against the existing local full stack.
- [x] Run a one-repeat smoke set covering retrieval, one write route, inventory follow-up, pending unrelated question and restart recovery.
- [ ] Run the complete catalog with the agreed repeat count and retain the sanitized report path.
- [x] Confirm all created knowledge/context data remains under the dedicated evaluation user and only the temporary grant was revoked.
- [x] Review runtime/eval artifacts for token, key, tenant, storage-key and unrelated-content leakage.

Live verification (2026-08-09): preflight passed against the complete reused
stack and the authorized one-repeat smoke completed with `6 pass / 0 fail /
0 skip`. The sanitized report is retained at
`.eval-results/natural-language/20260809T090608Z-d9ab2235`. All three baseline
fixtures were reused for the dedicated evaluation user; the fixture proof covered
PostgreSQL, pgvector embeddings, MinIO, ingestion dispatches and completion
events, and the run-owned grant was revoked. The full 22-case paid run remains
an explicit operator command because only the smoke spend was authorized.

Final commands:

```bash
.venv/bin/python -m evals.natural_language --smoke --repeat 1
.venv/bin/python -m evals.natural_language --all --repeat 3
.venv/bin/pytest -q
```

## Risky files and review gates

- `app/diagnostics.py`: avoid production diagnostic schema changes unless trace correlation proves impossible through existing fields.
- `app/mcp_server.py`: do not change public MCP schemas or readiness semantics for evaluator convenience.
- `app/agent/runtime.py`: do not weaken tool visibility, confirmation or evidence rules to improve scores.
- Grant/user lifecycle: never revoke or mutate grants not created by the current run.
- Persistent fixtures: never bulk-delete or reset the dedicated user's retained data.

Before implementation start, confirm `prd.md`, `design.md` and this plan are approved and the context manifests contain the relevant backend specs.
