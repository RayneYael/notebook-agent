# Embedding and chunking audit

## Current production path

The built-in ingestion connector currently supports YouTube URLs. Subtitle JSON3 events are normalized into
timestamped `Cue(start, end, text)` values, then passed through `app.ingest.chunker.chunk()`.

```text
YouTube subtitle events
  -> timestamped cues
  -> chapter/gap/punctuation/semantic/hard-cut boundaries
  -> final chunks
  -> one embedding-3 vector (1536 dimensions) per final chunk
  -> Segment rows + pgvector HNSW index
```

## There is no local model tokenizer for embedding chunks

No tiktoken/provider tokenizer is used by the chunker. Its fallback density estimate is:

- Chinese: count only Han characters matching `U+3400..U+9FFF`; target 280.
- Other languages: count regex words matching `\b[\w']+\b`; target 170.
- Also stop near 60 seconds, never include a cue that would take a hard-cut chunk past 120 seconds.
- Hard-cut chunks overlap by about 15% of duration.

The embedding provider performs its own internal tokenization after receiving each text, but this repository does
not inspect that tokenization or enforce a provider-token maximum per chunk. `EMBEDDING_BATCH_SIZE=64` limits the
number of independent text inputs in one HTTP request, not tokens and not combined chunk size.

The conversation-history `_estimate_tokens()` helper (`serialized JSON characters // 3`) is unrelated to ingestion
or embedding chunking.

## Boundary priority

1. Metadata chapters: a chapter up to 180 seconds becomes one chunk directly.
2. Subtitle silence gap of at least 2 seconds.
3. Sentence-ending punctuation (`.?!。？！`) when more boundaries are needed.
4. Semantic boundary: embed every cue and split at strict local minima of adjacent cosine similarity.
5. Hard cut: 60 seconds / 280 Chinese characters / 170 non-Chinese words, max 120 seconds, 15% overlap.

Signal-derived gap/punctuation/semantic chunks are accepted only when every resulting chunk is at most 120 seconds.
The chapter shortcut is an exception and can create a chunk as long as 180 seconds.

## Embedding calls during ingestion

When gap/punctuation boundaries are insufficient, each cue is embedded once to discover semantic transitions.
After final chunks are selected, every chunk is embedded again for storage. Both phases use ordered provider batches
of at most 64 input strings.

## Query path

Each `search_segments` call embeds the whole model-provided query as one text, validates one 1536-dimensional vector,
then runs tenant-scoped lexical and vector searches. The two result lists are merged, deduplicated and capped at six
citations by default. One search returning six segments is still one Agent tool call.

## Relation to the tool-call-limit incident

Chunk count or citation count does not directly increment Agent tool usage. However, overly broad chunks can dilute
vector similarity, and overly small/fragmented chunks can make the model request neighbors. Retrieval quality can
therefore influence whether the model expands the search, but the observed incident's direct cause remains the lack
of an Agent-level convergence rule plus parallel tool-call fan-out.

## Design caveats for a future task

- There is no exact provider-token ceiling or observability for chunk token distributions.
- The 180-second chapter shortcut bypasses the normal 120-second and density targets.
- Semantic boundary discovery can embed every subtitle cue before embedding final chunks, increasing ingestion cost.
- The current built-in connector is timestamp/video-oriented; database fields anticipate article offsets, but there
  is no built-in article connector/chunker in the current production path.
