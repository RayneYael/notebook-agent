# 登录方式选择技术设计

## 1. Boundary

本任务只修改 React 登录视图、相关样式和前端测试。FastAPI、OpenAPI、数据库模型、迁移和认证服务保持不变。

## 2. State Model

`LoginPage` 继续以 TanStack Query 持有 capabilities 和 challenge 状态，以组件 `useState` 持有短期界面状态：

- 当前视图：登录方式列表或账号密码预留表单；
- 账号、密码和是否显示密码；
- 本地表单错误或未接入提示；
- 当前发起 challenge 的渠道，用于显示“正在创建登录请求”。

渠道状态由 capabilities 派生，不建立第二份服务端状态：`checking | available | disabled | unavailable`。

## 3. UI Composition

- 保留品牌、标题和私人资料库说明。
- 使用一组纵向的原生 `button` 登录方式条目；每项包含单色图标、名称、用途说明和右侧状态。
- 微信和 Telegram 使用“主要方式”文案；账号密码显示“前端预留”。
- 账号密码表单在同一卡片内替换方式列表，提供返回操作，不使用弹窗。
- challenge 成功、等待和错误继续在同一卡片内原位转换。

## 4. Security and Honesty

- 账号密码提交仅触发本地校验和未接入提示；不得调用 `fetch`、`requestJson`、challenge 或 exchange 方法。
- 密码仅保存在当前组件内存，退出账号密码视图时清空账号、密码和反馈。
- 不把密码、challenge secret 或 Session 数据写入 Web Storage、URL 或日志。
- 服务端未声明启用的渠道保持禁用；能力加载失败不能猜测可用性。

## 5. Compatibility and Rollback

- 保持 `LoginPageProps` 的现有注入接口和真实 channel challenge 契约。
- 不修改 OpenAPI，因此 `check:api` 应保持无差异。
- 回滚只需恢复 `LoginPage.tsx`、`LoginPage.test.tsx` 和 `styles.css` 中本任务的局部改动。
