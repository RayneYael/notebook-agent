import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import {
  createLoginChallenge,
  exchangeChallenge,
  getCapabilities,
  getChallengeStatus,
} from "../api/client";
import type {
  Capabilities,
  ChallengeStatus,
  LoginChallenge,
  LoginChannel,
  SessionInfo,
} from "../api/contracts";
import { BrandLogo } from "../app/BrandLogo";
import { useRouteNavigate } from "../app/RouteTransition";

type ChannelAvailability = "checking" | "available" | "disabled" | "unavailable";

interface LoginMethodOptionProps {
  ariaLabel: string;
  icon: ReactNode;
  iconClassName?: string;
  title: string;
  status: string;
  statusTone?: "ready" | "muted" | "error";
  disabled?: boolean;
  onClick: () => void;
}

interface LoginPageProps {
  loadCapabilities?: () => Promise<Capabilities>;
  createChallenge?: (channel: LoginChannel) => Promise<LoginChallenge>;
  getStatus?: (publicId: string, browserSecret: string) => Promise<ChallengeStatus>;
  exchangeSession?: (publicId: string, browserSecret: string) => Promise<SessionInfo>;
  onAuthenticated?: (session: SessionInfo) => void;
  directDemoLogin?: boolean;
}

const DEMO_LOGIN_TRANSITION_MS = 420;
const REDUCED_MOTION_TRANSITION_MS = 80;

export function LoginPage({
  loadCapabilities = getCapabilities,
  createChallenge = createLoginChallenge,
  getStatus = getChallengeStatus,
  exchangeSession = exchangeChallenge,
  onAuthenticated,
  directDemoLogin = false,
}: LoginPageProps) {
  const navigate = useRouteNavigate();
  const [challenge, setChallenge] = useState<LoginChallenge | null>(null);
  const [demoLoginChannel, setDemoLoginChannel] = useState<LoginChannel | null>(null);
  const demoLoginTimer = useRef<number | null>(null);
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: loadCapabilities,
    enabled: !directDemoLogin,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const mutation = useMutation({
    mutationFn: (channel: LoginChannel) => createChallenge(channel),
    onSuccess: setChallenge,
  });
  const status = useQuery({
    queryKey: ["login-challenge", challenge?.public_id],
    queryFn: () => getStatus(challenge!.public_id, challenge!.browser_secret),
    enabled: challenge !== null,
    retry: false,
    refetchInterval: challengePollInterval,
  });
  const exchange = useMutation({
    mutationFn: () => exchangeSession(challenge!.public_id, challenge!.browser_secret),
    onSuccess: (session) => {
      if (onAuthenticated) onAuthenticated(session);
      else navigate("/library", { replace: true });
    },
  });

  useEffect(() => {
    if (status.data?.status === "approved" && exchange.isIdle) exchange.mutate();
  }, [status.data?.status, exchange]);

  useEffect(() => () => {
    if (demoLoginTimer.current !== null) window.clearTimeout(demoLoginTimer.current);
  }, []);

  const loginFailed = mutation.isError || status.isError || exchange.isError;
  const telegramAvailability = directDemoLogin ? "available" : channelAvailability(capabilities, "telegram");
  const wechatAvailability = directDemoLogin ? "available" : channelAvailability(capabilities, "wechat");

  function startChannelLogin(channel: LoginChannel) {
    if (
      (!directDemoLogin && channelAvailability(capabilities, channel) !== "available")
      || mutation.isPending
      || demoLoginChannel !== null
    ) return;
    if (directDemoLogin) {
      setDemoLoginChannel(channel);
      const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
      demoLoginTimer.current = window.setTimeout(
        () => {
          if (onAuthenticated) {
            onAuthenticated({
              authenticated: true,
              login_channel: channel,
              expires_at: new Date(Date.now() + 8 * 60 * 60_000).toISOString(),
            });
          } else {
            navigate("/library", { replace: true });
          }
        },
        reduceMotion ? REDUCED_MOTION_TRANSITION_MS : DEMO_LOGIN_TRANSITION_MS,
      );
      return;
    }
    mutation.mutate(channel);
  }

  function restartLogin() {
    setChallenge(null);
    mutation.reset();
    exchange.reset();
  }

  return (
    <main
      className={`login-page${demoLoginChannel ? " login-page--leaving" : ""}`}
      aria-busy={demoLoginChannel ? true : undefined}
    >
      <div className="paper-glow" aria-hidden="true" />
      <section className="login-card" aria-labelledby="login-title">
        <a className="wordmark" href="/" aria-label="Notebook Agent 首页">
          <BrandLogo className="wordmark__sigil" />
          <span>Notebook Agent</span>
        </a>
        <p className="eyebrow">你的私人视频资料库</p>
        <h1 id="login-title">登录你的视频资料库</h1>

        {challenge ? (
          <div className="login-flow">
            <div className="challenge-card" aria-live="polite">
              <span className="step-number">01</span>
              <div>
                <p>请在 {challenge.target_channel === "telegram" ? "Telegram" : "微信"} 中发送这条登录指令：</p>
                <code>{challenge.command}</code>
                <p className="muted">
                  {exchange.isSuccess
                    ? "登录已确认，正在打开资料库…"
                    : "发送后请留在本页；确认完成会自动进入资料库。这条登录指令会在短时间后失效。"}
                </p>
              </div>
            </div>
            <button className="login-back-button" type="button" onClick={restartLogin}>
              ← 更换登录方式
            </button>
          </div>
        ) : (
          <div className="login-method-panel">
            <div className="login-method-heading">
              <span>登录方式</span>
              <small>使用已绑定的聊天账号继续</small>
            </div>
            <div className="login-methods" aria-label="选择登录方式">
              <LoginMethodOption
                ariaLabel="使用微信登录"
                icon={<WechatBrandIcon />}
                iconClassName="login-method__icon--wechat"
                title="微信"
                status={demoLoginChannel === "wechat"
                  ? "正在进入资料库"
                  : channelStatusLabel(wechatAvailability, mutation.isPending && mutation.variables === "wechat")}
                statusTone={channelStatusTone(wechatAvailability)}
                disabled={wechatAvailability !== "available" || mutation.isPending || demoLoginChannel !== null}
                onClick={() => startChannelLogin("wechat")}
              />
              <LoginMethodOption
                ariaLabel="使用 Telegram 登录"
                icon={<TelegramBrandIcon />}
                iconClassName="login-method__icon--telegram"
                title="Telegram"
                status={demoLoginChannel === "telegram"
                  ? "正在进入资料库"
                  : channelStatusLabel(telegramAvailability, mutation.isPending && mutation.variables === "telegram")}
                statusTone={channelStatusTone(telegramAvailability)}
                disabled={telegramAvailability !== "available" || mutation.isPending || demoLoginChannel !== null}
                onClick={() => startChannelLogin("telegram")}
              />
            </div>
            {!directDemoLogin && capabilities.isError ? (
              <div className="login-capability-error">
                <p className="inline-error" role="alert">登录方式暂时无法加载，请检查网络后重试。</p>
                <button
                  className="login-retry-button"
                  type="button"
                  aria-label="重试"
                  onClick={() => void capabilities.refetch()}
                >
                  重新加载登录方式
                </button>
              </div>
            ) : null}
            {!directDemoLogin && capabilities.isPending ? (
              <p className="login-capability-note" aria-live="polite">正在加载登录方式…</p>
            ) : null}
          </div>
        )}
        {loginFailed ? (
          <div>
            <p className="inline-error" role="alert">
              {challenge ? "登录没有完成，请重新获取登录指令。" : "暂时无法开始登录，请重试。"}
            </p>
            {challenge ? (
              <button className="button button--quiet button--wide" type="button" onClick={restartLogin}>
                重新获取
              </button>
            ) : null}
          </div>
        ) : null}
        <p className="privacy-note">登录后只会显示你自己的资料库。</p>
      </section>
    </main>
  );
}

