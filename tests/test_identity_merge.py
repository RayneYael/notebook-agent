import pytest

from app.channels.errors import IdentityConflict
from app.channels.identity import _merge_why_saved


def _merge(source: str | None, target: str | None) -> str | None:
    return _merge_why_saved(source, target, 1, 2, 1, 2)


def test_identity_note_merge_preserves_exact_500_character_boundary():
    source = "a" * 240
    target = "b" * 241

    merged = _merge(source, target)

    assert merged == f"[source] {source} [target] {target}"
    assert len(merged) == 500


def test_identity_note_merge_refuses_lossy_overflow():
    with pytest.raises(IdentityConflict, match="too long to merge"):
        _merge("a" * 500, "b" * 500)


def test_identity_note_merge_keeps_one_shared_max_length_value():
    note = "x" * 500
    assert _merge(note, note) == note
