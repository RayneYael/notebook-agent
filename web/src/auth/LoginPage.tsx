import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";

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

type LoginView = "methods" | "password";
type ChannelAvailability = "checking" | "available" | "disabled" | "unavailable";

interface LoginMethodOptionProps {
  ariaLabel: string;
  icon: string;
  kind: "primary" | "reserved";
  title: string;
  description: string;
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
}

export function LoginPage({
  loadCapabilities = getCapabilities,
  createChallenge = createLoginChallenge,
  getStatus = getChallengeStatus,
  exchangeSession = exchangeChallenge,
  onAuthenticated,
}: LoginPageProps) {
  const navigate = useNavigate();
  const [challenge, setChallenge] = useState<LoginChallenge | null>(null);
  const [view, setView] = useState<LoginView>("methods");
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [passwordFeedback, setPasswordFeedback] = useState<string | null>(null);
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: loadCapabilities,
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

  const loginFailed = mutation.isError || status.isError || exchange.isError;
  const telegramAvailability = channelAvailability(capabilities, "telegram");
  const wechatAvailability = channelAvailability(capabilities, "wechat");

  function startChannelLogin(channel: LoginChannel) {
    if (channelAvailability(capabilities, channel) !== "available" || mutation.isPending) return;
    mutation.mutate(channel);
  }

  function restartLogin() {
    setChallenge(null);
    mutation.reset();
    exchange.reset();
  }

  function openPasswordLogin() {
    clearPasswordLogin();
    setView("password");
  }

  function closePasswordLogin() {
    clearPasswordLogin();
    setView("methods");
  }

  function clearPasswordLogin() {
    setAccount("");
    setPassword("");
    setPasswordVisible(false);
    setPasswordFeedback(null);
  }

  function submitPasswordLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!account.trim() || !password) {
      setPasswordFeedback("请输入账号和密码。");
      return;
    }
    setPasswordFeedback("当前版本暂未接入账号密码认证，请使用微信或 Telegram。");
  }

  return (
    <main className="login-page">
      <div className="paper-glow" aria-hidden="true" />
      <section className="login-card" aria-labelledby="login-title">
        <a className="wordmark" href="/" aria-label="Notebook Agent 首页">
          <span className="wordmark__sigil" aria-hidden="true">N</span>
          <span>Notebook Agent</span>
        </a>
        <p className="eyebrow">你的私人视频资料库</p>
        <h1 id="login-title">登录你的视频资料库</h1>
        <p className="login-intro">选择已经绑定的聊天渠道确认身份。账号密码入口目前仅作界面预留。</p>

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
        ) : view === "password" ? (
          <form className="password-login" onSubmit={submitPasswordLogin} noValidate>
            <div className="login-view-heading">
              <div>
                <p className="login-view-kicker">前端预留</p>
                <h2>账号密码登录</h2>
              </div>
              <button
                className="login-back-button"
                type="button"
                aria-label="返回其他登录方式"
                onClick={closePasswordLogin}
              >
                ← 返回其他登录方式
              </button>
            </div>
            <p className="password-login__intro">界面已经准备完成，当前版本仍以微信和 Telegram 认证为准。</p>
            <div className="login-field">
              <label htmlFor="login-account">账号</label>
              <input
                id="login-account"
                name="account"
                type="text"
                autoComplete="username"
                value={account}
                onChange={(event) => {
                  setAccount(event.target.value);
                  setPasswordFeedback(null);
                }}
              />
            </div>
            <div className="login-field">
              <label htmlFor="login-password">密码</label>
              <span className="login-password-control">
                <input
                  id="login-password"
                  name="password"
                  type={passwordVisible ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setPasswordFeedback(null);
                  }}
                />
                <button
                  type="button"
                  aria-label={passwordVisible ? "隐藏密码" : "显示密码"}
                  onClick={() => setPasswordVisible((visible) => !visible)}
                >
                  {passwordVisible ? "隐藏" : "显示"}
                </button>
              </span>
            </div>
            {passwordFeedback ? (
              <p className="inline-error" role="alert">{passwordFeedback}</p>
            ) : (
              <p className="password-login__status">不会发送或保存你在这里输入的内容。</p>
            )}
            <button className="button button--primary button--wide" type="submit">登录</button>
          </form>
        ) : (
          <div className="login-method-panel">
            <div className="login-method-heading">
              <span>登录方式</span>
              <small>优先使用已绑定的聊天账号</small>
            </div>
            <div className="login-methods" aria-label="选择登录方式">
              <LoginMethodOption
                ariaLabel="使用微信登录"
                icon="微"
                kind="primary"
                title="微信"
                description="在已绑定的微信聊天中确认身份"
                status={channelStatusLabel(wechatAvailability, mutation.isPending && mutation.variables === "wechat")}
                statusTone={channelStatusTone(wechatAvailability)}
                disabled={wechatAvailability !== "available" || mutation.isPending}
                onClick={() => startChannelLogin("wechat")}
              />
              <LoginMethodOption
                ariaLabel="使用 Telegram 登录"
                icon="TG"
                kind="primary"
                title="Telegram"
                description="通过已绑定的 Telegram 账号确认"
                status={channelStatusLabel(telegramAvailability, mutation.isPending && mutation.variables === "telegram")}
                statusTone={channelStatusTone(telegramAvailability)}
                disabled={telegramAvailability !== "available" || mutation.isPending}
                onClick={() => startChannelLogin("telegram")}
              />
              <LoginMethodOption
                ariaLabel="使用账号密码登录"
                icon="••"
                kind="reserved"
                title="账号密码"
                description="查看预留的账号密码登录界面"
                status="查看表单"
                statusTone="muted"
                onClick={openPasswordLogin}
              />
            </div>
            {capabilities.isError ? (
              <div className="login-capability-error">
                <p className="inline-error" role="alert">登录方式暂时无法加载，请检查网络后重试。</p>
                <button
                  className="login-retry-button"
                  type="button"
                  aria-label="重试"
                  onClick={() => void capabilities.refetch()}
                >
                  重新检测渠道
                </button>
              </div>
            ) : null}
            {capabilities.isPending ? (
              <p className="login-capability-note" aria-live="polite">正在确认当前部署可用的聊天渠道…</p>
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
  kind,
  title,
  description,
  status,
  statusTone = "muted",
  disabled = false,
  onClick,
}: LoginMethodOptionProps) {
  return (
    <button
      className={`login-method login-method--${kind}`}
      type="button"
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="login-method__icon" aria-hidden="true">{icon}</span>
      <span className="login-method__copy">
        <span className="login-method__kind">{kind === "primary" ? "主要方式" : "前端预留"}</span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <span className={`login-method__status login-method__status--${statusTone}`}>{status}</span>
    </button>
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
      return "当前部署未启用";
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
