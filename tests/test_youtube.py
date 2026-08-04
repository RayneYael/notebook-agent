import json

import pytest

from app.connectors.base import NeedsASR, TransientFetchError
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
