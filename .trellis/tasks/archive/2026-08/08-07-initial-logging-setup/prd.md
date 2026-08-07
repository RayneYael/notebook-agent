# 日志初步搭建

## Goal

为 LangBot bridge 与 Notebook Agent 搭建第一版隐私安全、真实可见、可跨进程关联的结构化日志，
使维护者能够判断一条请求经过了哪些阶段、在哪个阶段失败以及耗尽了哪类预算，同时不记录用户
内容、外部身份、模型/工具 payload 或 secret。

## Background

- 普通概念问答曾连续返回“检索步骤已达到上限”，但当前运行环境没有足以还原执行线路的日志，
  因而无法确认请求走过的模型、工具、embedding、检索和 citation 分支。
- `app/diagnostics.py` 已提供脱敏事件对象，但字段只有 stage、内部 request/tenant ID、error code、
  exception class 和累计耗时，缺少模型轮次、工具序列、安全计数和具体限额类型。
- `RequestDiagnostics` 使用 `notebook_agent.runtime` 的 `INFO` logger；CLI 与 gateway 启动入口没有
  显式配置其 level/handler/formatter，默认运行时可能完全看不到这些事件。
- LangBot 隐私补丁已删除消息正文、外部身份和 preview，同时保留内部 `query_id`、readiness 状态
  与异常类。现有 LangBot 日志/收集设施可以继续作为统一运维查看入口，不需要恢复原始消息日志。
- bridge 在早期 `PersonMessageReceived` 阶段阻止默认 LangBot 流水线，普通 MessageProcessor 日志
  不覆盖这条路径；bridge 异常分支也刻意保持沉默，因此需要补充白名单化的结构事件。
- 当前 PydanticAI 的 `UsageLimitExceeded` 可区分 request、tool_calls 和 output_tokens，但 runtime
  将它们统一映射为 `limit`，现有日志也没有安全分类。

## Requirements

### R1 — 明确日志所有权与输出通道

- LangBot core 继续使用自带 logger，同时输出到 stdout 和 LangBot 数据目录下的
  `data/logs/langbot-YYYY-MM-DD.log`。本仓库当前本机运行目录对应
  `.runtime/langbot/data/logs/langbot-YYYY-MM-DD.log`。
- bridge 插件运行在独立子进程；其 Python stderr 只会进入 LangBot plugin runtime 的有界内存日志，
  不会自动持久化到 LangBot core 每日文件。第一版只让 bridge 输出少量白名单 stderr 事件，供
  LangBot 插件日志页临时查看；不为 bridge 新增独立日志文件。
- Notebook Agent gateway 事件必须同时输出到 stdout 和自己的每日轮转文件。Linux 服务器文件固定
  位于 `/var/log/notebook-agent/notebook-agent-YYYY-MM-DD.log`；stdout 仍由 systemd journal 保存，
  可使用 `journalctl -u notebook-agent-gateway` 查看。
- 本地开发默认写入 `.runtime/logs/notebook-agent-YYYY-MM-DD.log`，并同时显示在启动终端；
  `.runtime/` 已被 Git 忽略，日志不得进入仓库。
- 本地开发可通过显式的双重配置（运行环境为 `development` 且检索内容日志开关为 true）把检索详情
  写入同一 stdout 与 `.runtime/logs/` 文件；默认值和服务器配置必须保持关闭，不能只根据日志路径
  猜测环境。
- Notebook Agent 不直接写 LangBot 的日志文件。两个进程分别拥有各自文件，避免同时写入和轮转
  同一文件造成所有权、并发与保留策略问题，再通过 trace/request ID 联合查询。
- LangBot/bridge 只记录 adapter、plugin、loopback POST 和平台 reply 阶段；Notebook Agent 只记录
  gateway、route、model、tool、embedding、retrieval、validation 和 answer 阶段。
- gateway/CLI 启动路径必须显式启用 `notebook_agent.runtime` 的结构化 `INFO` stdout 与文件
  handler；不得依赖宿主偶然配置 logger。bridge plugin stderr、Notebook Agent 文件和 gateway
  journal 通过 trace/request ID 联合查询；LangBot core 文件继续用于渠道与插件 readiness 排障。
