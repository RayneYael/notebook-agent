from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import get_settings


def test_agent_action_migration_upgrade_downgrade_upgrade_isolated():
    base_url = make_url(get_settings().database_url)
    if not base_url.database:
        pytest.skip("configured PostgreSQL URL has no database")

    database_name = f"test_agent_action_migration_{uuid4().hex}"
    assert database_name.startswith("test_agent_action_migration_")
    admin_engine = create_engine(
        base_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    target_engine = None
    created = False
    try:
        try:
            with admin_engine.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            created = True
        except Exception as exc:
            pytest.skip(
                "isolated PostgreSQL database unavailable: "
                f"{type(exc).__name__}"
            )

        target_engine = create_engine(
            base_url.set(database=database_name),
            pool_pre_ping=True,
        )
        alembic_config = Config("alembic.ini")
        with target_engine.connect() as connection:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "9a6b2c4d8e10")

            user_id = connection.scalar(
                text("INSERT INTO app_user DEFAULT VALUES RETURNING id")
            )
            identity_id = connection.scalar(
                text(
                    """
                    INSERT INTO channel_identity (
                        app_user_id, channel, account_id, external_user_id
                    ) VALUES (
                        :user_id, 'telegram', 'migration-test', 'legacy-user'
                    ) RETURNING id
                    """
                ),
                {"user_id": user_id},
            )
            thread_id = connection.scalar(
                text(
                    """
                    INSERT INTO conversation_thread (
                        public_id, app_user_id, channel_identity_id, channel,
                        account_id, external_conversation_id
                    ) VALUES (
                        :public_id, :user_id, :identity_id, 'telegram',
                        'migration-test', 'legacy-chat'
                    ) RETURNING id
                    """
                ),
                {
                    "public_id": uuid4().hex,
                    "user_id": user_id,
                    "identity_id": identity_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO conversation_turn (
                        thread_id, message_id, user_text, assistant_text,
                        sources, model_messages
                    ) VALUES
                        (
                            :thread_id, 'sourceful', 'q1', 'a1',
                            '[{"segment_id": 1}]'::jsonb, '[]'::jsonb
                        ),
                        (
                            :thread_id, 'sourceless', 'q2', 'a2',
                            '[]'::jsonb, '[]'::jsonb
                        )
                    """
                ),
                {"thread_id": thread_id},
            )
            connection.commit()

            command.upgrade(alembic_config, "head")
            assert inspect(connection).has_table("ingest_completion_event")
            rows = connection.execute(
                text(
                    """
                    SELECT message_id, answer_status, error_code, action_results
                    FROM conversation_turn
                    ORDER BY message_id
                    """
                )
            ).mappings().all()
            assert rows == [
                {
                    "message_id": "sourceful",
                    "answer_status": "ok",
                    "error_code": None,
                    "action_results": [],
                },
                {
                    "message_id": "sourceless",
                    "answer_status": "not_found",
                    "error_code": "no_evidence",
                    "action_results": [],
                },
            ]

            command.downgrade(alembic_config, "9a6b2c4d8e10")
            columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "conversation_turn"
                )
            }
            assert "answer_status" not in columns
            assert "error_code" not in columns
            assert "action_results" not in columns
            assert not inspect(connection).has_table("ingest_dispatch")
            assert not inspect(connection).has_table("ingest_completion_event")
            assert not inspect(connection).has_table(
                "pending_channel_action"
            )

            command.upgrade(alembic_config, "head")
            assert inspect(connection).has_table("ingest_completion_event")
            columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "conversation_turn"
                )
            }
            assert {"answer_status", "error_code", "action_results"} <= columns
    finally:
        if target_engine is not None:
            target_engine.dispose()
        if created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(f'DROP DATABASE "{database_name}" WITH (FORCE)')
                )
        admin_engine.dispose()
