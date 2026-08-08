import type { ReactNode } from "react";
import { Link } from "react-router";

import type { LoginChannel } from "../api/contracts";

interface AppShellProps {
  children: ReactNode;
  loginChannel: LoginChannel;
  onLogout: () => void;
  logoutPending?: boolean;
}

export function AppShell({ children, loginChannel, onLogout, logoutPending = false }: AppShellProps) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <header className="topbar">
        <div className="topbar__inner">
          <Link className="wordmark" to="/library" aria-label="Notebook Agent 资料库">
            <span className="wordmark__sigil" aria-hidden="true">N</span>
            <span>Notebook Agent</span>
          </Link>
          <details className="account-menu">
            <summary aria-label="打开账户菜单">
              <span aria-hidden="true">{loginChannel === "telegram" ? "TG" : "WX"}</span>
            </summary>
            <div className="account-popover">
              <p className="eyebrow">当前登录</p>
              <strong>{loginChannel === "telegram" ? "Telegram" : "微信"}</strong>
              <button disabled={logoutPending} onClick={onLogout}>退出登录</button>
            </div>
          </details>
        </div>
      </header>
      <main className="page-container" id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}
