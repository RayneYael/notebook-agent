import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LibraryEmptyState, LibraryErrorState, LibraryLoadingState } from "./LibraryStates";

describe("library page states", () => {
  it("shows agent guidance only for a true first empty library", () => {
    const { rerender } = render(<LibraryEmptyState trueFirstEmpty />);
    expect(screen.getByText(/我是你的资料整理助手/)).toBeInTheDocument();

    rerender(<LibraryEmptyState trueFirstEmpty={false} />);
    expect(screen.queryByText(/我是你的资料整理助手/)).not.toBeInTheDocument();
    expect(screen.getByText(/没有符合条件的视频/)).toBeInTheDocument();
  });

  it("keeps loading and error distinct from empty", () => {
    const { rerender } = render(<LibraryLoadingState />);
    expect(screen.getByLabelText("正在加载资料库")).toBeInTheDocument();
    expect(screen.queryByText(/我是你的资料整理助手/)).not.toBeInTheDocument();

    rerender(<LibraryErrorState onRetry={() => undefined} />);
    expect(screen.getByRole("alert")).toHaveTextContent("暂时无法读取资料库");
    expect(screen.queryByText(/我是你的资料整理助手/)).not.toBeInTheDocument();
  });
});
