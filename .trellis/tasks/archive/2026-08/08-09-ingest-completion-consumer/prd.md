# 定时轮询视频解析完成事件并通知来源 Channel

## Goal

复用现有 Celery Beat 与监听 `maintenance` 的 worker，定时从 PostgreSQL 轮询视频解析完成事件。
当一次视频保存或 ingestion retry 来自受信 Telegram/微信私聊时，poller 主动向**发起该次
请求的原始 bot + conversation**发送确定性通知，并通过持久化 delivery ledger 处理重复
tick、失败重试、进程崩溃和删除/身份竞态。

本任务仍实现“完成事件消费”的业务效果，但消费源是 PostgreSQL durable event，而不是
`ingest-completion` Redis 队列；不新增独立 completion worker。

## Confirmed facts

- `IngestCompletionEvent` 已与 dispatch 终态在同一事务中写入，是不丢事件的数据库真相。
- 现有周期入口是 Celery Beat，不是 OS cron。当前 completion publisher repair 的旧 schedule
  默认 60 秒；本任务用默认 10 秒的 notification schedule 替换它。部署已有一个监听
  `ingest,maintenance` 的 worker。
- 现有 `publish_state`/claim 只表示 event ID 是否成功发布到 Redis，不表示用户已收到通知，
  不能复用为通知 ACK。
- `ChannelService` 已持久化精确 `ConversationThread`，其中包含 source
  `channel_identity_id`、normalized channel、LangBot bot UUID (`account_id`) 和原始
  `external_conversation_id`。
- 当前 bridge 只拦截 `PersonMessageReceived`，所以本轮来源通知只覆盖 Telegram/微信私聊；
  不猜测 group target type。
- LangBot 4.10.6 官方提供 API-key 保护的
  `POST /api/v1/platform/bots/<bot_uuid>/send_message`。Telegram 使用原 chat/topic ID，
  OpenClaw 微信使用原 wxid。
- `request_key` 是 opaque idempotency key；channel 和 MCP 格式不同，绝不能解析它来路由。
- MCP/CLI 或没有受支持 source thread 的 ingestion 没有主动通知目标，poller 应安全
  `skipped_no_channel`，不能改发到之后绑定的任一 channel。

## Requirements

### R1 — 在 admission transaction 中固化来源会话

- `IngestDispatch` 增加 nullable `source_thread_id`，引用本次 save/retry 的原始
  `ConversationThread`；dispatch 创建后不得改写该目标。
- `AgentActionRuntime` 只能从 server-owned `AgentRequest.thread_db_id` 传递 target，
  target 不能成为模型/tool 参数，也不能进入模型历史或 action result。
- `IngestSubmissionService` 在创建 dispatch 的同一 transaction 内验证 thread、tenant、
  channel identity 和 channel。只有当前受支持的 `telegram`/`wechat` 私聊保存
  `source_thread_id`；MCP/CLI/unsupported channel 固定为 NULL。
- 直接 save、确认 save 和 retry 都必须携带本次请求来源。确认链路使用
  `PendingChannelAction.thread_id` 所指的原始 thread；不得从 confirmation 文本、
  `request_key` 或最新 linked identity 反推。
- 同一 request replay 返回原 dispatch/target；从已绑定的第二 channel 发起新 retry 时，
  新 dispatch 通知第二 channel，不改写旧 dispatch target。

### R2 — 复用现有 Beat + maintenance 做权威 poller

- 注册无业务参数的 bounded periodic task
  `app.ingest.tasks.deliver_pending_ingest_notifications_task`，固定路由到现有
  `maintenance` queue；由 Celery Beat 按正整数
  `INGEST_NOTIFICATION_INTERVAL_SECONDS` 调度，默认 10 秒。
- Beat 只负责调度；PostgreSQL 扫描、claim、LangBot HTTP 和 ACK 全部在 maintenance worker
  执行。不得在 Beat 进程内直接访问平台。
- task 按稳定顺序、小批量和小于 10 秒周期的整轮 wall-clock budget 扫描；每次 outbound
  timeout 还要受当前剩余 budget 限制，防止慢请求让 periodic task 持续堆积。并发 tick 使用
  `FOR UPDATE SKIP LOCKED`、DB time、claim token 和 stale timeout，不能依赖单实例 Beat
  作为幂等锁。
- 单个事件失败不得阻断同批其他事件；task 只返回安全数字 counters。
- 不新增监听 `ingest-completion` 的独立 worker，不注册
  `app.ingest.completion.consume` 作为来源通知路径。

### R3 — 持久化通知 delivery、退避与幂等

- 新增独立 `ingest_completion_delivery`，以
  `UNIQUE(event_id, handler_key)` 为幂等根，首个 handler key 固定
  `source-channel.notification.v1`。