- 不新增一条向 LangBot 传输 prompt、tool payload、异常原文或其他私密调试数据的 API，也不得由
  任一进程根据另一进程的最终结果猜测并伪造内部阶段。

### R2 — 建立跨进程关联与最小执行轨迹

- bridge 为每次转发生成随机、定长、无业务含义的 trace ID，并由现有 HMAC 请求保护；gateway
  校验格式后只将其用于日志关联。
- trace ID 不得参与身份、tenant、授权、幂等、消息去重或业务状态判断。gateway 继续生成自己的
  内部 request ID，并通过一条安全事件记录二者的映射。
- LangBot `query_id`、平台 `message_id` 和 fallback message digest 不得充当跨进程 trace ID，
  也不得进入 Notebook Agent 日志形成外部身份映射。
- 一次普通问答至少能够观察到实际经过的 `accepted → route → model attempt → tool call →
  embedding → retrieval → validation → final answer`；未经过的阶段不得输出事件。
- 每个事件仅允许固定枚举和数值，包括 stage、route、工具名、调用序号、安全结果数量、重试次数、
  预算类型/上限/已用计数、稳定 error code、exception class 与阶段耗时。
- 仅在显式启用的本地开发模式中，Notebook Agent 可另外记录检索工具的查询、limit/radius、
  segment/item ID、标题、作者/描述、URL、命中分数、片段正文和时间位置；这些详情仍必须来自真实
  工具边界，不得由最终回答反推。

### R3 — 环境化隐私边界与安全失败

- 服务器/生产模式日志严禁包含用户问题或历史正文、检索词、模型输出、prompt、tool
  arguments/result payload、evidence、citation/segment/item ID、URL、向量、外部渠道身份、provider
  payload、token、DSN、HMAC secret、二维码或任意 exception message。
- 显式启用的本地开发模式只放开“检索详情”：检索工具的查询及真实结果字段可以原样进入本地
  stdout 和 `.runtime/logs/`。用户历史、完整模型 prompt、模型输出、action/save 工具参数与结果、
  embedding 向量、外部身份、provider payload、secret 和异常消息在开发模式中仍然禁止。
- 内容开关必须 fail closed：仅 `development` 环境可开启；生产/服务器环境尝试开启时配置校验失败，
  不得静默降级为泄漏状态，也不得由日志目录相对/绝对路径推断环境。
- `UsageLimitExceeded` 只能按已知固定前缀映射为 request、tool_calls、output_tokens 或 unknown；
  unknown 保持 fail closed，不把完整异常消息写入日志。
- 所有新增字段必须经过显式 allow-list；开发检索详情使用专用、类型明确的事件 API，不能退化为
  接收任意 `extra`、任意 tool payload 或全局原始正文的“debug 模式”。
- 文件 handler 必须按日期和大小有界轮转，并设置最小必要的目录/文件权限；不得无限增长或允许
  非服务账户默认读取。
- 文件写入暂时不可用时必须在 stdout 输出一条不含路径外敏感信息的稳定诊断并继续使用 journal；
  不得改变 Agent 的权限、检索结果和用户回复，也不得造成第二条平台回复。

### R4 — 可验证和可运维

- 文档明确说明查看位置：本机/部署 LangBot core 的 `data/logs/`、LangBot 插件日志页中的 bridge
  stderr、本机 Notebook Agent 的 `.runtime/logs/`、服务器 Notebook Agent 的
  `/var/log/notebook-agent/`，以及 gateway 的 `journalctl -u notebook-agent-gateway`；同时说明如何
  按 trace/request ID 联合查询，以及哪些字段被有意禁止。
- Linux systemd 示例使用 `LogsDirectory=notebook-agent` 或等价的最小权限机制创建可写日志目录，
  与现有 `ProtectSystem=strict` 兼容；不得要求服务以 root 身份运行或放宽整个文件系统保护。
