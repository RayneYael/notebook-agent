import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { Capabilities, LibraryItem, LibraryPageResponse } from "../api/contracts";
import { LibraryPage } from "./LibraryPage";

const readyItem: LibraryItem = {
  public_id: "video-public",
  platform: "youtube",
  kind: "video",
  url: "https://youtu.be/x",
  title: "理解比收藏重要",
  author: "Notebook Studio",
  published_at: null,
  duration_sec: 60,
  lang: "zh",
  description: null,
  tags: [],
  chapters: [],
  cover_url: null,
  saved_at: "2026-08-07T10:00:00Z",
  why_saved: null,
  text_source: "youtube_captions",
  lifecycle: "ready",
  error_code: null,
  available_actions: ["archive"],
  latest_dispatch_public_id: null,
};

function renderPage(fetchItems: () => Promise<LibraryPageResponse>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const capabilities: Capabilities = {
    supported_platforms: ["youtube"],
    web_login_channels: ["telegram"],
    save_enabled: true,
    max_save_batch_size: 10,
    transcript_pagination: true,
    archive: true,
    summary_generation: false,
    chat: false,
  };
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LibraryPage
          fetchItems={fetchItems}
          loadCapabilities={vi.fn().mockResolvedValue(capabilities)}
          submitBatch={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("library page", () => {
  it("shows static agent guidance only after a successful true-empty response", async () => {
    renderPage(async () => ({ items: [], total: 0, page: 1, page_size: 20, is_true_first_empty: true }));
    expect(await screen.findByText("资料库还是空的")).toBeInTheDocument();
    expect(screen.queryByText(/我是你的资料整理助手/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加视频" })).toBeInTheDocument();
  });

  it("renders server-owned items instead of an empty agent state", async () => {
    renderPage(async () => ({ items: [readyItem], total: 1, page: 1, page_size: 20, is_true_first_empty: false }));
    expect(await screen.findByText("理解比收藏重要")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "我的视频资料库" })).toBeInTheDocument();
    expect(screen.queryByText("你真正想留下的内容")).not.toBeInTheDocument();
    expect(screen.queryByText(/我是你的资料整理助手/)).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索标题、作者或保存说明" })).toHaveAttribute(
      "name",
      "search",
    );
    expect(screen.getByRole("searchbox", { name: "搜索标题、作者或保存说明" })).toHaveAttribute(
      "autocomplete",
      "off",
    );
    expect(screen.getByRole("button", { name: "搜索" })).toHaveTextContent("搜索");
  });

  it("shows the server-owned read-only state instead of opening the add flow", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LibraryPage
            fetchItems={vi.fn().mockResolvedValue({
              items: [readyItem], total: 1, page: 1, page_size: 20, is_true_first_empty: false,
            })}
            loadCapabilities={vi.fn().mockResolvedValue({
              supported_platforms: ["youtube"],
              web_login_channels: ["telegram"],
              save_enabled: false,
              max_save_batch_size: 10,
              transcript_pagination: true,
              archive: true,
              summary_generation: false,
              chat: false,
            })}
            submitBatch={vi.fn()}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("button", { name: "暂时无法添加视频" })).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
