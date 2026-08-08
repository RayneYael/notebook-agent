import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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

  it("keeps every login method visible and disables channels not advertised by the server", async () => {
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

    await waitFor(() => expect(screen.getByRole("button", { name: "使用 Telegram 登录" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "使用微信登录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "使用账号密码登录" })).toBeEnabled();
    expect(screen.getByText("当前部署未启用")).toBeInTheDocument();
  });

  it("keeps channel entries visible with a retryable status when capabilities fail", async () => {
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
    expect(screen.getByRole("button", { name: "使用 Telegram 登录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "使用微信登录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "使用账号密码登录" })).toBeEnabled();
    expect(screen.getAllByText("暂时无法连接")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "使用微信登录" })).toBeEnabled());
  });

  it("shows all login methods while capabilities are still loading", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LoginPage loadCapabilities={() => new Promise(() => undefined)} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("button", { name: "使用 Telegram 登录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "使用微信登录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "使用账号密码登录" })).toBeEnabled();
    expect(screen.getAllByText("正在检测")).toHaveLength(2);
  });

  it("validates the reserved password form without calling an authentication API", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const createChallenge = vi.fn();
    const exchangeSession = vi.fn();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LoginPage
            loadCapabilities={vi.fn().mockResolvedValue(capabilities)}
            createChallenge={createChallenge}
            exchangeSession={exchangeSession}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "使用账号密码登录" }));
    const account = screen.getByRole("textbox", { name: "账号" });
    const password = screen.getByLabelText("密码");
    expect(password).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "显示密码" }));
    expect(password).toHaveAttribute("type", "text");

    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请输入账号和密码");

    await user.type(account, "demo-user");
    await user.type(password, "not-sent-anywhere");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "当前版本暂未接入账号密码认证，请使用微信或 Telegram",
    );
    expect(createChallenge).not.toHaveBeenCalled();
    expect(exchangeSession).not.toHaveBeenCalled();
    expect(window.localStorage).toHaveLength(0);
    expect(window.sessionStorage).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "返回其他登录方式" }));
    expect(screen.getByRole("button", { name: "使用微信登录" })).toBeEnabled();
    expect(screen.queryByRole("textbox", { name: "账号" })).not.toBeInTheDocument();
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
