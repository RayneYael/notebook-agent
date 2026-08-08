import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
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

  function restartLogin() {
    setChallenge(null);
    mutation.reset();
    exchange.reset();
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
        <p className="login-intro">使用已经绑定的聊天账号确认身份，无需设置新密码。</p>

        {challenge ? (
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
        ) : capabilities.isPending ? (
          <p className="muted" aria-live="polite">正在加载登录方式…</p>
        ) : capabilities.isError ? (
          <div>
            <p className="inline-error" role="alert">登录方式暂时无法加载，请检查网络后重试。</p>
            <button
              className="button button--quiet button--wide"
              type="button"
              onClick={() => void capabilities.refetch()}
            >
              重试
            </button>
          </div>
        ) : (
          <div className="login-actions">
            {capabilities.data.web_login_channels.includes("telegram") ? (
              <button
                className="button button--primary button--wide"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate("telegram")}
              >
                使用 Telegram 登录
              </button>
            ) : null}
            {capabilities.data.web_login_channels.includes("wechat") ? (
              <button
                className="button button--quiet button--wide"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate("wechat")}
              >
                使用微信登录
              </button>
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

export function challengePollInterval(query: {
  state: { status: string; data?: ChallengeStatus };
}): number | false {
  if (query.state.status === "error") return false;
  return query.state.data?.status === "pending" ? 1_500 : false;
}
