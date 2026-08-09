# Fix exact video reference and session routing

## Goal

Prevent a user-supplied YouTube URL from being answered with evidence from a
different saved video, and prevent prior conversation history from changing a
bare supported URL into an unrelated inventory action.

The user must be able to trust that “this video” always refers to the exact
video ID present in the current message. Starting a new session must not be a
prerequisite for correct routing.

## Background

- Production-like diagnostics for tenant 57 recorded searches for YouTube ID
  `8Xxwq7uGibY` returning only item 314, whose actual ID was
  `FwOTs4UxQS4`, with vector scores around 0.31–0.46.
- Two answers about the requested video were composed entirely from the wrong
  item. A later bare URL was routed to `list_saved_items` until `/new` removed
  the old history.
- The current planner requires link-content questions to use ordinary semantic
  retrieval. Vector search always returns the nearest tenant candidates and
  has no exact-reference constraint.
- Management outcomes intentionally remain in canonical history to support
  safe follow-ups such as “next page”; globally removing management history is
  therefore not an acceptable fix.
- Existing product behavior distinguishes a bare URL (request save
  confirmation) from a URL plus a content question (retrieve only; asking
  about content is not consent to save).

## Requirements

### R1 — Parse current-message video references deterministically

- Extract supported YouTube URLs from the current user message without model
  interpretation and normalize them through the existing submission URL
  contract.
- Preserve input order and duplicates where action confirmation requires them.
- Classify a message as a bare URL batch only when, after removing its supported
  URLs and harmless whitespace/punctuation, no semantic text remains.
- Unsupported or malformed URLs retain their existing safe validation behavior.

### R2 — Make bare URL routing independent of history

- A bare batch of 1–10 supported URLs must invoke the existing durable save
  confirmation path without a model request.
- The existing save-enabled, unavailable, batch-size, tenant, thread,
  confirmation, and idempotency contracts remain authoritative.
- Old inventory, delete, summary, or mistaken-answer history must not change
  the result into retrieval or item management.

### R3 — Scope explicit-reference knowledge retrieval to the exact videos

- When the current message contains supported video URLs plus semantic text,
  every retrieval path must be constrained to active knowledge items with the
  same tenant, platform, and platform ID.
- The constraint applies to vector search, lexical search, result hydration,
  neighbor expansion, item metadata, timestamp resolution, and the final
  citation allow-list.
- If an exact referenced video is absent, deleted, not ready, or has no usable
  evidence, return a source-free not-found response. Do not fall back to other
  tenant videos and do not automatically save the URL.
- A model-authored item or segment ID from history must not escape the
  current-message reference scope.
- Management tools that could turn an explicit video reference into an
  unrelated inventory result must not be exposed for that request. Existing
  explicit save tools remain available for messages that actually ask to save.

### R4 — Preserve existing behavior outside the defect

- Ordinary free-text knowledge questions retain the current hybrid retrieval,
  convergence budgets, composer, and Top-5 source behavior.
- Canonical management history remains available for inventory pagination and
  ordinal follow-ups.
- Pending save/delete safety, tenant isolation, deleted-content exclusion,
  duplicate delivery, MCP behavior, and public response contracts must not
  regress.

## Acceptance Criteria

- [ ] Given saved video A and an unsaved URL for video B, asking what B is about
      returns no evidence and never cites or summarizes A.
- [ ] Given saved and ready videos A and B, a question containing B's URL can
      return only B citations even when history prominently discusses A.
- [ ] A referenced deleted, pending, failed, or otherwise non-ready video cannot
      leak evidence from another active video.
- [ ] A model attempt to expand a segment or item outside the explicit URL scope
      fails closed and cannot reach the composer as trusted evidence.
- [ ] A bare supported URL produces `save_confirmation_required` with zero model
      attempts, including when history contains inventory and deletion turns.
- [ ] A bare supported URL batch preserves order/duplicates and existing
      1–10-item validation.
- [ ] A URL plus a content question never becomes an inventory listing and is
      not treated as consent to save.
- [ ] Existing inventory pagination using canonical history still passes.
- [ ] Focused Agent, action, retrieval, channel, management, and tenant-isolation
      tests pass, followed by the complete test suite.

## Out of Scope

- Choosing a new global vector-similarity threshold for unrestricted free-text
  retrieval; that requires a separate relevance evaluation and tuning task.
- Removing canonical management history or changing the configured history
  turn/token limits.
- Adding absolute timestamps or message content to diagnostic logs.
- Automatically fetching or summarizing an unsaved external video in the same
  request.
- Changing ingestion workers, transcript generation, embedding models, or the
  public `/new` command.
