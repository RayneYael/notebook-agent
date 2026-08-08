import { type FormEvent, useState } from "react";

import type { LibraryItem, TranscriptPage } from "../api/contracts";
import { lifecycleCopy } from "../library/lifecycle";
import { formatDuration } from "../library/VideoCard";

interface VideoDetailViewProps {
  item: LibraryItem;
  transcriptPages: TranscriptPage[];
  onLoadMore: () => void;
  onRetryTranscript?: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onRetry: () => void;
  onUpdateWhySaved: (value: string | null) => Promise<void> | void;
  actionPending?: boolean;
  actionError?: boolean;
  transcriptPending?: boolean;
  transcriptInitialPending?: boolean;
  transcriptError?: boolean;
}

function timestampUrl(url: string, seconds: number): string {
  const parsed = new URL(url);
  parsed.searchParams.set("t", String(Math.max(0, Math.floor(seconds))));
  return parsed.toString();
}

function formatTimestamp(seconds: number): string {
  return formatDuration(seconds) ?? "0:00";
}

export function VideoDetailView({
  item,
  transcriptPages,
  onLoadMore,
  onRetryTranscript,
  onArchive,
  onRestore,
  onRetry,
  onUpdateWhySaved,
  actionPending = false,
  actionError = false,
  transcriptPending = false,
  transcriptInitialPending = false,
  transcriptError = false,
}: VideoDetailViewProps) {
  const [editingReason, setEditingReason] = useState(false);
  const [reason, setReason] = useState(item.why_saved ?? "");
  const blocks = transcriptPages.flatMap((page) => page.blocks);
  const nextCursor = transcriptPages.at(-1)?.next_cursor ?? null;
  const actions = new Set(item.available_actions);

  async function submitReason(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await onUpdateWhySaved(reason.trim() || null);
      setEditingReason(false);
    } catch {
      // The parent mutation renders a safe error while this form stays editable.
    }
  }

  return (
    <article className="detail-layout">
      <header className="detail-hero">
        <div className="detail-cover">
          {item.cover_url ? <img src={item.cover_url} alt="" width={960} height={540} fetchPriority="high" /> : <div className="cover-placeholder cover-placeholder--large" aria-hidden="true"><span>YT</span></div>}
        </div>
        <div className="detail-heading">
          <span className={`status-pill status-pill--${item.lifecycle}`}>{lifecycleCopy[item.lifecycle].label}</span>
          <h1>{item.title?.trim() || "正在等待视频信息"}</h1>
          <p className="detail-meta">
            {item.author ? <span>{item.author}</span> : null}
            {item.duration_sec !== null ? <span>{formatDuration(item.duration_sec)}</span> : null}
            {item.lang ? <span>{item.lang.toUpperCase()}</span> : null}
          </p>
          <div className="detail-actions" aria-label="视频操作">
            <a className="button button--primary" href={item.url} target="_blank" rel="noreferrer">打开原视频</a>
            {actions.has("retry") ? <button className="button button--quiet" disabled={actionPending} onClick={onRetry}>重新处理</button> : null}
            {actions.has("archive") ? <button className="button button--ghost" disabled={actionPending} onClick={onArchive}>归档</button> : null}
            {actions.has("restore") ? <button className="button button--quiet" disabled={actionPending} onClick={onRestore}>恢复到资料库</button> : null}
          </div>
          {actionError ? <p className="inline-error" role="alert" aria-label="视频操作失败">操作没有完成，请重试。</p> : null}
        </div>
      </header>

      <section className="detail-section reason-section" aria-labelledby="reason-title">
        <div className="section-heading-row">
          <div><p className="eyebrow">你的上下文</p><h2 id="reason-title">为什么保存</h2></div>
          {actions.has("edit_why_saved") ? <button className="text-button" onClick={() => setEditingReason((value) => !value)}>{editingReason ? "取消" : "编辑"}</button> : null}
        </div>
        {editingReason ? (
          <form onSubmit={submitReason}>
            <label className="field"><span className="sr-only">为什么保存</span><textarea name="why-saved-detail" autoComplete="off" rows={3} maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
            <button className="button button--quiet" disabled={actionPending} type="submit">保存说明</button>
          </form>
        ) : <p>{item.why_saved || "还没有添加说明。"}</p>}
      </section>

      {item.chapters.length > 0 ? (
        <section className="detail-section" aria-labelledby="chapters-title">
          <p className="eyebrow">导航</p>
          <h2 id="chapters-title">章节</h2>
          <ol className="chapter-list">
            {item.chapters.map((chapter, index) => {
              const start = Number(chapter.start_sec ?? chapter.start_time ?? chapter.start ?? 0);
              return (
                <li key={`${start}-${index}`}>
                  <a href={timestampUrl(item.url, start)} target="_blank" rel="noreferrer">
                    <time>{formatTimestamp(start)}</time>
                    <span>{chapter.title?.trim() || `章节 ${index + 1}`}</span>
                  </a>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {item.description?.trim() ? (
        <section className="detail-section" aria-labelledby="description-title">
          <p className="eyebrow">来自 YouTube</p>
          <h2 id="description-title">视频简介</h2>
          <p className="description-copy">{item.description}</p>
        </section>
      ) : null}

      {item.summary?.trim() ? (
        <section className="detail-section" aria-labelledby="summary-title">
          <p className="eyebrow">已存内容</p>
          <h2 id="summary-title">已有摘要</h2>
          <p className="description-copy">{item.summary}</p>
        </section>
      ) : null}

      <section className="detail-section transcript-section" aria-labelledby="transcript-title">
        <div className="section-heading-row">
          <div><p className="eyebrow">原始字幕 · 非搜索切片</p><h2 id="transcript-title">原始全文</h2></div>
          {blocks.length > 0 ? <span className="block-count">{blocks.length} 段</span> : null}
        </div>
        {transcriptError ? (
          <div className="inline-error transcript-error" role="alert" aria-label="全文加载失败">
            <p>全文暂时无法加载，请检查网络后重试。</p>
            {onRetryTranscript ? <button className="button button--quiet" type="button" onClick={onRetryTranscript}>重新加载全文</button> : null}
          </div>
        ) : transcriptInitialPending ? (
          <p className="muted" aria-live="polite" aria-busy="true">正在加载原始全文…</p>
        ) : blocks.length > 0 ? (
          <ol className="transcript-list">
            {blocks.map((block) => (
              <li key={block.ordinal}>
                <a href={block.source_url} target="_blank" rel="noreferrer" aria-label={`从 ${formatTimestamp(block.start_sec)} 播放`}>{formatTimestamp(block.start_sec)}</a>
                <p>{block.text}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">{item.lifecycle === "ready" ? "这段视频没有可显示的字幕。" : "全文会在视频整理完成后出现。"}</p>
        )}
        {nextCursor ? <button className="button button--quiet button--wide" disabled={transcriptPending} onClick={onLoadMore}>继续加载全文</button> : null}
      </section>
    </article>
  );
}
