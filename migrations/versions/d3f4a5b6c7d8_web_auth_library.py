"""web login challenges, sessions, and public library identifiers

Revision ID: d3f4a5b6c7d8
Revises: c7e8a91b2d34
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "c7e8a91b2d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PUBLIC_ID_DEFAULT = sa.text("replace(gen_random_uuid()::text, '-', '')")


def upgrade() -> None:
    op.add_column(
        "content_item",
        sa.Column(
            "public_id",
            sa.Text(),
            server_default=_PUBLIC_ID_DEFAULT,
            nullable=True,
        ),
    )
    # The volatile function is evaluated once per legacy row. The unique
    # constraint is installed only after all existing rows have a value.
    op.execute(
        """
        UPDATE content_item
        SET public_id = replace(gen_random_uuid()::text, '-', '')
        WHERE public_id IS NULL
        """
    )
    op.alter_column("content_item", "public_id", nullable=False)
    op.create_unique_constraint(
        "uq_content_item_public_id", "content_item", ["public_id"]
    )
    op.add_column(
        "content_item",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_content_item_user_archived_saved_at",
        "content_item",
        ["user_id", "archived_at", sa.text("saved_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_content_item_saved_at",
        "content_item",
        [sa.text("saved_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_ingest_dispatch_created_item",
        "ingest_dispatch",
        [sa.text("created_at DESC"), "item_id"],
        unique=False,
    )

    op.create_table(
        "web_login_challenge",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("browser_token_hash", sa.Text(), nullable=False),
        sa.Column("requester_hash", sa.Text(), nullable=False),
        sa.Column("target_channel", sa.Text(), nullable=False),
        sa.Column("approved_app_user_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_by_identity_id", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approved_app_user_id"],
            ["app_user.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_identity_id"],
            ["channel_identity.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_web_login_challenge_public_id"),
        sa.UniqueConstraint("code_hash", name="uq_web_login_challenge_code_hash"),
    )
    op.create_index(
        "ix_web_login_challenge_expires_at",
        "web_login_challenge",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_web_login_challenge_created_at",
        "web_login_challenge",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_web_login_challenge_requester_created",
        "web_login_challenge",
        ["requester_hash", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_web_login_challenge_approved_user",
        "web_login_challenge",
        ["approved_app_user_id"],
        unique=False,
        postgresql_where=sa.text("approved_app_user_id IS NOT NULL"),
    )

    op.create_table(
        "web_session",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token_hash", sa.Text(), nullable=False),
        sa.Column("app_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login_channel", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["app_user_id"], ["app_user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_web_session_public_id"),
        sa.UniqueConstraint("token_hash", name="uq_web_session_token_hash"),
    )
    op.create_index(
        "ix_web_session_user_expires",
        "web_session",
        ["app_user_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_web_session_expires_at",
        "web_session",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_web_session_revoked_at",
        "web_session",
        ["revoked_at"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_web_session_revoked_at", table_name="web_session")
    op.drop_index("ix_web_session_expires_at", table_name="web_session")
    op.drop_index("ix_web_session_user_expires", table_name="web_session")
    op.drop_table("web_session")
    op.drop_index(
        "ix_web_login_challenge_approved_user",
        table_name="web_login_challenge",
    )
    op.drop_index(
        "ix_web_login_challenge_requester_created",
        table_name="web_login_challenge",
    )
    op.drop_index(
        "ix_web_login_challenge_created_at",
        table_name="web_login_challenge",
    )
    op.drop_index(
        "ix_web_login_challenge_expires_at",
        table_name="web_login_challenge",
    )
    op.drop_table("web_login_challenge")
    op.drop_index(
        "ix_ingest_dispatch_created_item",
        table_name="ingest_dispatch",
    )
    op.drop_index("ix_content_item_saved_at", table_name="content_item")
    op.drop_index(
        "ix_content_item_user_archived_saved_at", table_name="content_item"
    )
    op.drop_column("content_item", "archived_at")
    op.drop_constraint(
        "uq_content_item_public_id", "content_item", type_="unique"
    )
    op.drop_column("content_item", "public_id")
