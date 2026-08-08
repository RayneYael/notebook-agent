"""recycle-bin lifecycle fields and tenant-scoped management indexes

Revision ID: d4e5f6a7b8c9
Revises: c7e8a91b2d34
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c7e8a91b2d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Replace the original broad saved-at index with a partial index.  The
    # index name is retained so existing query plans and operational tooling
    # remain recognizable.
    op.drop_index("ix_content_item_user_saved_at", table_name="content_item")
    op.add_column("content_item", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_item", sa.Column("purge_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "content_item",
        sa.Column("purge_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("content_item", sa.Column("purge_error_code", sa.Text(), nullable=True))
    op.add_column("content_item", sa.Column("delete_claim_token", sa.Text(), nullable=True))
    op.create_index(
        "ix_content_item_user_saved_at",
        "content_item",
        ["user_id", sa.text("saved_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_content_item_user_deleted_at",
        "content_item",
        ["user_id", sa.text("deleted_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index(
        "ix_content_item_deleted_at_id",
        "content_item",
        ["deleted_at", "id"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    # This is intentionally a schema-only rollback.  Deployments must restore
    # or purge soft-deleted rows before removing these columns; a migration
    # cannot safely make that tenant/business decision for operators.
    bind = op.get_bind()
    remaining = bind.execute(
        sa.text("SELECT count(*) FROM content_item WHERE deleted_at IS NOT NULL")
    ).scalar_one()
    if int(remaining or 0) > 0:
        raise RuntimeError(
            "refusing downgrade while content_item contains recycle-bin rows; "
            "restore or purge them after backup and disable management/beat"
        )
    op.drop_index("ix_content_item_deleted_at_id", table_name="content_item")
    op.drop_index("ix_content_item_user_deleted_at", table_name="content_item")
    op.drop_index("ix_content_item_user_saved_at", table_name="content_item")
    op.drop_column("content_item", "delete_claim_token")
    op.drop_column("content_item", "purge_error_code")
    op.drop_column("content_item", "purge_attempts")
    op.drop_column("content_item", "purge_claimed_at")
    op.drop_column("content_item", "deleted_at")
    op.create_index(
        "ix_content_item_user_saved_at",
        "content_item",
        ["user_id", sa.text("saved_at DESC")],
    )
