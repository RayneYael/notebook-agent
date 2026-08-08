import { describe, expect, it, vi } from "vitest";

import { requestJson, setUnauthorizedHandler } from "./client";

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
});
