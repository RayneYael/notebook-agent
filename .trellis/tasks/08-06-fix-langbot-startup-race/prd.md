# 修复 LangBot 启动竞态并更新部署文档

## Goal

消除 LangBot 4.10.6 在桥接插件尚未就绪时提前启动消息 adapter 的竞态，并在插件
运行中断线或未处理事件时保持 fail closed，确保 Telegram、微信等已启用渠道可以
同时运行且不会回退到 LangBot Local Agent。同步更新可复现的部署、重启、回滚与
排障文档。

## Background

- 已观测到微信 adapter 接收积压 `/whoami` 比桥接插件 `initialized` 早约 126 ms；
  该消息随后进入默认流水线并触发 `No LLM model configured`。
- LangBot 4.10.6 的 `Application.run()` 在启动 `PlatformManager` 前调用
  `PluginRuntimeConnector.initialize_plugins()`，但后者为空实现；plugin runtime 的
  实际连接和插件初始化在后台异步进行
  （`.runtime/langbot/patched_site/langbot/pkg/core/app.py:174`、
  `.runtime/langbot/patched_site/langbot/pkg/plugin/connector.py:83`、
  `.runtime/langbot/patched_site/langbot/pkg/plugin/connector.py:187`）。
- `RuntimePipeline.process_query()` 只有在早期 `MessageReceived` event 被插件
  `prevent_default()` 后才会停止；若 runtime 已连接而指定插件尚未注册，空 event
  结果会继续执行默认 `MessageProcessor`
  （`.runtime/langbot/patched_site/langbot/pkg/pipeline/pipelinemgr.py:317`）。
- 私聊消息在到达早期插件事件前，adapter EventLogger 已记录正文和外部 sender
  session；默认 `MessageProcessor` 也会记录二者
  （`.runtime/langbot/patched_site/langbot/pkg/platform/botmgr.py:199`、
  `.runtime/langbot/patched_site/langbot/pkg/pipeline/process/process.py:31`）。竞态因此同时
  是可用性和隐私问题。
- 当前受支持组合固定为 `langbot==4.10.6`、`langbot-plugin==0.4.13`；仓库通过固定版本
  patch 复现 LangBot 定制，不把 `.runtime/` 下的本机运行副本当作交付物。

## Requirements

### R1 — Condition-based startup readiness

- LangBot 配置必须能声明一个或多个关键插件，标识使用 `author/name`。
- 当关键插件列表非空时，全部 enabled adapters 只能在 plugin runtime 已连接且每个
  关键插件状态均为 `initialized` 后启动。
- 等待必须检查真实状态，并有可配置 deadline；不得用固定 `sleep` 猜测插件启动
  用时。deadline 到期时 LangBot 启动失败并保持 adapters 未启动，交由进程管理器
  重启或人工排障。
- 未配置关键插件时保持 LangBot 4.10.6 原有行为，降低补丁对其他部署的影响。

### R2 — Per-message fail-closed guard

- 对显式绑定关键插件的 pipeline，每条消息都必须确认该插件实际接收了早期 event，
  且 event 已阻止默认处理。
- runtime 未连接、插件未发出处理证据、插件异常退出或未 `prevent_default()` 时，
  query 必须在 `MessageProcessor` 前终止；可以 best-effort 返回不含用户数据的固定
  “渠道暂时不可用”提示，但不得回退到 LangBot Local Agent。
- 插件恢复后应由真实 readiness / event 证据恢复处理，不要求切换“当前渠道”或重启
  另一个正常 adapter。stdio runtime 自身不支持自动重连时，仍按 LangBot 限制要求
  安全重启整个 LangBot。

### R3 — Multi-gateway compatibility

- Telegram、微信及其他 enabled adapters 仍由 `PlatformManager` 并发启动，不增加
  单选渠道状态。
- 同一个桥接插件可以同时服务多个 bot UUID；本任务不改变 `KB_BOT_CHANNELS` 的
  显式 bot UUID → channel 映射，也不改变项目侧用户、身份和会话模型。
- LangBot 内置模型继续保持未配置；修复不得依赖启用 Local Agent。

### R4 — Privacy-preserving failure path

