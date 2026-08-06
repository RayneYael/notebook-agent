import io
import json

import pytest

from app.ingest.embed import EmbeddingError, ZhipuEmbedder


def _response(data):
    return io.BytesIO(json.dumps({"data": data}).encode())


def test_embed_splits_inputs_into_ordered_batches_of_64(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout, context):
        payload = json.loads(request.data)
        calls.append((request, timeout, context, payload))
        rows = [
            {"index": index, "embedding": [float(text.removeprefix("cue-"))]}
            for index, text in enumerate(payload["input"])
        ]
        return _response(list(reversed(rows)))

    monkeypatch.setattr("app.ingest.embed.urlopen", fake_urlopen)
    embedder = ZhipuEmbedder("secret", dimensions=1)

    embeddings = embedder.embed([f"cue-{index}" for index in range(130)])

    assert [len(call[3]["input"]) for call in calls] == [64, 64, 2]
    assert embeddings == [[float(index)] for index in range(130)]
    assert all(call[1] == 60 for call in calls)
    assert all(call[2] is None for call in calls)
    assert all(call[3]["model"] == "embedding-3" for call in calls)
    assert all(call[3]["dimensions"] == 1 for call in calls)
    assert all(call[0].get_header("Authorization") == "Bearer secret" for call in calls)


def test_embed_empty_input_does_not_call_api(monkeypatch):
    monkeypatch.setattr(
        "app.ingest.embed.urlopen",
        lambda *_args, **_kwargs: pytest.fail("API should not be called"),
    )
    assert ZhipuEmbedder("secret").embed([]) == []


def test_embed_rejects_batch_size_above_zhipu_limit():
    with pytest.raises(ValueError, match="between 1 and 64"):
        ZhipuEmbedder("secret", batch_size=65)


def test_embed_rejects_incomplete_batch_response(monkeypatch):
    monkeypatch.setattr(
        "app.ingest.embed.urlopen",
        lambda *_args, **_kwargs: _response(
            [{"index": 0, "embedding": [1.0]}]
        ),
    )

    with pytest.raises(EmbeddingError, match="response count mismatch"):
        ZhipuEmbedder("secret").embed(["first", "second"])


@pytest.mark.parametrize(
    ("embedding", "message"),
    [([1.0], "dimension mismatch"), ([float("nan"), 1.0], "invalid values")],
)
def test_embed_rejects_invalid_vector_shape_or_values(monkeypatch, embedding, message):
    monkeypatch.setattr(
        "app.ingest.embed.urlopen",
        lambda *_args, **_kwargs: _response([{"index": 0, "embedding": embedding}]),
    )

    with pytest.raises(EmbeddingError, match=message):
        ZhipuEmbedder("secret", dimensions=2).embed(["redacted-input"])


def test_embed_rejects_non_positive_dimensions():
    with pytest.raises(ValueError, match="dimensions must be positive"):
        ZhipuEmbedder("secret", dimensions=0)
