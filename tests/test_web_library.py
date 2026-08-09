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
        "platform": "youtube",
        "kind": "video",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Example video",
        "author": "Example author",
        "published_at": None,
        "duration_sec": None,
        "lang": None,
        "description": None,
        "tags": None,
        "chapters": None,
        "cover_url": None,
        "saved_at": datetime.now(UTC),
        "why_saved": None,
        "text_source": "none",
        "state": "pending",
        "fail_reason": None,
        "archived_at": None,
        "deleted_at": None,
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


def test_update_why_saved_rejects_501_characters_before_database_access():
    service = ContentLibraryService(
        lambda: (_ for _ in ()).throw(AssertionError("database must stay untouched")),
        lambda _value: "task",
    )

    with pytest.raises(LibraryConflict) as caught:
        service.update_why_saved(
            SimpleNamespace(app_user_id=7),
            "item-public",
            "x" * 501,
        )

    assert caught.value.error_code == "why_saved_too_long"


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


class Result:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values

    def one_or_none(self):
        return self.values


class QuerySession(ScalarSession):
    def __init__(self, scalar_values=(), scalars_values=(), execute_values=()):
        super().__init__(scalar_values)
        self.scalars_values = list(scalars_values)
        self.execute_values = list(execute_values)

    def scalars(self, statement):
        self.statements.append(statement)
        return Result(self.scalars_values.pop(0))

    def execute(self, statement):
        self.statements.append(statement)
        return Result(self.execute_values.pop(0))


def test_cross_tenant_public_id_is_indistinguishable_from_missing():
    db = ScalarSession([None])
    service = ContentLibraryService(lambda: db, lambda _dispatch_id: "task")

    with pytest.raises(LibraryNotFound) as caught:
        service.get_item(SimpleNamespace(app_user_id=7), "other-tenant-item")

    assert caught.value.error_code == "not_found"
    sql = str(db.statements[0])
    assert "content_item.user_id" in sql
    assert "content_item.public_id" in sql
    assert "content_item.deleted_at IS NULL" in sql


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
    assert "content_item.deleted_at IS NULL" in latest_sql


def test_list_count_items_and_latest_dispatches_share_deleted_and_tenant_fences():
    db = QuerySession(
        scalar_values=[1],
        scalars_values=[[item()], [dispatch(state="enqueued")]],
    )

    page = ContentLibraryService(lambda: db, lambda _value: "task").list_items(
        SimpleNamespace(app_user_id=7)
    )

    assert page.total == 1
    assert page.is_true_first_empty is False
    assert len(db.statements) == 3
    count_sql, items_sql, latest_sql = (str(value) for value in db.statements)
    assert "content_item.user_id" in count_sql
    assert "content_item.deleted_at IS NULL" in count_sql
    assert "content_item.user_id" in items_sql
    assert "content_item.deleted_at IS NULL" in items_sql
    assert "content_item.archived_at IS NULL" in items_sql
    assert "content_item.user_id" in latest_sql
    assert "content_item.deleted_at IS NULL" in latest_sql


def test_archived_filter_remains_independent_from_deleted_visibility():
    db = QuerySession(scalar_values=[0], scalars_values=[[]])

    ContentLibraryService(lambda: db, lambda _value: "task").list_items(
        SimpleNamespace(app_user_id=7), lifecycle="archived"
    )

    items_sql = str(db.statements[1])
    assert "content_item.deleted_at IS NULL" in items_sql
    assert "content_item.archived_at IS NOT NULL" in items_sql


def test_collection_filter_uses_an_exact_hashtag_token_not_a_like_wildcard():
    db = QuerySession(scalar_values=[0], scalars_values=[[]])

    ContentLibraryService(lambda: db, lambda _value: "task").list_items(
        SimpleNamespace(app_user_id=7), collection="AI_入门"
    )

    statement = db.statements[1]
    items_sql = str(statement)
    assert "~*" in items_sql
    assert "why_saved" in items_sql
    assert any("#AI_入门" in str(value) for value in statement.compile().params.values())


