import { describe, expect, it, vi } from "vitest";

import {
  consumeLinkToken,
  createTelegramLinkToken,
  requestJson,
  setUnauthorizedHandler,
} from "./client";

describe("same-origin API client", () => {
  it("copies the readable CSRF cookie to unsafe requests", async () => {
    document.cookie = "__Host-kb_csrf=csrf-value; Path=/; Secure";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await requestJson("/api/v1/example", { method: "POST", body: "{}" });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-value");
    expect(init.credentials).toBe("same-origin");
  });

  it("clears private client state through the unauthorized hook before surfacing 401", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ code: "session_invalid", message: "登录已失效" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(requestJson("/api/v1/library/items")).rejects.toEqual(
      expect.objectContaining({ status: 401, code: "session_invalid" }),
    );
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("keeps recoverable email verification failures inside the login form", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ code: "verification_failed", message: "验证码无效或已过期" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      requestJson("/api/v1/auth/verify", { method: "POST", body: "{}" }),
    ).rejects.toEqual(expect.objectContaining({ status: 401, code: "verification_failed" }));
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("creates a Telegram-targeted link token through the CSRF-protected API", async () => {
    document.cookie = "__Host-kb_csrf=csrf-link; Path=/; Secure";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ token: "ephemeral-link-token" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(createTelegramLinkToken()).resolves.toEqual({ token: "ephemeral-link-token" });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/link-tokens");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ target_channel: "telegram" });
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-link");
    expect(init.credentials).toBe("same-origin");
  });

  it("consumes a Telegram link token with the same unsafe-request contract", async () => {
    document.cookie = "__Host-kb_csrf=csrf-consume; Path=/; Secure";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ linked: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(consumeLinkToken("one-time-token")).resolves.toEqual({ linked: true });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/link-tokens/consume");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ token: "one-time-token" });
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-consume");
    expect(init.credentials).toBe("same-origin");
  });
});
