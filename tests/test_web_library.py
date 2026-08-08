from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.ingest.submission import IngestQuotaExceeded
from app.web.library import (
    ContentLibraryService,
    LibraryConflict,
    LibraryNotFound,
    project_lifecycle,
)
from app.retrieval.search import bm25_search, vector_search


def item(**overrides):
    values = {
        "id": 41,
        "public_id": "item-public",
        "user_id": 7,
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "state": "pending",
        "fail_reason": None,
        "archived_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def dispatch(**overrides):
    values = {
        "id": 71,
        "public_id": "dispatch-public",
        "item_id": 41,
        "attempt": 1,
        "state": "pending",
        "error_code": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("content", "latest", "expected_state", "expected_error"),
    [
        (item(archived_at=datetime.now(UTC)), dispatch(state="running"), "archived", None),
        (item(state="ready"), dispatch(state="failed"), "ready", None),
        (item(state="needs_asr"), None, "needs_action", None),
        (item(state="pending"), dispatch(state="failed", error_code="queue_unavailable"), "failed", "queue_unavailable"),
        (item(state="failed", fail_reason="private stack trace"), None, "failed", "ingestion_failed"),
        (item(state="fetching"), dispatch(state="running"), "processing", None),
        (item(state="pending"), dispatch(state="enqueued"), "queued", None),
        (item(state="pending"), None, "failed", "missing_dispatch"),
    ],
)
def test_lifecycle_precedence_and_safe_errors(content, latest, expected_state, expected_error):
    projected = project_lifecycle(content, latest)

    assert projected.state == expected_state
    assert projected.error_code == expected_error
    assert "private stack trace" not in repr(projected)


def test_available_actions_are_server_derived():
    assert project_lifecycle(item(state="ready"), dispatch(state="completed")).available_actions == (
        "edit_why_saved", "archive", "open_source"
    )
    assert project_lifecycle(item(archived_at=datetime.now(UTC)), None).available_actions == ("restore",)
    assert project_lifecycle(item(state="failed"), dispatch(state="failed")).available_actions == (
        "edit_why_saved", "archive", "retry", "open_source"
    )
    assert "retry" not in project_lifecycle(item(state="failed"), dispatch(state="running")).available_actions


class ScalarSession:
    def __init__(self, values):
        self.values = list(values)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def scalar(self, statement):
        self.statements.append(statement)
        return self.values.pop(0)


def test_cross_tenant_public_id_is_indistinguishable_from_missing():
    db = ScalarSession([None])
    service = ContentLibraryService(lambda: db, lambda _dispatch_id: "task")

    with pytest.raises(LibraryNotFound) as caught:
        service.get_item(SimpleNamespace(app_user_id=7), "other-tenant-item")

    assert caught.value.error_code == "not_found"
    sql = str(db.statements[0])
    assert "content_item.user_id" in sql
    assert "content_item.public_id" in sql


def test_latest_dispatch_lookup_repeats_the_tenant_predicate():
    content = item(
        platform="youtube",
        kind="video",
        title=None,
        author=None,
        published_at=None,
        duration_sec=None,
        lang=None,
        description=None,
        tags=None,
        chapters=None,
        cover_url=None,
        saved_at=datetime.now(UTC),
        why_saved=None,
        text_source="none",
    )
    db = ScalarSession([content, dispatch(state="enqueued")])

    ContentLibraryService(lambda: db, lambda _value: "task").get_item(
        SimpleNamespace(app_user_id=7), "item-public"
    )

    latest_sql = str(db.statements[1])
    assert "content_item.user_id" in latest_sql
    assert "content_item.id = ingest_dispatch.item_id" in latest_sql


def test_retry_rejects_active_dispatch_without_publishing():
    db = ScalarSession([item(state="failed"), None, dispatch(state="running")])
    published = []
    service = ContentLibraryService(lambda: db, lambda value: published.append(value) or "task")

    with pytest.raises(LibraryConflict) as caught:
        service.retry(
            SimpleNamespace(app_user_id=7),
            "item-public",
            request_key="user:retry",
        )

    assert caught.value.error_code == "retry_unavailable"
    assert published == []


def test_retry_is_disabled_by_the_global_save_switch_before_database_access():
    published = []
    service = ContentLibraryService(
        lambda: (_ for _ in ()).throw(AssertionError("database must stay untouched")),
        lambda value: published.append(value) or "task",
        save_enabled=False,
    )

    with pytest.raises(LibraryConflict) as caught:
        service.retry(
            SimpleNamespace(app_user_id=7),
            "item-public",
            request_key="user:retry:read-only",
            publish_budget_seconds=0.25,
        )

    assert caught.value.error_code == "save_disabled"
    assert published == []


def test_retry_passes_the_remaining_web_budget_to_the_broker_publisher(monkeypatch):
    class RetrySession(ScalarSession):
        def add(self, value):
            self.added = value
            value.id = 72

        def flush(self):
            return None

        def commit(self):
            return None

    db = RetrySession([item(state="failed"), None, dispatch(state="failed")])
    observed = []

    def publish(dispatch_id, *, remaining_budget_seconds):
        observed.append((dispatch_id, remaining_budget_seconds))
        return "task"

    service = ContentLibraryService(lambda: db, publish)
    monkeypatch.setattr(service, "_set_dispatch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "get_item", lambda *_args, **_kwargs: "updated")

    result = service.retry(
        SimpleNamespace(app_user_id=7),
        "item-public",
        request_key="user:retry:budget",
        publish_budget_seconds=0.25,
    )

    assert result == "updated"
    assert observed[0][0] == 72
    assert 0 < observed[0][1] <= 0.25


def test_retry_marks_the_dispatch_unavailable_when_web_budget_is_exhausted(
    monkeypatch,
):
    class RetrySession(ScalarSession):
        def add(self, value):
            self.added = value
            value.id = 72

        def flush(self):
            return None

        def commit(self):
            return None

    db = RetrySession([item(state="failed"), None, dispatch(state="failed")])
    published = []
    transitions = []
    service = ContentLibraryService(
        lambda: db,
        lambda dispatch_id, **kwargs: published.append((dispatch_id, kwargs)),
    )
    clock = iter((10.0, 10.3))
    monkeypatch.setattr("app.web.library.time.monotonic", lambda: next(clock))
    monkeypatch.setattr(
        service,
        "_set_dispatch",
        lambda *args, **kwargs: transitions.append((args, kwargs)),
    )
    monkeypatch.setattr(service, "get_item", lambda *_args, **_kwargs: "updated")

    result = service.retry(
        SimpleNamespace(app_user_id=7),
        "item-public",
        request_key="user:retry:exhausted",
        publish_budget_seconds=0.25,
    )

    assert result == "updated"
    assert published == []
    assert transitions == [
        ((72, 7, "failed"), {"error_code": "queue_unavailable"})
    ]


def test_retry_uses_the_shared_active_ingest_quota_before_publishing():
    class RejectingQuota:
        def acquire_locks(self, _db, _app_user_id):
            return True

        def enforce(self, _db, _app_user_id, *, include_new_item_limits):
            assert include_new_item_limits is False
            raise IngestQuotaExceeded

    db = ScalarSession([item(state="failed"), None, dispatch(state="failed")])
    published = []
    service = ContentLibraryService(
        lambda: db,
        lambda value: published.append(value) or "task",
        quota_policy=RejectingQuota(),
    )

    with pytest.raises(LibraryConflict) as caught:
        service.retry(
            SimpleNamespace(app_user_id=7),
            "item-public",
            request_key="user:retry:quota",
        )

    assert caught.value.error_code == "quota_exceeded"
    assert published == []


def test_every_search_statement_excludes_archived_items():
    class Result:
        def all(self):
            return []

    class DB:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            return Result()

    db = DB()

    assert vector_search(db, [0.01] * 1536, user_id=7) == []
    assert bm25_search(db, "evidence", user_id=7) == []

    assert len(db.statements) == 2
    assert all("content_item.archived_at IS NULL" in str(value) for value in db.statements)
