# 来源 Channel 完成通知 Poller：实现计划

## Implementation order

1. **冻结并行状态与基线**
   - 记录 dirty tree，只认领本任务文件；排除 agent autonomy、腾讯部署等并行任务。
   - 确认 producer focused tests、LangBot patch baseline 和单一 Alembic head。
   - 记录当前 `ingest-completion` publish schedule/immediate hook/queue tests，作为退役清单。

2. **来源 thread admission**
   - 为 `IngestDispatch` 添加 nullable `source_thread_id` model/migration/FK/index。
   - 扩展 `AgentActionRuntime` → `IngestSubmissionService` 内部调用，direct save、confirm save、
     retry 均传 server-owned thread ID。
   - submission 在 dispatch transaction 内验证 tenant/thread/identity/channel；MCP/CLI/unsupported
     channel 保存 NULL；replay 不改既有 target。

3. **通知 delivery schema 与 claim service**
   - 新增 `IngestCompletionDelivery` model/migration、check constraints、唯一 handler key、
     claim/retry index、`next_attempt_at` 和 attempt ceiling 状态合同。
   - 实现 event + delivery 的稳定批量 selection：missing delivery、eligible failed、stale claimed；
     使用 PostgreSQL DB time、`FOR UPDATE SKIP LOCKED`、随机 token、短 transaction。
   - 实现 claim-token success/skip/retryable/terminal ACK、有界退避、retry exhausted、manual
     re-drive 和整轮 wall-clock budget；不得持锁执行 HTTP。

4. **来源 target 解析与确定性 renderer**
   - poller 从 event → dispatch → thread → identity → item/owner 加载受信 snapshot。
   - 实现 NULL source、missing/purge、disabled owner/identity、target mismatch、deleted item 等
     terminal skip；closed thread 仍允许通知原 conversation。
   - 实现四种固定中文模板和 bounded title sanitizer；禁止把 target/body/title/URL/异常写入
     log、ledger、diagnostics 或 task result。

5. **LangBot outbound transport**
   - 新增 Settings 和 `.env.example`：base URL、dedicated API key、timeout；校验 loopback
     HTTP/HTTPS，禁止 redirect。
   - 实现 bounded HTTP client；path/body 使用 DB target，HTTP/transport 异常映射固定 terminal/
     retryable codes，不记录 target/message/response/exception。
   - 更新 `integrations/langbot-4.10.6-redact-monitoring.patch`，脱敏 `send_message` endpoint 的
     traceback/exception response；扩展 fixed-wheel tests。

6. **复用 Beat + maintenance 注册 poller**
   - 注册无参数 `app.ingest.tasks.deliver_pending_ingest_notifications_task`，固定路由
     `maintenance`；返回安全 counters，不配置 Celery autoretry。
   - 增加 fail-closed `INGEST_NOTIFICATION_*` interval/batch/claim timeout/max duration/retry
     ceiling/backoff 配置。
   - 用新的 notification entry 替换 Beat 的 `publish-pending-ingest-completion-events` entry；
     现有 purge schedule 保持不变。
   - 测试单/双 Beat tick、并发 maintenance worker、task crash/stale claim、deadline/deferred 和
     peer isolation。

7. **停止无人消费的 completion queue 生产**
   - 删除 terminal completion 后的 request-local immediate publish 调用；completion event 仍在
     同一 terminal transaction 中创建。
   - 保留 legacy publisher schema/code 仅用于兼容回滚，但确保没有自动 schedule、请求内调用
     或新的生产流量；poller 完全忽略 `publish_state`。
   - 更新 producer queue tests，证明新终态不向 `ingest-completion` 发布；保留数据库 event
     原子性、唯一性、删除和隐私回归。
   - 文档定义先停旧 producer、确认 poller DB coverage、观察并安全清理既有 Redis backlog 的
     顺序，防止 poller/queue 双发。

8. **Docs/spec/deployment**
   - 更新 completion backend spec：PostgreSQL event 是 durable source，source-channel
     notification 由 periodic ledger poller 权威处理，broker publisher 为 legacy/disabled。
   - 更新 README、environment/deployment：现有单 Beat + `ingest,maintenance` worker、LangBot
     key/network、poller interval/heartbeat、delivery backlog、failed re-drive、旧 queue 退役、
     rollout/rollback、Telegram/微信私聊 E2E。
   - 保持 MCP readiness 和 ingestion truth 边界不变。

9. **Validation matrix**
   - Unit：Beat exact task/route/no args、配置 validation、四模板、title bounds、URL/auth/HTTP
     classification、no redirect、privacy sentinels、无 completion queue publish。
   - PostgreSQL：source thread atomic capture/replay、linked-channel retry、两个 poller claim
     disjoint rows、duplicate/stale/token race、next-attempt backoff、retry ceiling/re-drive、
     disabled/deleted/merge/restore/new-attempt。
   - Crash：send 前/后崩溃、ACK token 丢失、下一 tick recovery；明确 LangBot 无 idempotency 时
     send-accepted/ACK-not-committed 窗口允许重复。
   - MCP：no source target、no retroactive linked-channel notification。
   - Migration：model parity、single head、expected revision、upgrade/downgrade roundtrip。
   - LangBot：patch dry-run/apply/compile/API-key/send target/redaction tests 和 fake Telegram/微信
     outbound E2E；真实账号 E2E 留作部署验收并明确记录。
   - Ops：Beat outage 留下 eligible rows，恢复后一 tick 处理；heartbeat/backlog age 诊断不泄露
     target 且不阻断 MCP readiness。

10. **Subagent review and finish**
   - `trellis_implement` 实现后，`trellis_check` 对数据模型、poller races、source capture、
     queue retirement、privacy、LangBot patch、tests/docs 做 full-scope review并修复 P1/P2。
   - 运行 Python compile、focused/full pytest、可用时的 PostgreSQL tests、Alembic heads、Trellis
     validate、`git diff --check`；环境/并行失败逐项写入 `validation.md`。

## Rollback points

- Schema/source target 已上线但 poller schedule 未启用：安全，completion event 留在数据库；
  只有通知延迟，不影响 ingestion truth。
- LangBot API/key/network 未就绪：可以部署 schema/捕获 target，但先不启用 notification Beat
  entry；不得恢复向无人消费 queue 的生产来代替通知。
- 通知重复或泄露风险：禁用 notification Beat entry，保留 ledger/event/backlog 现场；
  `ingest` 和其他 `maintenance` task 继续。
- 旧 queue backlog 只在生产者已停止、数据库 event coverage 已验证且获得部署授权后处理；
  未确认前不得删除 Redis 数据。
- 常规代码回滚保留前向兼容 schema；未经明确授权不 downgrade 有生产 delivery 数据的
  migration，不同时启动 queue consumer 和 poller 发送同一 handler。

## Required review before start

确认首版复用现有 Celery Beat + `maintenance` worker 默认每 10 秒（可配置）轮询 PostgreSQL；
单轮 budget 小于调度周期且 outbound timeout 受 remaining budget 限制；不新增
独立 completion worker。poller 直接调用 LangBot 官方 API，只通知 Telegram/微信**原始私聊
会话**；MCP/CLI/no-target 事件安全跳过。旧 immediate/repair queue publish 停止，避免无人消费
积压和未来双发。
