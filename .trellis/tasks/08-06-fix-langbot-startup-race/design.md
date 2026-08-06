# LangBot 启动就绪门与运行时 fail-closed 设计

## Problem statement

消息 adapter 只能在承担租户解析和 Agent 转发的桥接插件真实可用时接收消息；一旦该
插件不可用，消息也不能回退到 LangBot 默认 Agent。

## Fundamental invariants

1. `gateway-server`、plugin runtime、桥接插件和 channel adapter 是四个不同的就绪
   边界；进程存在不等于插件已 `initialized`。
2. adapter 一旦启动就可能立即收到平台积压消息，因此“通常插件先完成”不是可靠
   保证。
3. 启动时就绪不代表运行期间一直就绪；必须在每条需要关键插件的消息上保留
   fail-closed 证据。
4. Telegram 与微信是并行入口，不存在全局“当前渠道”。就绪门只控制何时开放入口，
   不改变 adapter 数量或用户身份键。
5. 私聊正文和外部身份在任何失败路径都不是运维诊断所必需的数据。

## Options considered

### A. 在启动脚本中固定等待若干秒

不采用。插件启动时间受依赖安装、数据库、CPU 和扫码状态影响；固定等待既可能过短
保留竞态，也可能无谓拉长每次启动，并且无法处理运行中断线。

### B. 只实现 application 启动门

不采用。它可以消除当前 126 ms 窗口，但 plugin runtime 或单个插件在运行中退出后，
下一条消息仍可能得到空 event context 并进入默认流水线。

### C. 状态驱动启动门 + 每消息处理证据

采用。启动门降低开放渠道前的失败概率；每消息门验证关键插件确实处理并
`prevent_default()`，覆盖 runtime 断线、插件进程退出和错误配置。这是满足全部不变量
的最小机制。

## Configuration contract

在 LangBot `plugin` 配置节增加向后兼容字段：

```yaml
plugin:
  required_plugins: []
  required_plugins_ready_timeout_seconds: 30
```

- `required_plugins` 是 `author/name` 字符串列表。空列表保持上游 4.10.6 行为。
- 本部署显式配置
  `notebook-agent/notebook-knowledge-agent`。
- deadline 是最长等待时间，不是固定延迟。实现会在条件满足时立即继续；超时抛出
  不含用户数据的 startup error，且不会启动任何 enabled adapter。
- 配置模板保留 list 类型，使 LangBot 现有环境变量覆盖逻辑可通过
  `PLUGIN__REQUIRED_PLUGINS` 接受逗号分隔列表。

配置解析必须拒绝空项、缺少 `/` 的标识和非正 deadline，错误发生在 adapter 启动前。

## Connector state and readiness

`PluginRuntimeConnector` 维护明确状态，而不是通过 `hasattr(handler)` 推断：

- runtime connected；
- 当前连接 generation；
- 每个 configured required plugin 的 `initialized` 状态；
- overall ready event/boolean。

连接建立后设置 runtime connected；disconnect callback 必须先清除 overall ready，再执行
现有重连策略。`initialize_plugins()` 从空实现改为 condition-based wait：

1. 等 runtime connection；
2. 查询每个 required plugin 的 `get_plugin_info(author, name)`；
3. 仅当全部 `status == "initialized"` 时设置 ready 并返回；
4. 未满足时使用短、上限受控的 polling/backoff 重新查询，直到状态变化或 deadline；
5. deadline 到期抛出专用 readiness exception。

polling 只是发现状态变化的机制，不代表等待固定时长；插件在首次检查即 ready 时应立即
通过。日志记录插件标识、状态和耗时，不记录 event 或 sender。

`Application.run()` 保留关键顺序：`await initialize_plugins()` 成功后才创建
`platform-manager` task。所有 enabled bots 仍由 `PlatformManager.run()` 逐个创建独立
adapter task，因此 Telegram、微信继续并发运行。

## Per-message fail-closed contract

只有同时满足以下条件的 pipeline 才启用严格门：

1. pipeline 使用显式 `bound_plugins`，而不是隐含依赖 `enable_all_plugins`；
2. `bound_plugins` 与 configured `required_plugins` 有交集。

对于这种 pipeline，早期 `PersonMessageReceived` / `GroupMessageReceived` event 返回后，
在调用任何 stage 前检查：

- 每个适用的 required plugin 都出现在 event context 的 `emitted_plugins` manifest 中；
- event context 的 default 已被阻止。

任一条件不满足或 runtime 调用抛错时：

