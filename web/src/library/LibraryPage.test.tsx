import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { LibraryItem, LibraryPageResponse } from "../api/contracts";
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
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LibraryPage fetchItems={fetchItems} submitBatch={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("library page", () => {
  it("shows static agent guidance only after a successful true-empty response", async () => {
    renderPage(async () => ({ items: [], total: 0, page: 1, page_size: 20, is_true_first_empty: true }));
    expect(await screen.findByText(/我是你的资料整理助手/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加视频" })).toBeInTheDocument();
  });

  it("renders server-owned items instead of an empty agent state", async () => {
    renderPage(async () => ({ items: [readyItem], total: 1, page: 1, page_size: 20, is_true_first_empty: false }));
    expect(await screen.findByText("理解比收藏重要")).toBeInTheDocument();
    expect(screen.queryByText(/我是你的资料整理助手/)).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索标题、作者或保存原因" })).toHaveAttribute(
      "name",
      "search",
    );
    expect(screen.getByRole("searchbox", { name: "搜索标题、作者或保存原因" })).toHaveAttribute(
      "autocomplete",
      "off",
    );
  });
});
