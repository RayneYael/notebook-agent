# 日志初步搭建执行计划

## 1. 固化日志配置与安全序列化

- [ ] 为 Notebook Agent 增加日志目录、单文件大小和备份数量配置及 `.env.example`。
- [ ] 实现项目自有的日期 + 大小轮转 handler、stdout/file 双 handler 和幂等初始化。
- [ ] 把 `RequestDiagnostics` 收紧为固定字段 allow-list、枚举和非负计数，不接受任意 payload。
- [ ] 增加 `UsageLimitExceeded` 固定前缀分类器，未知文本只返回 `unknown`。
- [ ] 测试 logger 初始化、双写、日切换、大小轮转、备份上限、重复初始化和文件失败 fallback。
- [ ] 修正审查发现的问题：gateway 日志只初始化一次；权限设置异常关闭已打开流；保留文件删除失败
  触发一次安全 fallback，不能静默突破备份上限。

## 2. 打通 trace 与渠道边界

- [ ] bridge 为首次投递生成 32 位随机 trace ID，并把它放入现有 HMAC 覆盖的 JSON body。
- [ ] `ChannelEnvelope` 验证可选 trace ID；HTTP gateway 保留合法 trace 但始终覆盖生成 request ID。
- [ ] CLI/可信非 HTTP 入口缺 trace 时生成内部 trace，且 trace 不参与身份、幂等或授权。
- [ ] bridge 增加只含白名单字段的 stderr 日志，复用 LangBot plugin runtime 的有界日志，不新增文件。
- [ ] 覆盖合法、非法、超长、未签名 trace，以及 duplicate delivery 单回复回归。

## 3. 补齐请求阶段事件

- [ ] 在 ChannelService 增加 accepted、route 和 response 事件，不记录 envelope 内容或外部身份。
- [ ] 通过当前 PydanticAI 2.15.0 的 per-run event stream/usage context记录模型请求计数，不读取事件内容。
- [ ] 为所有 Agent 工具记录固定 tool name、call index、成功/失败和安全 result count。
- [ ] 并发工具调用使用线程安全、调用级不可变 index，使 started/succeeded/failed 可一一配对。
- [ ] 为 citation validation/retry 记录次数和计数；不记录草稿或 citation ID。
- [ ] 在 timeout、usage limit、embedding、retrieval、runtime 和 action 分支记录稳定结果分类。
- [ ] tool-call limit 分开记录实际已开始数量与 PydanticAI projected 数，修正伪造的低于 limit 测试值。

## 3.1 本地开发检索详情

- [ ] 增加显式 `NOTEBOOK_AGENT_ENV` 与 `NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT` 配置，默认
  production/false；只有 development+true 可以启用，其他组合 fail closed。
- [ ] 通过专用 typed/allow-listed 事件记录 search/get_neighbors/get_item/open_at 的查询或定位参数，
  以及真实 ID、标题、作者/描述、URL、score、excerpt、start/anchor；不接受任意 tool payload。
- [ ] 开发检索详情只进入 Notebook Agent 本地 stdout 与 `.runtime/logs/`，不传给 bridge、LangBot
  core、AgentAnswer、conversation store 或 provider。
- [ ] 开发模式仍禁止历史、完整 prompt、模型输出、action/save payload、向量、外部身份、provider
  payload、secret 与异常消息；为允许和禁止字段分别增加 stdout/file 哨兵测试。

## 4. 部署与文档

- [ ] 更新 plugin 文档，说明安全事件只进入有界 stderr/plugin 日志，不作为持久化来源。
- [ ] 更新 Notebook Agent `.env.example`，说明本地 `.runtime/logs` 默认与服务器绝对路径。
- [ ] 文档说明本地开发检索详情的双重显式开关、字段范围和生产 fail-closed 行为；systemd 显式设置
  production/false。
- [ ] 更新 systemd 示例：`LogsDirectory=notebook-agent`、最小权限和显式日志目录，同时保留
  `ProtectSystem=strict`。
- [ ] 文档列出 LangBot core、bridge、Notebook Agent file 和 journal 的查看方法及 trace 联查示例。
- [ ] 明确禁止 debug 正文/payload 开关，记录文件不可写的 stdout fallback。

## 5. 自动验证

- [ ] 运行日志、gateway、bridge、Agent runtime 的定向测试。
- [ ] 运行 multiuser/channel/action 回归，确认 tenant、conversation、幂等和单回复不变。
- [ ] 对 stdout 和两个新增文件运行敏感哨兵断言。
- [ ] 分别运行 production 全脱敏和 development 检索详情可见的双模式测试。
- [ ] 运行全量 pytest、`git diff --check` 和 Trellis validate。

建议命令：

```bash
.venv/bin/pytest -q tests/test_diagnostics.py tests/test_http_gateway.py \
  tests/test_langbot_bridge_plugin.py tests/test_agent_runtime.py
.venv/bin/pytest -q tests/test_multiuser_integration.py tests/test_agent_actions.py
.venv/bin/pytest -q
git diff --check
python3 ./.trellis/scripts/task.py validate 08-07-initial-logging-setup
```

## 6. 人工 smoke

- [ ] 本地启动 gateway，确认终端和 `.runtime/logs/notebook-agent-<today>.log` 双写同一安全事件。
- [ ] 本地 development+true 发起检索，确认 query 与命中详情双写；切回 production/false 后确认同一
  检索详情完全不可见。
- [ ] fake/本地 bridge 事件确认安全事件进入 stderr，且没有创建 bridge 日志文件。
- [ ] Linux 部署确认 journal 与 `/var/log/notebook-agent/notebook-agent-<today>.log` 双写，文件权限正确。
- [ ] 用一个 trace ID 串联 bridge 与 gateway/Agent 阶段，人工确认没有正文、身份或 payload。

## 风险与回滚点

- 修改 LangBot bridge 包后必须重新打包/安装，并保留现有 required-plugin readiness 与 fail-closed 补丁。
- 文件 handler 失败时只回滚到 stdout/stderr，不得关闭脱敏或打开原始消息日志。
- trace 合约异常时回滚可选字段，不修改 request ID、message ID、HMAC、identity 或数据库 schema。
