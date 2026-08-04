"""SQLAlchemy models for the personal knowledge base.

Mirrors the DDL in `.trellis/tasks/08-04-video-text-kb/design.md` (数据模型
section) exactly: enum types, `content_item` + `segment` tables, the
`loc_ck` mutual-exclusion constraint, uniqueness constraints, and the
HNSW / GIN / trigram indexes on `segment`.

`app_user` is intentionally minimal (single-user MVP, no auth logic) — it
exists only so `content_item.user_id` has something to reference.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --- Enum types (native Postgres ENUM, matches design.md DDL names) ---

platform_enum = PgEnum(
    "youtube", "bilibili", "wechat_mp",
    name="platform",
)

item_kind_enum = PgEnum(
    "video", "article",
    name="item_kind",
)

text_source_enum = PgEnum(
    "official_cc", "auto_caption", "asr_whisper", "article_text", "none",
    name="text_source",
)

ingest_state_enum = PgEnum(
    "pending", "fetching", "needs_extension", "needs_asr",
    "chunking", "embedding", "ready", "failed", "no_text",
    name="ingest_state",
)


class AppUser(Base):
    """Minimal user table — single-user MVP, no auth/roles/permissions.

    Exists solely to satisfy `content_item.user_id` FK (design.md 已知取舍:
    单用户优先，schema 有 user_id 但不做多租户隔离).
    """

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class ContentItem(Base):
    __tablename__ = "content_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(platform_enum, nullable=False)
    platform_id: Mapped[str] = mapped_column(Text, nullable=False)  # video_id / bvid / sn
    kind: Mapped[str] = mapped_column(item_kind_enum, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[int | None] = mapped_column(Integer)  # video only
    char_count: Mapped[int | None] = mapped_column(Integer)  # article only
    lang: Mapped[str | None] = mapped_column(Text)  # 'en' / 'zh' -> 驱动切分阈值
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    chapters: Mapped[dict | list | None] = mapped_column(JSONB)  # YouTube: [{start,end,title}]
    cover_url: Mapped[str | None] = mapped_column(Text)

    # 用户侧
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    why_saved: Mapped[str | None] = mapped_column(Text)
    watch_state: Mapped[str | None] = mapped_column(Text, server_default="unwatched")
    watch_pos_sec: Mapped[int | None] = mapped_column(Integer)

    # 去重与溯源
    content_hash: Mapped[str | None] = mapped_column(Text)  # 正文/转录规范化后 sha256
    raw_object_key: Mapped[str | None] = mapped_column(Text)  # MinIO: 原始 json3 / HTML
    text_source: Mapped[str] = mapped_column(
        text_source_enum, nullable=False, server_default="none"
    )
    state: Mapped[str] = mapped_column(
        ingest_state_enum, nullable=False, server_default="pending"
    )
    fail_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform", "platform_id",
            name="uq_content_item_user_platform_platform_id",
        ),
        Index("ix_content_item_user_saved_at", "user_id", saved_at.desc()),
        Index(
            "ix_content_item_content_hash",
            "content_hash",
            postgresql_where=content_hash.isnot(None),
        ),
    )


class Segment(Base):
    __tablename__ = "segment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_item.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    # 定位符：视频用秒，图文用字符偏移；互斥（见 loc_ck）
    start_sec: Mapped[float | None] = mapped_column(Numeric(9, 2))
    end_sec: Mapped[float | None] = mapped_column(Numeric(9, 2))
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    anchor: Mapped[str | None] = mapped_column(Text)  # 图文：段落序号或标题锚点

    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    fts: Mapped[str | None] = mapped_column(TSVECTOR)
    boundary_kind: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # chapter|gap|punct|semantic|hard_cut

    __table_args__ = (
        CheckConstraint(
            "(start_sec IS NOT NULL AND char_start IS NULL) OR "
            "(char_start IS NOT NULL AND start_sec IS NULL)",
            name="loc_ck",
        ),
        UniqueConstraint("item_id", "seq", name="uq_segment_item_id_seq"),
        Index(
            "ix_segment_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_segment_fts_gin", "fts", postgresql_using="gin"),
        Index(
            "ix_segment_text_trgm_gin",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )
