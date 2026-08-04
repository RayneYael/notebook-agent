import pytest

from app.connectors.base import Cue
from app.ingest.validate import EmptySuccess, guard_transcript


def test_http_200_empty_body_is_failure_not_no_text():
    with pytest.raises(EmptySuccess, match="empty body"):
        guard_transcript(b"", [], platform="youtube")


def test_nonempty_body_without_text_cues_is_failure():
    with pytest.raises(EmptySuccess, match="0 text cues"):
        guard_transcript(b'{"events":[]}', [], platform="youtube")


def test_valid_transcript_passes():
    guard_transcript(b"{}", [Cue(0, 1, "hello")])
