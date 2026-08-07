"""pending channel actions, ingest dispatches and durable action replies

Revision ID: c7e8a91b2d34
Revises: 9a6b2c4d8e10
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c7e8a91b2d34"
down_revision: Union[str, Sequence[str], None] = "9a6b2c4d8e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_turn",
        sa.Column(
            "answer_status",
            sa.Text(),
            server_default="legacy",
            nullable=False,
        ),
    )
    op.add_column(
        "conversation_turn",
        sa.Column("error_code", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversation_turn",
        sa.Column(
            "action_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE conversation_turn
        SET answer_status = CASE
                WHEN sources <> '[]'::jsonb THEN 'ok'
                ELSE 'not_found'
            END,
            error_code = CASE
                WHEN sources <> '[]'::jsonb THEN NULL
                ELSE 'no_evidence'
            END
        """
    )

    op.create_table(
        "pending_channel_action",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "consumed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("consumed_message_id", sa.Text(), nullable=True),
        sa.Column(
            "cancelled_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["conversation_thread.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_pending_channel_action_thread_active",
        "pending_channel_action",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text(
            "consumed_at IS NULL AND cancelled_at IS NULL"
        ),
    )

    op.create_table(
        "ingest_dispatch",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column(
            "attempt", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column(
            "state", sa.Text(), server_default="pending", nullable=False
        ),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["content_item.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "request_key",
            "item_id",
            name="uq_ingest_dispatch_request_item",
        ),
    )
    op.create_index(
        "uq_ingest_dispatch_item_active",
        "ingest_dispatch",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('pending', 'enqueued', 'running')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ingest_dispatch_item_active", table_name="ingest_dispatch"
    )
    op.drop_table("ingest_dispatch")
    op.drop_index(
        "uq_pending_channel_action_thread_active",
        table_name="pending_channel_action",
    )
    op.drop_table("pending_channel_action")
    op.drop_column("conversation_turn", "action_results")
    op.drop_column("conversation_turn", "error_code")
    op.drop_column("conversation_turn", "answer_status")
