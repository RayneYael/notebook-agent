import json
import logging
from datetime import date
from pathlib import Path

from app.diagnostics import RequestDiagnostics


def test_diagnostics_emit_only_stable_fields(caplog):
    diagnostics = RequestDiagnostics.start("a" * 32, 7)
    private_message = "private question and secret-looking payload"

    with caplog.at_level(logging.INFO, logger="notebook_agent.runtime"):
        diagnostics.event(
            "embedding_failed",
            error_code="embedding_unavailable",
            exception=RuntimeError(private_message),
        )

    payload = caplog.records[-1].diagnostic_payload
    assert payload["request_id"] == "a" * 32
    assert payload["error_code"] == "embedding_unavailable"
    assert payload["error_class"] == "RuntimeError"
    assert private_message not in json.dumps(payload)


def test_invalid_request_id_is_replaced_before_logging():
    private = "PRIVATE-request-body"
    payloads = []
    diagnostics = RequestDiagnostics.start(private, 7)
    assert diagnostics.request_id != private
    diagnostics.event("accepted")


def test_retrieval_content_is_explicitly_local_only(tmp_path: Path, capsys):
    from app.diagnostics import configure_runtime_logging, shutdown_runtime_logging

    configure_runtime_logging(log_dir=str(tmp_path))
    private = "history-prompt-model-output-secret"
    RequestDiagnostics.start("a" * 32, 1).retrieval_detail(
        tool_name="search_segments", call_index=1, query="allowed query", url="https://allowed", excerpt="allowed excerpt"
    )
    RequestDiagnostics.start("b" * 32, 1, allow_retrieval_content=True, environment="development").retrieval_detail(
        tool_name="search_segments", call_index=1, query="allowed query", url="https://allowed", excerpt="allowed excerpt"
    )
    output = capsys.readouterr().out
    disk = "\n".join(path.read_text() for path in tmp_path.glob("*.log*"))
    assert "allowed query" in output and "allowed query" in disk
    assert private not in output and private not in disk
    shutdown_runtime_logging()


def test_retrieval_detail_projects_score_without_tool_payload_leak(tmp_path: Path, capsys):
    from app.diagnostics import configure_runtime_logging, shutdown_runtime_logging
    from app.agent.types import Citation
    configure_runtime_logging(log_dir=str(tmp_path))
    citation = Citation(item_id=4, segment_id=8, title="title", excerpt="excerpt", url="https://url", start_sec=3)
    citation._retrieval_score = 0.875
    RequestDiagnostics.start("c" * 32, 2, allow_retrieval_content=True, environment="development").retrieval_detail(
        tool_name="search_segments", call_index=2, segment_id=citation.segment_id, score=citation._retrieval_score, title=citation.title, url=citation.url, excerpt=citation.excerpt
    )
    text = capsys.readouterr().out
    assert "0.875" in text
    assert "_retrieval_score" not in citation.model_dump()
    shutdown_runtime_logging()


