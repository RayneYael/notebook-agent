import { Link } from "react-router";

import type { LibraryItem } from "../api/contracts";
import { lifecycleCopy } from "./lifecycle";

export function formatDuration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return null;
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`
    : `${minutes}:${String(remaining).padStart(2, "0")}`;
}

export function VideoCard({ item }: { item: LibraryItem }) {
  const duration = formatDuration(item.duration_sec);
  const title = item.title?.trim() || "视频信息尚未准备好";
  return (
    <article className="video-card" data-lifecycle={item.lifecycle}>
      <Link className="video-card__link" to={`/videos/${item.public_id}`} aria-label={`${title}，查看详情`}>
        <div className="video-card__cover">
          {item.cover_url ? <img src={item.cover_url} alt="" width={960} height={540} loading="lazy" decoding="async" /> : <div className="cover-placeholder" aria-hidden="true"><span>暂无封面</span></div>}
          {duration ? <span className="duration-badge">{duration}</span> : null}
        </div>
        <div className="video-card__body">
          <div className="video-card__topline">
            <span className={`status-pill status-pill--${item.lifecycle}`}>{lifecycleCopy[item.lifecycle].label}</span>
            <time dateTime={item.saved_at}>{new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(item.saved_at))}</time>
          </div>
          <h2>{title}</h2>
          {item.author ? <p className="video-card__author">{item.author}</p> : null}
          {item.why_saved ? <blockquote>{item.why_saved}</blockquote> : null}
          {item.lifecycle === "failed" ? <p className="card-hint">打开详情后可重新整理</p> : null}
        </div>
      </Link>
    </article>
  );
}
