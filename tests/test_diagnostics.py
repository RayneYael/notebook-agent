import logging

from app.diagnostics import RequestDiagnostics


def test_diagnostics_emit_only_stable_fields(caplog):
    diagnostics = RequestDiagnostics.start("request-1", 7)
    private_message = "private question and secret-looking payload"

    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        diagnostics.event(
            "embedding_failed",
            error_code="embedding_unavailable",
            exception=RuntimeError(private_message),
        )

    text = caplog.text
    assert "request-1" in text
    assert "embedding_unavailable" in text
    assert "RuntimeError" in text
    assert private_message not in text
