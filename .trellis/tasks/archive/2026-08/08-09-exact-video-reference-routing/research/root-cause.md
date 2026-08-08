# Root-cause research: cross-video answers before session reset

## Observed evidence

- The 2026-08-09 development log searched for `8Xxwq7uGibY` and
  `8Xxwq7uGibY 视频`, but every returned segment belonged to item 314 and URL
  `FwOTs4UxQS4`; scores ranged from roughly 0.31 to 0.46.
- A correction turn called `get_item(314)` and received the canonical
  `FwOTs4UxQS4` URL, yet the final answer still described that item as the
  requested video.
- A later bare `8Xxwq7uGibY` URL performed repeated semantic searches and then
  called `list_saved_items`.
- `/new` closed thread 57 at 2026-08-09 01:52:00 Asia/Singapore. The replacement
  thread had zero history; the same bare URL then called
  `request_save_confirmation`, and the next affirmative turn queued it.

## Code-path findings

- `app/agent/runtime.py` tells the planner that link-content questions must use
  ordinary knowledge retrieval and requires at least one `search_segments`
  call before an answer.
- `app/retrieval/search.py` vector search always orders tenant rows by cosine
  distance and returns Top-K. It has no exact URL/platform-ID predicate and no
  minimum relevance threshold.
- `app/agent/services.py` merges lexical and vector candidates and treats any
  returned segment as evidence. Hydration repeats the tenant and deletion
  filters but has no current-message subject filter.
- Composer validation proves only that citation segment IDs came from the
  trusted cache and span no more than five items. It does not prove those items
  match an explicit URL in the current question.
- `app/channels/conversations.py` intentionally loads up to eight completed
  non-MCP-management turns under the token budget. Before the bad bare-URL
  route, the selected history included an earlier `FwOTs4UxQS4` summary,
  inventory results, deletion results, and two already-wrong answers about
  `8Xxwq7uGibY`.
- Management history cannot simply be removed: item-management tests require
  canonical inventory context for safe “next page” follow-ups.

## Design conclusion

The defect is not solved by prompt wording or session reset. Correctness needs
two server-owned invariants:

1. a bare supported URL has one deterministic save-confirmation route; and
2. an explicit URL in a knowledge question constrains every evidence-producing
   read and final citation to that exact tenant-owned content item.

A global vector threshold is useful defense for unrestricted queries but is a
separate calibration problem. It cannot replace exact-reference enforcement.

## Relevant specifications

- `.trellis/spec/backend/agent-retrieval-convergence.md`
- `.trellis/spec/backend/knowledge-item-management.md`
- `.trellis/spec/backend/youtube-connector.md`
