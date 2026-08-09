"""capture source conversations and add completion notification ledger

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_dispatch",
        sa.Column("source_thread_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ingest_dispatch_source_thread",
        "ingest_dispatch",
        "conversation_thread",
        ["source_thread_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ingest_dispatch_source_thread",
        "ingest_dispatch",
        ["source_thread_id"],
    )

    op.create_table(
        "ingest_completion_delivery",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("handler_key", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default="claimed", nullable=False
        ),
        sa.Column("disposition", sa.Text(), nullable=True),
        sa.Column("claim_token", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('claimed', 'succeeded', 'failed')",
            name="ck_ingest_completion_delivery_status",
        ),
        sa.CheckConstraint(
            "attempts >= 1",
            name="ck_ingest_completion_delivery_attempts",
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR last_error_code IN "
            "('outbound_api_key_missing', 'invalid_outbound_target', "
            "'outbound_auth_rejected', 'outbound_contract_invalid', "
            "'outbound_target_not_found', 'outbound_rate_limited', "
            "'outbound_server_error', 'outbound_http_4xx', "
            "'outbound_http_status', 'outbound_timeout', "
            "'outbound_connect_failed', 'outbound_transport_failed', "
            "'redirect_rejected', 'notification_deferred', "
            "'notification_internal_failure', 'retry_exhausted', 'manual_redrive')",
            name="ck_ingest_completion_delivery_error_code",
        ),
        sa.CheckConstraint(
            "(status = 'claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND disposition IS NULL AND last_error_code IS NULL "
            "AND next_attempt_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'succeeded' AND disposition IS NOT NULL AND disposition IN "
            "('sent', 'skipped_no_channel', 'skipped_deleted', "
            "'skipped_identity_disabled', 'skipped_owner_disabled', "
            "'skipped_target_mismatch') "
            "AND completed_at IS NOT NULL AND claim_token IS NULL "
            "AND claimed_at IS NULL AND next_attempt_at IS NULL "
            "AND last_error_code IS NULL) OR "
            "(status = 'failed' AND last_error_code IS NOT NULL "
            "AND claim_token IS NULL AND claimed_at IS NULL "
            "AND completed_at IS NULL AND "
            "((next_attempt_at IS NOT NULL AND disposition IS NULL) OR "
            "(next_attempt_at IS NULL AND disposition IS NOT NULL AND disposition IN "
            "('terminal_failure', 'retry_exhausted'))))",
            name="ck_ingest_completion_delivery_state_contract",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["ingest_completion_event.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "handler_key",
            name="uq_ingest_completion_delivery_event_handler",
        ),
    )
    op.create_index(
        "ix_ingest_completion_delivery_claim",
        "ingest_completion_delivery",
        ["status", "next_attempt_at", "claimed_at"],
    )
    op.create_index(
        "ix_ingest_completion_delivery_event",
        "ingest_completion_delivery",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingest_completion_delivery_event",
        table_name="ingest_completion_delivery",
    )
    op.drop_index(
        "ix_ingest_completion_delivery_claim",
        table_name="ingest_completion_delivery",
    )
    op.drop_table("ingest_completion_delivery")
    op.drop_index(
        "ix_ingest_dispatch_source_thread",
        table_name="ingest_dispatch",
    )
    op.drop_constraint(
        "fk_ingest_dispatch_source_thread",
        "ingest_dispatch",
        type_="foreignkey",
    )
    op.drop_column("ingest_dispatch", "source_thread_id")