- ledger 记录 `claimed / succeeded / failed`、claim token/DB time、attempt、
  `next_attempt_at`、稳定错误码、disposition 和 completed time；不得复用 producer
  `publish_state`。
- poller 从 event 表选择未创建 delivery 的事件，或重领 stale `claimed` / 到达
  `next_attempt_at` 的 `failed` delivery。已成功不再发送，新鲜 claim 不抢占，迟到 worker
  不能 ACK 新 claim。
- retryable failure 用有界指数退避写回 ledger，由后续 Beat tick 重试；超过 attempt ceiling
  保持 `failed` 等待显式 re-drive。不得依赖 Celery autoretry 恢复一批中的部分工作。
- 正常 duplicate tick 不重复发消息。LangBot 官方接口没有 downstream idempotency key，因此
  “平台已接受、ledger 尚未成功”崩溃窗口仍是明确的 at-least-once 重复窗口，不宣称
  exactly-once。

### R4 — 按终态发送确定性消息

- poller 从 PostgreSQL join event → dispatch → source thread → channel identity → item/owner；
  只使用受信数据库字段，不接受 task payload target。
- 使用 event 的不可变 `outcome + item_state + error_code` 快照渲染固定中文模板：
  - `ready`：已解析并加入知识库，可开始提问；
  - `needs_extension`：已保存，但需要扩展补充文本后才能检索；
  - `needs_asr`：已保存，但需要语音识别后才能检索；
  - `failed`：解析失败，可稍后重试。
- 可以在目标会话中加入经过控制字符清理、空白归一和长度上限处理的 title；title/URL
  不进入 task result、diagnostics、ledger 或日志。无安全 title 时使用固定“你提交的视频”。
- 每个 dispatch/event 独立通知；不把批量保存的多个事件错误合并或路由到最近 conversation。

### R5 — LangBot outbound transport

- maintenance worker 通过 LangBot 官方 API 发送，path 中 bot UUID 来自持久化 source thread，
  body 固定为 `target_type=person`、原始 conversation ID 和一个 Plain message chain。
- 新增 `LANGBOT_OUTBOUND_BASE_URL`、`LANGBOT_OUTBOUND_API_KEY` 和 bounded timeout 配置。
  HTTP 只允许 loopback；跨主机必须是 HTTPS。禁止跟随重定向，API key 永不记录。
- 401/403、400、bot/target not found 等配置/目标错误稳定分类；429、5xx、timeout 和连接错误
  是 retryable transport failure。响应 body、adapter exception 和 URL 不进入 ledger/log。
- 更新现有 LangBot 4.10.6 patch，使 `send_message` controller 不再打印 traceback 或返回
  `str(exception)`；只返回固定安全失败分类，并在 fixed-wheel 测试中验证。

### R6 — 删除、身份和迟到事件

- send 前重新验证 thread 的 identity tuple、identity/owner 未 disabled、thread/item tenant
  一致、item 未 soft-delete/purge-claimed；不得按 tenant 选择“最新 channel”。
- missing/purged event、NULL/unsupported source、disabled identity/owner、已删除 item 都记录
  固定 skip disposition 并成功完成 delivery，不发送、不重建 target。
- `ConversationThread.closed_at` 只表示 Agent 历史已重置，不改变外部 conversation address；
  只要 identity/item 仍有效，仍通知原始会话。
- tenant merge 的存活 item 保留原始 source thread；被删除的 duplicate event 安全 missing。
  restore/resave/new retry 创建新 dispatch/event/delivery，不复用旧通知。

### R7 — 退役无消费者的 completion broker 路径

- poller 上线时，来源通知以数据库 poller 为唯一 owner。停止 ingestion terminal hook 的
  immediate completion publish，并移除 `publish-pending-ingest-completion-events` Beat schedule，
  防止无人消费的 durable Redis queue 无限增长。
- 保留 `IngestCompletionEvent` 作为 durable terminal event；poller 不依赖或改写历史
  `publish_state`。已有 `pending/claimed/enqueued` 行都按 delivery ledger 独立处理。
- migration/部署文档必须定义旧 worker 停止顺序和 `ingest-completion` backlog 清理步骤；
  只有在确认数据库事件可由 poller 覆盖且生产者已停止后，才清理冗余 broker envelope。
- 未来如重新引入 queue subscriber，必须使用不同 handler ownership，或与 poller 共用同一
  ledger claim；不得同时让两个路径发送 `source-channel.notification.v1`。

### R8 — 隐私、可观测性和运维恢复

- diagnostics 只包含内部 event ID、固定 handler/result/disposition、attempt、duration、
  backlog age 和稳定 error code；不含 bot UUID、conversation/user ID、title、URL、字幕、
  凭据或 exception text。
- task result 只返回 `claimed/succeeded/skipped/failed/deferred/duration_ms` 数字 counters，
  不回显消息或 target。
