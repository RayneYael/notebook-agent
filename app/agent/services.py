"""Tenant-scoped read-only knowledge services used by Agent tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.types import Citation
from app.channels.types import TenantContext
from app.diagnostics import RequestDiagnostics
from app.ingest.embed import EmbeddingError, EmbeddingProvider
from app.models import ContentItem, Segment
from app.retrieval.search import bm25_search, vector_search


class KnowledgeNotFound(LookupError):
    """Raised uniformly for missing and cross-tenant resources."""


class EmbeddingUnavailable(RuntimeError):
    """Query embedding is missing or could not be safely produced."""


class RetrievalUnavailable(RuntimeError):
    """Database retrieval did not finish and must not be presented as no evidence."""


@dataclass(frozen=True)
class ItemDetails:
    item_id: int
    title: str
    author: str | None
    description: str | None
    url: str
    platform: str
    duration_sec: int | None


def _title(item: ContentItem) -> str:
    return item.title or item.platform_id


def _url(item: ContentItem, segment: Segment | None = None) -> str:
    if item.platform == "youtube" and segment is not None and segment.start_sec is not None:
        return f"https://youtu.be/{item.platform_id}?t={int(float(segment.start_sec))}"
    if segment is not None and segment.anchor:
        return f"{item.url}#{segment.anchor}"
    return item.url


def _citation(item: ContentItem, segment: Segment) -> Citation:
    return Citation(
        item_id=item.id,
        segment_id=segment.id,
        title=_title(item),
        excerpt=segment.text,
        url=_url(item, segment),
        start_sec=float(segment.start_sec) if segment.start_sec is not None else None,
    )


class KnowledgeServices:
    """Read-only services whose tenant is fixed at construction time."""

    def __init__(
        self,
        tenant: TenantContext,
        session_factory: Callable[[], Session],
        *,
        embedder: EmbeddingProvider | None = None,
        max_results: int = 10,
    ) -> None:
        self._tenant = tenant
        self._session_factory = session_factory
        self._embedder = embedder
        self._max_results = max_results
        self._diagnostics: RequestDiagnostics | None = None

    def set_diagnostics(self, diagnostics: RequestDiagnostics) -> None:
        """Attach the request-scoped, redacted diagnostic sink."""

        self._diagnostics = diagnostics

    def search_segments(self, query: str, *, limit: int = 6) -> list[Citation]:
        """Hybrid lexical/vector search, merged without exposing tenant arguments."""

        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, self._max_results))
        vector = self._embed_query(query)
        self._event("retrieval_started")
        try:
            with self._session_factory() as db:
                hits = bm25_search(
                    db, query, user_id=self._tenant.app_user_id, k=limit
                )
                hits.extend(
                    vector_search(
                        db,
                        vector,
                        user_id=self._tenant.app_user_id,
                        k=limit,
                    )
                )

                segment_ids: list[int] = []
                for hit in sorted(hits, key=lambda value: value.score, reverse=True):
                    if hit.segment_id not in segment_ids:
                        segment_ids.append(hit.segment_id)
                    if len(segment_ids) >= limit:
                        break
                if not segment_ids:
                    self._event("retrieval_completed", error_code="no_evidence")
                    return []
                rows = db.execute(
                    select(Segment, ContentItem)
                    .join(ContentItem, Segment.item_id == ContentItem.id)
                    .where(
                        ContentItem.user_id == self._tenant.app_user_id,
                        Segment.id.in_(segment_ids),
                    )
                ).all()
                by_id = {
                    segment.id: _citation(item, segment) for segment, item in rows
                }
                citations = [by_id[value] for value in segment_ids if value in by_id]
                self._event("retrieval_completed")
                return citations
        except Exception as exc:
            self._event(
                "retrieval_failed", error_code="retrieval_unavailable", exception=exc
            )
            raise RetrievalUnavailable("retrieval unavailable") from exc

    def _embed_query(self, query: str) -> list[float]:
        self._event("embedding_started")
        try:
            if self._embedder is None:
                raise EmbeddingUnavailable("embedding provider is not configured")
            vectors = self._embedder.embed([query])
            if len(vectors) != 1:
                raise ValueError("query embedding count mismatch")
            vector = vectors[0]
            if len(vector) != self._embedder.dimensions:
                raise ValueError("query embedding dimension mismatch")
            if any(not math.isfinite(value) for value in vector):
                raise ValueError("query embedding contains invalid values")
            self._event("embedding_completed")
            return vector
        except Exception as exc:
            self._event(
                "embedding_failed", error_code="embedding_unavailable", exception=exc
            )
            if isinstance(exc, EmbeddingUnavailable):
                raise
            raise EmbeddingUnavailable("query embedding unavailable") from exc

    def _event(
        self,
        stage: str,
        *,
        error_code: str | None = None,
        exception: BaseException | None = None,
    ) -> None:
        if self._diagnostics is not None:
            self._diagnostics.event(
                stage, error_code=error_code, exception=exception
            )

    def get_neighbors(self, segment_id: int, *, radius: int = 1) -> list[Citation]:
        """Return adjacent segments only when the anchor belongs to this tenant."""

        radius = max(1, min(radius, 3))
        with self._session_factory() as db:
            anchor = db.execute(
                select(Segment, ContentItem)
                .join(ContentItem, Segment.item_id == ContentItem.id)
                .where(
                    Segment.id == segment_id,
                    ContentItem.user_id == self._tenant.app_user_id,
                )
            ).one_or_none()
            if anchor is None:
                raise KnowledgeNotFound("segment not found")
            segment, item = anchor
            neighbors = db.scalars(
                select(Segment)
                .where(
                    Segment.item_id == item.id,
                    Segment.seq.between(segment.seq - radius, segment.seq + radius),
                )
                .order_by(Segment.seq)
            ).all()
            return [_citation(item, value) for value in neighbors]

    def get_item(self, item_id: int) -> ItemDetails:
        """Return item metadata if and only if it belongs to the fixed tenant."""

        with self._session_factory() as db:
            item = db.scalar(
                select(ContentItem).where(
                    ContentItem.id == item_id,
                    ContentItem.user_id == self._tenant.app_user_id,
                )
            )
            if item is None:
                raise KnowledgeNotFound("item not found")
            return ItemDetails(
                item_id=item.id,
                title=_title(item),
                author=item.author,
                description=item.description,
                url=item.url,
                platform=item.platform,
                duration_sec=item.duration_sec,
            )

    def open_at(self, segment_id: int) -> Citation:
        """Resolve a tenant-owned segment to its timestamp or article anchor."""

        with self._session_factory() as db:
            row = db.execute(
                select(Segment, ContentItem)
                .join(ContentItem, Segment.item_id == ContentItem.id)
                .where(
                    Segment.id == segment_id,
                    ContentItem.user_id == self._tenant.app_user_id,
                )
            ).one_or_none()
            if row is None:
                raise KnowledgeNotFound("segment not found")
            return _citation(row[1], row[0])
