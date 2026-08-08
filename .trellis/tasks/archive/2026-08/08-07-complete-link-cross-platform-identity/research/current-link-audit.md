# Current cross-platform identity link audit

Date: 2026-08-07

## Existing production path

The repository already contains a first-pass implementation rather than an
empty placeholder:

- `app/models.py:76` defines `ChannelIdentity` with a unique trusted external
  key and one `app_user_id` owner.
- `app/models.py:103` defines hashed, expiring `ChannelLinkToken` rows with a
  consumed timestamp and optional target channel.
- `app/channels/identity.py:87` creates a high-entropy token and stores only its
  SHA-256 hash.
- `app/channels/identity.py:109` locks and consumes a token, rejects expiry,
  replay and channel mismatch, then inserts a new identity for the token owner.
- `app/channels/service.py:187` implements the two `/link` interpretations:
  a bound source identity treats its argument as a target channel; an unbound
  target identity treats its argument as a token.
- `tests/test_multiuser_integration.py:502` covers the repository-level happy
  path, expiry, replay, channel mismatch and disabled-user resolution.

## Why the current flow is not complete

1. `ChannelService._handle_locked()` routes `/link` before automatic
   registration, but every other first message calls `resolve_or_register()`
   (`app/channels/service.py:73-80`). Therefore token consumption works only if
   it is the target account's first interaction.
2. When the target identity already exists, `_handle_link()` treats every
   argument as a new target channel and generates another token
   (`app/channels/service.py:195-219`). It cannot consume a token or link two
   already registered accounts.
3. The repository method explicitly rejects any existing target identity
   (`app/channels/identity.py:130-131`) without distinguishing “already linked
   to this user” from “owned by another user”. The user receives the generic
   `identity_error` wrapper, not an actionable conflict contract.
4. Existing tests call `consume_link_token()` with a fresh envelope. They do
   not exercise the common ChannelService sequence where the target account
   first auto-registers, nor do they cover source/target tenant content.
5. The existing admin `rebind-identity` command changes only
   `ChannelIdentity.app_user_id` (`app/cli.py:89-98`). It does not reconcile the
   target user's `ContentItem`, `ConversationThread`, tokens or other state and
   is therefore a manual correction tool, not a safe self-service merge path.

## Data affected by a pre-existing target tenant

Direct `AppUser` ownership currently exists on:

- `ChannelIdentity.app_user_id`
- `ChannelLinkToken.app_user_id`
- `ConversationThread.app_user_id`
- `ContentItem.user_id`

Conversation turns, pending channel actions, segments and ingest dispatch rows
are owned transitively through threads or content items. Reassigning only the
target channel identity can leave conversation rows with an `app_user_id` that
disagrees with the identity owner; deleting the target user can cascade-delete
identities, link tokens and conversations, while `ContentItem.user_id` has no
delete cascade.

## Security and concurrency notes

- Token possession is suitable for proving control of both message accounts:
  the source account creates it and the target account presents it through a
  trusted channel envelope.
- SHA-256 without a salt is acceptable for a 32-byte random token, provided
  raw tokens never enter logs or persistence.
- `SELECT ... FOR UPDATE` serializes consumption of one known token, but the
  current check-then-insert target identity path still needs explicit tests for
  races with automatic registration and multi-process delivery.
- Linking must remain outside LLM/retrieval and must not use display names or
  client-provided internal user IDs.

## Planning implication

The current task is not a greenfield identity system. Implementation should
replace the existing `/link` decision flow and harden the repository contract.
The product scope explicitly includes merging two non-empty tenants, so the
task needs a dedicated tenant-merge service rather than a single identity
update.

`ContentItem` has a unique `(user_id, platform, platform_id)` key
(`app/models.py:272-276`). When both tenants saved the same external content,
bulk owner reassignment will fail. A merge contract must choose one canonical
item, reconcile `saved_at`, `why_saved`, watch state and ingestion state, and
either repoint or retire the losing item's segments and dispatch history.

Active dispatches introduce an additional race: a worker may already hold the
losing item ID while the link transaction is committing. The implementation
must either make workers resolve a durable merge redirect or establish a safe
claim/cancellation protocol. Deleting or silently abandoning the losing row is
not sufficient.
