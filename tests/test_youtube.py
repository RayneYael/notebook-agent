import json

import pytest

from app.connectors.base import TransientFetchError
from app.connectors.youtube import YouTubeConnector, parse_json3


def test_parse_json3_normalizes_timestamps_and_text():
    body = json.dumps({"events": [{"tStartMs": 1500, "dDurationMs": 2000, "segs": [{"utf8": "hello\n"}, {"utf8": "world"}]}]}).encode()
    cues = parse_json3(body)
    assert (cues[0].start, cues[0].end, cues[0].text) == (1.5, 3.5, "hello world")


def test_url_matching():
    connector = YouTubeConnector()
    assert connector.match("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert connector.match("https://example.com") is None


def test_429_is_transient_and_item_scoped():
    class Result:
        returncode = 1
        stdout = ""
        stderr = "HTTP Error 429: Too Many Requests"

    connector = YouTubeConnector(runner=lambda *a, **k: Result())
    with pytest.raises(TransientFetchError, match="rate limited this video"):
        connector.fetch_meta("dQw4w9WgXcQ")


def test_yt_dlp_uses_verified_android_vr_client():
    calls = []

    class Result:
        returncode = 0
        stdout = "{}"
        stderr = ""

    connector = YouTubeConnector(runner=lambda args, **kwargs: calls.append(args) or Result())
    connector.fetch_meta("dQw4w9WgXcQ")
    assert "--extractor-args" in calls[0]
    assert "youtube:player_client=android_vr" in calls[0]
