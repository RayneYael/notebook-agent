# 打通 Agent 与 PostgreSQL 检索实时链路

## Goal

在不改变数据模型、用户身份或渠道绑定的前提下，修复并证明部署中的知识问答确实经过：

```text
KnowledgeAgent → query embedding → tenant-scoped PostgreSQL/pgvector
  → Citation → signed channel gateway response
```

本任务关注真实运行链路和可诊断性，不以单元组件“分别可用”代替端到端证据。

## Confirmed Facts

- 本机 PostgreSQL 可连接：已有 2 个用户、1 个 ready content item、291 个 segment，且
  291 个 segment 都已有 embedding；tenant 1 拥有可检索内容。
- `build_channel_service()` 已经装配 `KnowledgeAgent`、embedding provider 和
  `KnowledgeServices`，后者会调用 tenant-scoped BM25/vector search；问题不是缺少整条代码，
  而是部署实例未证明这条路径成功执行。
- 项目 Python 的 `ssl.get_default_verify_paths().cafile` 为空，但 certifi CA 文件存在；这可能
  使外部 embedding/model provider 在 TLS 阶段失败。
- `KnowledgeAgent` 已区分 `not_found`、`embedding_unavailable`、
  `retrieval_unavailable`，但 gateway 对未处理异常和真实运行阶段缺少足够的脱敏诊断。

## Requirements

### R1 — Real provider and database path

- 普通知识问题必须实际生成 query embedding，并由服务端注入不可变 tenant 后查询
  PostgreSQL/pgvector；模型不得提供 `user_id`、向量或 SQL。
- 使用当前配置的真实 embedding provider 做安全探针，至少验证一次返回恰好一个
  1536 维、全部为有限数值的向量。
- 使用现有 ready 私有内容验证 tenant 1 查询能得到该 tenant 的真实 citation；不得创建第二条
  parallel retrieval path，也不得绕过 `KnowledgeServices.search_segments()`。
- signed `/v1/messages` 必须走与部署 gateway 相同的 composition，并返回由 Agent 生成的稳定
  `AgentAnswer`。

### R2 — Fail closed with distinct outcomes

- provider 配置缺失、TLS/HTTP/响应校验失败映射为 `failed/embedding_unavailable`；不得退化成
  lexical-only 成功答案。
- PostgreSQL/pgvector/tool execution 失败映射为 `failed/retrieval_unavailable`。
- embedding 和 retrieval 均成功但当前 tenant 没有证据时映射为
  `not_found/no_evidence`；文案不得声称系统故障。
- 未执行必要搜索必须保持 `failed/search_required`，不能被误报为零命中。
- gateway 不得把异常 traceback、SQL、DSN、query text、vector、API key 或消息正文返回给用户。

### R3 — TLS trust and runtime diagnostics

- gateway/provider 进程必须使用该 Python 环境可解析的可信 CA bundle；优先 certifi，并保持
  TLS verification 开启。
- 为请求增加阶段化、脱敏诊断，至少能区分 model、query embedding、retrieval、answer
  validation 和 gateway response；只允许内部 request/query ID、tenant internal ID、阶段、
  stable error code、异常类和耗时。
- readiness/诊断不得打印外部渠道身份、消息正文、证据正文、token、secret 或二维码。

### R4 — Regression and deployment boundary

- 自动测试必须跨过 Agent tool、embedding provider、真实 PostgreSQL/pgvector、citation 和
  signed gateway；mock-only 测试不能作为 live-path 验收的唯一证据。
- `/start`、`/whoami`、`/link`、`/new` 等确定性命令仍不依赖模型或 embedding。
- 若改动启动配置或环境变量，更新部署说明，并保证已有 Telegram/LangBot bridge 配置不被重置。

## Out of Scope

- 数据库 schema、重新 embedding、ranking/RRF/reranker。
- 多用户身份、注册、绑定、授权和长期记忆模型。
- Agent system prompt、渠道文案产品改版或新增 Agent 框架。
- OpenClaw 自身的 poll TLS/readiness 修复；由兄弟任务
  `08-06-openclaw-tls-readiness` 负责。
- 单消息双回复兼容问题；由 `08-06-debug-wechat-double-reply` 负责。

## Acceptance Criteria

- [ ] 在部署使用的 Python/配置环境中，真实 embedding provider 对脱敏探针返回一个长度为
  1536 且全部为有限数值的向量；测试/日志不包含探针正文、向量或 key。
- [ ] PostgreSQL 集成测试或等价 live probe 证明 tenant 1 的已知查询经过
  `KnowledgeAgent.run()` → `search_segments()` → pgvector，得到 tenant 1 的真实 citation，
  且不能检索另一个 tenant 的 segment/item。
- [ ] 带正确 HMAC 的 `/v1/messages` 请求完成端到端调用，并保留 Agent 的 status、error code、
  citations；错误 HMAC 仍被拒绝。
- [ ] 自动测试分别覆盖并断言 `ok`、`not_found/no_evidence`、
  `failed/embedding_unavailable`、`failed/retrieval_unavailable`，用户提示意图互不混淆。
- [ ] provider/database 故障的日志能从 request ID 定位失败阶段，但不出现消息正文、外部身份、
  evidence、SQL/DSN、vector 或 secret。
- [ ] 确定性渠道命令在 embedding provider 不可用时仍正常，普通知识问题 fail closed。
- [ ] 相关自动测试及全量回归通过；人工微信知识问答留给用户在统一父任务验收时执行。

## Notes

- Parent task: `08-06-connect-agent-embedding`.
- 本任务先于 `08-06-openclaw-tls-readiness` 实施，避免两个任务同时修改启动入口或部署文档。
