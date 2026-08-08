import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { ShowcasePage } from "./ShowcasePage";

function renderShowcase() {
  return render(
    <MemoryRouter>
      <ShowcasePage />
    </MemoryRouter>,
  );
}

describe("ShowcasePage", () => {
  it("explains the project, audience, workflow, and honest preset-demo boundary", () => {
    renderShowcase();

    expect(screen.getByRole("heading", { name: "让收藏过的知识，再次可用。" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /收藏不是终点/ })).toBeInTheDocument();
    expect(screen.getByText(/当我们按下收藏键的刹那/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "独立资料空间" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "基于原文生成回答" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "答案依据全程可追溯" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "适合不想让“看过”等于“忘过”的人。" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "保存视频链接，取回答案与出处。" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "选一个场景，看答案出处。" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "下次需要答案，直接回到原文。" })).toBeInTheDocument();
    expect(screen.getByText(/不会调用模型或上传数据/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /进入资料库/ })).toHaveAttribute("href", "/login");
    expect(screen.getByLabelText("从视频到可追溯答案的处理路径")).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(3);
    expect(screen.getByRole("img", { name: "How to Talk to Users 视频封面" })).toHaveAttribute(
      "src",
      "https://i.ytimg.com/vi/MT4Ig2uqjTc/hqdefault.jpg",
    );
    expect(document.body).toHaveTextContent("视频链接 + 保存说明");
    expect(document.body).toHaveTextContent("页面内容、检索结果与回答依据都限定在当前账户范围内");
    expect(document.body).toHaveTextContent("可用登录入口以当前部署配置为准");
    expect(document.body).not.toHaveTextContent(/why_saved|tenant|Transcript|Chunks|Hybrid Search|EVIDENCE MODE|混合索引/i);
  });

  it("runs each source-backed preset only after the visitor asks for it", async () => {
    const user = userEvent.setup();
    renderShowcase();

    expect(screen.queryByText(/不要先推销方案/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /查看这次回答/ }));

    expect(screen.getByText(/不要先推销方案/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /06:07/ })).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=MT4Ig2uqjTc&t=367s",
    );

    await user.click(screen.getByRole("button", { name: /AI 入门/ }));
    expect(screen.queryByText(/784 个输入到 10 个输出/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /查看这次回答/ }));

    expect(screen.getByText(/784 个输入到 10 个输出/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /03:08/ })).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=aircAruvnKk&t=188s",
    );
  });
});
