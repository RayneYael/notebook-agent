"""private users, channel identities, link tokens and conversations

Revision ID: 9a6b2c4d8e10
Revises: 6df2e721d7b2
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "9a6b2c4d8e10"
down_revision: Union[str, Sequence[str], None] = "6df2e721d7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "app_user", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    # P0/local databases may have inserted explicit user ids before self-registration
    # existed. Align the identity sequence so the first generated id cannot collide.
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('app_user', 'id'),
            COALESCE((SELECT MAX(id) FROM app_user), 1),
            EXISTS (SELECT 1 FROM app_user)
        )
        """
    )

    op.create_table(
        "channel_identity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("app_user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("external_user_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["app_user_id"], ["app_user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel",
            "account_id",
            "external_user_id",
            name="uq_channel_identity_external",
        ),
    )
    op.create_index(
        "ix_channel_identity_user", "channel_identity", ["app_user_id"]
    )

    op.create_table(
        "channel_link_token",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("app_user_id", sa.BigInteger(), nullable=False),
        sa.Column("target_channel", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["app_user_id"], ["app_user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_channel_link_token_user", "channel_link_token", ["app_user_id"]
    )

    op.create_table(
        "conversation_thread",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column("app_user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("external_conversation_id", sa.Text(), nullable=False),
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
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["app_user_id"], ["app_user.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["channel_identity_id"], ["channel_identity.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_conversation_thread_user_updated",
        "conversation_thread",
        ["app_user_id", sa.text("updated_at DESC")],
    )
    op.create_index(
        "uq_conversation_thread_active",
        "conversation_thread",
        ["channel_identity_id", "external_conversation_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )

    op.create_table(
        "conversation_turn",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("assistant_text", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "model_messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "status", sa.Text(), server_default="completed", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["conversation_thread.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id", "message_id", name="uq_conversation_turn_message"
        ),
    )
    op.create_index(
        "ix_conversation_turn_thread_created",
        "conversation_turn",
        ["thread_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_turn_thread_created", table_name="conversation_turn"
    )
    op.drop_table("conversation_turn")
    op.drop_index(
        "uq_conversation_thread_active", table_name="conversation_thread"
    )
    op.drop_index(
        "ix_conversation_thread_user_updated", table_name="conversation_thread"
    )
    op.drop_table("conversation_thread")
    op.drop_index("ix_channel_link_token_user", table_name="channel_link_token")
    op.drop_table("channel_link_token")
    op.drop_index("ix_channel_identity_user", table_name="channel_identity")
    op.drop_table("channel_identity")
    op.drop_column("app_user", "disabled_at")
    op.drop_column("app_user", "created_at")
