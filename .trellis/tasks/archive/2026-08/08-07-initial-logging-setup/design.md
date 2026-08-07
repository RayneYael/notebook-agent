# 日志初步搭建设计

## 1. 目标与边界

本任务建立可用于真实排障的最小日志链路，不记录任何私聊内容。执行事实由实际拥有该事实的进程
产生，并用随机 trace ID 关联；日志输出失败不能改变 Agent 的业务行为。

本任务不定位或修复“检索步骤已达到上限”的根因，只保证后续能够用真实轨迹定位。

## 2. 目标数据流

```text
LangBot adapter
  -> LangBot core log
       stdout + data/logs/langbot-YYYY-MM-DD.log
  -> bridge plugin (new random trace_id)
       stderr (LangBot plugin runtime bounded log only)
  -> signed loopback POST (trace_id is inside HMAC-protected body)
  -> HTTP gateway (new authoritative request_id; keep trace_id only for correlation)
  -> ChannelService -> KnowledgeAgent -> tools -> embedding/retrieval -> validation
       stdout/systemd + notebook-agent-YYYY-MM-DD.log
```

日志关联不改变现有信任模型：`request_id` 仍由 gateway 覆盖生成；`trace_id` 只用于查询日志，不能
参与 tenant、身份、授权、幂等、消息去重或业务状态。

## 3. 日志文件与配置

### 3.1 LangBot core

保留 LangBot 4.10.6 现有配置和文件：

```text
data/logs/langbot-YYYY-MM-DD.log
```

不让其他进程写这个文件，也不改变 LangBot 的 10 MiB / 5 backups 轮转约定。

### 3.2 Bridge plugin

bridge 使用 Python stdlib logger 只写 stderr，供 plugin runtime 的有界日志页临时读取。第一版不为
bridge 配置目录、每日文件或长期保留；bridge 不从 `__file__` 猜测 LangBot 根目录，也不写
`langbot-*.log`。

### 3.3 Notebook Agent

新增 Notebook Agent 日志配置：

```text
NOTEBOOK_AGENT_LOG_DIR=.runtime/logs                 # 本地默认
NOTEBOOK_AGENT_LOG_DIR=/var/log/notebook-agent      # Linux systemd
NOTEBOOK_AGENT_LOG_MAX_BYTES=10485760                # 默认 10 MiB
NOTEBOOK_AGENT_LOG_BACKUP_COUNT=5                    # 默认 5 backups
NOTEBOOK_AGENT_ENV=production                        # 安全默认
NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=false           # 安全默认
```

本地若确实需要开发检索详情，必须同时设置
`NOTEBOOK_AGENT_ENV=development` 与 `NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=true`。只设置内容开关、在
生产环境设置内容开关，或使用未知环境枚举都必须配置失败。不得根据 `.runtime/logs`、绝对路径、
TTY 或 hostname 自动判定环境。systemd 示例显式使用 `production` 与 `false`。

文件名为 `notebook-agent-YYYY-MM-DD.log`，同时输出到 stdout。systemd unit 使用
`LogsDirectory=notebook-agent` 和显式 `NOTEBOOK_AGENT_LOG_DIR=/var/log/notebook-agent`，保持
`ProtectSystem=strict`，不以 root 运行。

Notebook Agent 实现项目内的 stdlib 日轮转 + 大小轮转 handler；不得 import LangBot 的私有
runtime 模块。handler 安装必须幂等，避免测试、CLI 或重复 composition 添加多份输出。

## 4. 事件契约与隐私白名单

Notebook Agent 的事件由 `RequestDiagnostics` 统一序列化。调用方不得拼接任意文本或传入任意
`extra` dict；API 只接受明确字段：

```text
stage, request_id, trace_id, tenant_id, route,
tool_name, call_index, result_count, retry_count,
limit_kind, limit_value, used_value,
error_code, error_class, duration_ms
```

字段缺失写固定占位符。stage、route、tool_name、limit_kind 和 error_code 使用固定枚举；计数字段只
接受非负整数。`exception` 只投影为类名，永不读取或写出任意异常消息。

bridge 使用更小白名单：`stage`、`trace_id`、固定 channel enum、HTTP outcome enum、error class、
duration。它不记录 LangBot query ID、bot UUID、平台 message ID、fallback digest、外部身份或正文。

开发检索详情不能通过任意 `extra` dict 实现。`RequestDiagnostics` 提供专用、显式字段的
`retrieval_detail` 事件，由真正拥有事实的 retrieval/tool 层调用，允许字段限定为：固定工具名、
调用序号、query、limit/radius、segment/item ID、title、author/description、URL、score、excerpt 与
start/anchor。结果数量仍受现有工具上限约束；不得把任意模型 tool payload 直接交给 logger。

