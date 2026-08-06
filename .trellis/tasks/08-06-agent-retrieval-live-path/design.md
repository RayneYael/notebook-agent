# Agent 检索实时链路设计

## 1. Boundary

只修复和验证已有生产链路，不创建新 Agent、数据库或检索服务：

```text
signed gateway request
  → ChannelService
  → KnowledgeAgent
  → KnowledgeServices.search_segments(query)
  → configured EmbeddingProvider
  → tenant-scoped BM25 + pgvector
  → Citation allow-list
  → AgentAnswer
```

tenant ID 只能由可信的 channel identity mapping 注入。模型只提供自然语言 query，不可影响
tenant、向量、SQL 或 provider 配置。

## 2. Trust-store initialization

在 gateway/provider 的 composition root 解析 CA bundle：显式部署配置优先，其次使用当前
Python 环境的 certifi bundle。将同一 CA 传给使用 HTTPS 的 provider，或者在进程启动前设置
兼容库使用的标准变量。禁止 `ssl=False`、unverified context、关闭 hostname verification 或
捕获证书错误后继续报告成功。

静态路径无效应尽早给出脱敏配置错误；运行期 provider TLS/HTTP 错误应在请求级映射为
`embedding_unavailable`，不影响确定性身份/会话命令。

## 3. Stage diagnostics

为一条 gateway 请求建立内部 correlation/request ID，并记录有限状态转换：

```text
accepted → agent_started → model/tool_requested → embedding_started
  → retrieval_started → citation_validated → response_ready
```

失败记录 `stage`、stable error code、exception class、duration 和内部 tenant/query ID。禁止记录
用户文本、外部 sender ID、昵称、citation 内容、模型/provider payload、向量、token 或 secret。
HTTP 响应继续只返回稳定领域结果，不暴露诊断详情。

## 4. Result contract

结果由最后成功完成的边界决定：

| Condition | Result |
| --- | --- |
| embedding + retrieval + citation success | `ok` |
| embedding + retrieval success, no tenant evidence | `not_found/no_evidence` |
| config/provider/vector validation failure | `failed/embedding_unavailable` |
| database/pgvector/tool execution failure | `failed/retrieval_unavailable` |
| no required search tool call | `failed/search_required` |

gateway 和 bridge 透传这套状态，不根据文本内容重新分类。

## 5. Test shape

- unit: CA resolution、异常映射、redaction、command bypass；
- PostgreSQL integration: 两个 tenant 和互斥数据，fake deterministic vector 证明 SQL/hydration
  隔离；
- provider smoke: 真实 HTTPS provider，只记录向量维度与 finite 断言；
- gateway E2E: HMAC request 经过真实 composition，证明 Agent 调用了 `search_segments` 并返回
  citation；
- full regression: Agent、retrieval、multiuser、gateway、ingest 和 LangBot bridge 相关测试。

## 6. Compatibility and rollback

不做 schema migration，不重写 embedding。若 CA/composition 改动导致回归，可回滚该初始化；
但普通问题必须继续 fail closed，不能恢复 lexical-only 假成功。若发现 tenant 泄漏，立即停止
知识问答路径并保留确定性命令，不对数据库做 destructive rollback。
