import pytest

from app.connectors.base import TransientFetchError
from app.ingest.tasks import IngestTask, fetch_text_task, run_isolated_batch


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


def test_retry_exhaustion_marks_failed_not_no_text(monkeypatch):
    class Item:
        state = "fetching"
        fail_reason = None

    item = Item()

    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, model, item_id): return item
        def commit(self): pass

    monkeypatch.setattr("app.ingest.tasks.get_session_factory", lambda: lambda: DB())
    IngestTask().on_failure(TransientFetchError("empty body"), "task", (41,), {}, None)
    assert item.state == "failed"
    assert item.state != "no_text"


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

    class Connector:
        def fetch_meta(self, platform_id): pass
        def fetch_text(self, platform_id): raise TransientFetchError("429")

    from app.ingest.tasks import process_item

    with pytest.raises(TransientFetchError, match="429"):
        process_item(41, connector=Connector(), session_factory=lambda: DB())
    assert item.state == "fetching"


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
            connector=object(),
            session_factory=lambda: DB(),
        )
    assert item.state == "failed"
    assert item.fail_reason == "embedding failed"
