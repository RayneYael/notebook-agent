"""init schema

Creates the `vector` and `pg_trgm` extensions plus the `content_item` and
`segment` tables (with their enum types, constraints, and indexes) per
`.trellis/tasks/08-04-video-text-kb/design.md` 数据模型 section.

Revision ID: 6df2e721d7b2
Revises:
Create Date: 2026-08-04 20:22:05.935829

"""
from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6df2e721d7b2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# create_type=False: the enum types are created explicitly below (once,
# via checkfirst=True) so create_table must not try to create them again
# when it sees these enum-typed columns.
platform_enum = postgresql.ENUM(
    "youtube", "bilibili", "wechat_mp", name="platform", create_type=False
)
item_kind_enum = postgresql.ENUM(
    "video", "article", name="item_kind", create_type=False
)
text_source_enum = postgresql.ENUM(
    "official_cc", "auto_caption", "asr_whisper", "article_text", "none",
    name="text_source", create_type=False,
)
ingest_state_enum = postgresql.ENUM(
    "pending", "fetching", "needs_extension", "needs_asr",
    "chunking", "embedding", "ready", "failed", "no_text",
    name="ingest_state", create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    bind = op.get_bind()
    platform_enum.create(bind, checkfirst=True)
    item_kind_enum.create(bind, checkfirst=True)
    text_source_enum.create(bind, checkfirst=True)
    ingest_state_enum.create(bind, checkfirst=True)

    op.create_table(
        "app_user",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
    )

    op.create_table(
        "content_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform", platform_enum, nullable=False),
        sa.Column("platform_id", sa.Text(), nullable=False),
        sa.Column("kind", item_kind_enum, nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("lang", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("chapters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("why_saved", sa.Text(), nullable=True),
        sa.Column("watch_state", sa.Text(), server_default="unwatched", nullable=True),
        sa.Column("watch_pos_sec", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("raw_object_key", sa.Text(), nullable=True),
        sa.Column("text_source", text_source_enum, server_default="none", nullable=False),
        sa.Column("state", ingest_state_enum, server_default="pending", nullable=False),
        sa.Column("fail_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name="fk_content_item_user_id_app_user"),
        sa.PrimaryKeyConstraint("id", name="pk_content_item"),
        sa.UniqueConstraint(
            "user_id", "platform", "platform_id",
            name="uq_content_item_user_platform_platform_id",
        ),
    )
    op.create_index(
        "ix_content_item_user_saved_at",
        "content_item",
        ["user_id", sa.text("saved_at DESC")],
    )
    op.create_index(
        "ix_content_item_content_hash",
        "content_item",
        ["content_hash"],
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )

    op.create_table(
        "segment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("start_sec", sa.Numeric(9, 2), nullable=True),
        sa.Column("end_sec", sa.Numeric(9, 2), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("anchor", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("fts", postgresql.TSVECTOR(), nullable=True),
        sa.Column("boundary_kind", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(start_sec IS NOT NULL AND char_start IS NULL) OR "
            "(char_start IS NOT NULL AND start_sec IS NULL)",
            name="loc_ck",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["content_item.id"],
            name="fk_segment_item_id_content_item",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_segment"),
        sa.UniqueConstraint("item_id", "seq", name="uq_segment_item_id_seq"),
    )
    op.create_index(
        "ix_segment_embedding_hnsw",
        "segment",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_segment_fts_gin",
        "segment",
        ["fts"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_segment_text_trgm_gin",
        "segment",
        ["text"],
        postgresql_using="gin",
        postgresql_ops={"text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_segment_text_trgm_gin", table_name="segment")
    op.drop_index("ix_segment_fts_gin", table_name="segment")
    op.drop_index("ix_segment_embedding_hnsw", table_name="segment")
    op.drop_table("segment")

    op.drop_index("ix_content_item_content_hash", table_name="content_item")
    op.drop_index("ix_content_item_user_saved_at", table_name="content_item")
    op.drop_table("content_item")

    op.drop_table("app_user")

    bind = op.get_bind()
    ingest_state_enum.drop(bind, checkfirst=True)
    text_source_enum.drop(bind, checkfirst=True)
    item_kind_enum.drop(bind, checkfirst=True)
    platform_enum.drop(bind, checkfirst=True)

    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")

