import pytest

from dataclasses import replace
from datetime import UTC, datetime

from kombu import Connection

from app.connectors.base import (
    ItemMeta,
    NeedsASR,
    TransientFetchError,
)
from app.config import Settings
from app.ingest.tasks import (
    IngestTask,
    _claim_dispatch,
    _complete_dispatch,
    _release_dispatch_for_retry,
    build_worker_embedder,
    create_item,
    fetch_text_task,
    process_item,
    publish_ingest_dispatch,
    run_isolated_batch,
)
from app.models import AppUser, ContentItem, IngestDispatch
from app.tls import TrustedCA


def test_celery_task_declares_exponential_item_retry():
    assert fetch_text_task.max_retries == 5
    assert fetch_text_task.retry_backoff == 8
    assert fetch_text_task.retry_backoff_max == 600


def test_one_429_does_not_interrupt_fifteen_item_batch():
    attempts = {7: 0}
    sleeps = []
    calls = []

    def worker(item):
        calls.append(item)
        if item == 7 and attempts[7] == 0:
            attempts[7] += 1
            raise TransientFetchError("429")
        return item

    result = run_isolated_batch(list(range(15)), worker, sleep=sleeps.append)
    assert result == list(range(15))
    assert sleeps == [8]
    assert calls[:15] == list(range(15))
    assert calls[15:] == [7]


def test_retry_exhaustion_marks_dispatch_failed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.ingest.tasks._mark_dispatch_failed",
        lambda dispatch_id, exc, **_kwargs: calls.append(
            (dispatch_id, type(exc).__name__, _kwargs.get("task_id"))
        ),
    )
    IngestTask().on_failure(TransientFetchError("empty body"), "task", (41,), {}, None)
    assert calls == [(41, "TransientFetchError", "task")]


def test_retryable_first_failure_does_not_prematurely_mark_failed():
    class Item:
        id = 41
        platform_id = "dQw4w9WgXcQ"
        url = "https://youtu.be/dQw4w9WgXcQ"
        state = "fetching"

    item = Item()

    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, model, item_id): return item
        def commit(self): pass

    class Connector:
        def fetch_meta(self, platform_id): pass
        def fetch_text(self, platform_id): raise TransientFetchError("429")

    from app.ingest.tasks import process_item

    with pytest.raises(TransientFetchError, match="429"):
        process_item(41, connector=Connector(), session_factory=lambda: DB())
    assert item.state == "fetching"


def test_worker_fetches_and_persists_metadata_before_text():
    class Item:
        id = 41
        user_id = 57
        platform = "youtube"
        platform_id = "dQw4w9WgXcQ"
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        title = None
        author = None
        published_at = None
        duration_sec = None
        lang = None
        description = None
        tags = None
        chapters = None
        cover_url = None
        state = "pending"

    item = Item()
    commits = []

    class DB:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def get(self, _model, _item_id): return item
        def commit(self): commits.append(item.state)

    calls = []
    published_at = datetime(2026, 8, 6, tzinfo=UTC)

    class Connector:
        def fetch_meta(self, platform_id):
            calls.append(("meta", platform_id))
            return ItemMeta(
                platform_id=platform_id,
                url=item.url,
                title="worker title",
                author="worker author",
                published_at=published_at,
                duration_sec=42,
                lang="zh",
                description="worker description",
                tags=["worker"],
                chapters=[{"start": 0, "end": 42, "title": "all"}],
                cover_url="https://example.test/cover",
            )

        def fetch_text(self, platform_id):
            calls.append(("text", platform_id))
            return NeedsASR()

    state = process_item(
        item.id,
        connector=Connector(),
        session_factory=lambda: DB(),
    )

    assert state == "needs_asr"
    assert calls == [
        ("meta", item.platform_id),
        ("text", item.platform_id),
    ]
    assert commits == ["fetching", "needs_asr"]
    assert item.title == "worker title"
    assert item.author == "worker author"
    assert item.published_at == published_at
    assert item.duration_sec == 42
    assert item.tags == ["worker"]
    assert item.state == "needs_asr"


