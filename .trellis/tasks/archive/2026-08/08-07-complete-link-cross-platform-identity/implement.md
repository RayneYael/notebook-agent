# Implementation plan

## 1. Domain contract and command routing

- [x] Add the explicit Telegram/WeChat link allow-list and token-shape classification.
- [x] Add typed link outcomes/errors with stable user-facing messages.
- [x] Replace the bound-vs-unbound branch in `ChannelService._handle_link()` with deterministic generate/consume routing; keep it before registration and Agent execution.
- [x] Test unsupported/current channel, malformed argument, valid generation, token consumption by fresh and already-registered targets, and no conversation/model side effects.

## 2. Transactional tenant merge

- [x] Implement a dedicated merge operation that locks token/users/identity/content/dispatch rows in deterministic order.
- [x] Preserve the source `AppUser`; move target identities, threads, tokens and non-duplicate content; delete the empty target user.
- [x] Implement same-user idempotent success, disabled-user failures, replay protection, channel mismatch and atomic rollback on conflicts.
- [x] Reconcile duplicate content using the confirmed metadata and survivor rules; retire non-running loser dispatches before deletion.
- [x] Return `merge_busy` without consuming the token when running ingestion makes ownership unsafe.

## 3. Worker and concurrency hardening

- [x] Make missing/retired queued dispatch delivery a clean duplicate result with no tenant write.
- [x] Add PostgreSQL tests for concurrent token consumption, registration-vs-consumption, and retry after a running dispatch completes.
- [x] Assert every failed/racing path leaves identity, token, content, thread, pending action, segment and dispatch ownership consistent.

## 4. Cross-channel behavior and documentation

- [x] Add ChannelService tests proving `/whoami`, retrieval/save tenant sharing, isolation from a third user, and separate Telegram/WeChat histories after merge.
- [x] Extend bridge/gateway tests for the normalized Telegram and WeChat `/link` payloads without storing sensitive values.
- [x] Perform the real Telegram-to-WeChat and reverse link smoke manually; no script is retained.
- [x] Update README/deployment text for supported channels, registered-target merge, TTL, replay, busy retry and irreversible merge behavior.

## 5. Validation gates

- [x] Run focused identity, channel, ingestion, gateway and bridge tests.
- [x] Run PostgreSQL migration round-trip and concurrency/integration tests against the configured test database.
- [x] Run the complete pytest suite and compile checks (`191 passed, 8 skipped`; skipped LangBot wheel checks are out of scope).
- [x] Perform real Telegram and WeChat smoke in both directions; verify matching `/whoami`, shared knowledge and separate conversation context.
- [x] Scan logs/test artifacts for raw codes, message text, external identities and content notes.

## Suggested commands

```bash
.venv/bin/pytest -q tests/test_multiuser_integration.py tests/test_ingest_submission_postgres.py
.venv/bin/pytest -q tests/test_http_gateway.py tests/test_langbot_bridge_plugin.py tests/test_channel_supervisor.py
.venv/bin/pytest -q tests/test_migration_roundtrip_postgres.py
.venv/bin/pytest -q
.venv/bin/python -m compileall -q app integrations/langbot_kb_plugin
```

## Risk and rollback points

- Do not publish a code path that moves identity ownership without content/thread reconciliation in the same transaction.
- Do not consume a token before the merge flush succeeds.
- Stop and roll back the transaction on any running target ingestion or uniqueness conflict.
- Before deployment, take the normal PostgreSQL backup. Code rollback preserves already-merged knowledge but does not split completed merges.
