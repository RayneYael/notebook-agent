"""hash-only, revocable MCP bearer grants

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_access_grant",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("grant_id", sa.Text(), nullable=False),
        sa.Column("app_user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), server_default="read", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "scope IN ('read', 'full')", name="ck_mcp_access_grant_scope"
        ),
        sa.CheckConstraint(
            "label IS NULL OR length(label) <= 200",
            name="ck_mcp_access_grant_label_length",
        ),
        sa.CheckConstraint(
            "created_by IS NULL OR length(created_by) <= 128",
            name="ck_mcp_access_grant_created_by_length",
        ),
        sa.ForeignKeyConstraint(
            ["app_user_id"], ["app_user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_id", name="uq_mcp_access_grant_grant_id"),
        sa.UniqueConstraint("token_hash", name="uq_mcp_access_grant_token_hash"),
    )
    op.create_index(
        "ix_mcp_access_grant_user", "mcp_access_grant", ["app_user_id"]
    )
    op.create_index(
        "ix_mcp_access_grant_active", "mcp_access_grant",
        ["grant_id", "revoked_at", "disabled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_access_grant_active", table_name="mcp_access_grant")
    op.drop_index("ix_mcp_access_grant_user", table_name="mcp_access_grant")
    op.drop_table("mcp_access_grant")
