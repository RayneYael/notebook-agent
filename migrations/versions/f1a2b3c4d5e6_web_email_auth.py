"""web email challenges and unified browser-session linkage

Revision ID: f1a2b3c4d5e6
Revises: b2c3d4e5f6a7
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_auth_challenge",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_failed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_web_auth_challenge_email_expiry", "web_auth_challenge", ["email", "expires_at"])
    # ``web_session`` is already created by the upstream channel-assisted
    # login migration.  Keep that API-compatible session shape, then add the
    # email flow's identity linkage and usage audit fields without rewriting
    # or invalidating existing channel sessions.
    op.add_column(
        "web_session",
        sa.Column("channel_identity_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_web_session_channel_identity_id",
        "web_session",
        "channel_identity",
        ["channel_identity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "web_session",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_web_session_token_active",
        "web_session",
        ["token_hash", "revoked_at"],
    )
    op.create_index(
        "ix_web_session_user_active",
        "web_session",
        ["app_user_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_web_session_user_active", table_name="web_session")
    op.drop_index("ix_web_session_token_active", table_name="web_session")
    op.drop_constraint(
        "fk_web_session_channel_identity_id",
        "web_session",
        type_="foreignkey",
    )
    op.drop_column("web_session", "last_used_at")
    op.drop_column("web_session", "channel_identity_id")
    op.drop_index("ix_web_auth_challenge_email_expiry", table_name="web_auth_challenge")
    op.drop_table("web_auth_challenge")
