import type { LibraryItemSummary, LibraryLifecycle } from "../api/contracts";

export const lifecycleCopy: Record<
  LibraryLifecycle,
  { label: string; description: string }
> = {
  queued: { label: "等待处理", description: "任务已保存，等待后台开始。" },
  processing: { label: "正在整理", description: "正在读取字幕并生成可搜索内容。" },
  ready: { label: "可阅读", description: "字幕与章节已经准备好。" },
  needs_action: { label: "需要处理", description: "当前字幕来源不足，需要其他处理方式。" },
  failed: { label: "处理失败", description: "这次整理没有完成，可以稍后重试。" },
  archived: { label: "已归档", description: "该视频已从日常资料库中收起。" },
};

export function shouldPollLibrary(
  items: ReadonlyArray<Pick<LibraryItemSummary, "lifecycle">>,
): boolean {
  return items.some(({ lifecycle }) => lifecycle === "queued" || lifecycle === "processing");
}
