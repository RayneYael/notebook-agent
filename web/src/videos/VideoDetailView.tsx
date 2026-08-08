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

function formatLanguage(code: string | null): string | null {
  if (!code) return null;
  const normalized = code.trim().toLowerCase();
  const names: Record<string, string> = {
    zh: "中文",
    "zh-cn": "简体中文",
    "zh-hans": "简体中文",
    "zh-tw": "繁体中文",
    "zh-hant": "繁体中文",
    en: "英文",
    "en-us": "英文",
    "en-gb": "英文",
    ja: "日文",
    ko: "韩文",
  };
  return names[normalized] ?? names[normalized.split("-")[0]] ?? null;
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
  const language = formatLanguage(item.lang);

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
          {item.cover_url ? <img src={item.cover_url} alt="" width={960} height={540} fetchPriority="high" /> : <div className="cover-placeholder cover-placeholder--large" aria-hidden="true"><span>暂无封面</span></div>}
        </div>
        <div className="detail-heading">
          <span className={`status-pill status-pill--${item.lifecycle}`}>{lifecycleCopy[item.lifecycle].label}</span>
          <h1>{item.title?.trim() || "视频信息尚未准备好"}</h1>
          <p className="detail-meta">
            {item.author ? <span>{item.author}</span> : null}
            {item.duration_sec !== null ? <span>{formatDuration(item.duration_sec)}</span> : null}
            {language ? <span>{language}</span> : null}
          </p>
          <div className="detail-actions" aria-label="视频操作">
            <a className="button button--primary" href={item.url} target="_blank" rel="noreferrer">在 YouTube 查看</a>
            {actions.has("retry") ? <button className="button button--quiet" disabled={actionPending} onClick={onRetry}>重新整理</button> : null}
            {actions.has("archive") ? <button className="button button--ghost" disabled={actionPending} onClick={onArchive}>归档</button> : null}
            {actions.has("restore") ? <button className="button button--quiet" disabled={actionPending} onClick={onRestore}>恢复到资料库</button> : null}
          </div>
          {actionError ? <p className="inline-error" role="alert" aria-label="视频操作失败">操作未完成，请稍后重试。</p> : null}
        </div>
      </header>

      <section className="detail-section reason-section" aria-labelledby="reason-title">
        <div className="section-heading-row">
          <div><p className="eyebrow">保存说明</p><h2 id="reason-title">为什么保存</h2></div>
          {actions.has("edit_why_saved") ? <button className="text-button" onClick={() => setEditingReason((value) => !value)}>{editingReason ? "取消" : "编辑"}</button> : null}
        </div>
        {editingReason ? (
          <form onSubmit={submitReason}>
            <label className="field"><span className="sr-only">保存说明</span><textarea name="why-saved-detail" autoComplete="off" rows={3} maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
            <button className="button button--quiet" disabled={actionPending} type="submit">保存说明</button>
          </form>
        ) : <p>{item.why_saved || "还没有添加保存说明。"}</p>}
      </section>

      {item.chapters.length > 0 ? (
        <section className="detail-section" aria-labelledby="chapters-title">
          <p className="eyebrow">快速跳转</p>
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
          <p className="eyebrow">整理结果</p>
          <h2 id="summary-title">摘要</h2>
          <p className="description-copy">{item.summary}</p>
        </section>
      ) : null}

      <section className="detail-section transcript-section" aria-labelledby="transcript-title">
        <div className="section-heading-row">
          <div><p className="eyebrow">来自原视频字幕</p><h2 id="transcript-title">完整字幕</h2></div>
          {blocks.length > 0 ? <span className="block-count">已加载 {blocks.length} 段</span> : null}
        </div>
        {transcriptError ? (
          <div className="inline-error transcript-error" role="alert" aria-label="字幕加载失败">
            <p>字幕暂时无法加载，请稍后重试。</p>
            {onRetryTranscript ? <button className="button button--quiet" type="button" onClick={onRetryTranscript}>重新加载字幕</button> : null}
          </div>
        ) : transcriptInitialPending ? (
          <p className="muted" aria-live="polite" aria-busy="true">正在加载字幕…</p>
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
          <p className="muted">{item.lifecycle === "ready" ? "这个视频没有可显示的字幕。" : "整理完成后可查看字幕。"}</p>
        )}
        {nextCursor ? <button className="button button--quiet button--wide" disabled={transcriptPending} onClick={onLoadMore}>继续加载字幕</button> : null}
      </section>
    </article>
  );
}