def test_cli_ingestion_fetches_metadata_exactly_once():
    class Store:
        item = None

    store = Store()

    class DB:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, model, object_id):
            if model is AppUser and object_id == 57:
                return object()
            if model is ContentItem and store.item is not None:
                return store.item
            return None

        def scalar(self, _statement):
            return None

        def add(self, value):
            if isinstance(value, ContentItem):
                value.id = 41
                store.item = value

        def commit(self):
            return None

    calls = []

    class Connector:
        platform = "youtube"

        def match(self, _url):
            return "dQw4w9WgXcQ"

        def fetch_meta(self, platform_id):
            calls.append(("meta", platform_id))
            return ItemMeta(
                platform_id=platform_id,
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                title="one fetch",
                author=None,
                published_at=None,
                duration_sec=None,
                lang=None,
                description=None,
                tags=None,
                chapters=None,
                cover_url=None,
            )

        def fetch_text(self, platform_id):
            calls.append(("text", platform_id))
            return NeedsASR()

    from app.ingest.tasks import ingest_url

    item_id, state = ingest_url(
        "https://youtu.be/dQw4w9WgXcQ",
        user_id=57,
        connector=Connector(),
        session_factory=lambda: DB(),
    )

    assert (item_id, state) == (41, "needs_asr")
    assert calls == [
        ("meta", "dQw4w9WgXcQ"),
        ("text", "dQw4w9WgXcQ"),
    ]
    assert store.item.title == "one fetch"
    assert store.item.public_id


def test_cli_resave_from_trash_clears_the_web_archive_marker(monkeypatch):
    deleted_at = datetime(2026, 8, 7, tzinfo=UTC)
    item = ContentItem(
        id=41,
        public_id="restored-public",
        user_id=57,
        platform="youtube",
        platform_id="dQw4w9WgXcQ",
        kind="video",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        state="ready",
        archived_at=datetime(2026, 8, 6, tzinfo=UTC),
        deleted_at=deleted_at,
    )
    scalar_results = [item, datetime(2026, 8, 8, tzinfo=UTC)]

    class DB:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, model, object_id):
            if model is AppUser and object_id == 57:
                return object()
            return None

        def scalar(self, _statement):
            return scalar_results.pop(0)

        def commit(self):
            return None

    class Connector:
        platform = "youtube"

        def match(self, _url):
            return "dQw4w9WgXcQ"

    class SettingsProbe:
        trash_retention_days = 30

    monkeypatch.setattr("app.ingest.tasks.get_settings", lambda: SettingsProbe())

    restored_id = create_item(
        item.url,
        user_id=item.user_id,
        why_saved="restored",
        connector=Connector(),
        session_factory=lambda: DB(),
    )

    assert restored_id == item.id
    assert item.deleted_at is None
    assert item.archived_at is None
    assert item.why_saved == "restored"


def test_celery_task_passes_only_dispatch_and_current_task_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.ingest.tasks.process_dispatch",
        lambda dispatch_id, *, task_id: calls.append(
            (dispatch_id, task_id)
        ) or "ready",
    )
    fetch_text_task.push_request(id="celery-task-id")
    try:
        assert fetch_text_task.run(71) == "ready"
    finally:
        fetch_text_task.pop_request()
    assert calls == [(71, "celery-task-id")]


def test_synchronous_embedding_failure_marks_item_failed(monkeypatch):
    class Item:
        state = "fetching"
        fail_reason = None

    item = Item()

    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, model, item_id): return item
        def commit(self): pass

    monkeypatch.setattr("app.ingest.tasks.create_item", lambda *args, **kwargs: 41)
    monkeypatch.setattr(
        "app.ingest.tasks.process_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("embedding failed")),
    )
    from app.ingest.tasks import ingest_url

    with pytest.raises(RuntimeError, match="embedding failed"):
        ingest_url(
            "https://youtu.be/dQw4w9WgXcQ",
            user_id=1,
            connector=object(),
            session_factory=lambda: DB(),
        )
    assert item.state == "failed"
    assert item.fail_reason == "ingestion_failed"


class DispatchDB:
    def __init__(self, dispatch, item):
        self.dispatch = dispatch
        self.item = item

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def scalar(self, _statement):
        return self.dispatch

    def get(self, model, object_id):
        if model is ContentItem and object_id == self.item.id:
            return self.item
        return None

    def commit(self):
        return None


def test_dispatch_claim_retry_release_and_completion_are_conditional():
    dispatch = IngestDispatch(
        id=71,
        public_id="dispatch",
        item_id=41,
        request_key="request",
        attempt=1,
        state="pending",
    )
    item = ContentItem(
        id=41,
        user_id=57,
        platform="youtube",
        platform_id="dQw4w9WgXcQ",
        kind="video",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        state="pending",
    )
    factory = lambda: DispatchDB(dispatch, item)

    assert _claim_dispatch(71, "task-1", session_factory=factory) == 41
    assert dispatch.state == "running"
    assert dispatch.task_id == "task-1"
    assert _claim_dispatch(71, "task-2", session_factory=factory) is None

    _release_dispatch_for_retry(
        71, "task-1", session_factory=factory
    )
    assert dispatch.state == "enqueued"
    assert _claim_dispatch(71, "task-1", session_factory=factory) == 41

    item.state = "ready"
    _complete_dispatch(
        71,
        "task-1",
        process_state="ready",
        session_factory=factory,
    )
    assert dispatch.state == "completed"
    assert _claim_dispatch(71, "task-1", session_factory=factory) is None


