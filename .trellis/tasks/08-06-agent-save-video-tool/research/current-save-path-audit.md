# Current natural-language save-path audit

Date: 2026-08-06

## Finding

The channel bridge forwards normalized text to `ChannelService`, which recognizes only identity/session
commands before invoking `KnowledgeAgent`. The Agent exposes four read-only tools: segment search, neighbors,
item metadata, and timestamp/anchor resolution. There is no channel-to-ingestion tool, so a standalone video
URL is currently treated as an ordinary Agent question.

The existing ingestion path already has useful primitives:

- `ContentItem.user_id` is required and has a unique `(user_id, platform, platform_id)` constraint;
- `create_item()` returns an existing tenant-owned item for a duplicate URL;
- `fetch_text_task` is a Celery task with bounded retry for transient fetch errors;
- CLI `ingest_url()` currently performs `process_item()` synchronously and must not be called inside a channel
  request.

The smallest safe extension is a tenant-bound Agent service method that validates a supported URL, performs
idempotent item creation, and enqueues the existing background task. The tool must not expose `user_id` or
wait for transcript/embedding completion.

## Collection-import extension audit

The current `Connector` protocol handles one normalized item (`match`, `fetch_meta`, `fetch_text`) and the
database has only per-item `ContentItem`/`Segment` records. This is sufficient for direct URLs. A public
playlist or private favorites collection additionally needs a collection enumerator with pagination/cursors,
an import-job progress model, rate limiting, and per-item partial results. Private collections also require
platform authorization stored independently from channel identity; the current YouTube connector explicitly
persists no cookies.

This does not require a new Agent architecture. A future `import_collection` tool can resolve an authorized
collection, enumerate item references asynchronously, and submit each reference through the same tenant-bound
item submission service used by `save_videos`. The current task should create that service seam but must not
implement collection OAuth or large-job orchestration.

## Runtime outcome gap

The current Agent runtime treats a run as successful only when `search_segments` was called and the final
answer cites returned evidence. `ChannelService` also reconstructs a duplicate turn as `not_found` whenever
the persisted citation list is empty. Both assumptions are correct for read-only knowledge answers but are
incorrect for a save-intent clarification or a successful write-tool outcome.

Implementation must introduce an explicit action outcome/record rather than weakening citation validation.
A factual knowledge answer still requires search and citations. A save clarification or confirmed save may
omit citations only when the run contains the corresponding safe action state/tool result, and duplicate
delivery must reproduce the original action status instead of converting it to `not_found`.
