from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.agent.services import (
    EmbeddingUnavailable,
    KnowledgeServices,
    RetrievalUnavailable,
    _diversify_hits,
)
from app.channels.types import TenantContext
from app.retrieval.search import Hit


class FakeEmbeddingProvider:
    dimensions = 2

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result if result is not None else [[0.5, 0.5]]
        self.error = error
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.error is not None:
            raise self.error
        return self.result


def tenant() -> TenantContext:
    return TenantContext(1, 1, "telegram", "account", "user")


def hit(item_id: int, segment_id: int, score: float, start_sec: float = 0) -> Hit:
    return Hit(
        item_id=item_id,
        title=f"video-{item_id}",
        platform_id=f"platform-{item_id}",
        segment_id=segment_id,
        text=f"evidence-{segment_id}",
        start_sec=start_sec,
        score=score,
    )


def test_search_requires_embedding_before_any_database_work():
    def database_must_not_open():
        raise AssertionError("database search must not run without an embedding")

    service = KnowledgeServices(tenant(), database_must_not_open)

    with pytest.raises(EmbeddingUnavailable):
        service.search_segments("redacted query")


def test_provider_failure_is_embedding_unavailable_without_query_leakage():
    provider = FakeEmbeddingProvider(error=RuntimeError("upstream failure"))
    service = KnowledgeServices(tenant(), lambda: pytest.fail("database must not open"), embedder=provider)

    with pytest.raises(EmbeddingUnavailable) as caught:
        service.search_segments("redacted query")

    assert "redacted query" not in str(caught.value)
    assert provider.calls == [["redacted query"]]


def test_zero_hits_is_distinct_from_database_failure(monkeypatch):
    @contextmanager
    def database():
        yield object()

    provider = FakeEmbeddingProvider()
    service = KnowledgeServices(tenant(), database, embedder=provider)
    monkeypatch.setattr("app.agent.services.bm25_search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("app.agent.services.vector_search", lambda *_args, **_kwargs: [])

    assert service.search_segments("redacted query") == []
    assert provider.calls == [["redacted query"]]

    @contextmanager
    def broken_database():
        raise RuntimeError("database down")
        yield object()

    broken = KnowledgeServices(tenant(), broken_database, embedder=provider)
    with pytest.raises(RetrievalUnavailable) as caught:
        broken.search_segments("redacted query")
    assert "redacted query" not in str(caught.value)


def test_diversified_candidates_reserve_top_five_videos_before_extra_segments():
    crowded = [hit(1, segment_id, 100 - segment_id, start_sec=segment_id * 120) for segment_id in range(1, 9)]
    weaker_videos = [hit(item_id, item_id * 100, 10 - item_id) for item_id in range(2, 7)]

    selected = _diversify_hits(crowded + weaker_videos, limit=10)

    assert [row.item_id for row in selected[:5]] == [1, 2, 3, 4, 5]
    assert 6 not in {row.item_id for row in selected}
    # After video representatives, the public window can retain the distant
    # first video's chapters in relevance order rather than flattening it.
    assert [row.segment_id for row in selected[5:]] == [2, 3, 4, 5, 6]


def test_diversification_keeps_best_duplicate_and_distant_same_item_evidence():
    selected = _diversify_hits(
        [
            hit(1, 11, 0.4, 10),
            hit(1, 11, 0.9, 10),
            hit(1, 19, 0.8, 900),
            hit(2, 21, 0.7, 20),
        ],
        limit=10,
    )

    assert [row.segment_id for row in selected] == [11, 21, 19]
    assert selected[0].score == 0.9
    assert [row.start_sec for row in selected if row.item_id == 1] == [10, 900]


def test_search_overfetch_is_bounded_and_public_limit_is_clamped(monkeypatch):
    calls = []

    @contextmanager
    def database():
        yield object()

    service = KnowledgeServices(tenant(), database, embedder=FakeEmbeddingProvider())
    monkeypatch.setattr(
        "app.agent.services.bm25_search",
        lambda _db, _query, *, user_id, k: calls.append(("bm25", user_id, k)) or [],
    )
    monkeypatch.setattr(
        "app.agent.services.vector_search",
        lambda _db, _vector, *, user_id, k: calls.append(("vector", user_id, k)) or [],
    )

    assert service.search_segments("redacted query", limit=999) == []
    assert calls == [("bm25", 1, 50), ("vector", 1, 50)]
