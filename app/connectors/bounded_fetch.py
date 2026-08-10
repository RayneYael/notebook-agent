"""Isolated, bounded HTTPS fetch used for provider-resolved subtitle URLs."""

from __future__ import annotations

import json
import socket
import sys
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.ingest.validate import IngestLimitExceeded


_ALLOWED_HOST_SUFFIXES = (".youtube.com", ".googlevideo.com")
_ALLOWED_HEADERS = frozenset({"accept", "accept-language", "user-agent"})
_CHUNK_BYTES = 64 * 1024
EXIT_CONTENT_TOO_LARGE = 10
EXIT_FETCH_FAILED = 11
EXIT_RATE_LIMITED = 12
EXIT_PROXY_UNAVAILABLE = 13
EXIT_PROXY_TIMEOUT = 14
EXIT_PROXY_AUTHENTICATION_FAILED = 15


def _proxy_url_error_exit_code(exc: URLError, *, proxy_enabled: bool) -> int:
    if not proxy_enabled:
        return EXIT_FETCH_FAILED
    reason = exc.reason
    reason_text = str(reason).lower()
    if "407" in reason_text or "proxy authentication required" in reason_text:
        return EXIT_PROXY_AUTHENTICATION_FAILED
    if isinstance(reason, (socket.timeout, TimeoutError)) or any(
        marker in reason_text for marker in ("timed out", "timeout")
    ):
        return EXIT_PROXY_TIMEOUT
    return EXIT_PROXY_UNAVAILABLE


def _trusted_https_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_url")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not any(host == suffix[1:] or host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES)
    ):
        raise ValueError("invalid_url")
    return value


def _safe_headers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(name): str(header_value)
        for name, header_value in value.items()
        if str(name).lower() in _ALLOWED_HEADERS
        and isinstance(header_value, str)
        and "\r" not in header_value
        and "\n" not in header_value
    }


def fetch_bounded(
    url: str,
    *,
    headers: Mapping[str, str] | None,
    max_bytes: int,
    socket_timeout_seconds: float,
    opener: Callable = urlopen,
) -> bytes:
    """Read at most ``max_bytes`` without creating a provider-controlled file."""

    if max_bytes <= 0 or socket_timeout_seconds <= 0:
        raise ValueError("invalid_limit")
    request = Request(
        _trusted_https_url(url),
        headers=_safe_headers(headers),
        method="GET",
    )
    with opener(request, timeout=socket_timeout_seconds) as response:
        raw_length = response.headers.get("Content-Length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                content_length = None
            if content_length is not None and content_length > max_bytes:
                raise IngestLimitExceeded()
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = response.read(min(_CHUNK_BYTES, max_bytes + 1 - total))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
        raise IngestLimitExceeded()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        body = fetch_bounded(
            payload["url"],
            headers=payload.get("headers"),
            max_bytes=int(payload["max_bytes"]),
            socket_timeout_seconds=float(payload["socket_timeout_seconds"]),
        )
    except IngestLimitExceeded:
        return EXIT_CONTENT_TOO_LARGE
    except HTTPError as exc:
        if exc.code == 429:
            return EXIT_RATE_LIMITED
        if payload.get("proxy_enabled") and exc.code == 407:
            return EXIT_PROXY_AUTHENTICATION_FAILED
        return EXIT_FETCH_FAILED
    except (socket.timeout, TimeoutError):
        if payload.get("proxy_enabled"):
            return EXIT_PROXY_TIMEOUT
        return EXIT_FETCH_FAILED
    except URLError as exc:
        return _proxy_url_error_exit_code(
            exc,
            proxy_enabled=bool(payload.get("proxy_enabled")),
        )
    except Exception:
        return EXIT_FETCH_FAILED
    sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
