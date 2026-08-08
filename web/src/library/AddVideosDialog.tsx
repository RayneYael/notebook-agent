import { useEffect, useRef, useState } from "react";

import { submitVideoBatch } from "../api/client";
import type { BatchSubmitInput, BatchSubmitResponse } from "../api/contracts";

interface AddVideosDialogProps {
  open: boolean;
  onClose: () => void;
  submitBatch?: (input: BatchSubmitInput) => Promise<BatchSubmitResponse>;
  onSubmitted?: (result: BatchSubmitResponse) => void;
}

const resultCopy: Record<string, string> = {
  queued: "已添加，等待整理",
  already_exists: "资料库中已有此视频",
  unsupported_url: "暂不支持这个链接",
  invalid_url: "链接格式不正确",
  queue_unavailable: "暂时无法开始整理，请稍后重试",
  create_failed: "添加失败，请稍后重试",
  quota_exceeded: "已达到保存上限",
};

export function AddVideosDialog({
  open,
  onClose,
  submitBatch = submitVideoBatch,
  onSubmitted,
}: AddVideosDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [rawUrls, setRawUrls] = useState("");
  const [whySaved, setWhySaved] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchSubmitResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submissionGenerationRef = useRef(0);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) dialog.showModal();
      return;
    }
    if (dialog.open) dialog.close();
    submissionGenerationRef.current += 1;
    setRawUrls("");
    setWhySaved("");
    setError(null);
    setResult(null);
    setSubmitting(false);
  }, [open]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const urls = rawUrls.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    if (urls.length === 0) {
      setError("请至少粘贴一个 YouTube 链接。");
      return;
    }
    if (urls.length > 10) {
      setError("一次最多添加 10 个链接。");
      return;
    }
    setError(null);
    setSubmitting(true);
    const submissionGeneration = ++submissionGenerationRef.current;
    try {
      const nextResult = await submitBatch({ urls, why_saved: whySaved.trim() || null });
      if (submissionGeneration !== submissionGenerationRef.current) return;
      setResult(nextResult);
      onSubmitted?.(nextResult);
    } catch {
      if (submissionGeneration !== submissionGenerationRef.current) return;
      setError("添加未完成，请检查网络后重试。");
    } finally {
      if (submissionGeneration === submissionGenerationRef.current) setSubmitting(false);
    }
  }

  return (
    <dialog
      className="add-dialog"
      ref={dialogRef}
      aria-labelledby="add-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <form className="add-form" onSubmit={handleSubmit}>
        <header className="dialog-header">
          <div>
            <p className="eyebrow">一次最多添加 10 个</p>
            <h2 id="add-dialog-title">添加 YouTube 视频</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭添加视频窗口" onClick={onClose}>×</button>
        </header>
        <label className="field">
          <span>YouTube 链接，每行一个</span>
          <textarea
            name="urls"
            autoComplete="off"
            spellCheck={false}
            rows={6}
            value={rawUrls}
            onChange={(event) => setRawUrls(event.target.value)}
          />
        </label>
        <label className="field">
          <span>为什么保存（可选）</span>
          <input
            name="why-saved"
            autoComplete="off"
            value={whySaved}
            maxLength={500}
            placeholder="例如：用于周末精读或项目调研"
            onChange={(event) => setWhySaved(event.target.value)}
          />
        </label>
        {error ? <p className="inline-error" role="alert">{error}</p> : null}
        {result ? (
          <ol className="submission-results" aria-label="添加结果" aria-live="polite">
            {result.results.map((item) => (
              <li key={`${item.input_index}-${item.status}`} data-status={item.status}>
                <span>第 {item.input_index + 1} 个链接</span>
                <strong>{resultCopy[item.status] ?? "未能确认处理结果，请稍后查看资料库"}</strong>
              </li>
            ))}
          </ol>
        ) : null}
        <button className="button button--primary button--wide" disabled={submitting} type="submit">
          {submitting ? "正在添加…" : "添加并整理"}
        </button>
      </form>
    </dialog>
  );
}
