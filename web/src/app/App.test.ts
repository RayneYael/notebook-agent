import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { createPrivateQueryClient, createSessionQueryClient, logoutAndClear } from "./App";

describe("private cache boundary", () => {
  it("clears all cached tenant data after a successful logout", async () => {
    const client = new QueryClient();
    client.setQueryData(["library"], { private: "previous-user" });
    const navigate = vi.fn();

    await logoutAndClear(client, vi.fn().mockResolvedValue(undefined), navigate);

    expect(client.getQueryData(["library"])).toBeUndefined();
    expect(navigate).toHaveBeenCalledWith("/login", { replace: true });
  });

  it("still clears local tenant data when the server session is already invalid", async () => {
    const client = new QueryClient();
    client.setQueryData(["library-item", "x"], { private: "previous-user" });
    const navigate = vi.fn();

    await expect(
      logoutAndClear(client, vi.fn().mockRejectedValue(new Error("session expired")), navigate),
    ).rejects.toThrow("session expired");

    expect(client.getQueryData(["library-item", "x"])).toBeUndefined();
    expect(navigate).toHaveBeenCalledWith("/login", { replace: true });
  });

  it("rotates the cache so a late old-session mutation cannot rehydrate the active tenant", async () => {
    const oldClient = createPrivateQueryClient();
    const replacementClient = createPrivateQueryClient();
    let activeClient = oldClient;
    let resolveMutation: (value: { private: string }) => void = () => undefined;
    const lateResult = new Promise<{ private: string }>((resolve) => {
      resolveMutation = resolve;
    });
    const mutation = oldClient.getMutationCache().build(oldClient, {
      mutationFn: () => lateResult,
      onSuccess: (value) => oldClient.setQueryData(["library-item", "old"], value),
    });
    const pendingMutation = mutation.execute(undefined);

    await logoutAndClear(
      oldClient,
      vi.fn().mockResolvedValue(undefined),
      vi.fn(),
      () => { activeClient = replacementClient; },
    );
    resolveMutation({ private: "previous-user" });
    await pendingMutation;

    expect(oldClient.getQueryData(["library-item", "old"])).toEqual({ private: "previous-user" });
    expect(activeClient).toBe(replacementClient);
    expect(activeClient.getQueryData(["library-item", "old"])).toBeUndefined();
  });

  it("activates a new login in a fresh cache without copying the previous tenant", () => {
    const oldClient = createPrivateQueryClient();
    oldClient.setQueryData(["library"], { private: "previous-user" });
    const session = {
      authenticated: true as const,
      login_channel: "wechat" as const,
      expires_at: "2026-09-06T10:00:00Z",
    };

    const nextClient = createSessionQueryClient(session);

    expect(nextClient).not.toBe(oldClient);
    expect(nextClient.getQueryData(["library"])).toBeUndefined();
    expect(nextClient.getQueryData(["session"])).toEqual(session);
  });
});