@pytest.mark.parametrize("collection", ["#AI", "bad name", "a" * 21])
def test_collection_filter_rejects_invalid_names(collection):
    service = ContentLibraryService(
        lambda: (_ for _ in ()).throw(AssertionError("database must stay untouched")),
        lambda _value: "task",
    )

    with pytest.raises(LibraryConflict) as caught:
        service.list_items(SimpleNamespace(app_user_id=7), collection=collection)

    assert caught.value.error_code == "invalid_collection"


@pytest.mark.parametrize("action", ["archive", "restore"])
def test_deleted_items_are_not_found_by_archive_actions(action):
    db = ScalarSession([None])
    service = ContentLibraryService(lambda: db, lambda _value: "task")

    with pytest.raises(LibraryNotFound) as caught:
        getattr(service, action)(SimpleNamespace(app_user_id=7), "deleted-item")

    assert caught.value.error_code == "not_found"
    sql = str(db.statements[0])
    assert "content_item.user_id" in sql
    assert "content_item.public_id" in sql
    assert "content_item.deleted_at IS NULL" in sql


def test_deleted_item_dispatch_is_not_found():
    db = QuerySession(execute_values=[None])
    service = ContentLibraryService(lambda: db, lambda _value: "task")

    with pytest.raises(LibraryNotFound) as caught:
        service.get_dispatch(SimpleNamespace(app_user_id=7), "deleted-dispatch")

    assert caught.value.error_code == "not_found"
    sql = str(db.statements[0])
    assert "content_item.user_id" in sql
    assert "content_item.deleted_at IS NULL" in sql


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


def test_retry_rejects_archived_item_before_idempotency_replay():
    class AcceptingQuota:
        def acquire_locks(self, _db, _app_user_id):
            return True

        def enforce(self, *_args, **_kwargs):
            pytest.fail("archived retry must not reach quota enforcement")

    archived = item(state="failed", archived_at=datetime.now(UTC))
    db = ScalarSession(
        [archived, dispatch(state="failed"), dispatch(state="failed")]
    )
    published = []
    service = ContentLibraryService(
        lambda: db,
        lambda value: published.append(value) or "task",
        quota_policy=AcceptingQuota(),
    )

    with pytest.raises(LibraryConflict) as caught:
        service.retry(
            SimpleNamespace(app_user_id=7),
            "item-public",
            request_key="user:retry:archived",
        )

    assert caught.value.error_code == "retry_unavailable"
    assert published == []


def test_retry_treats_deleted_item_as_not_found_before_dispatch_lookup():
    class AcceptingQuota:
        def acquire_locks(self, _db, _app_user_id):
            return True

        def enforce(self, *_args, **_kwargs):
            pytest.fail("deleted retry must not reach quota enforcement")

    db = ScalarSession([None])
    published = []
    service = ContentLibraryService(
        lambda: db,
        lambda value: published.append(value) or "task",
        quota_policy=AcceptingQuota(),
    )

    with pytest.raises(LibraryNotFound) as caught:
        service.retry(
            SimpleNamespace(app_user_id=7),
            "deleted-item",
            request_key="user:retry:deleted",
        )

    assert caught.value.error_code == "not_found"
    assert published == []
    sql = str(db.statements[0])
    assert "content_item.user_id" in sql
    assert "content_item.deleted_at IS NULL" in sql


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


def test_retry_publish_failure_converges_even_if_delete_wins_the_race():
    content = item(
        state="pending",
        deleted_at=datetime.now(UTC),
    )
    pending = dispatch(state="pending")

    class TransitionSession(QuerySession):
        def __init__(self):
            super().__init__(execute_values=[(pending, content)])
            self.committed = False

        def commit(self):
            self.committed = True

    db = TransitionSession()
    service = ContentLibraryService(lambda: db, lambda _value: "task")

    service._set_dispatch(
        pending.id,
        content.user_id,
        "failed",
        error_code="queue_unavailable",
    )

    assert pending.state == "failed"
    assert pending.error_code == "queue_unavailable"
    assert content.state == "failed"
    assert content.fail_reason == "queue_unavailable"
    assert db.committed is True
    convergence_sql = str(db.statements[0])
    assert "content_item.user_id" in convergence_sql
    assert "content_item.deleted_at IS NULL" not in convergence_sql


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