def test_settings_reject_production_or_unknown_retrieval_content(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("NOTEBOOK_AGENT_ENV", "production")
    monkeypatch.setenv("NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT", "true")
    with __import__("pytest").raises(ValueError): Settings()
    monkeypatch.setenv("NOTEBOOK_AGENT_ENV", "unknown")
    monkeypatch.setenv("NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT", "false")
    with __import__("pytest").raises(ValueError): Settings()


def test_runtime_logging_dual_writes_and_keeps_private_sentinels_out(
    tmp_path: Path, capsys
):
    from app.diagnostics import configure_runtime_logging, shutdown_runtime_logging

    configure_runtime_logging(log_dir=str(tmp_path), max_bytes=100, backup_count=2)
    sentinel = "PRIVATE-question-prompt-output-url-token"
    RequestDiagnostics.start("r", 1, "a" * 32).event(
        "embedding_failed", error_code="embedding_unavailable", exception=RuntimeError(sentinel)
    )
    captured = capsys.readouterr().out
    contents = "\n".join(path.read_text() for path in tmp_path.glob("*.log*"))
    assert "embedding_unavailable" in captured and "embedding_unavailable" in contents
    assert sentinel not in captured and sentinel not in contents
    shutdown_runtime_logging()


def test_usage_limit_classifier_never_returns_original_text():
    from app.diagnostics import classify_usage_limit
    from pydantic_ai.exceptions import UsageLimitExceeded

    assert classify_usage_limit(
        UsageLimitExceeded("The next request would exceed the request_limit of 3")
    ) == ("request", 3, None)
    assert classify_usage_limit(
        UsageLimitExceeded("The next tool call(s) would exceed the tool_calls_limit of 7 (tool_calls=6)")
    ) == ("tool_calls", 7, 6)
    assert classify_usage_limit(
        UsageLimitExceeded("Exceeded the output_tokens_limit of 99 (output_tokens=101)")
    ) == ("output_tokens", 99, 101)
    assert classify_usage_limit(RuntimeError("PRIVATE sentinel")) == ("unknown", None, None)


def test_size_rotation_is_bounded_and_file_failure_keeps_stdout(
    tmp_path: Path, capsys
):
    from app.diagnostics import configure_runtime_logging, shutdown_runtime_logging

    configure_runtime_logging(log_dir=str(tmp_path), max_bytes=80, backup_count=2)
    diagnostics = RequestDiagnostics.start("request", 1, "b" * 32)
    for _ in range(8):
        diagnostics.event("accepted")
    assert len(list(tmp_path.glob("notebook-agent-*.log*"))) <= 3
    shutdown_runtime_logging()

    for invalid in (0, -1):
        try:
            configure_runtime_logging(log_dir=str(tmp_path), backup_count=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("zero/negative backup count must be rejected")
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("block")
    assert not configure_runtime_logging(log_dir=str(blocked))
    assert "file_logging_unavailable" in capsys.readouterr().out
    shutdown_runtime_logging()


def test_daily_handler_switches_to_the_current_date(tmp_path: Path):
    from app.diagnostics import DailySizeRotatingFileHandler

    handler = DailySizeRotatingFileHandler(tmp_path, max_bytes=1024, backup_count=1)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._active_day = date(2000, 1, 1)
    handler.emit(logging.makeLogRecord({"msg": "safe", "levelno": logging.INFO, "levelname": "INFO"}))
    assert (tmp_path / f"notebook-agent-{date.today().isoformat()}.log").exists()
    handler.close()


def test_later_file_sink_failure_reports_once_to_stdout(tmp_path: Path, capsys):
    from app.diagnostics import DailySizeRotatingFileHandler, LOGGER, configure_runtime_logging, shutdown_runtime_logging

    assert configure_runtime_logging(log_dir=str(tmp_path))
    file_handler = next(handler for handler in LOGGER.handlers if isinstance(handler, DailySizeRotatingFileHandler))
    record = logging.makeLogRecord({"msg": "safe", "levelno": logging.INFO, "levelname": "INFO"})
    file_handler.handleError(record)
    file_handler.handleError(record)
    output = capsys.readouterr().out
    assert output.count("file_logging_unavailable") == 1
    assert file_handler not in LOGGER.handlers
    shutdown_runtime_logging()


def test_emit_retention_failure_falls_back_without_raising(tmp_path: Path, capsys, monkeypatch):
    from app.diagnostics import DailySizeRotatingFileHandler, LOGGER, configure_runtime_logging, shutdown_runtime_logging

    configure_runtime_logging(log_dir=str(tmp_path))
    handler = next(value for value in LOGGER.handlers if isinstance(value, DailySizeRotatingFileHandler))
    monkeypatch.setattr(handler, "_trim_days", lambda: (_ for _ in ()).throw(OSError("PRIVATE")))
    LOGGER.info("diagnostic", extra={"diagnostic_payload": {"event": "safe"}})
    assert "file_logging_unavailable" in capsys.readouterr().out
    assert handler not in LOGGER.handlers
    shutdown_runtime_logging()
