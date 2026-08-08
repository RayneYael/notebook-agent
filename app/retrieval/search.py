"""Independent vector and lexical retrieval paths for P0 comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import desc, func, or_, select

from app.models import ContentItem, Segment


@dataclass(frozen=True)
class Hit:
    item_id: int
    title: str | None
    platform_id: str
    segment_id: int
    text: str
    start_sec: float
    score: float

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.platform_id}?t={int(self.start_sec)}"


def _hits(rows) -> list[Hit]:
    return [Hit(item.id, item.title, item.platform_id, segment.id, segment.text, float(segment.start_sec), float(score)) for segment, item, score in rows]


def vector_search(db, query_vector: list[float], *, user_id: int, k: int = 20) -> list[Hit]:
    distance = Segment.embedding.cosine_distance(query_vector)
    stmt = select(Segment, ContentItem, (1 - distance).label("score")).join(ContentItem).where(ContentItem.user_id == user_id, ContentItem.deleted_at.is_(None), ContentItem.state == "ready", Segment.embedding.isnot(None)).order_by(distance).limit(k)
    return _hits(db.execute(stmt).all())


def bm25_search(db, query: str, *, user_id: int, k: int = 20) -> list[Hit]:
    is_zh = bool(re.search(r"[\u3400-\u9fff]", query))
    base = select(Segment, ContentItem).join(ContentItem).where(ContentItem.user_id == user_id, ContentItem.deleted_at.is_(None), ContentItem.state == "ready")
    if is_zh:
        score = func.similarity(Segment.text, query)
        stmt = base.add_columns(score.label("score")).where(ContentItem.lang.like("zh%"), or_(Segment.text.op("%")(query), Segment.text.ilike(f"%{query}%"))).order_by(desc(score)).limit(k)
    else:
        tsquery = func.websearch_to_tsquery("english", query)
        score = func.ts_rank_cd(Segment.fts, tsquery)
        stmt = base.add_columns(score.label("score")).where(Segment.fts.op("@@")(tsquery)).order_by(desc(score)).limit(k)
    return _hits(db.execute(stmt).all())
