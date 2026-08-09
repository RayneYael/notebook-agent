import { afterEach, expect, it, vi } from "vitest";

import { startRouteTransition } from "./RouteTransition";

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.classList.remove("route-transition--entering");
});

it("adds a short enter animation when the browser has no native view transition", () => {
  vi.useFakeTimers();
  Reflect.deleteProperty(document, "startViewTransition");
  const update = vi.fn();

  startRouteTransition(update);

  expect(update).toHaveBeenCalledOnce();
  expect(document.documentElement.classList.contains("route-transition--entering")).toBe(true);
  vi.advanceTimersByTime(380);
  expect(document.documentElement.classList.contains("route-transition--entering")).toBe(false);
});
