"""Shared product limits used at every trusted write boundary."""

MAX_WHY_SAVED_CHARS = 500


def normalize_why_saved(value: str | None) -> str | None:
    """Normalize a save note without silently truncating it."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid_why_saved")
    normalized = " ".join(value.split())
    if len(normalized) > MAX_WHY_SAVED_CHARS:
        raise ValueError("why_saved_too_long")
    return normalized or None
