# Implementation plan: exact video reference and session routing

## 1. Add deterministic current-message reference parsing

- Add a shared helper for ordered URL extraction, supported-reference
  normalization, unique retrieval scope, and bare-message classification.
- Reuse the helper in action input matching so punctuation and canonical URL
  equivalence retain one definition.
- Unit-test short/canonical YouTube URLs, punctuation, semantic remainder,
  batches, duplicates, invalid URLs, and unsupported hosts.

## 2. Make bare supported URLs deterministic

- Pre-route bare supported URL batches through the existing
  `AgentActionRuntime.request_confirmation()` outcome path.
- Preserve disabled/unavailable and durable pending-action behavior.
- Assert zero model requests and history-independent results.

## 3. Enforce exact reference scope on retrieval

- Carry the normalized reference set in request-scoped Agent dependencies and
  the production knowledge service.
- Add optional exact-reference predicates to vector and lexical retrieval.
- Repeat the scope in hydration, neighbor, item-detail, and open-at reads.
- Filter or reject out-of-scope service results before they become trusted
  planner evidence or Composer citations.
- Hide management tools whenever the current message has an explicit supported
  URL while retaining save/pending tools.

## 4. Add regression and integration coverage

- Reproduce the logged A/B mismatch with one saved item and a different URL.
- Cover ready, absent, deleted, pending, and failed exact references.
- Cover history containing a prior video summary, inventory listing, and delete
  outcome without allowing cross-video evidence or inventory misrouting.
- Cover malicious/stale model calls to out-of-scope item and segment IDs.
- Preserve free-text hybrid retrieval, management pagination, pending actions,
  tenant isolation, and duplicate delivery tests.

## 5. Validate and review

Run focused checks first:

```text
pytest -q tests/test_ingest_submission.py tests/test_agent_actions.py
pytest -q tests/test_knowledge_services.py tests/test_agent_runtime.py
pytest -q tests/test_multiuser_integration.py tests/test_item_management_tools.py
```

Then run:

```text
python -m compileall -q app tests
pytest -q
git diff --check
```

The check pass must inspect the full task diff, confirm no unrelated dirty files
were included, and verify that exact-reference enforcement is server-owned
rather than prompt-only.

## Rollback points

- After step 1: parser-only changes must not alter runtime behavior.
- After step 2: bare URL behavior can be reverted independently of retrieval
  scope.
- After step 3: no persistent migration exists; reverting code restores the
  prior behavior without data rollback.
