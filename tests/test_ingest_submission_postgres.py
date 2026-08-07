from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.channels.types import TenantContext
from app.connectors.base import TransientFetchError
from app.db import get_engine
from app.ingest.submission import IngestSubmissionService
from app.ingest.tasks import (
    _mark_dispatch_failed,
    process_dispatch,
)
from app.models import AppUser, Base, ContentItem, IngestDispatch


@pytest.fixture
def submission_factory():
    engine = get_engine()
    schema = f"test_save_{uuid4().hex}"
    tables = [
        AppUser.__table__,
        ContentItem.__table__,
        IngestDispatch.__table__,
    ]
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(
                text(f'SET LOCAL search_path TO "{schema}", public')
            )
            Base.metadata.create_all(
                connection,
                tables=tables,
                checkfirst=False,
            )
    except Exception as exc:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
        finally:
            pytest.skip(
                "isolated PostgreSQL schema unavailable: "
                f"{type(exc).__name__}"
            )

    def factory():
        db = Session(bind=engine, expire_on_commit=False)
        db.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        return db

    try:
        yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            )


def _tenant(factory, number):
    with factory() as db:
        user = AppUser()
        db.add(user)
        db.commit()
        return TenantContext(
            user.id,
            number,
            "telegram",
            "account",
            f"external-{number}",
        )


def test_same_request_replays_queued_and_tenants_remain_isolated(
    submission_factory,
):
    tenant_a = _tenant(submission_factory, 1)
    tenant_b = _tenant(submission_factory, 2)
    published = []
    service = IngestSubmissionService(
        submission_factory,
        lambda dispatch_id: published.append(dispatch_id)
        or f"task-{dispatch_id}",
    )
    url = "https://youtu.be/dQw4w9WgXcQ"

    first = service.submit_urls(
        tenant_a, [url], why_saved=None, request_key="a:first"
    )
    replay = service.submit_urls(
        tenant_a, [url], why_saved=None, request_key="a:first"
    )
    other_request = service.submit_urls(
        tenant_a, [url], why_saved=None, request_key="a:second"
    )
    other_tenant = service.submit_urls(
        tenant_b, [url], why_saved=None, request_key="b:first"
    )

    assert first.results[0].status == "queued"
    assert replay.results[0].status == "queued"
    assert other_request.results[0].status == "already_exists"
    assert other_tenant.results[0].status == "queued"
    assert len(published) == 2
    with submission_factory() as db:
        items = list(
            db.scalars(select(ContentItem).order_by(ContentItem.user_id))
        )
    assert [item.user_id for item in items] == [
        tenant_a.app_user_id,
        tenant_b.app_user_id,
    ]


def test_pending_same_request_never_claims_publish_succeeded(
    submission_factory,
):
    tenant = _tenant(submission_factory, 3)
    publisher_entered = Event()
    release_publisher = Event()

    def publisher(dispatch_id):
        publisher_entered.set()
        assert release_publisher.wait(timeout=5)
        return f"task-{dispatch_id}"

    service = IngestSubmissionService(submission_factory, publisher)
    url = "https://youtu.be/9bZkp7q19f0"

    with ThreadPoolExecutor(max_workers=1) as pool:
        first_future = pool.submit(
            service.submit_urls,
            tenant,
            [url],
            why_saved=None,
            request_key="pending:request",
        )
        assert publisher_entered.wait(timeout=5)
        while_pending = service.submit_urls(
            tenant,
            [url],
            why_saved=None,
            request_key="pending:request",
        )
        release_publisher.set()
        first = first_future.result(timeout=5)

    after_publish = service.submit_urls(
        tenant,
        [url],
        why_saved=None,
        request_key="pending:request",
    )

    assert while_pending.results[0].status == "already_exists"
    assert first.results[0].status == "queued"
    assert after_publish.results[0].status == "queued"


