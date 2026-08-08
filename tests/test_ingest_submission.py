from dataclasses import replace
from datetime import UTC, datetime
import time

from kombu import Connection
import pytest

from app.connectors.youtube import YouTubeConnector
from app.ingest.submission import (
    BatchTooLarge,
    EmptyBatch,
    IngestSubmissionService,
    ItemReference,
    MAX_SAVE_BATCH_SIZE,
    PreparedItem,
    normalize_item_reference,
    prepare_submission,
)
from app.channels.types import TenantContext
from app.config import Settings
from app.ingest.tasks import publish_ingest_dispatch
from app.models import ContentItem, IngestDispatch


def test_normalize_youtube_url_without_remote_fetch():
    reference = normalize_item_reference("https://youtu.be/dQw4w9WgXcQ?t=42")

    assert reference.platform == "youtube"
    assert reference.platform_id == "dQw4w9WgXcQ"
    assert reference.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_batch_preflight_preserves_order_and_safe_validation_results():
    prepared = prepare_submission(
        [
            "https://youtu.be/dQw4w9WgXcQ",
            "not-a-url",
            "https://example.test/video",
        ]
    )

    assert [item.input_index for item in prepared.items] == [0, 1, 2]
    assert prepared.items[0].reference == ItemReference(
        platform="youtube",
        platform_id="dQw4w9WgXcQ",
        canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    assert prepared.items[0].failure is None
    assert prepared.items[1].failure.status == "invalid_url"
    assert prepared.items[1].failure.safe_error_code == "invalid_url"
    assert prepared.items[1].failure.result_id == "A2"
    assert prepared.items[2].failure.status == "unsupported_url"
    assert prepared.items[2].failure.safe_error_code == "unsupported_url"
    assert prepared.items[2].failure.result_id == "A3"


def test_batch_size_is_checked_before_item_normalization(monkeypatch):
    calls = []

    def normalize(url):
        calls.append(url)
        return ItemReference("youtube", "dQw4w9WgXcQ", url)

    monkeypatch.setattr("app.ingest.submission.normalize_item_reference", normalize)
    urls = [f"https://example.test/{index}" for index in range(MAX_SAVE_BATCH_SIZE)]

    assert len(prepare_submission(urls).items) == 10
    assert calls == urls

    calls.clear()
    with pytest.raises(BatchTooLarge) as caught:
        prepare_submission(urls + ["https://example.test/overflow"])
    assert caught.value.error_code == "batch_too_large"
    assert calls == []

    with pytest.raises(EmptyBatch) as caught:
        prepare_submission([])
    assert caught.value.error_code == "empty_batch"
    assert calls == []


def test_ten_url_broker_outage_obeys_one_total_publish_budget(monkeypatch):
    store = FakeStore([None] * MAX_SAVE_BATCH_SIZE)
    observed_budgets = []
    clock = [100.0]
    monkeypatch.setattr(
        "app.ingest.submission.time.monotonic",
        lambda: clock[0],
    )

    def unavailable(_dispatch_id, *, remaining_budget_seconds):
        observed_budgets.append(remaining_budget_seconds)
        clock[0] += remaining_budget_seconds + 0.01
        raise TimeoutError("private broker timeout")

    service = IngestSubmissionService(store.session, unavailable)
    urls = [
        f"https://www.youtube.com/watch?v=budget{i:05d}"
        for i in range(MAX_SAVE_BATCH_SIZE)
    ]

    started = time.monotonic()
    result = service.submit_urls(
        TenantContext(57, 9, "wechat", "account", "external"),
        urls,
        why_saved=None,
        request_key="web:whole-batch-budget",
        publish_budget_seconds=0.05,
    )
    elapsed = time.monotonic() - started

    assert [value.status for value in result.results] == [
        "queue_unavailable"
    ] * MAX_SAVE_BATCH_SIZE
    assert len(observed_budgets) == 1
    assert elapsed < 0.2


def test_youtube_marker_on_an_untrusted_host_is_not_supported():
    prepared = prepare_submission(
        ["https://example.test/youtu.be/dQw4w9WgXcQ"]
    )

    assert prepared.items[0].failure.status == "unsupported_url"


class FakeStore:
    def __init__(self, scalar_results):
        self.scalar_results = list(scalar_results)
        self.items = []
        self.dispatches = []
        self.statements = []

    def session(self):
        return FakeSession(self)


class FakeSession:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def scalar(self, _statement):
        self.store.statements.append(_statement)
        return self.store.scalar_results.pop(0)

    def add(self, value):
        if isinstance(value, ContentItem):
            value.id = len(self.store.items) + 41
            self.store.items.append(value)
        elif isinstance(value, IngestDispatch):
            value.id = len(self.store.dispatches) + 71
            self.store.dispatches.append(value)

    def flush(self):
        return None

    def commit(self):
        return None

    def get(self, model, object_id):
        if model is IngestDispatch:
            return next(
                (
                    value
                    for value in self.store.dispatches
                    if value.id == object_id
                ),
                None,
            )
        return None


@pytest.mark.parametrize(
    "quota_name",
    (
        "max_active_per_tenant",
        "daily_new_item_limit",
        "max_items_per_tenant",
        "max_active_global",
        "daily_new_item_limit_global",
        "daily_dispatch_limit_per_tenant",
        "daily_dispatch_limit_global",
    ),
)
@pytest.mark.parametrize("invalid_value", (0, -1))
def test_ingest_quota_configuration_rejects_non_positive_limits(
    quota_name,
    invalid_value,
):
    with pytest.raises(ValueError, match=rf"^{quota_name} must be positive$"):
        IngestSubmissionService(
            FakeStore([]).session,
            lambda _dispatch_id: "task-id",
            **{quota_name: invalid_value},
        )


def test_archived_failed_item_with_new_key_is_already_exists_without_retry():
    existing = ContentItem(
        id=41,
        public_id="archived-public",
        user_id=57,
        platform="youtube",
        platform_id="dQw4w9WgXcQ",
        kind="video",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        state="failed",
        fail_reason="ingestion_failed",
        archived_at=datetime.now(UTC),
    )
    store = FakeStore([existing])
    published = []

    result = IngestSubmissionService(
        store.session,
        lambda dispatch_id: published.append(dispatch_id) or "task",
    ).submit_urls(
        TenantContext(57, 9, "telegram", "account", "external"),
        [existing.url],
        why_saved=None,
        request_key="new-request-key",
    )

    assert result.results[0].status == "already_exists"
    assert result.results[0].state == "failed"
    assert result.results[0].item_public_id == "archived-public"
    assert result.results[0].archived is True
    assert existing.state == "failed"
    assert existing.fail_reason == "ingestion_failed"
    assert store.dispatches == []
    assert published == []
    assert len(store.statements) == 1


def test_conflict_recovery_checks_same_request_dispatch_before_already_exists():
    existing = ContentItem(
        id=41,
        public_id="item-public",
        user_id=57,
        platform="youtube",
        platform_id="dQw4w9WgXcQ",
        kind="video",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        state="pending",
    )
    replay = IngestDispatch(
        id=71,
        public_id="dispatch-public",
        item_id=41,
        request_key="same-request",
        attempt=1,
        state="failed",
        error_code="queue_unavailable",
    )
    store = FakeStore([existing, replay])
    service = IngestSubmissionService(store.session, lambda _value: "task")
    prepared = PreparedItem(
        input_index=0,
        reference=ItemReference(
            "youtube",
            "dQw4w9WgXcQ",
            existing.url,
        ),
    )

    result = service._result_after_conflict(
        TenantContext(57, 9, "telegram", "account", "external"),
        prepared,
        prepared.reference,
        request_key="same-request",
    )

    assert result.status == "queue_unavailable"
    assert result.safe_error_code == "queue_unavailable"
    assert len(store.statements) == 2
    assert "content_item.user_id" in str(store.statements[0])
    assert "ingest_dispatch.request_key" in str(store.statements[1])
    assert "ingest_dispatch.item_id" in str(store.statements[1])


def test_submission_is_tenant_bound_async_and_partial():
    store = FakeStore([None, None])
    published = []

    def publisher(dispatch_id):
        published.append(dispatch_id)
        if len(published) == 2:
            raise RuntimeError("private broker detail")
        return "private-task-id"

    service = IngestSubmissionService(store.session, publisher)
    tenant = TenantContext(57, 9, "wechat", "account", "external")

    result = service.submit_urls(
        tenant,
        [
            "https://youtu.be/dQw4w9WgXcQ",
            "not-a-url",
            "https://youtu.be/9bZkp7q19f0",
        ],
        why_saved="later",
        request_key="thread:message:save",
    )

    assert [value.status for value in result.results] == [
        "queued",
        "invalid_url",
        "queue_unavailable",
    ]
    assert [value.input_index for value in result.results] == [0, 1, 2]
    assert result.results[0].item_id == 41
    assert result.results[0].item_public_id == store.items[0].public_id
    assert result.results[2].item_id == 42
    assert result.results[2].item_public_id == store.items[1].public_id
    assert result.results[2].safe_error_code == "queue_unavailable"
    assert "private broker detail" not in repr(result)
    assert published == [71, 72]

    assert [item.user_id for item in store.items] == [57, 57]
    assert all(item.public_id for item in store.items)
    assert [item.state for item in store.items] == ["pending", "pending"]
    assert all(item.title is None for item in store.items)
    assert all(
        item.url.startswith("https://www.youtube.com/watch?v=")
        for item in store.items
    )
    assert [dispatch.request_key for dispatch in store.dispatches] == [
        "thread:message:save",
        "thread:message:save",
    ]
    assert [dispatch.state for dispatch in store.dispatches] == [
        "enqueued",
        "failed",
    ]


def test_channel_submission_never_fetches_remote_metadata(monkeypatch):
    def forbidden_fetch(*_args, **_kwargs):
        pytest.fail("channel submission fetched remote metadata")

    monkeypatch.setattr(YouTubeConnector, "fetch_meta", forbidden_fetch)
    store = FakeStore([None])
    published = []
    service = IngestSubmissionService(
        store.session,
        lambda dispatch_id: published.append(dispatch_id) or "task-id",
    )

    result = service.submit_urls(
        TenantContext(57, 9, "wechat", "account", "external"),
        ["https://youtu.be/dQw4w9WgXcQ"],
        why_saved=None,
        request_key="thread:metadata-off-request:save",
    )

    assert result.results[0].status == "queued"
    assert published == [71]
    assert store.items[0].state == "pending"
    assert store.items[0].title is None
    assert store.items[0].author is None


def test_bounded_standalone_publish_failure_becomes_durable_queue_unavailable(
    monkeypatch,
):
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
    monkeypatch.setattr(
        "app.ingest.tasks.celery_app.connection_for_write",
        lambda **_kwargs: Connection("memory://"),
    )

    def timed_out(**kwargs):
        time.sleep(kwargs["timeout"])
        raise TimeoutError("broker_publish_timeout")

    monkeypatch.setattr(
        "app.ingest.tasks.fetch_text_task.apply_async",
        timed_out,
    )
    store = FakeStore([None])
    service = IngestSubmissionService(
        store.session,
        publish_ingest_dispatch,
    )

    started = time.monotonic()
    result = service.submit_urls(
        TenantContext(57, 9, "wechat", "account", "external"),
        ["https://youtu.be/dQw4w9WgXcQ"],
        why_saved=None,
        request_key="thread:pool-exhausted:save",
    )
    elapsed = time.monotonic() - started

    assert result.results[0].status == "queue_unavailable"
    assert result.results[0].safe_error_code == "queue_unavailable"
    assert store.dispatches[0].state == "failed"
    assert store.dispatches[0].error_code == "queue_unavailable"
    assert elapsed < settings.broker_publish_timeout_seconds


def test_existing_item_replays_same_request_and_does_not_republish():
    store = FakeStore([None])
    published = []
    service = IngestSubmissionService(
        store.session,
        lambda dispatch_id: published.append(dispatch_id) or "task-id",
    )
    tenant = TenantContext(57, 9, "telegram", "account", "external")

    first = service.submit_urls(
        tenant,
        ["https://youtu.be/dQw4w9WgXcQ"],
        why_saved=None,
        request_key="thread:first:save",
    )
    # Same request consumes: existing item, matching dispatch.
    store.scalar_results.extend([store.items[0], store.dispatches[0]])
    replay = service.submit_urls(
        tenant,
        ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        why_saved=None,
        request_key="thread:first:save",
    )
    # Different request consumes: existing item, no matching dispatch,
    # then the latest active dispatch.
    store.scalar_results.extend(
        [store.items[0], None, store.dispatches[0]]
    )
    repeated = service.submit_urls(
        tenant,
        ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        why_saved=None,
        request_key="thread:second:save",
    )

    assert first.results[0].status == "queued"
    assert replay.results[0].status == "queued"
    assert repeated.results[0].status == "already_exists"
    assert repeated.results[0].item_id == first.results[0].item_id
    assert repeated.results[0].item_public_id == first.results[0].item_public_id
    assert len(store.items) == 1
    assert len(store.dispatches) == 1
    assert published == [71]
