# 自动化真实模型自然语言工具与上下文评测

## Goal

建立一套调用真实配置模型的自动化评测，验证模型能否从自然语言中正确选择 Notebook Agent tools、在连续对话中使用可信上下文，并在闲聊、模糊表达和对抗输入下避开禁止操作。现有确定性契约测试继续作为服务端安全底座，但不属于本任务交付。

## Background and Confirmed Facts

- MCP full scope 当前暴露 10 个工具；`ask_notebook_agent` 进入真实 Channel/Agent 路径，其他工具覆盖 URL 提交、库存、详情、收藏原因、删除确认、恢复和 ingestion 重试（`app/mcp_server.py`）。
- Agent 当前包含 4 个检索工具、5 个保存/保存确认工具和 9 个库存管理/删除确认工具，并通过动态 tool visibility、服务端 pending state 和检索预算限制危险或无依据调用（`app/agent/runtime.py`）。
- 现有 pytest 已使用 `FunctionModel` / `TestModel` 覆盖工具执行契约、安全边界、MCP SDK 往返、pending save/delete、精确 URL 范围、上下文恢复和会话隔离；本任务不重复建设这类预编程模型测试。
- 真正的自然语言路由评测必须调用 `build_model(Settings())` 所解析的真实 provider/model；预先指定工具调用的假模型不能计为通过。
- 项目已有单一模型配置入口：`AGENT_MODEL`、`AGENT_API_KEY`、`AGENT_BASE_URL`，并支持 OpenAI、DeepSeek 和 OpenAI-compatible gateway（`app/agent/provider.py`、`app/config.py`）。
- 真实模型评测会产生网络依赖、费用、延迟和一定非确定性，因此应与普通离线 pytest 明确分开、显式运行，并记录实际模型标识。
- 用户已选择完整基础设施边界：评测必须连接真实 PostgreSQL/pgvector、Redis、Celery worker、MinIO、ingestion connector、embedding、检索、MCP/Channel 上下文和管理路径，不能以 fake tool service 代替。
- 用户已选择复用已经运行的完整评测栈，仅用专属评测用户隔离；评测产生的数据长期保留，不自动回滚、删除数据库行或清理对象存储。
- 评测不得触碰用户或生产知识库，不得泄露 raw MCP token、provider key、tenant identity 或服务端 pending payload。

## Requirements

### R1. Machine-readable evaluation catalog

- 提供便于人工 review 和持续增补的机器可读自然语言 case catalog。
- 每个 case 至少包含稳定 ID、能力分类、单轮或多轮输入、前置可信状态、必须/允许/禁止的工具、上下文关系和预期结果类别。
- 语料覆盖：检索、上下文展开、条目元数据、精确跳转、显式保存、保存确认三分支、库存与详情、更新收藏原因、删除确认三分支、恢复、失败重试、精确 URL 问答、无证据、闲聊和安全对抗。
- 使用固定测试实体或占位 fixture 表达 URL、item/segment ID、确认码和 conversation ID，不写入真实用户数据。

### R2. Real-model runner

- runner 必须通过项目现有 provider 配置调用真实模型；缺少凭据或显式开关时清晰拒绝或 skip，不能静默改用 `TestModel`。
- 默认评测当前配置的单一 `AGENT_MODEL`，并在报告中记录模型/provider 标识、运行时间和 case catalog 版本。
- runner 支持选择单个 case、分类或全量执行，便于控制成本和复现失败。
- tool trace 来自实际 Agent/tool 执行边界，不能依赖解析模型自由文本来猜测调用了什么。

### R3. Tool-routing assertions

- 对实际 tool trace 支持 `required`、`allowed` 和 `forbidden` 约束；避免把非必要的精确调用次数和完整序列写成脆弱断言。
- 区分确定性预路由、MCP 直接管理调用与模型选择行为。例如裸 URL 由服务端直接进入确认路径，MCP 的 9 个管理 tools 由调用方直接选择；二者均不得误标为 Notebook Agent 模型路由成功。
- 明确显示每个 case 的实际工具、缺失工具、意外工具和终止结果。
- 高风险写操作的成功标准必须包含“正确选择”与“没有调用禁止工具”，不能只检查最终自然语言回复。

### R4. Multi-turn context evaluation

- 真实模型依次处理同一 conversation 的多个 turn；不能把多轮文本拼成单一 prompt 代替实际历史机制。
- 覆盖同会话指代承接、库存列表后选择、pending 中插入无关问题、删除确认码、MCP/Agent 服务重启恢复和不同 conversation 隔离。
- 服务端生成的 item ID、cursor 和删除确认码由 runner 捕获后注入后续模板，不允许模型或 fixture 猜测。

### R5. Safe and reproducible execution boundary

- 所有 case 通过 full-scope MCP/Channel/Agent 的真实运行路径执行，并通过实际数据库、broker、worker、对象存储、connector、embedding 和检索服务完成状态变化。
- 所有可能改变状态的模型选择只能作用于明确隔离的评测环境；不得连接生产 tenant 或复用个人 MCP grant。
- runner 必须完成依赖 readiness 检查，确认 MCP `tools/list` 暴露完整 10 tools 后才开始全量评测；readiness 不完整时 fail closed。
- runner 通过真实 ingestion 建立可检索基线数据，并按明确 deadline 轮询条目状态，不使用固定 sleep 伪装就绪。
- 每次 run 使用配置的专属评测用户、临时 full grant、唯一 conversation IDs 和可识别的 fixture/run 标记；case 间不得依赖不属于该评测用户的数据。
- 评测结束或中断后撤销本次临时 grant，但保留评测用户、知识条目、上下文、ingestion 记录和对象数据；不得误删或修改其他用户数据。
- 重复运行优先复用已 ready 的基线内容；缺失内容才重新提交并等待真实 ingestion。删除/恢复等状态型用例必须形成可重复的显式序列，而不是依赖自动回滚。
- 报告记录基础设施 readiness、ingestion 终态和实际 tool trace，但不得输出 secrets 或超出本次 fixture 的私有内容。

### R6. Reporting and documentation

- 输出按 case 汇总的 pass/fail/skip、实际 tool trace、错误阶段和耗时，并提供按能力分类的覆盖摘要。
- 模型非确定性通过可配置重复次数和通过阈值表达；原始每次结果保留，不能只报告多数票。
- 文档说明配置、运行单 case/分类/全量、成本风险、添加 case、解释失败以及安全边界。

## Acceptance Criteria

- [x] AC1: catalog schema 校验通过，case ID 唯一，多轮 turn 顺序有效，引用的工具名都存在于当前 MCP/Agent allow-list。
- [x] AC2: 至少有一个真实 provider/model 完成 smoke 评测，报告明确证明没有使用 `TestModel` 或预编程 `FunctionModel`。
- [x] AC3: 评测覆盖 Agent 主要检索、保存确认和管理工具；MCP/服务端确定性预路由与真实模型路由在报告中分开统计。
- [x] AC4: 至少覆盖同会话指代承接、pending 中无关问题、不同 conversation 隔离和重启恢复四类上下文序列。
- [x] AC5: 至少覆盖问候、致谢、能力询问、实时信息请求、要求绕过知识库、提示词注入和跨 tenant 请求等非标准输入。
- [x] AC6: 每个 case 能断言 required/allowed/forbidden tools，失败输出包含 case ID、turn、实际 trace 和不满足的约束。
- [x] AC7: 写操作只作用于隔离评测状态；真实 ingestion、embedding、pgvector retrieval、Redis/Celery 和 MinIO 路径均被至少一个 smoke case 证明实际参与，且不连接生产 tenant、不泄露凭据或服务端私有状态。
- [x] AC8: 支持单 case、分类和全量运行；缺少真实模型配置时清晰 skip/fail，不回退到假模型。
- [x] AC9: 支持配置重复次数和通过阈值，并保留每次真实模型结果用于分析波动。
- [x] AC10: runner 在依赖不 ready、ingestion 超时或 full MCP tools 未全部公布时 fail closed，并在报告中区分模型失败与基础设施失败。
- [x] AC11: 现有契约测试保持不变并继续通过；新增文档能让开发者独立复现一次完整基础设施上的真实模型 smoke run。

## Out of Scope

- 新增或重写已有 `FunctionModel` / `TestModel` 契约测试。
- 用真实 Telegram、微信或生产 MCP endpoint 执行评测。
- 自动修改 Agent prompt、tool schema 或业务行为来迎合评测；发现的回归作为独立缺陷处理。
- 对最终答案做逐字匹配、主观文风打分或建设大规模 RAG 语义质量 benchmark。
- 建设网页仪表盘、持续线上观测服务或多供应商排行榜。
