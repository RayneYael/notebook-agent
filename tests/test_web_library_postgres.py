from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.channels.types import UserScope
from app.db import get_engine
from app.models import AppUser, Base, ContentItem, IngestDispatch, Segment
from app.retrieval.search import bm25_search, vector_search
from app.web.library import ContentLibraryService, LibraryNotFound


@pytest.fixture
def library_factory():
    engine = get_engine()
    schema = f"test_library_{uuid4().hex}"
    tables = [AppUser.__table__, ContentItem.__table__, IngestDispatch.__table__, Segment.__table__]
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            Base.metadata.create_all(connection, tables=tables, checkfirst=False)
    except Exception as exc:
        try:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            pytest.skip(f"isolated PostgreSQL schema unavailable: {type(exc).__name__}")

    def factory():
        db = Session(bind=engine, expire_on_commit=False)
        db.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        return db

    try:
        yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def add_user(factory):
    with factory() as db:
        user = AppUser()
        db.add(user)
        db.commit()
        return UserScope(user.id)


def add_item(factory, scope, *, platform_id, state="pending"):
    with factory() as db:
        item = ContentItem(
            public_id=uuid4().hex,
            user_id=scope.app_user_id,
            platform="youtube",
            platform_id=platform_id,
            kind="video",
            url=f"https://www.youtube.com/watch?v={platform_id}",
            title=platform_id,
            state=state,
        )
        db.add(item)
        db.flush()
        db.add(IngestDispatch(
            public_id=uuid4().hex,
            item_id=item.id,
            request_key=uuid4().hex,
            attempt=1,
            state="failed" if state == "failed" else "pending",
            error_code="queue_unavailable" if state == "failed" else None,
        ))
        db.commit()
        return item.public_id


def test_library_is_tenant_scoped_and_archive_excludes_agent_retrieval(library_factory):
    scope_a = add_user(library_factory)
    scope_b = add_user(library_factory)
    public_a = add_item(library_factory, scope_a, platform_id="dQw4w9WgXcQ", state="ready")
    public_b = add_item(library_factory, scope_b, platform_id="9bZkp7q19f0", state="ready")
    service = ContentLibraryService(library_factory, lambda _dispatch_id: "task")

    assert service.get_item(scope_a, public_a).public_id == public_a
    with pytest.raises(LibraryNotFound):
        service.get_item(scope_a, public_b)

    service.archive(scope_a, public_a)
    with library_factory() as db:
        assert vector_search(db, [0.01] * 1536, user_id=scope_a.app_user_id) == []
        assert bm25_search(db, "anything", user_id=scope_a.app_user_id) == []


def test_latest_dispatch_uses_attempt_then_id_and_pending_failed_projects_failed(library_factory):
    scope = add_user(library_factory)
    public_id = add_item(library_factory, scope, platform_id="M7lc1UVf-VE")
    with library_factory() as db:
        item = db.scalar(select(ContentItem).where(ContentItem.public_id == public_id))
        first = db.scalar(select(IngestDispatch).where(IngestDispatch.item_id == item.id))
        first.state = "enqueued"
        db.add(IngestDispatch(
            public_id=uuid4().hex,
            item_id=item.id,
            request_key=uuid4().hex,
            attempt=2,
            state="failed",
            error_code="queue_unavailable",
        ))
        db.commit()

    detail = ContentLibraryService(library_factory, lambda _dispatch_id: "task").get_item(scope, public_id)

    assert detail.lifecycle == "failed"
    assert detail.error_code == "queue_unavailable"
