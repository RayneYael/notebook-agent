from types import SimpleNamespace

import sqlalchemy as sa

from app.channels.service import _answer_from_turn
from migrations.versions import c7e8a91b2d34_agent_save_actions as migration


class RecordingOp:
    def __init__(self):
        self.added_columns = []
        self.executed = []
        self.tables = {}
        self.indexes = {}

    def add_column(self, table_name, column):
        self.added_columns.append((table_name, column))

    def execute(self, statement):
        self.executed.append(str(statement))

    def create_table(self, name, *elements, **_kwargs):
        self.tables[name] = elements

    def create_index(self, name, table_name, columns, **kwargs):
        self.indexes[name] = (table_name, columns, kwargs)


def test_migration_adds_action_schema_and_legacy_backfill(monkeypatch):
    recorder = RecordingOp()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    assert migration.down_revision == "9a6b2c4d8e10"
    columns = {
        column.name: column
        for table_name, column in recorder.added_columns
        if table_name == "conversation_turn"
    }
    assert set(columns) == {"answer_status", "error_code", "action_results"}
    assert "legacy" in str(columns["answer_status"].server_default.arg)
    assert "[]" in str(columns["action_results"].server_default.arg)
    backfill = "\n".join(recorder.executed)
    assert "sources <> '[]'::jsonb" in backfill
    assert "'ok'" in backfill
    assert "'not_found'" in backfill
    assert "'no_evidence'" in backfill

    pending = recorder.tables["pending_channel_action"]
    assert {
        element.name for element in pending if isinstance(element, sa.Column)
    } == {
        "id",
        "thread_id",
        "kind",
        "payload",
        "expires_at",
        "consumed_at",
        "consumed_message_id",
        "cancelled_at",
        "created_at",
    }
    pending_targets = {
        foreign_key.target_fullname
        for element in pending
        if isinstance(element, sa.ForeignKeyConstraint)
        for foreign_key in element.elements
    }
    assert pending_targets == {"conversation_thread.id"}

    dispatch = recorder.tables["ingest_dispatch"]
    assert {
        element.name for element in dispatch if isinstance(element, sa.Column)
    } == {
        "id",
        "public_id",
        "item_id",
        "request_key",
        "attempt",
        "state",
        "task_id",
        "error_code",
        "created_at",
        "updated_at",
    }
    dispatch_targets = {
        foreign_key.target_fullname
        for element in dispatch
        if isinstance(element, sa.ForeignKeyConstraint)
        for foreign_key in element.elements
    }
    assert dispatch_targets == {"content_item.id"}
    assert any(
        isinstance(element, sa.UniqueConstraint)
        and element.name == "uq_ingest_dispatch_request_item"
        for element in dispatch
    )

    pending_index = recorder.indexes[
        "uq_pending_channel_action_thread_active"
    ]
    assert pending_index[2]["unique"]
    assert "consumed_at IS NULL" in str(
        pending_index[2]["postgresql_where"]
    )
    dispatch_index = recorder.indexes["uq_ingest_dispatch_item_active"]
    assert dispatch_index[2]["unique"]
    assert "running" in str(dispatch_index[2]["postgresql_where"])


def _turn(*, sources, answer_status, error_code=None, action_results=None):
    return SimpleNamespace(
        sources=sources,
        assistant_text="stored answer",
        answer_status=answer_status,
        error_code=error_code,
        action_results=action_results or [],
    )


def test_legacy_replay_infers_only_old_knowledge_contract():
    citation = {
        "item_id": 2,
        "segment_id": 3,
        "title": "source",
        "excerpt": "evidence",
        "url": "https://example.test/source",
        "start_sec": None,
    }

    sourceful = _answer_from_turn(
        _turn(sources=[citation], answer_status="legacy"), "thread"
    )
    sourceless = _answer_from_turn(
        _turn(sources=[], answer_status="legacy"), "thread"
    )

    assert sourceful.status == "ok"
    assert sourceful.error_code is None
    assert sourceful.citations
    assert sourceless.status == "not_found"
    assert sourceless.error_code == "no_evidence"


def test_explicit_action_replay_does_not_infer_from_empty_citations():
    action_results = [
        {
            "result_id": "A1",
            "input_index": 0,
            "status": "queued",
            "item_id": 41,
            "state": "pending",
        }
    ]

    answer = _answer_from_turn(
        _turn(
            sources=[],
            answer_status="ok",
            error_code="save_accepted",
            action_results=action_results,
        ),
        "thread",
    )

    assert answer.status == "ok"
    assert answer.error_code == "save_accepted"
    assert answer.citations == []
    assert answer.action_results == action_results
