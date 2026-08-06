from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.agent.services import (
    EmbeddingUnavailable,
    KnowledgeServices,
    RetrievalUnavailable,
)
from app.channels.types import TenantContext


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
