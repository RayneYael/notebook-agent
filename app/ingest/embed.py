"""Small injectable client for Zhipu's OpenAI-compatible embedding API."""

from __future__ import annotations

import json
import math
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    """The small, shared boundary used by ingestion and query retrieval."""

    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ZhipuEmbedder:
    MAX_BATCH_SIZE = 64

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "embedding-3",
        endpoint: str = "https://open.bigmodel.cn/api/paas/v4/embeddings",
        dimensions: int = 1536,
        batch_size: int = MAX_BATCH_SIZE,
    ) -> None:
        if not api_key:
            raise ValueError("ZHIPU_API_KEY is required for embedding")
        if dimensions < 1:
            raise ValueError("embedding dimensions must be positive")
        if not 1 <= batch_size <= self.MAX_BATCH_SIZE:
            raise ValueError(
                f"embedding batch_size must be between 1 and {self.MAX_BATCH_SIZE}"
            )
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.dimensions = dimensions
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            embeddings.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return embeddings

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps(
            {
                "model": self.model,
                "input": texts,
                "dimensions": self.dimensions,
            }
        ).encode()
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=60) as response:
                data = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmbeddingError("embedding request failed") from exc
        try:
            rows = data.get("data", [])
            if not isinstance(rows, list):
                raise TypeError("data is not a list")
            ordered = sorted(rows, key=lambda row: row["index"])
            if len(ordered) != len(texts):
                raise EmbeddingError("embedding response count mismatch")
            if [row["index"] for row in ordered] != list(range(len(texts))):
                raise EmbeddingError("embedding response index mismatch")
            vectors = [row["embedding"] for row in ordered]
            for vector in vectors:
                if not isinstance(vector, list) or len(vector) != self.dimensions:
                    raise EmbeddingError("embedding response dimension mismatch")
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in vector
                ):
                    raise EmbeddingError("embedding response contains invalid values")
            return [[float(value) for value in vector] for vector in vectors]
        except (EmbeddingError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, EmbeddingError):
                raise
            raise EmbeddingError("embedding response is invalid") from exc
