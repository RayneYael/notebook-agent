"""Guards against HTTP-success responses which contain no usable content."""

try:
    from prometheus_client import Counter
except ImportError:  # Keeps core guards usable in minimal/offline test installs.
    class Counter:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.value = 0

        def labels(self, **kwargs):
            return self

        def inc(self):
            self.value += 1

from app.connectors.base import Cue, TransientFetchError


EMPTY_SUCCESS_TOTAL = Counter(
    "kb_empty_success_total", "HTTP success responses without usable content", ["platform"]
)


class EmptySuccess(TransientFetchError):
    pass


class IngestLimitExceeded(ValueError):
    """Stable terminal error for content that exceeds configured hard limits."""

    error_code = "ingest_too_large"

    def __init__(self) -> None:
        super().__init__(self.error_code)


def guard_ingest_limits(
    body: bytes,
    parsed_cues: list[Cue],
    *,
    max_raw_bytes: int,
    max_cues: int,
    max_text_chars: int,
) -> None:
    if len(body) > max_raw_bytes or len(parsed_cues) > max_cues:
        raise IngestLimitExceeded()
    if sum(len(cue.text) for cue in parsed_cues) > max_text_chars:
        raise IngestLimitExceeded()


def guard_transcript(body: bytes, parsed_cues: list[Cue], *, platform: str = "youtube") -> None:
    if not body:
        EMPTY_SUCCESS_TOTAL.labels(platform=platform).inc()
        raise EmptySuccess("empty body on HTTP 200")
    if not any(cue.text.strip() for cue in parsed_cues):
        EMPTY_SUCCESS_TOTAL.labels(platform=platform).inc()
        raise EmptySuccess("parsed 0 text cues from non-empty body")


def guard_article(text: str, *, platform: str = "wechat_mp") -> None:
    if len(text.strip()) < 50:
        EMPTY_SUCCESS_TOTAL.labels(platform=platform).inc()
        raise EmptySuccess(f"article text too short: {len(text.strip())}")