def test_failed_publish_is_stable_for_same_request_and_retryable_by_new_request(
    submission_factory,
):
    tenant = _tenant(submission_factory, 4)
    calls = []

    def publisher(dispatch_id):
        calls.append(dispatch_id)
        if len(calls) == 1:
            raise RuntimeError("private broker failure")
        return f"task-{dispatch_id}"

    service = IngestSubmissionService(submission_factory, publisher)
    url = "https://youtu.be/M7lc1UVf-VE"

    failed = service.submit_urls(
        tenant, [url], why_saved=None, request_key="request:one"
    )
    replay = service.submit_urls(
        tenant, [url], why_saved=None, request_key="request:one"
    )
    recovered = service.submit_urls(
        tenant, [url], why_saved=None, request_key="request:two"
    )
    active = service.submit_urls(
        tenant, [url], why_saved=None, request_key="request:three"
    )

    assert failed.results[0].status == "queue_unavailable"
    assert replay.results[0].status == "queue_unavailable"
    assert recovered.results[0].status == "queued"
    assert active.results[0].status == "already_exists"
    assert len(calls) == 2
    with submission_factory() as db:
        dispatches = list(
            db.scalars(
                select(IngestDispatch).order_by(IngestDispatch.attempt)
            )
        )
    assert [dispatch.attempt for dispatch in dispatches] == [1, 2]
    assert [dispatch.state for dispatch in dispatches] == [
        "failed",
        "enqueued",
    ]


def test_concurrent_duplicate_submission_creates_one_item_and_dispatch(
    submission_factory,
):
    tenant = _tenant(submission_factory, 5)
    barrier = Barrier(6)
    published = []
    published_lock = Lock()

    def publisher(dispatch_id):
        with published_lock:
            published.append(dispatch_id)
        return f"task-{dispatch_id}"

    service = IngestSubmissionService(submission_factory, publisher)

    def submit(_index):
        barrier.wait(timeout=5)
        return service.submit_urls(
            tenant,
            ["https://youtu.be/aqz-KE-bpKQ"],
            why_saved=None,
            request_key="concurrent:request",
        ).results[0].status

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(submit, range(6)))

    assert set(statuses) <= {"queued", "already_exists"}
    assert "queued" in statuses
    assert "create_failed" not in statuses
    assert len(published) == 1
    with submission_factory() as db:
        assert len(list(db.scalars(select(ContentItem)))) == 1
        assert len(list(db.scalars(select(IngestDispatch)))) == 1


def test_fast_worker_transition_is_not_overwritten_by_publish_ack(
    submission_factory,
):
    tenant = _tenant(submission_factory, 6)

    def publisher(dispatch_id):
        with submission_factory() as db:
            dispatch = db.get(IngestDispatch, dispatch_id)
            dispatch.state = "running"
            db.commit()
        return f"task-{dispatch_id}"

    service = IngestSubmissionService(submission_factory, publisher)
    result = service.submit_urls(
        tenant,
        ["https://youtu.be/ScMzIvxBSi4"],
        why_saved=None,
        request_key="fast-worker",
    )

    assert result.results[0].status == "queued"
    with submission_factory() as db:
        dispatch = db.scalar(select(IngestDispatch))
    assert dispatch.state == "running"
    assert dispatch.task_id is None


def _worker_dispatch(factory, tenant, *, suffix, state, task_id):
    with factory() as db:
        item = ContentItem(
            user_id=tenant.app_user_id,
            platform="youtube",
            platform_id=f"worker{suffix:05d}",
            kind="video",
            url=(
                "https://www.youtube.com/watch?v="
                f"worker{suffix:05d}"
            ),
            state="pending",
        )
        db.add(item)
        db.flush()
        dispatch = IngestDispatch(
            public_id=uuid4().hex,
            item_id=item.id,
            request_key=f"worker:{suffix}",
            attempt=1,
            state=state,
            task_id=task_id,
        )
        db.add(dispatch)
        db.commit()
        return item.id, dispatch.id