def test_publisher_sends_only_durable_dispatch_id(monkeypatch):
    calls = []

    class Result:
        id = "celery-task-id"

    monkeypatch.setattr(
        "app.ingest.tasks.celery_app.connection_for_write",
        lambda **_kwargs: Connection("memory://"),
    )

    monkeypatch.setattr(
        fetch_text_task,
        "apply_async",
        lambda *, args, **kwargs: calls.append((args, kwargs)) or Result(),
    )

    task_id = publish_ingest_dispatch(71)

    assert task_id == "celery-task-id"
    assert calls[0][0] == [71]
    assert calls[0][1]["producer"].connection.connect_timeout > 0
    assert calls[0][1]["retry"] is True
    assert calls[0][1]["retry_policy"]["max_retries"] == 1
    assert calls[0][1]["retry_policy"]["max_retries"] < 10
    assert calls[0][1]["timeout"] > 0
    assert calls[0][1]["timeout"] < Settings().agent_timeout_seconds


def test_publish_bounds_clamp_to_agent_deadline():
    from app.ingest.tasks import _bounded_publish_options

    options = _bounded_publish_options(
        replace(
            Settings(),
            agent_timeout_seconds=45,
            agent_tool_timeout_seconds=2,
            broker_publish_timeout_seconds=20,
            broker_publish_max_retries=3,
        )
    )

    assert options["_total_timeout"] == 1.0
    assert options["retry_policy"]["max_retries"] == 3
    assert options["timeout"] > 0


def test_publisher_timeout_propagates_to_submission_service(monkeypatch):
    def timed_out(*_args, **_kwargs):
        raise TimeoutError("broker publish timed out")

    monkeypatch.setattr(fetch_text_task, "apply_async", timed_out)

    monkeypatch.setattr(
        "app.ingest.tasks.celery_app.connection_for_write",
        lambda **_kwargs: Connection("memory://"),
    )

    with pytest.raises(TimeoutError, match="broker publish timed out"):
        publish_ingest_dispatch(71)


def test_publisher_bypasses_both_unbounded_shared_pools(monkeypatch):
    settings = replace(
        Settings(),
        broker_publish_timeout_seconds=0.2,
        broker_publish_max_retries=0,
        agent_timeout_seconds=2,
        agent_tool_timeout_seconds=1,
    )
    monkeypatch.setattr("app.ingest.tasks.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.ingest.tasks.celery_app.producer_pool.acquire",
        lambda **_kwargs: pytest.fail("shared producer pool was used"),
    )
    monkeypatch.setattr(
        "app.ingest.tasks.celery_app.producer_pool.connections.acquire",
        lambda **_kwargs: pytest.fail("shared connection pool was used"),
    )
    connection_options = []
    monkeypatch.setattr(
        "app.ingest.tasks.celery_app.connection_for_write",
        lambda **kwargs: connection_options.append(kwargs)
        or Connection("memory://"),
    )
    published = []

    class Result:
        id = "task-id"

    monkeypatch.setattr(
        fetch_text_task,
        "apply_async",
        lambda **kwargs: published.append(kwargs) or Result(),
    )

    assert publish_ingest_dispatch(71) == "task-id"

    assert connection_options[0]["connect_timeout"] > 0
    assert connection_options[0]["transport_options"]["socket_timeout"] > 0
    assert published[0]["args"] == [71]
    assert published[0]["producer"] is not None


def test_worker_embedder_receives_verified_ca(monkeypatch):
    context = object()
    captured = {}
    monkeypatch.setattr(
        "app.ingest.tasks.configure_trusted_ca",
        lambda _configured: TrustedCA("/safe/ca.pem", context),
    )

    class Embedder:
        def __init__(self, api_key, **kwargs):
            captured["api_key"] = api_key
            captured.update(kwargs)

    monkeypatch.setattr("app.ingest.tasks.ZhipuEmbedder", Embedder)
    build_worker_embedder(
        replace(Settings(), zhipu_api_key="worker-key")
    )

    assert captured["api_key"] == "worker-key"
    assert captured["ssl_context"] is context
