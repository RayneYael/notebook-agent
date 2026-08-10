import json
import subprocess

import pytest

from app.connectors.base import NeedsASR, TransientFetchError
from app.connectors.bounded_fetch import fetch_bounded
from app.connectors.youtube import YouTubeConnector, parse_json3
from app.ingest.validate import IngestLimitExceeded


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


def test_select_track_prefers_original_english_over_chinese_translation():
    connector = YouTubeConnector()
    data = {
        "language": "en-US",
        "subtitles": {},
        "automatic_captions": {
            "zh-Hans": [{}],
            "en-orig": [{}],
        },
    }

    assert connector._select_track(data) == ("auto_caption", "en-orig")


def test_select_track_prefers_official_caption_when_both_match_original_language():
    connector = YouTubeConnector()
    data = {
        "language": "en",
        "subtitles": {"en": [{}]},
        "automatic_captions": {"en-orig": [{}]},
    }

    assert connector._select_track(data) == ("official_cc", "en")


def test_select_track_prefers_automatic_original_language_over_official_translation():
    connector = YouTubeConnector()
    data = {
        "language": "en",
        "subtitles": {"zh-Hans": [{}]},
        "automatic_captions": {"en-orig": [{}]},
    }

    assert connector._select_track(data) == ("auto_caption", "en-orig")


def test_select_track_uses_orig_marker_when_metadata_language_is_missing():
    connector = YouTubeConnector()
    data = {
        "subtitles": {},
        "automatic_captions": {
            "zh-Hans": [{}],
            "en": [{}],
            "fr-orig": [{}],
        },
    }

    assert connector._select_track(data) == ("auto_caption", "fr-orig")


def test_select_track_normalises_underscore_language_codes():
    connector = YouTubeConnector()
    data = {
        "language": "pt_BR",
        "subtitles": {"pt-BR": [{}]},
        "automatic_captions": {"zh-Hans": [{}]},
    }

    assert connector._select_track(data) == ("official_cc", "pt-BR")


def test_select_track_falls_back_to_english_before_chinese():
    connector = YouTubeConnector()
    data = {
        "subtitles": {},
        "automatic_captions": {
            "zh-Hans": [{}],
            "en": [{}],
        },
    }

    assert connector._select_track(data) == ("auto_caption", "en")


def test_fetch_text_returns_needs_asr_when_no_caption_tracks_exist():
    connector = YouTubeConnector()
    connector._meta["dQw4w9WgXcQ"] = {
        "subtitles": {},
        "automatic_captions": {},
    }

    assert isinstance(connector.fetch_text("dQw4w9WgXcQ"), NeedsASR)


class _Response:
    def __init__(self, body: bytes, content_length: str | None = None):
        self._body = body
        self._position = 0
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int) -> bytes:
        chunk = self._body[self._position : self._position + size]
        self._position += len(chunk)
        return chunk


def test_bounded_fetch_rejects_content_length_before_reading_body():
    response = _Response(b"x" * 11, content_length="11")

    with pytest.raises(IngestLimitExceeded):
        fetch_bounded(
            "https://www.youtube.com/api/timedtext",
            headers=None,
            max_bytes=10,
            socket_timeout_seconds=1,
            opener=lambda *_args, **_kwargs: response,
        )

    assert response._position == 0


def test_bounded_fetch_stream_stops_after_limit_without_disk_file():
    response = _Response(b"x" * 11)

    with pytest.raises(IngestLimitExceeded):
        fetch_bounded(
            "https://www.youtube.com/api/timedtext",
            headers=None,
            max_bytes=10,
            socket_timeout_seconds=1,
            opener=lambda *_args, **_kwargs: response,
        )

    assert response._position == 11


def test_fetch_text_uses_bounded_child_process_without_ytdlp_file_download():
    body = json.dumps(
        {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "hello"}]}]}
    ).encode()
    calls = []

    class Result:
        returncode = 0
        stdout = body
        stderr = b""

    connector = YouTubeConnector(
        subtitle_runner=lambda args, **kwargs: calls.append((args, kwargs)) or Result(),
        fetch_timeout_seconds=7,
    )
    connector._meta["dQw4w9WgXcQ"] = {
        "language": "en",
        "subtitles": {
            "en": [
                {
                    "ext": "json3",
                    "url": "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ",
                }
            ]
        },
        "automatic_captions": {},
    }

    result = connector.fetch_text("dQw4w9WgXcQ")

    assert result.cues[0].text == "hello"
    assert calls[0][0][-2:] == ["-m", "app.connectors.bounded_fetch"]
    assert calls[0][1]["timeout"] == 7
    assert b'"max_bytes": 5000000' in calls[0][1]["input"]


def test_fetch_text_terminates_timed_out_bounded_child():
    def timed_out(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    connector = YouTubeConnector(subtitle_runner=timed_out, fetch_timeout_seconds=0.1)
    connector._meta["dQw4w9WgXcQ"] = {
        "language": "en",
        "subtitles": {
            "en": [
                {
                    "ext": "json3",
                    "url": "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ",
                }
            ]
        },
        "automatic_captions": {},
    }

    with pytest.raises(TransientFetchError, match="subtitle_fetch_timeout"):
        connector.fetch_text("dQw4w9WgXcQ")


def test_ytdlp_metadata_call_has_hard_wall_clock_timeout():
    seen = {}

    def timed_out(args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    connector = YouTubeConnector(runner=timed_out, fetch_timeout_seconds=0.25)

    with pytest.raises(TransientFetchError, match="youtube_fetch_timeout"):
        connector.fetch_meta("dQw4w9WgXcQ")

    assert seen["timeout"] == 0.25
