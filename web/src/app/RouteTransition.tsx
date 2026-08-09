import { flushSync } from "react-dom";
import { useCallback, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router";
import type { LinkProps, NavigateOptions, To } from "react-router";

type TransitionDocument = Document & {
  startViewTransition?: (update: () => void) => unknown;
};

export type RouteNavigate = (to: To, options?: NavigateOptions) => void;

let fallbackCleanupTimer: number | undefined;

export function startRouteTransition(update: () => void): void {
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const startViewTransition = (document as TransitionDocument).startViewTransition;
  if (reduceMotion) {
    update();
    return;
  }

  if (!startViewTransition) {
    window.clearTimeout(fallbackCleanupTimer);
    document.documentElement.classList.remove("route-transition--entering");
    void document.documentElement.offsetWidth;
    document.documentElement.classList.add("route-transition--entering");
    flushSync(update);
    fallbackCleanupTimer = window.setTimeout(() => {
      document.documentElement.classList.remove("route-transition--entering");
    }, 380);
    return;
  }

  startViewTransition.call(document, () => flushSync(update));
}

export function useRouteNavigate(): RouteNavigate {
  const navigate = useNavigate();
  return useCallback(
    (to: To, options?: NavigateOptions) => {
      startRouteTransition(() => navigate(to, options));
    },
    [navigate],
  );
}

export function RouteLink({
  onClick,
  preventScrollReset,
  relative,
  reloadDocument,
  replace,
  state,
  target,
  to,
  ...props
}: LinkProps) {
  const navigate = useNavigate();

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (
      event.defaultPrevented
      || reloadDocument
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
      || (target !== undefined && target !== "_self")
    ) {
      return;
    }

    event.preventDefault();
    startRouteTransition(() => navigate(to, { preventScrollReset, relative, replace, state }));
  }

  return (
    <Link
      {...props}
      onClick={handleClick}
      preventScrollReset={preventScrollReset}
      relative={relative}
      reloadDocument={reloadDocument}
      replace={replace}
      state={state}
      target={target}
      to={to}
    />
  );
}
