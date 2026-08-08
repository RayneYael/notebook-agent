# Why-saved Collection Tags

## Goal

Let Web users organize saved videos with lightweight folder-like collection
tags while preserving the existing `why_saved` API and storage model. The UI
must make the feature feel like a collection picker, but the persisted value
remains an ordinary validated hashtag inside `why_saved`.

## Product Requirements

- The Add Video dialog includes a collection section between URLs and the save
  reason.
- A user may select one existing collection, create and select one new
  collection, or explicitly choose `未归类`.
- Existing collection suggestions are derived from collection hashtags found
  in the authenticated user's currently loaded library items. They are never
  derived from YouTube metadata `tags`.
- A collection name is 1-20 characters after trimming and may contain Unicode
  letters, numbers, `_`, or `-`. Spaces, punctuation, control characters, and
  a second leading `#` are rejected with inline Chinese guidance.
- Saving with a collection appends one canonical `#name` token to the shared
  save reason. Saving without a collection sends only the ordinary reason or
  `null`.
- The final combined `why_saved` value must not exceed the upstream-compatible
  500-character limit.
- The ordinary save reason is a multiline textarea with native vertical resize
  affordance, a practical maximum height, and a visible character count.
- Collection tags and ordinary save-reason copy are visually separated on
  library cards and video detail pages.
- The library displays discovered collections as quiet filter chips. Choosing
  one uses the existing server-side `why_saved` search by querying its exact
  hashtag; choosing `全部视频` clears that collection filter.
- All additions match the existing pale editorial UI, remain usable at
  390x844, expose programmatic labels, and never rely on color alone.

## Compatibility and Non-goals

- No database model, migration, OpenAPI schema, API route, auth behavior, or
  tenant selection changes.
- Do not overwrite or reinterpret `ContentItem.tags`; those remain connector
  metadata supplied by YouTube.
- No nested collections, collection rename/delete workflow, drag-and-drop,
  multi-select folder assignment, or cross-page collection aggregation in this
  increment.
- Existing `why_saved` values without recognized tags remain unchanged and
  render as ordinary save reasons.

## Acceptance Criteria

- [x] Unit tests prove collection parsing, stable de-duplication, name limits,
  combined 500-character validation, and reason/tag separation.
- [x] Add Video tests prove existing-tag selection, new-tag validation,
  explicit unclassified selection, resizable reason textarea, and unchanged
  `{urls, why_saved}` submission shape.
- [x] Library tests prove discovered collection chips and existing-search
  filtering without a new API request field.
- [x] Card and detail tests prove tags render separately from reason copy and
  ordinary hashtags outside the supported token grammar are not misclassified.
- [x] Targeted Vitest, TypeScript, ESLint, production build, and diff checks
  pass.
- [x] Browser smoke proves the dialog and tag controls work at desktop and
  390x844 without horizontal overflow.
