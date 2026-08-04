"""YouTube connector backed by yt-dlp; no platform cookies are persisted."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.connectors.base import Cue, ItemMeta, NeedsASR, TextResult, TransientFetchError
from app.ingest.validate import guard_transcript


_ID_RE = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?.*?v=|shorts/|embed/))([\w-]{11})")


def _normalise_language(value: object) -> str:
    return value.strip().lower().replace("_", "-") if isinstance(value, str) else ""


def _base_language(value: object) -> str:
    return _normalise_language(value).split("-", 1)[0]


def parse_json3(body: bytes) -> list[Cue]:
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransientFetchError("invalid json3 subtitle response") from exc
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise TransientFetchError("json3 subtitle response has no events array")
    cues: list[Cue] = []
    for event in data["events"]:
        if not isinstance(event, dict) or "tStartMs" not in event:
            continue
        segments = event.get("segs", [])
        if not isinstance(segments, list):
            raise TransientFetchError("json3 subtitle event has invalid segments")
        text = "".join(
            seg.get("utf8", "") for seg in segments if isinstance(seg, dict)
        )
        text = " ".join(text.replace("\n", " ").split())
        if not text:
            continue
        try:
            start = float(event["tStartMs"]) / 1000
            duration = float(event.get("dDurationMs", 0)) / 1000
        except (TypeError, ValueError) as exc:
            raise TransientFetchError("json3 subtitle event has invalid timing") from exc
        cues.append(Cue(start, start + max(duration, 0.01), text))
    return cues


class YouTubeConnector:
    platform = "youtube"

    def __init__(self, *, runner=subprocess.run) -> None:
        self._runner = runner
        self._meta: dict[str, dict] = {}

    def match(self, url: str) -> str | None:
        match = _ID_RE.search(url)
        return match.group(1) if match else None

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        result = self._runner(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "--extractor-args",
                "youtube:player_client=android_vr",
                *args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            message = result.stderr.strip() or "yt-dlp failed"
            if "429" in message or "Too Many Requests" in message:
                raise TransientFetchError(f"YouTube rate limited this video: {message}")
            raise TransientFetchError(message)
        return result

    def fetch_meta(self, platform_id: str) -> ItemMeta:
        url = f"https://www.youtube.com/watch?v={platform_id}"
        result = self._run(["--no-playlist", "--skip-download", "--dump-single-json", url])
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise TransientFetchError("yt-dlp returned invalid metadata JSON") from exc
        self._meta[platform_id] = data
        uploaded = data.get("timestamp")
        return ItemMeta(
            platform_id=platform_id,
            url=url,
            title=data.get("title"),
            author=data.get("uploader") or data.get("channel"),
            published_at=datetime.fromtimestamp(uploaded, timezone.utc) if uploaded else None,
            duration_sec=round(data["duration"]) if data.get("duration") else None,
            lang=(data.get("language") or "").split("-")[0] or None,
            description=data.get("description"),
            tags=data.get("tags") or [],
            chapters=data.get("chapters") or [],
            cover_url=data.get("thumbnail"),
        )

    def _select_track(self, data: dict) -> tuple[str, str] | None:
        target = _normalise_language(data.get("language"))
        target_base = _base_language(target)
        candidates: list[tuple[str, str, tuple[int, int, int, int]]] = []
        sources = (
            ("official_cc", data.get("subtitles") or {}),
            ("auto_caption", data.get("automatic_captions") or {}),
        )
        for source_priority, (source_key, source) in enumerate(sources):
            for position, lang in enumerate(source):
                if not isinstance(lang, str):
                    continue
                normalised = _normalise_language(lang)
                base = _base_language(normalised)
                is_original = normalised.endswith("-orig")
                if target_base and base == target_base:
                    group = 0
                    precision = (
                        0 if normalised == f"{target}-orig"
                        else 1 if normalised == target
                        else 2 if normalised == f"{target_base}-orig"
                        else 3
                    )
                elif is_original:
                    group, precision = 1, 0
                elif base == "en":
                    group, precision = 2, 0
                elif base == "zh":
                    group, precision = 3, 0
                else:
                    group, precision = 4, 0
                candidates.append((source_key, lang, (group, source_priority, precision, position)))
        if not candidates:
            return None
        source, lang, _ = min(candidates, key=lambda candidate: candidate[2])
        return source, lang

    def fetch_text(self, platform_id: str) -> TextResult | NeedsASR:
        data = self._meta.get(platform_id)
        if data is None:
            self.fetch_meta(platform_id)
            data = self._meta[platform_id]
        selected = self._select_track(data)
        if selected is None:
            return NeedsASR()
        source, lang = selected
        url = f"https://www.youtube.com/watch?v={platform_id}"
        with tempfile.TemporaryDirectory(prefix="kb-ytdlp-") as temp_dir:
            output = str(Path(temp_dir) / "subtitle")
            flags = ["--write-subs"] if source == "official_cc" else ["--write-auto-subs"]
            self._run(["--no-playlist", "--skip-download", *flags, "--sub-langs", lang, "--sub-format", "json3", "-o", output, url])
            paths = sorted(Path(temp_dir).glob("*.json3"))
            if len(paths) > 1:
                raise TransientFetchError(
                    f"yt-dlp wrote multiple json3 tracks for requested language {lang}"
                )
            body = paths[0].read_bytes() if paths else b""
        cues = parse_json3(body) if body else []
        guard_transcript(body, cues, platform=self.platform)
        return TextResult(body, cues, source, _base_language(lang))