- 启动窗口和插件断线窗口内，私聊正文、昵称、外部 sender ID、token、共享密钥和
  二维码不得进入 LangBot monitoring、adapter/EventLogger、默认 processor 日志、
  自动测试输出或 Trellis 文档。
- 安全诊断只记录内部 query/bot 标识、关键插件标识、状态、错误类型和耗时。
- 已有历史日志的清理由用户另行明确授权；本任务不擅自删除历史文件。

### R5 — Reproducible fixed-version patch

- 更新仓库内固定 LangBot 4.10.6 patch，使全新 4.10.6 源码可以重复应用 readiness、
  fail-closed 和相关脱敏改动。
- 自动测试必须验证 patch 可应用到固定 wheel/source，并覆盖关键行为；只修改被
  `.gitignore` 排除的 `.runtime/langbot/patched_site` 不算完成。
- 本地 smoke 如需同步运行副本，必须从同一 patch 生成或应用，并记录版本，不得形成
  第二套手工补丁。

### R6 — Deployment documentation

`docs/deployment.md` 与桥接插件 README 必须补充：

- 固定版本安装和 patch 应用/反向回滚检查；
- 插件安装目录私有 `.env`、所需变量、`chmod 600` 与禁止记录 secret 的要求；
- macOS 使用 certifi 的 `SSL_CERT_FILE` 和 `REQUESTS_CA_BUNDLE`；
- gateway health、关键插件 initialized、LangBot readiness、plugin-first / adapter-second
  的启动验证；
- 微信二维码首次登录和过期后的安全重登录；
- 日常启动、停止、安全重启、deadline 失败、runtime 断线和回滚排障；
- 明确禁止用固定等待时长代替 readiness，也禁止通过启用 LangBot 内置模型掩盖失败。

### R7 — Verification and acceptance handoff

- 自动测试至少覆盖：消息早于插件 ready、ready 后正常拦截、运行中断线、插件未
  `prevent_default()`、默认 `MessageProcessor` 未调用、敏感字段不落日志，以及多个
  enabled adapters 未被改成单选。
- 自动检查不得替代真实平台验收，但本子任务不拥有真实渠道验收门：微信连续
  `/whoami`、重启回归和日志人工复查由直接父任务
  `08-06-diagnose-wechat-whoami` 负责；Telegram 完整端到端由上层
  `08-05-knowledge-retrieval-agent` 总体验收负责。这样同一平台探针只执行一次。

## Acceptance Criteria

- [x] AC1：在测试中让消息早于关键插件 ready；enabled adapter 不处理该消息，且
  `MessageProcessor` 调用次数为 0。
- [x] AC2：关键插件达到 `initialized` 后，Telegram 与微信两个 enabled adapter 均
  被启动；通过早期 event 正常处理消息，未启用 LangBot Local Agent。
- [x] AC3：运行中模拟 runtime 断线、插件缺席和未 `prevent_default()`；三种情况均
  fail closed，`MessageProcessor` 调用次数为 0，恢复后无需切换渠道即可继续处理。
- [x] AC4：自动隐私测试使用唯一 canary 正文和外部身份，断言 monitoring、adapter、
  processor 与诊断日志均不含 canary；输出只含脱敏状态。
- [x] AC5：固定版本 patch 能在干净 LangBot 4.10.6 source 上 `patch --dry-run` 和实际
  应用成功，相关自动测试全部通过。
- [x] AC6：部署文档包含 R6 的全部配置、启动、readiness、扫码、安全重启、回滚和
  排障步骤，示例不含真实凭据。
- [x] AC7：已将真实渠道验收责任移交：微信 smoke 归直接父任务，Telegram E2E
  归上层总体验收；本任务不重复执行或宣称通过这些人工测试。

## Out of Scope

- 长期记忆策略、用户/身份 schema、知识检索排序和 embedding 数据库改造。
- 新增 Slack 等渠道的真实平台验收；本任务只保证多 adapter 机制没有被破坏。
- 修改 LangBot 上游版本或把补丁泛化到 4.10.6 以外版本。
- 自动清理已经存在的敏感历史日志。

## Open Questions

没有阻塞 planning 的产品问题。实现采用可配置关键插件列表、30 秒 readiness deadline、
状态驱动等待和每消息 fail-closed 双重保护；deadline 可由部署配置调整。
