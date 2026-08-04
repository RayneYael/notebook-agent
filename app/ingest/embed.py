"""Small injectable client for OpenAI-compatible embedding APIs."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingError(RuntimeError):
    pass


class OpenAIEmbedder:
    def __init__(self, api_key: str, *, model: str = "text-embedding-3-small", endpoint: str = "https://api.openai.com/v1/embeddings") -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for embedding")
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": texts, "dimensions": 1536}).encode()
        request = Request(self.endpoint, data=payload, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=60) as response:
                data = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmbeddingError(f"embedding request failed: {exc}") from exc
        ordered = sorted(data.get("data", []), key=lambda row: row["index"])
        if len(ordered) != len(texts):
            raise EmbeddingError("embedding response count mismatch")
        return [row["embedding"] for row in ordered]
