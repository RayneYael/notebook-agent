import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { Capabilities } from "../api/contracts";
import { challengePollInterval, LoginPage } from "./LoginPage";

const capabilities: Capabilities = {
  supported_platforms: ["youtube"],
  web_login_channels: ["telegram", "wechat"],
  save_enabled: true,
  max_save_batch_size: 10,
  transcript_pagination: true,
  archive: true,
  summary_generation: false,
  chat: false,
};

describe("login page", () => {
  it("creates a channel challenge and keeps its browser secret in memory", async () => {
    const createChallenge = vi.fn().mockResolvedValue({
      public_id: "challenge-public",
      command: "/web-login ABCD-EFGH",
      browser_secret: "browser-only-secret",
      target_channel: "telegram",
      expires_at: "2026-08-07T12:10:00Z",
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LoginPage
            loadCapabilities={vi.fn().mockResolvedValue(capabilities)}
            createChallenge={createChallenge}
            getStatus={vi.fn().mockResolvedValue({ status: "pending", expires_at: "2026-08-07T12:10:00Z" })}
            exchangeSession={vi.fn()}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "使用 Telegram 登录" }));

    expect(createChallenge).toHaveBeenCalledWith("telegram");
    expect(screen.getByRole("heading", { name: "登录你的视频资料库" })).toBeInTheDocument();
    expect(screen.getByText("请在 Telegram 中发送这条登录指令：")).toBeInTheDocument();
    expect(await screen.findByText("/web-login ABCD-EFGH")).toBeInTheDocument();
    expect(screen.getByText(/这条登录指令会在短时间后失效/)).toBeInTheDocument();
    expect(screen.queryByText(/10 分钟/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Cookie|令牌/)).not.toBeInTheDocument();
    expect(screen.queryByText("browser-only-secret")).not.toBeInTheDocument();
    expect(window.localStorage).toHaveLength(0);
    expect(window.sessionStorage).toHaveLength(0);
  });

  it("exchanges an approved challenge and hands off without exposing session tokens", async () => {
    const onAuthenticated = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    const createChallenge = vi.fn().mockResolvedValue({
      public_id: "challenge-public",
      command: "/web-login ABCD-EFGH",
      browser_secret: "browser-only-secret",
      target_channel: "telegram",
      expires_at: "2026-08-07T12:10:00Z",
    });
    const exchangeSession = vi.fn().mockResolvedValue({
      authenticated: true,
      login_channel: "telegram",
      expires_at: "2026-09-07T12:00:00Z",
    });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LoginPage
            loadCapabilities={vi.fn().mockResolvedValue(capabilities)}
            createChallenge={createChallenge}
            getStatus={vi.fn().mockResolvedValue({ status: "approved", expires_at: "2026-08-07T12:10:00Z" })}
            exchangeSession={exchangeSession}
            onAuthenticated={onAuthenticated}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "使用 Telegram 登录" }));

    expect(await screen.findByText("登录已确认，正在打开资料库…")).toBeInTheDocument();
    expect(exchangeSession).toHaveBeenCalledWith("challenge-public", "browser-only-secret");
    expect(onAuthenticated).toHaveBeenCalledOnce();
  });

  it("lets the user restart in place after challenge polling fails", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    const createChallenge = vi.fn().mockResolvedValue({
      public_id: "challenge-public",
      command: "/web-login ABCD-EFGH",
      browser_secret: "browser-only-secret",
      target_channel: "telegram",
      expires_at: "2026-08-07T12:10:00Z",
    });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LoginPage
            loadCapabilities={vi.fn().mockResolvedValue(capabilities)}
            createChallenge={createChallenge}
            getStatus={vi.fn().mockRejectedValue(new Error("network unavailable"))}
            exchangeSession={vi.fn()}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "使用 Telegram 登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("登录没有完成，请重新获取登录指令");
    await user.click(screen.getByRole("button", { name: "重新获取" }));

    expect(screen.getByRole("button", { name: "使用 Telegram 登录" })).toBeEnabled();
    expect(screen.queryByText("/web-login ABCD-EFGH")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders only channels advertised by the server", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LoginPage
            loadCapabilities={vi.fn().mockResolvedValue({
              ...capabilities,
              web_login_channels: ["telegram"],
            })}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("button", { name: "使用 Telegram 登录" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "使用微信登录" })).not.toBeInTheDocument();
  });

  it("shows a retryable error instead of guessing login channels", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const loadCapabilities = vi
      .fn()
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce(capabilities);
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LoginPage loadCapabilities={loadCapabilities} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("登录方式暂时无法加载");
    expect(screen.queryByRole("button", { name: "使用 Telegram 登录" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("button", { name: "使用微信登录" })).toBeEnabled();
  });

  it("stops polling after an error even when the previous result was pending", () => {
    expect(challengePollInterval({
      state: {
        status: "error",
        data: { status: "pending", expires_at: "2026-08-07T12:10:00Z" },
      },
    })).toBe(false);
  });
});