def test_dispatch_worker_claim_retry_and_completion_are_conditional_pg(
    submission_factory,
):
    tenant = _tenant(submission_factory, 70)
    item_id, dispatch_id = _worker_dispatch(
        submission_factory,
        tenant,
        suffix=1,
        state="enqueued",
        task_id="task-current",
    )
    attempts = []

    def transient(current_item_id):
        attempts.append(current_item_id)
        raise TransientFetchError("private provider detail")

    with pytest.raises(TransientFetchError) as caught:
        process_dispatch(
            dispatch_id,
            task_id="task-current",
            processor=transient,
            session_factory=submission_factory,
        )
    assert str(caught.value) == "transient_fetch_failed"
    assert "private provider detail" not in repr(caught.value)
    with submission_factory() as db:
        dispatch = db.get(IngestDispatch, dispatch_id)
        item = db.get(ContentItem, item_id)
        assert (dispatch.state, dispatch.task_id) == (
            "enqueued",
            "task-current",
        )
        assert item.state == "pending"
        assert item.user_id == tenant.app_user_id

    assert process_dispatch(
        dispatch_id,
        task_id="task-stale",
        processor=lambda _item_id: pytest.fail(
            "stale task processed the item"
        ),
        session_factory=submission_factory,
    ) == "duplicate"
    assert attempts == [item_id]

    assert process_dispatch(
        dispatch_id,
        task_id="task-current",
        processor=lambda current_item_id: (
            "ready" if current_item_id == item_id else "wrong_item"
        ),
        session_factory=submission_factory,
    ) == "ready"
    assert process_dispatch(
        dispatch_id,
        task_id="task-current",
        processor=lambda _item_id: pytest.fail(
            "completed dispatch was processed twice"
        ),
        session_factory=submission_factory,
    ) == "duplicate"
    with submission_factory() as db:
        dispatch = db.get(IngestDispatch, dispatch_id)
        item = db.get(ContentItem, item_id)
        assert dispatch.state == "completed"
        assert dispatch.error_code is None
        assert item.user_id == tenant.app_user_id


def test_stale_task_failure_cannot_overwrite_current_delivery_pg(
    submission_factory,
):
    tenant = _tenant(submission_factory, 71)
    item_id, dispatch_id = _worker_dispatch(
        submission_factory,
        tenant,
        suffix=2,
        state="running",
        task_id="task-current",
    )

    _mark_dispatch_failed(
        dispatch_id,
        RuntimeError("private stale failure"),
        task_id="task-stale",
        session_factory=submission_factory,
    )
    with submission_factory() as db:
        dispatch = db.get(IngestDispatch, dispatch_id)
        item = db.get(ContentItem, item_id)
        assert dispatch.state == "running"
        assert dispatch.error_code is None
        assert item.state == "pending"
        assert item.fail_reason is None

    _mark_dispatch_failed(
        dispatch_id,
        RuntimeError("private current failure"),
        task_id="task-current",
        session_factory=submission_factory,
    )
    with submission_factory() as db:
        dispatch = db.get(IngestDispatch, dispatch_id)
        item = db.get(ContentItem, item_id)
        assert dispatch.state == "failed"
        assert dispatch.error_code == "ingestion_failed"
        assert item.state == "failed"
        assert item.fail_reason == "ingestion_failed"
        assert item.user_id == tenant.app_user_id


def test_generic_worker_failure_exposes_and_persists_only_safe_code_pg(
    submission_factory,
):
    tenant = _tenant(submission_factory, 72)
    item_id, dispatch_id = _worker_dispatch(
        submission_factory,
        tenant,
        suffix=3,
        state="enqueued",
        task_id="task-current",
    )

    def failed_processor(_item_id):
        raise RuntimeError("private URL/provider payload")

    with pytest.raises(RuntimeError) as caught:
        process_dispatch(
            dispatch_id,
            task_id="task-current",
            processor=failed_processor,
            session_factory=submission_factory,
        )

    assert str(caught.value) == "ingestion_failed"
    assert "private URL/provider payload" not in repr(caught.value)
    with submission_factory() as db:
        dispatch = db.get(IngestDispatch, dispatch_id)
        item = db.get(ContentItem, item_id)
        assert dispatch.state == "failed"
        assert dispatch.task_id == "task-current"
        assert dispatch.error_code == "ingestion_failed"
        assert item.state == "failed"
        assert item.fail_reason == "ingestion_failed"
        assert item.user_id == tenant.app_user_id
