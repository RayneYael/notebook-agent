import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AddVideosDialog } from "./AddVideosDialog";

describe("add videos dialog", () => {
  it("opens modally on first render without a declarative open attribute", () => {
    const showModal = vi.spyOn(HTMLDialogElement.prototype, "showModal");

    render(<AddVideosDialog open onClose={() => undefined} />);

    expect(showModal).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog", { name: "添加 YouTube 视频" })).toBeInTheDocument();
  });

  it("submits 1-10 trimmed URLs and renders per-item partial outcomes", async () => {
    const submit = vi.fn().mockResolvedValue({
      results: [
        { input_index: 0, status: "queued", item_public_id: "item-1", lifecycle: "queued" },
        { input_index: 1, status: "unsupported_url", error_code: "unsupported_url" },
        { input_index: 2, status: "quota_exceeded", safe_error_code: "quota_exceeded" },
      ],
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={client}>
        <AddVideosDialog open onClose={() => undefined} submitBatch={submit} />
      </QueryClientProvider>,
    );

    const dialog = screen.getByRole("dialog", { name: "添加 YouTube 视频" });
    await user.type(
      within(dialog).getByLabelText("YouTube 链接，每行一个"),
      "https://youtu.be/dQw4w9WgXcQ\nhttps://example.com/nope",
    );
    await user.type(within(dialog).getByLabelText("为什么保存（可选）"), "准备周末精读");
    await user.click(within(dialog).getByRole("button", { name: "添加并整理" }));

    expect(submit).toHaveBeenCalledWith({
      urls: ["https://youtu.be/dQw4w9WgXcQ", "https://example.com/nope"],
      why_saved: "准备周末精读",
    });
    expect(await within(dialog).findByText("已添加，等待整理")).toBeInTheDocument();
    expect(within(dialog).getByText("暂不支持这个链接")).toBeInTheDocument();
    expect(within(dialog).getByText("已达到保存上限")).toBeInTheDocument();
    expect(within(dialog).getByText("第 1 个链接")).toBeInTheDocument();
    expect(within(dialog).queryByText(/队列暂时不可用|请求已处理/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("list", { name: "添加结果" })).toHaveAttribute(
      "aria-live",
      "polite",
    );
    expect(within(dialog).getByLabelText("YouTube 链接，每行一个")).toHaveAttribute("name", "urls");
    expect(within(dialog).getByLabelText("YouTube 链接，每行一个")).toHaveAttribute("autocomplete", "off");
    expect(within(dialog).getByLabelText("为什么保存（可选）")).toHaveAttribute("name", "why-saved");
  });

  it("blocks more than ten non-empty URLs before a network call", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();

    render(<AddVideosDialog open onClose={() => undefined} submitBatch={submit} />);
    await user.type(
      screen.getByLabelText("YouTube 链接，每行一个"),
      Array.from({ length: 11 }, (_, index) => `https://youtu.be/video${index}`).join("\n"),
    );
    await user.click(screen.getByRole("button", { name: "添加并整理" }));

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("一次最多添加 10 个链接");
  });

  it("clears form values and submission results after closing", async () => {
    const submit = vi.fn().mockResolvedValue({
      results: [
        { input_index: 0, status: "queued", item_public_id: "item-1", lifecycle: "queued" },
      ],
    });
    const user = userEvent.setup();
    const { rerender } = render(
      <AddVideosDialog open onClose={() => undefined} submitBatch={submit} />,
    );

    await user.type(screen.getByLabelText("YouTube 链接，每行一个"), "https://youtu.be/dQw4w9WgXcQ");
    await user.type(screen.getByLabelText("为什么保存（可选）"), "准备周末精读");
    await user.click(screen.getByRole("button", { name: "添加并整理" }));
    expect(await screen.findByText("已添加，等待整理")).toBeInTheDocument();

    rerender(<AddVideosDialog open={false} onClose={() => undefined} submitBatch={submit} />);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    rerender(<AddVideosDialog open onClose={() => undefined} submitBatch={submit} />);

    expect(screen.getByLabelText("YouTube 链接，每行一个")).toHaveValue("");
    expect(screen.getByLabelText("为什么保存（可选）")).toHaveValue("");
    expect(screen.queryByText("已添加，等待整理")).not.toBeInTheDocument();
  });

  it("ignores a submission result that arrives after closing", async () => {
    let resolveSubmit: (result: {
      results: Array<{
        input_index: number;
        status: "queued";
        item_public_id: string;
        lifecycle: "queued";
        result_id: string;
      }>;
    }) => void = () => undefined;
    const submit = vi.fn(() => new Promise<{
      results: Array<{
        input_index: number;
        status: "queued";
        item_public_id: string;
        lifecycle: "queued";
        result_id: string;
      }>;
    }>((resolve) => {
      resolveSubmit = resolve;
    }));
    const user = userEvent.setup();
    const { rerender } = render(
      <AddVideosDialog open onClose={() => undefined} submitBatch={submit} />,
    );

    await user.type(screen.getByLabelText("YouTube 链接，每行一个"), "https://youtu.be/dQw4w9WgXcQ");
    await user.click(screen.getByRole("button", { name: "添加并整理" }));
    rerender(<AddVideosDialog open={false} onClose={() => undefined} submitBatch={submit} />);
    await act(async () => {
      resolveSubmit({
        results: [
          {
            input_index: 0,
            status: "queued",
            item_public_id: "item-1",
            lifecycle: "queued",
            result_id: "result-1",
          },
        ],
      });
    });
    rerender(<AddVideosDialog open onClose={() => undefined} submitBatch={submit} />);

    expect(screen.queryByText("已添加，等待整理")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加并整理" })).toBeEnabled();
  });
});