- 增加安全的最近 poller 成功时间/最老 eligible backlog age 观测；Beat 故障不会丢事件，
  恢复后下一 tick 继续处理。通知可用性不并入现有 MCP/read readiness。
- 运维修复 LangBot/网络/config 后可显式 re-drive failed delivery，不得通过重跑 ingestion
  恢复通知。

### R9 — migration、部署和兼容

- migration 从实现时的唯一 Alembic head 派生，并同步
  `vercel.json.env.EXPECTED_DATABASE_REVISION`；model/migration 约束与 FK 行为一致。
- 文档补充现有 Beat + maintenance worker、LangBot API key/network restriction、poller interval、
  delivery backlog、failed ledger、manual re-drive、旧 queue 退役、上线顺序和回滚。
- LangBot outbound 不并入现有 MCP mutation readiness；channel notification 故障不得阻断
  MCP/read-only 或 ingestion 提交。

## Out of scope

- Telegram/微信 group、Slack 或其他 channel 的主动通知；当前 bridge 只支持私聊事件。
- MCP webhook/callback、CLI 通知或把通知转发到同 tenant 的另一 linked channel。
- ASR、浏览器扩展 workflow 的具体启动；本轮只通知对应 action-required 状态。
- 修改字幕抓取、chunking、embedding、retrieval 或 source ingestion truth。
- exactly-once platform delivery。正常 duplicate 会被 ledger 抑制，但平台 ACK/ledger commit
  崩溃窗口允许一条重复通知。
- 新增 OS cron、APScheduler 或 dedicated completion worker。

## Acceptance Criteria

- [ ] AC1：direct save、confirmed save 和 retry 的新 dispatch 在同 transaction 内持久化正确
  source thread；request replay 不改 target，linked second-channel retry 使用新来源。
- [ ] AC2：MCP/CLI/unsupported channel dispatch 没有 target，poller 为
  `skipped_no_channel`，不会通知后来绑定的 Telegram/微信。
- [ ] AC3：Beat 注册无参数 periodic task 并固定路由 `maintenance`；正整数 interval、batch、
  stale timeout、retry ceiling/backoff 和 wall-clock budget 都有 fail-closed 配置校验。
- [ ] AC4：四种 event snapshot 分别向原 bot UUID + 原 conversation ID 发送正确固定模板，
  Telegram topic/微信 wxid 不被变形。
- [ ] AC5：delivery ledger 的唯一键、check constraints、FK cascade/SET NULL、claim/backoff index、
  model/migration 和 hosted revision 完全一致。
- [ ] AC6：两个并发 tick、顺序 duplicate、fresh/stale claim、next-attempt backoff、retry ceiling、
  claim-token race 和 manual re-drive 行为符合合同。
- [ ] AC7：missing/purge、soft-delete、disabled owner/identity、closed thread、tenant merge、
  restore/new attempt 和 target mismatch 全部安全处理。
- [ ] AC8：HTTP client 使用 API key、bounded timeout、loopback/HTTPS 限制和安全状态分类；
  LangBot patch 不记录 traceback/exception text，fixed-wheel check 通过。
- [ ] AC9：task/diagnostics/log/ledger 中没有 bot UUID、conversation/user ID、title、URL、字幕、
  API key 或原始异常；title 仅可出现在发给已验证来源 conversation 的 bounded body。
- [ ] AC10：旧 immediate publish 和 completion publisher Beat entry 已停止；测试证明不会继续向
  无消费者的 `ingest-completion` queue 生产，文档包含安全 backlog 清理和防双发步骤。
- [ ] AC11：部署文档只要求现有单 Beat + `ingest,maintenance` worker，并包含 poller heartbeat、
  backlog/failed ledger、re-drive/rollback；现有 MCP readiness 边界保持不变。
- [ ] AC12：focused/unit/PostgreSQL/migration/LangBot patch 回归、单一 Alembic head、Python
  compile、Trellis validation 和 `git diff --check` 全部通过；环境限制需准确记录。

## Reviewed scope decision

首版选择数据库 poller，而不是 `ingest-completion` 队列 worker：可靠性来自同事务 completion
event + notification delivery ledger，失败由后续 Beat tick 恢复。这样复用现有进程拓扑，正常
通知最多延迟默认 10 秒。transport 直接调用 LangBot 4.10.6 官方 `send_message` API，只通知
Telegram/微信原始私聊会话；MCP/CLI/no-target 安全跳过。

## Notes

- Parent task: `08-04-video-text-kb`.
- Producer task: archived `08-09-video-worker-completion-queue`; its durable DB event is retained,
  while its now-redundant Redis publication path is retired by this task.
- Research: `research/current-consumer-boundary.md`,
  `research/source-channel-outbound-notification.md`, and
  `research/periodic-notification-poller.md`.