- 终止 query，不进入 `_execute_from_stage()`；
- best-effort 通过当前 adapter 返回固定的渠道不可用提示；reply 失败只记录错误类型；
- 不记录正文、外部 sender、昵称或 reply preview；
- 不调用 LangBot Local Agent。

插件正常处理时，沿用 0.1.1 的 `EventContext.reply(...)` 直达当前 adapter，然后
`prevent_default()` 结束默认 pipeline。

## Privacy boundary

当前 monitoring patch 需要扩展为固定版本的 privacy/readiness patch：

- `MonitoringHelper` 继续使用固定脱敏 message/session/user 值；
- `RuntimeBot.on_friend_message` 不把 message chain、图片内容或 sender ID 放入
  `EventLogger`；
- `MessageProcessor` 的 info log 不包含 message text、launcher ID 或 sender ID；
- plugin delivery diagnostic 不包含 `message_preview`；
- readiness/fail-closed 日志只允许内部 query ID、bot UUID、plugin ref、状态和错误类型。

群聊是否存储正文不在当前真实验收范围，但共用的 processor/diagnostic 防御性脱敏不得
因 launcher 类型绕过。桥接入口仍只接受它当前支持的私聊事件。

## Patch and test strategy

仓库保留一个可审计的 LangBot 4.10.6 patch 作为交付源。实现阶段先取得并校验固定
wheel/source 的 SHA-256，再在临时目录中：

1. `patch --dry-run`；
2. 实际应用 patch；
3. 对 patched modules 运行聚焦测试。

测试使用 fake connector/runtime/plugin context 和 fake adapters，不连接真实微信或
Telegram，也不输出平台字段。覆盖矩阵：

| 场景 | Adapter | Plugin event | 默认 processor | 预期 |
| --- | --- | --- | --- | --- |
| runtime 未连接 | 未启动 | 无 | 0 次 | readiness 等待/超时 |
| 插件正在初始化 | 未启动 | 无 | 0 次 | 状态变化后立即开放 |
| ready 后双 adapter | TG + 微信均启动 | bridge emitted + prevented | 0 次 | 正常桥接 |
| 运行中断线 | 保持配置 enabled | 抛错/无证据 | 0 次 | 固定不可用提示 |
| 插件 emitted 但未 prevent | 已启动 | 有证据但 contract 失败 | 0 次 | fail closed |
| 非关键 pipeline | 原行为 | 按原配置 | 原行为 | 向后兼容 |

隐私测试生成唯一 canary 正文、昵称和 sender ID，捕获 monitoring、EventLogger、应用
logger 与 diagnostic payload 后断言 canary 全部缺席。

## Deployment flow

```text
data services healthy
        |
migration at head
        |
Notebook Agent gateway /health = 200
        |
private plugin .env present (0600)
        |
LangBot runtime connected + required bridge initialized
        |
PlatformManager starts every enabled adapter
        |
Telegram E2E + WeChat private smoke
```

微信扫码是 adapter 的认证步骤，不替代 plugin readiness。已有 token 有效时可直接进入
轮询；token 过期时先停 LangBot，安全重登录后再按同一 readiness 顺序启动。

## Rollout and rollback

### Rollout

1. 停止 LangBot，保留 gateway 和数据服务；
2. 备份 LangBot 数据库、bot/pipeline/plugin 配置；
3. 对固定 4.10.6 source 应用 patch，配置 required plugin 与私有 `.env`；
4. 启动并验证 gateway health、plugin initialized、LangBot health；
5. 确认两个 adapters 均 enabled 后进行人工 smoke。

### Rollback

1. 先停 adapters/LangBot，避免回滚窗口继续收消息；
2. 反向应用同一 patch 或恢复已备份的干净 4.10.6 runtime；
3. 恢复 LangBot 配置，但不要启用内置模型作为 fallback；
4. 若必须回到无 readiness 的版本，在人工验收环境中保持渠道 disabled，直到另有安全
   方案。Notebook Agent 数据库无需 downgrade。

## Compatibility notes

- 固定支持 LangBot 4.10.6 和 plugin SDK 0.4.13；patch 对其他版本必须拒绝或由人工
  重新审查 hunk。
- `required_plugins: []` 时不改变普通 LangBot pipeline；Notebook Agent 部署不得留空。
- stdio runtime 断线后沿用 LangBot 的“重启整个 LangBot”限制；Docker/WebSocket 模式
  可重连，但仍必须重新取得 plugin initialized/event emitted 证据。
- 不修改 `KB_BOT_CHANNELS`、HMAC envelope、tenant repository 或 PydanticAI runtime。
