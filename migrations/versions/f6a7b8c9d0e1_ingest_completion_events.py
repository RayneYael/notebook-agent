"""durable ingestion completion outbox events

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingest_completion_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column("dispatch_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("item_state", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "publish_state",
            sa.Text(),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("claim_token", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_task_id", sa.Text(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "outcome IN ('completed', 'failed')",
            name="ck_ingest_completion_event_outcome",
        ),
        sa.CheckConstraint(
            "item_state IN ('ready', 'needs_extension', 'needs_asr', 'failed')",
            name="ck_ingest_completion_event_item_state",
        ),
        sa.CheckConstraint(
            "publish_state IN ('pending', 'claimed', 'enqueued')",
            name="ck_ingest_completion_event_publish_state",
        ),
        sa.CheckConstraint(
            "(outcome = 'completed' AND item_state IN ('ready', 'needs_extension', 'needs_asr') AND error_code IS NULL) OR "
            "(outcome = 'failed' AND item_state = 'failed' AND error_code IS NOT NULL)",
            name="ck_ingest_completion_event_completed_error",
        ),
        sa.ForeignKeyConstraint(
            ["dispatch_id"],
            ["ingest_dispatch.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["content_item.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_ingest_completion_event_public_id"),
        sa.UniqueConstraint(
            "dispatch_id", name="uq_ingest_completion_event_dispatch"
        ),
    )
    op.create_index(
        "ix_ingest_completion_event_publish_claim",
        "ingest_completion_event",
        ["publish_state", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingest_completion_event_publish_claim",
        table_name="ingest_completion_event",
    )
    op.drop_table("ingest_completion_event")