function LoginMethodOption({
  ariaLabel,
  icon,
  iconClassName,
  title,
  status,
  statusTone = "muted",
  disabled = false,
  onClick,
}: LoginMethodOptionProps) {
  return (
    <button
      className="login-method"
      type="button"
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
    >
      <span className={`login-method__icon${iconClassName ? ` ${iconClassName}` : ""}`} aria-hidden="true">
        {icon}
      </span>
      <span className="login-method__copy">
        <strong>{title}</strong>
      </span>
      <span className={`login-method__status login-method__status--${statusTone}`}>{status}</span>
    </button>
  );
}

function WechatBrandIcon() {
  return (
    <svg data-testid="wechat-brand-icon" viewBox="0 0 32 32" focusable="false">
      <path d="M13.5 5.4C7.3 5.4 2.3 9.6 2.3 14.8c0 2.9 1.6 5.5 4.1 7.2l-1 3.6 4-2c1.3.4 2.7.7 4.1.7h.7a8.8 8.8 0 0 1-.5-2.9c0-5.1 4.7-9.2 10.5-9.4-1.5-3.8-5.7-6.6-10.7-6.6Zm-3.8 7.1a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3Zm7.5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3Z" />
      <path d="M29.7 21.4c0-4.2-4-7.6-8.8-7.6S12 17.2 12 21.4s4 7.6 8.9 7.6c1.2 0 2.3-.2 3.3-.6l3.2 1.7-.8-2.9a7.3 7.3 0 0 0 3.1-5.8Zm-11.8-1.2a1.2 1.2 0 1 1 0-2.4 1.2 1.2 0 0 1 0 2.4Zm6 0a1.2 1.2 0 1 1 0-2.4 1.2 1.2 0 0 1 0 2.4Z" />
    </svg>
  );
}

function TelegramBrandIcon() {
  return (
    <svg data-testid="telegram-brand-icon" viewBox="0 0 24 24" focusable="false">
      <path d="M21.7 3.4 18.5 20c-.2 1.2-.9 1.5-1.9.9l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.4-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6 13.7l-4.8-1.5c-1.1-.3-1.1-1.1.2-1.6L20.2 3.3c.9-.3 1.7.2 1.5 1.1Z" />
    </svg>
  );
}

function channelAvailability(
  capabilities: { isPending: boolean; isError: boolean; data?: Capabilities },
  channel: LoginChannel,
): ChannelAvailability {
  if (capabilities.isPending) return "checking";
  if (capabilities.isError || !capabilities.data) return "unavailable";
  return capabilities.data.web_login_channels.includes(channel) ? "available" : "disabled";
}

function channelStatusLabel(availability: ChannelAvailability, isStarting: boolean): string {
  if (isStarting) return "正在创建…";
  switch (availability) {
    case "checking":
      return "正在检测";
    case "available":
      return "可以使用";
    case "disabled":
      return "暂不可用";
    case "unavailable":
      return "暂时无法连接";
  }
}

function channelStatusTone(availability: ChannelAvailability): "ready" | "muted" | "error" {
  switch (availability) {
    case "available":
      return "ready";
    case "unavailable":
      return "error";
    case "checking":
    case "disabled":
      return "muted";
  }
}

export function challengePollInterval(query: {
  state: { status: string; data?: ChallengeStatus };
}): number | false {
  if (query.state.status === "error") return false;
  return query.state.data?.status === "pending" ? 1_500 : false;
}
