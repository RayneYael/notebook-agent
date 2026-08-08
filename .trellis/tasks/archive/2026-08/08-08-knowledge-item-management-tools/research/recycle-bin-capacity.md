# Recycle-bin capacity and purge audit

## Conclusion

PostgreSQL can support the recycle-bin design if deleted content has a bounded retention period and physical purge
runs in small, retryable batches. The capacity driver is not the `content_item` row. It is the retained `segment`
rows, 1536-dimensional vectors, full-text/trigram indexes, and HNSW index entries.

The current repository does not have a running local Compose database from which to capture a production-like size
baseline, so this note establishes structural lower bounds and required measurements rather than claiming a fixed
maximum item count.

## Repository evidence

- `ContentItem` owns `saved_at`, ingestion state, and `raw_object_key` (`app/models.py:231-283`).
- Each `Segment` contains transcript text plus `Vector(1536)` and participates in HNSW, GIN FTS, and GIN trigram
  indexes (`app/models.py:332-375`).
- Chunking targets roughly 60 seconds and caps a normal chunk at 120 seconds (`app/ingest/chunker.py:61-92`).
- Database foreign keys already cascade a physical `ContentItem` delete to `Segment` and `IngestDispatch`
  (`migrations/versions/6df2e721d7b2_init_schema.py:133-139`,
  `migrations/versions/c7e8a91b2d34_agent_save_actions.py:126-130`).
- MinIO is not covered by database cascade. `RawObjectStore` currently implements only `put`, so physical purge must
  add an idempotent object delete path (`app/ingest/tasks.py:94-106`).
- There is no periodic purge scheduler in the current app configuration or Compose stack. The deployment currently
  provisions PostgreSQL, Redis, and MinIO only (`docker-compose.yml:1-44`).

## Storage lower bound

A dense 1536-dimensional float vector alone is approximately `1536 * 4 = 6144` bytes, excluding PostgreSQL row
overhead, transcript text, and every index. Therefore:

- 1 million retained segments imply about 6.1 GB of vector values in the table before indexes and text.
- 10 million retained segments imply about 61 GB of vector values before indexes and text.
- HNSW stores graph/index data and the GIN indexes store searchable text structures, so actual database size will be
  materially higher than those lower bounds.

At the current roughly one-minute target, a one-hour video commonly produces on the order of dozens of primary
segments, with more possible around chapters, gaps, or hard cuts. Capacity must therefore be planned and monitored in
segments, not just videos.

## Required purge shape

1. Add `deleted_at` plus an index whose leading keys support the expiry scan, for example `(deleted_at, id)` with a
   partial predicate for deleted rows.
2. Default list/detail/search paths exclude `deleted_at IS NOT NULL`.
3. A periodic scheduler selects expired candidates by stable cursor in a small batch and uses
   `FOR UPDATE SKIP LOCKED` (or an equivalent atomic claim) so retries and multiple workers cannot double-purge.
4. Do not place all expired items in one transaction or one broker message. Use a configurable item limit and also
   bound work by associated segment count or elapsed time, because video lengths vary.
5. An active ingestion dispatch must be cancelled/settled before physical deletion. Worker claim and finalization
   must check deleted/purging state so a late worker cannot recreate visible content.
6. Delete the MinIO object idempotently and retain a retryable purge state until both object cleanup and database
   cleanup have converged. Database cascade then removes segments and dispatch history.
7. PostgreSQL `DELETE` creates dead tuples; autovacuum makes space reusable but does not necessarily reduce the data
   files immediately. Monitor dead tuples and index bloat, and schedule controlled `REINDEX` or stronger maintenance
   only when measured bloat requires it.

## Operational metrics and capacity alarms

- active/trash item counts and oldest `deleted_at`
- active/trash/expired segment counts
- `pg_database_size`, table size, and HNSW/GIN index sizes
- dead tuples and autovacuum recency for `segment`, `content_item`, and `ingest_dispatch`
- purge candidates, claimed/completed/failed counts, batch duration, and backlog age
- MinIO delete failures and outstanding purge records
- retrieval latency and result count as the trash ratio grows

## Planning recommendation

Use a 30-day restore window for the first release, purge frequently in small batches, and make retention and batch
limits configuration values. Thirty days bounds how long soft-deleted vectors remain in HNSW while giving users a
conventional recovery window. A shorter window reduces storage and search-index pressure; a longer window increases
recoverability at proportional storage cost.
