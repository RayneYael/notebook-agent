# Cross-platform identity link design

## 1. Boundaries and invariants

- `ChannelEnvelope` remains the only trusted external identity input. Display names, message-provided internal IDs and model output never participate in linking.
- `/link` is parsed and completed inside `ChannelService` before registration, conversation persistence or Agent execution. The binding-code message is never stored as a turn.
- The token creator is the surviving `AppUser`. A registered target tenant is merged into that user in one PostgreSQL transaction.
- Telegram and WeChat are the only linkable channels for this release. The bridge may know future channels such as Slack, but that does not make them valid `/link` targets.
- Conversation threads remain channel-identity scoped. Their `app_user_id` changes during a tenant merge, but threads and turns are not combined.

## 2. Command contract

`/link <argument>` uses deterministic syntax:

1. A normalized member of `{telegram, wechat}` is a token-generation request.
2. A value matching the exact generated token shape is a token-consumption request.
3. A channel-like value outside the allow-list returns `link_channel_unsupported`; malformed token input returns `link_token_invalid`.

Generation requires an enabled, bound source identity on a supported channel. The target must be supported and different from the source channel. The response names the target, TTL and exact target-side command. Only the SHA-256 token hash is persisted.

Consumption locks the token, validates unused/unexpired state and target channel, then resolves or registers the presenting identity inside the same transaction. Results are explicit: linked, already linked to the same user, invalid, expired, used, wrong channel, disabled account, merge busy, or merge conflict. An already-linked-to-same-user presentation consumes the valid token idempotently; all failure results leave it unconsumed.

## 3. Tenant merge service

Add a dedicated domain operation in the channel identity layer rather than embedding ownership updates in command rendering. Its transaction performs:

1. Lock the link token and both `AppUser` rows in ascending ID order. Lock the presenting `ChannelIdentity` when it already exists.
2. Fail closed if either user/identity is disabled. Re-read ownership after locks so concurrent registration or another merge cannot use stale state.
3. Lock both users' `ContentItem` and `IngestDispatch` rows. If a target-owned dispatch is `running`, or a duplicate row that would be retired has a running dispatch, return `merge_busy` without consuming the token. The user can retry after ingestion completes.
4. Reconcile duplicate `(platform, platform_id)` groups, then move every surviving target content row to the source user.
5. Move every target `ChannelIdentity`, `ConversationThread` and `ChannelLinkToken` to the source user, preserving each token's consumed/expiry state. Pending actions and turns follow their threads and retain channel-local history.
6. Delete the now-empty target `AppUser`, mark the presented token consumed, flush all constraints, and commit once.

Row locks and the existing unique external-identity key serialize automatic registration and repeated consumption. An integrity conflict rolls back the entire merge and returns a fixed conflict result; no partial ownership changes are committed.

## 4. Duplicate content reconciliation

Choose one survivor deterministically in this order:

1. a row with `state=ready`;
2. the row with more persisted segments and more complete content metadata;
3. a row with a non-running active dispatch;
4. the source-tenant row, then the lower row ID as a stable tie-break.

Before retiring the loser:

- `saved_at` becomes the earlier timestamp;
- distinct non-empty `why_saved` values are preserved in deterministic source/target-labelled blocks, without platform IDs;
- `watch_pos_sec` becomes the greatest known position; `watched` wins over `unwatched`, otherwise a non-null state is retained deterministically;
- missing descriptive/content fields on the survivor are filled from the loser, without replacing a complete ready payload with a weaker one;
- only the survivor's coherent segment set is kept. Segment sets are not interleaved because sequence, transcript source and embeddings must remain internally consistent;
- pending/enqueued loser dispatches are retired before the loser item is deleted. A queued delivery then finds no claim and exits as a duplicate. Completed/failed loser dispatch history is deleted with the duplicate item; the surviving item and its useful processing result remain.

Non-duplicate pending/enqueued target items are reassigned intact, so later workers resolve the surviving tenant before claiming. Running target work blocks the merge to prevent object keys or ORM writes from retaining the old tenant.

## 5. Compatibility, migration and rollback

The merge can use the current schema; no DDL migration is required. Existing identities and hashed tokens remain compatible. The production code path replaces the old fresh-target-only consumption behavior rather than adding a second link mechanism.

Each merge is transactionally reversible until commit. A completed identity merge is intentionally irreversible through user commands. Rolling back the application version does not delete merged knowledge, but it also does not split users again. Operators must take the normal PostgreSQL backup before deployment; restoring/splitting a completed merge is an administrative recovery procedure outside this task.

## 6. Privacy and diagnostics

Responses expose only the raw code on the source/target platform messages and the existing internal `/whoami` number. Production logs and test evidence contain fixed outcomes, counts and error classes only: never raw token, message body, nickname, external sender ID, content note, URL or identity mapping.

## 7. Platform verification

Automated tests cover the domain and normalized bridge/gateway path. A manual smoke script prompts the operator to send commands in real Telegram and WeChat, records only pass/fail checkpoints and `/whoami` equality, and never echoes or persists the code or platform identity.
