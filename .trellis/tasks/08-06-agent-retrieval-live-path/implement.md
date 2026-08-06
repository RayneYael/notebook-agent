# 实施计划

## 1. 建立可复现证据

- [ ] 在不记录 query/body/secret 的情况下，复现 signed gateway 普通知识请求，标记失败发生在
  model、embedding、retrieval 还是 response 阶段。
- [ ] 使用部署 Python 环境确认 certifi CA 路径和默认 trust store 状态。
- [ ] 添加失败测试，证明当前 live path 的实际缺口；不得用 mock-only 测试推断真实 provider
  或 PostgreSQL 已连通。

## 2. 修复 gateway/provider TLS 与诊断边界

- [ ] 在单一 composition/launcher 边界解析并校验 CA bundle，保持证书和 hostname 校验开启。
- [ ] 为 gateway→Agent→embedding→retrieval 添加脱敏 stage diagnostics 和 correlation ID。
- [ ] 未处理异常映射为现有稳定领域错误；HTTP 响应和日志均不泄露正文、外部身份或 secret。

## 3. 收紧真实检索路径

- [ ] 确认普通问题强制使用 configured query embedder，provider 失败时不执行 lexical-only 成功
  路径。
- [ ] 确认 `KnowledgeAgent.run()` 的 `search_segments` 实际进入 tenant-scoped vector search，并
  hydrate 真实 citation。
- [ ] 保留确定性命令 bypass、tool schema 不含 tenant/vector/SQL，以及现有 owner recheck。
- [ ] 保留 `not_found`、`embedding_unavailable`、`retrieval_unavailable` 的稳定分类和不同提示意图。

## 4. 自动验证

- [ ] 单元测试：CA resolution、provider TLS/error mapping、vector shape、diagnostic redaction、
  deterministic command bypass。
- [ ] PostgreSQL integration：两个 tenant、互斥 citation，完整 Agent tool→embedding→pgvector
  路径，无跨 tenant 命中。
- [ ] signed gateway E2E：正确 HMAC 成功，错误 HMAC 拒绝，Agent result contract 不被改写。
- [ ] 真实 provider smoke：一个 1536 维 finite vector，仅输出 pass/fail 和耗时范围。
- [ ] 分别注入 zero-hit、provider failure 和 database failure，断言状态/错误码不混淆。

建议命令（实现者按仓库实际测试文件补充，不得删减相关全量回归）：

```bash
.venv/bin/pytest -q tests/test_embed.py tests/test_agent_runtime.py
.venv/bin/pytest -q tests/test_multiuser_integration.py tests/test_http_gateway.py
.venv/bin/pytest -q
git diff --check
python3 ./.trellis/scripts/task.py validate 08-06-agent-retrieval-live-path
```

## 5. 部署交接

- [ ] 若启动配置有变，更新部署文档，说明 CA resolution、必要 provider 配置和安全 smoke。
- [ ] 重启 gateway 后执行只读 readiness/provider/database probe；不得重置 LangBot 用户数据或
  渠道绑定。
- [ ] 将自动验收证据写回任务；微信人工知识问答留给父任务统一验收。

## Rollback points

- CA 初始化不兼容：回滚该初始化并保持知识问答 fail closed，不能关闭 TLS verification。
- diagnostics 泄露风险：禁用新增日志字段并保留稳定 error code。
- tenant isolation 失败：停止知识问答路径；不修改或删除现有数据库内容。
