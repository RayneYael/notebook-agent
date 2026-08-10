# 登录方式选择实施计划

## 1. 登录方式与状态模型

- [x] 在 `LoginPage` 中加入方式视图和账号密码预留视图的本地状态。
- [x] 从 capabilities 派生微信/Telegram 的 checking、available、disabled、unavailable 状态。
- [x] 保持现有 challenge 创建、轮询、交换和跳转路径不变。

## 2. 账号密码前端预留

- [x] 添加账号、密码、显示密码、返回方式列表控件。
- [x] 添加空字段校验和非空提交的未接入反馈。
- [x] 离开表单时清空敏感输入和本地反馈。
- [x] 证明提交不会调用任何认证 API 或写入 Web Storage。

## 3. 视觉与可访问性

- [x] 在现有 `styles.css` 中增加方式列表、状态、图标和表单样式。
- [x] 保持单一强调色、44px 触控目标、可见 focus、清晰 disabled 和错误状态。
- [x] 检查桌面与 390×844 手机布局。

## 4. Tests and Verification

- [x] 更新 `LoginPage.test.tsx` 覆盖 capabilities pending/error/单渠道/双渠道。
- [x] 覆盖账号密码本地校验、未接入反馈、无 API 调用和无 Web Storage 写入。
- [x] 运行 `pnpm test`、`pnpm typecheck`、`pnpm lint`、`pnpm build`、`pnpm check:api`。
- [x] 复用现有 5173 服务做桌面和手机 browser smoke，检查控制台与横向溢出。

## Risky Files and Rollback Points

- `web/src/auth/LoginPage.tsx`：真实 challenge 状态机不可回归。
- `web/src/auth/LoginPage.test.tsx`：必须保留浏览器 secret 仅存内存和 approved exchange 断言。
- `web/src/styles.css`：只扩展现有登录页设计系统，避免影响资料库与展示页。

## Final Verification Evidence

- Targeted regression: `LoginPage`, `ShowcasePage`, and `VideoDetailView` — 3 files, 18 tests passed.
- Full frontend: 12 files, 42 tests passed; typecheck, lint, production build, and OpenAPI stale check passed.
- Login browser smoke: 1724×1375 and 390×844, all three methods visible, account/password labels accessible, and no horizontal overflow.
- Local environment note: the reused 5173 Vite server had no backend attached, so `/api/v1/capabilities` returned the expected 502 and the page showed its explicit unavailable/retry state.
- Browser metrics are recorded above; screenshots are retained as thread-local visualization artifacts and are intentionally excluded from Git.