- readiness 或启动日志必须能确认结构化诊断已启用；诊断未启用时不得给维护者“已经可观察”的
  错误信号。
- 第一版只建立本地/部署现有 collector 可消费的日志，不引入新的日志 SaaS、搜索集群、指标平台、
  dashboard 或告警系统。

## Acceptance Criteria

- [ ] 在不依赖测试框架临时设置 logger level 的情况下，gateway/CLI smoke 会向 stdout 和
  `.runtime/logs/notebook-agent-YYYY-MM-DD.log` 同时输出同一条结构化 INFO 事件。
- [ ] Linux systemd smoke 证明同一事件既可通过 `journalctl -u notebook-agent-gateway` 查看，也会
  出现在 `/var/log/notebook-agent/notebook-agent-YYYY-MM-DD.log`；目录由 service manager 以最小
  权限创建，现有 `ProtectSystem=strict` 保持启用。
- [ ] LangBot core 事件保持进入 stdout 与 `data/logs/langbot-YYYY-MM-DD.log`；bridge 安全事件只
  进入 plugin stderr 的有界日志，不新增 bridge 文件，也不要求 Notebook Agent 进程写入 LangBot 文件。
- [ ] fake LangBot event → bridge → signed gateway 测试证明同一个随机 trace ID 可关联两个进程的
  事件；伪造格式、超长值和未签名请求 fail closed，trace ID 不影响任何业务判断。
- [ ] 有证据、零命中、embedding failure、retrieval failure 和 usage limit 场景分别输出实际经过
  的阶段；未经过的阶段不会出现。
- [ ] request、tool_calls、output_tokens 三类人工限额映射为不同固定枚举，并带有安全计数；unknown
  类型不输出原始异常文本。
- [ ] 日志隐私测试同时检查 stdout 与每日文件，使用敏感哨兵覆盖问题、历史、检索词、prompt、
  模型输出、工具参数/结果、证据、URL、外部身份、向量、provider payload、secret 和 exception
  message；生产模式断言所有哨兵均不出现。
- [ ] 本地 development + 检索内容开关 smoke 证明检索 query、命中 ID/标题/URL/分数/片段正文会同时
  出现在 stdout 与 `.runtime/logs/`，而历史、完整 prompt、模型输出、action payload、向量、外部
  身份、provider payload、secret 和 exception message 仍不出现。
- [ ] 默认配置关闭检索内容日志；生产环境尝试打开开关会在启动前失败，且 bridge、LangBot core、
  journal 和 `/var/log/notebook-agent` 不会因此得到检索正文。
- [ ] 日期/大小轮转与保留上限测试通过；文件不可写时 stdout/journal 出现稳定告警，问答行为不变。
- [ ] LangBot/bridge 与 Notebook Agent 的事件所有权边界可测试；任何一侧都不会伪造另一侧阶段，
  bridge stderr 与 Notebook Agent 日志可以通过 trace/request ID 联合查询。
- [ ] 日志失败不会改变现有 AgentAnswer、tenant isolation、conversation persistence、保存/确认动作、
  消息幂等或单消息单回复行为；相关回归测试通过。

## Out of Scope

- 定位或修复“检索步骤已达到上限”的具体业务根因；该工作在本任务产生日志证据后单独开展。
- 在服务器/生产日志中记录问题正文、检索词、prompt、模型输出或工具 payload；本地显式开发模式的
  检索详情例外仅限 R3 定义的字段。
- 引入 Loki、ELK、OpenTelemetry collector、Sentry 等新的外部可观测平台。
- 让 gateway 与 LangBot 两个进程共同写一个日志文件。
- 为 bridge plugin 新增独立的持久化日志文件；第一版只复用其 stderr 有界日志。
- 指标、dashboard、告警、长期日志归档、审计报表和用户可见的调试界面。
- 更换 LangBot、Agent 框架、模型 provider、embedding、数据库或检索算法。

## Notes

- Parent: `08-06-connect-agent-embedding`。
- 当前状态保持 `planning`；尚未开始实现。
