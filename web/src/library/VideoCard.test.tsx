import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { LibraryItem } from "../api/contracts";
import { VideoCard } from "./VideoCard";

const baseItem: LibraryItem = {
  public_id: "video-public",
  platform: "youtube",
  kind: "video",
  url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  title: "一段值得反复看的访谈",
  author: "Notebook Studio",
  published_at: null,
  duration_sec: 754,
  lang: "zh",
  description: null,
  tags: [],
  chapters: [],
  cover_url: "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
  saved_at: "2026-08-07T10:00:00Z",
  why_saved: "学习提问方式",
  text_source: "youtube_captions",
  lifecycle: "ready",
  error_code: null,
  available_actions: ["archive", "edit_why_saved", "open_source"],
  latest_dispatch_public_id: "dispatch-public",
};

describe("video card", () => {
  it("shows readable metadata and a server-derived lifecycle", () => {
    const { container } = render(<MemoryRouter><VideoCard item={baseItem} /></MemoryRouter>);

    expect(screen.getByRole("link", { name: /一段值得反复看的访谈/ })).toHaveAttribute(
      "href",
      "/videos/video-public",
    );
    expect(screen.getByText("12:34")).toBeInTheDocument();
    expect(screen.getByText("可阅读")).toBeInTheDocument();
    expect(screen.getByText("学习提问方式")).toBeInTheDocument();
    expect(container.querySelector("img")).toHaveAttribute("width", "960");
    expect(container.querySelector("img")).toHaveAttribute("height", "540");
  });

  it("never invents metadata for a newly queued item", () => {
    render(
      <MemoryRouter>
        <VideoCard item={{ ...baseItem, title: null, author: null, cover_url: null, duration_sec: null, lifecycle: "queued" }} />
      </MemoryRouter>,
    );

    expect(screen.getByText("视频信息尚未准备好")).toBeInTheDocument();
    expect(screen.getByText("等待整理")).toBeInTheDocument();
    expect(screen.getByText("暂无封面")).toBeInTheDocument();
    expect(screen.queryByText("YT")).not.toBeInTheDocument();
    expect(screen.queryByText("未知作者")).not.toBeInTheDocument();
  });

  it("uses the same retry action wording as the detail page", () => {
    render(
      <MemoryRouter>
        <VideoCard item={{ ...baseItem, lifecycle: "failed", available_actions: ["retry"] }} />
      </MemoryRouter>,
    );

    expect(screen.getByText("打开详情后可重新整理")).toBeInTheDocument();
    expect(screen.queryByText(/安全重试/)).not.toBeInTheDocument();
  });
});