生产模式明确禁止：问题/历史/检索词、prompt、模型输出、tool arguments/results、证据及内部内容
ID、URL、向量、外部身份、provider payload、token、DSN、HMAC secret、二维码和 exception message。
开发模式只豁免上一段定义的检索字段；历史、完整 prompt、模型输出、action/save payload、向量、
外部身份、provider payload、secret 与 exception message 继续禁止。bridge 与 LangBot core 永不接收
开发检索详情。

## 5. Trace 与 HTTP 合约

- bridge 每次首次投递生成 `uuid4().hex`（32 位小写 hex）。重复平台消息仍由现有 deduplicator 在 POST
  前抑制，后续重复不生成第二条平台回复。
- `ChannelEnvelope` 增加可选 `trace_id`，只接受 32 位小写 hex。
- HTTP gateway 只在 HMAC、timestamp、nonce 验证通过后解析 trace；非法 trace 返回
  `invalid_envelope`。gateway 仍无条件生成新的 32 位 `request_id`。
- CLI/非 LangBot adapter 没有 trace 时由可信应用边界生成一个，保持同一诊断契约。
- gateway 第一条安全事件同时含 `trace_id` 与内部 `request_id`，后续 Notebook Agent 事件只需沿用
  `RequestDiagnostics`，不把 trace 写入 `AgentAnswer` 或 conversation store。

## 6. Agent 阶段与预算诊断

- `ChannelService` 记录 accepted、route selected、duplicate/command/agent branch 和 final response。
- `KnowledgeAgent` 使用 PydanticAI 每次 run 的 event stream/usage context 只统计模型请求序号，不读取
  streaming content、tool args 或 model parts。
- 每个注册工具在执行边界记录固定 tool name、调用序号和安全结果数量；embedding/retrieval 继续由
  `KnowledgeServices` 记录阶段。
- citation validator 只记录 accepted/retry、repair 次数和 citation 数量，不记录 citation ID 或草稿。
- `UsageLimitExceeded` 只解析 PydanticAI 当前固定前缀，映射为 `request`、`tool_calls`、
  `output_tokens` 或 `unknown`。tool-call 异常中的框架数字是 projected usage，必须与实际已开始的调用
  数分开记录；原始字符串不进入 logger。
- 并发工具调用在 started 时分配不可变、线程安全的 call index，succeeded/failed 和对应开发检索
  详情必须复用同一 index，不能读取稍后增长的全局计数。

若 event stream API 在当前固定 PydanticAI 2.15.0 中不能稳定提供模型请求计数，实现应保留工具和
limit 计数，并在 design/测试中记录该技术限制；不得通过读取 prompt/model output 弥补。

## 7. 故障与兼容性

- 日志目录/文件初始化失败：保留 stdout handler，输出固定 `file_logging_unavailable` 和异常类；
  gateway 继续启动，业务结果不变。
- 单次 emit 失败：吞掉 logging sink 故障，不让异常穿过 Agent/channel 边界。
- 配置为非法负数/零：静态配置校验失败，不创建无界 handler。
- 生产环境尝试启用检索内容日志：静态配置校验失败，不启动可能泄漏内容的 handler。
- 既有用户回复、数据库 schema、conversation store、HMAC 验证、tenant isolation 和 LangBot
  fail-closed 行为均不改变。
- `.runtime/` 继续 gitignore；任何真实日志都不得提交。

## 8. 验证策略

- 单元测试验证 formatter/allow-list、日切换、大小轮转、handler 幂等与文件失败 fallback。
- bridge fake event 测试验证 trace、HMAC body、stderr/file 安全事件、失败和 duplicate 路径。
- HTTP/Channel/Agent 测试验证 request/trace 边界和各实际阶段。
- 生产模式敏感哨兵同时扫描 stdout、Notebook Agent 文件和捕获的 bridge stderr；开发模式单独断言
  允许的检索详情可见，而仍禁止的历史、模型/action/provider/secret/异常内容不可见。
- systemd 配置以静态断言 + Linux 人工 smoke 验证 `/var/log/notebook-agent` 与 journal 双写。

## 9. 回滚

- Notebook Agent handler 回归时可停用文件 handler 并保留 stdout；不得恢复原始消息日志。
- bridge 诊断回归时可移除新增 stderr 事件；不得让 bridge 写 LangBot core 文件或新增持久化文件。
- trace 字段回滚不影响 HMAC、identity、message ID 或 conversation schema，因为它只存在于请求级内存。
