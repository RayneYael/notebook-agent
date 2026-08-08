# 增加视频解析 Worker 完成队列

## Goal

当视频 ingestion worker 完成一个持久化 `IngestDispatch` 后，向独立的
`ingest-completion` 队列可靠发布一个可幂等消费的完成事件，供后续通知、
工作流编排或运维处理使用，不让渠道请求同步等待解析结果。

## Confirmed facts

- 当前只有 `ingest` 和 `maintenance` 两个 Celery 队列；`fetch_text_task`
  只收取内部 `dispatch_id`。
- `IngestDispatch` 已持久化 `pending / enqueued / running / completed / failed`
  状态，但 worker 把它写成终态后没有独立的完成事件出口。
- `dispatch.state='completed'` 表示 worker 正常结束，不等同于内容一定
  `ready`；它也可能对应 `needs_extension` 或 `needs_asr`。
- 当前最终失败由 `_mark_dispatch_failed()` 持久化，重试中的
  `running → enqueued` 不是终态。
- 在“提交 dispatch 终态”和“发布 broker 消息”之间直接双写会有崩溃
  窗口，只用 Celery callback 或 result backend 无法提供业务上的不丢事件保证。

## Requirements

### R1 — 独立完成队列与事件语义

- 新增独立、持久化的 `ingest-completion` 队列，不与 `ingest` 或
  `maintenance` 混用；解析 worker 不得被后续通知消费阻塞。
- 每个 dispatch attempt 最多创建一个完成事件。正常结束发布
  `outcome=completed`，最终失败发布 `outcome=failed`。
- 事件必须快照 `item_state`，使消费者能区分 `ready`、`needs_extension`、
  `needs_asr` 和 `failed`；失败时只保留稳定 `error_code`。
- 重试释放、重复 Celery delivery 的 `duplicate` 结果、仍在运行的 dispatch
  不产生完成事件。

### R2 — 不丢失的持久化出站事件

- dispatch 终态和完成 outbox 事件必须在同一数据库事务中提交；
  `UNIQUE(dispatch_id)` 保证重复 failure hook/delivery 只复用同一事件。
- 终态提交后立即做一次有界 broker publish。发布失败不得把已完成
  的 `ContentItem`/dispatch 倒退成失败，outbox 保持可重试。
- `maintenance` 定时扫描必须补发 pending 事件并回收超时 claim，以修复
  worker 在 DB commit 后、broker publish 前崩溃的窗口。
- 交付语义为 **at-least-once**；如果进程在 broker 接收后、回写
  `enqueued_at` 前崩溃，允许重复消息。事件的稳定 ID 是消费者幂等键。
- 单个事件的 broker/DB 故障不得阻塞同批其他事件，扫描和发布
  必须有批次上限、claim timeout 和有界超时。

### R3 — 隐私和队列边界

- broker message 只包含内部完成事件 ID；不携带 URL、title、字幕、
  segment、vector、`why_saved`、外部渠道身份、tenant ID、secret 或异常消息。
- 只有受信内部消费者才能用事件 ID 查询数据库；消费者仍需执行
  tenant 边界和删除状态检查。
- 运行日志只记录固定 stage/outcome、内部 ID、安全 error code、批次
  counter 和 duration；不序列化 broker/provider 异常文本。

### R4 — 部署和兼容

- 现有 worker 继续监听 `ingest,maintenance`；只有明确实现完成事件业务
  的后续 worker 才监听 `ingest-completion`，避免空消费者提前取走消息。
- 部署文档必须说明 beat/maintenance 是不丢事件保证的一部分，并给出
  queue readiness/backlog 检查。
- 不改变已有 `save_videos` 立即返回 `queued`、ingestion retry、知识检索、
  recycle-bin 和渠道 exactly-one reply 行为。

## Out of scope

- 不在本任务中实现微信/Telegram 的“解析完成”主动回复。
- 不把完成队列当作 exactly-once 消息系统；不为每个下游消费者实现
  独立 subscription/progress 表。
- 不改变字幕抓取、chunking、embedding 算法或增加新 connector。
- 不暴露对外 webhook/SSE API；不把 Celery result backend 作为业务完成状态。

## Acceptance Criteria

- [x] AC1：`ready`、`needs_extension`、`needs_asr` 会分别产生一个
  `outcome=completed` 事件；最终 ingestion 失败产生一个
  `outcome=failed` 事件，且只携带稳定 error code。
- [x] AC2：dispatch 终态与 outbox 事件同事务提交；模拟事务失败时
  两者均不提交，重复 delivery/failure hook 只有一行事件。
- [x] AC3：成功路径把任务发布到 `ingest-completion`，且 broker payload
  只有内部事件 ID；发布后记录 `enqueued_at/task_id`。
- [x] AC4：模拟 DB commit 后立即发布失败或 worker crash，dispatch/item 保持
  真实终态，outbox 保持 pending；下一次 maintenance sweep 会补发。
- [x] AC5：模拟 broker 已收到但未回写状态的崩溃，允许收到两个具有
  同一事件 ID 的消息；幂等 fake consumer 只产生一次业务效果。
- [x] AC6：retry release、duplicate delivery 和未进入终态的 dispatch 不产生
  完成事件；单个发布故障不影响 peer 事件。
- [x] AC7：migration 只有一个 Alembic head，`vercel.json` 的 expected revision
  同步更新，PostgreSQL migration roundtrip 通过。
- [x] AC8：单测、PostgreSQL 并发/恢复测试、Celery routing/payload 测试、现有
  ingestion/submission/management/channel 回归和 `git diff --check` 全部通过。
- [x] AC9：部署文档列出 `ingest-completion` 的启动边界、beat 补偿依赖、
  active queue/backlog 检查和安全回滚方式。

## Reviewed completion semantics

用户已确认把“worker 处理完成”定义为 dispatch 进入任一终态，因此成功、
需扩展/需 ASR 和最终失败都会进队，下游通过 `outcome + item_state`
区分。如果产品只需要 `ready` 成功事件，应在任务启动前收窄 R1/AC1。

## Notes

- Parent task: `08-04-video-text-kb`.
- Implementation and independent review completed on 2026-08-09; detailed evidence is in `validation.md`.
