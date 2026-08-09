# Design: exact current-message reference enforcement

## Boundary

The current user message is the only authority for explicit video references.
Conversation history may help interpret ordinary follow-ups, but it may not
select a different content item when the current message supplies a supported
URL.

```text
current message
  -> deterministic URL extraction + normalization
      -> bare supported URL batch
          -> existing durable save-confirmation action (no model)
      -> URL plus semantic text
          -> retrieval Agent with exact tenant/platform/platform-id scope
              -> scoped vector/BM25/hydration/expansion
              -> scoped Citation cache
              -> existing tool-free Composer
      -> no supported URL
          -> existing Agent behavior unchanged
```

## Shared reference parser

Introduce one application-owned helper that extracts HTTP(S) URL tokens from
the raw current message, strips only the existing safe trailing punctuation,
and normalizes supported values through `normalize_item_reference()`.

The helper returns both the original ordered URLs needed by save confirmation
and unique normalized `(platform, platform_id)` references needed by retrieval.
It also determines whether the non-URL remainder contains semantic text. This
keeps URL interpretation consistent with the existing action input-matching
contract instead of adding a second YouTube parser.

## Deterministic bare URL action

`KnowledgeAgent.run()` creates its existing `AgentActionRuntime` before model
execution. For a valid bare supported URL batch, it calls the same
`request_confirmation()` method currently exposed as a model tool and converts
the resulting `ActionOutcome` through the existing canonical response path.

No new pending-action state or response shape is introduced. The only change
is that the model and its history no longer choose the action for an input that
already has one unambiguous product meaning.

## Exact retrieval scope

For a message containing supported URLs and semantic text, the runtime passes
the normalized reference set into the request-scoped knowledge service. The
scope is an additional restriction after the tenant boundary, never a
replacement for it.

Every database read that can produce model-visible evidence applies all of:

```text
ContentItem.user_id == resolved tenant
ContentItem.deleted_at IS NULL
ContentItem.state == ready where segment evidence is required
ContentItem.(platform, platform_id) IN current-message references
```

Vector and lexical retrieval receive the same scope. Hydration repeats it so a
future backend regression cannot smuggle an out-of-scope segment through an ID
list. Neighbor, item-detail, and open-at lookups apply it as well, which blocks
the planner from reusing an item or segment ID learned from history.

The runtime also filters/validates returned citations against the normalized
reference set before adding them to the trusted Citation cache or returning
them to the planner. This is defense in depth for test doubles and future
service implementations. With no in-scope citations, the existing
`not_found/no_evidence` path runs and Composer is skipped.

## Tool exposure

When the current message contains an explicit supported URL, inventory and
item-management tools are hidden from that planner request. This prevents the
observed fallback to `list_saved_items`. Save/pending tools remain available so
an explicit request such as “保存 <URL>” retains its current behavior; the
existing instruction continues to prohibit treating a content question as save
consent.

## Compatibility and privacy

- No schema migration is required.
- No public tool gains a tenant ID, item ID, or reference-scope argument.
- General free-text retrieval and management-history persistence remain
  unchanged.
- Production diagnostics remain content-redacted. Existing stage/action events
  are reused for deterministic routing.
- Exact lookup remains tenant scoped and excludes soft-deleted content.

## Risks and rollback

- Tightening all retrieval reads may expose tests or alternate service
  implementations that relied on tenant-only access. Those callers should
  explicitly opt into an empty (unrestricted) scope for non-URL questions.
- URL remainder classification must not turn “保存 <URL>” into a bare URL; any
  non-punctuation text keeps model handling.
- If the change regresses ordinary queries, rollback is confined to the shared
  parser, deterministic pre-route, and optional service scope; no stored data
  needs migration or repair.
