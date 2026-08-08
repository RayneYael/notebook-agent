# 视频解析 Worker 完成队列：技术设计

## 1. Design boundary

本任务只建立“dispatch 终态 → 可靠完成事件队列”边界。不改解析算法，
不让 channel/Agent 请求等待 worker，也不在本任务中决定完成事件最终
生成哪种用户通知。

核心不变量：

1. 业务真相先写 PostgreSQL，broker 不是 dispatch/item 状态的真相源。
2. 事件不丢、可重复；不声称跨 DB/broker exactly-once。
3. broker 上只出现内部事件 ID，不出现私密内容或 tenant/channel identity。
4. 完成事件发布故障不改写已经确立的 ingestion 结果。

## 2. Event semantics

一个 `IngestDispatch` attempt 对应最多一个稳定完成事件：

| dispatch 终态 | item 快照 | event outcome | 含义 |
| --- | --- | --- | --- |
| `completed` | `ready` | `completed` | 字幕、切分、embedding 全部完成 |
| `completed` | `needs_extension` | `completed` | worker 正常结束，需扩展补文本 |
| `completed` | `needs_asr` | `completed` | worker 正常结束，需用户显式启动 ASR |
| `failed` | `failed` | `failed` | 最终失败，仅有稳定 `error_code` |

`running → enqueued` 重试释放和重复 delivery 的 `duplicate` 不是终态。

## 3. Persistent outbox model

新增 `ingest_completion_event`：

```text
id                 bigint primary key
public_id          text unique not null
dispatch_id        bigint unique not null -> ingest_dispatch(id) on delete cascade
item_id            bigint not null -> content_item(id) on delete cascade
outcome            text not null  # completed | failed
item_state         text not null  # terminal snapshot
error_code         text nullable  # stable code only
publish_state      text not null  # pending | claimed | enqueued
claim_token        text nullable
claimed_at         timestamptz nullable
publish_task_id    text nullable
enqueued_at        timestamptz nullable
created_at         timestamptz not null
updated_at         timestamptz not null
```

约束：

- `UNIQUE(dispatch_id)` 是 source idempotency 根。
- `outcome`/`publish_state` 使用 check constraint，不新增 PostgreSQL enum，避免为队列
  内部状态扩大现有 `ingest_state` enum。
- `outcome='completed'` 时 `error_code IS NULL`；`outcome='failed'` 时允许已有稳定
  error code。
- pending/stale-claimed 索引支持有界 sweep；`dispatch_id` 唯一索引支持重复
  failure hook 收敛。
- item 被最终物理 purge 时级联删除事件；队列中的迟到消息由下游将
  “事件已不存在”当作幂等 no-op。

Alembic revision 必须从当前单一 head `e5f6a7b8c9d0` 派生，并在同一改动
中更新 `vercel.json.env.EXPECTED_DATABASE_REVISION`。

## 4. Atomic terminal transition

把终态写入收敛为返回事件 ID 的条件转移：

```python
event_id = _complete_dispatch(..., process_state=state)
event_id = _mark_dispatch_failed(...)
```

在持有 dispatch row lock 的同一 transaction 中：

1. 验证 `running + task_id`；
2. 写 dispatch/item 终态；
3. insert-or-read 该 dispatch 的 `IngestCompletionEvent`；
4. commit 一次。

非法转移、duplicate delivery 或被别的 task ID 持有的 dispatch 返回 `None`，
不创建事件。failure hook 重入时，若 dispatch 已是对应终态，返回已有
event ID，不改写事件快照。

## 5. Publish path

队列常量：

```text
queue: ingest-completion
task:  app.ingest.completion.consume
args:  [completion_event_id]
delivery: persistent
```

`publish_ingest_completion_event(event_id)` 复用当前 request-local Kombu producer 和有界
publish options，通过 Celery `send_task()` 按稳定 task name 发布，并显式指定
`queue='ingest-completion'`。队列在 Celery 配置中显式声明为 durable，消息
使用 persistent delivery。成功 publish 后再做条件 `claimed → enqueued`，
记录 Celery task ID 和 DB time。

本任务**不在当前 Celery app 注册** `app.ingest.completion.consume`的处理
函数，也不让现有 worker 监听该队列。Celery 允许 producer 按名字发布
尚未在本进程注册的 task；只要没有 worker 监听，消息会保留在 durable queue。
后续真实 consumer 必须注册完全相同的 task name，实现业务副作并以 event ID
幂等。不得为了让 task “看起来已注册”而增加 no-op handler，否则误启
该 queue 的 worker 会 ack 并丢掉事件。

## 6. Immediate publish and repair sweep

正常路径在终态 transaction commit 后：

```text
create pending outbox -> bounded immediate publish -> mark enqueued
```

即时 publish 的任何异常都被投影为安全计数，不改变 worker 的成功/失败
结果。补偿任务 `publish_pending_ingest_completion_events_task` 运行在
`maintenance` queue，由 beat 定时调度：

1. 选取 `pending` 或超时 `claimed` 的有界批次，`FOR UPDATE SKIP LOCKED`；
2. 写随机 `claim_token`/DB `claimed_at`后提交，不持有 DB transaction 跨 broker I/O；
3. 逐项 publish，一项失败不阻塞 peers；
4. 用 claim token 条件标记 `enqueued`，失败项释放为 pending；
5. 返回/log 只有 `claimed/enqueued/failed/deferred/duration_ms` 等安全数值。

如果在第 3 步成功后、第 4 步前崩溃，claim timeout 会让事件再次发布，
这是设计中的 at-least-once 重复窗口。

## 7. Consumer contract

未来消费者必须：

- 只接受 `completion_event_id`，再从受信 DB 加载 event/dispatch/item；
- 以 event `public_id` 或内部 ID 作唯一幂等键；
- 对事件/item 已被 purge、item 已软删除、已消费返回安全 no-op；
- 根据 `outcome + item_state` 分流，不把 `dispatch.completed` 等同于 `ready`；
- 重试自身业务副作时不改写 source dispatch/item 真相。

## 8. Observability and deployment

新增安全 diagnostics：

- `completion_event_created`
- `completion_event_enqueued`
- `completion_event_publish_failed`
- `completion_event_sweep`

日志不使用 `str(exception)`。部署验收需要：

- migration head/expected revision 一致；
- Redis 可用，ingest worker 监听 `ingest,maintenance`，beat 唯一；
- `ingest-completion` 队列已声明且可观察 backlog；
- 没有真实 consumer 前，不启动监听该队列的 no-op worker。

## 9. Rollout and rollback

上线顺序：migration → 带 outbox/sweep 的 worker + beat → 验证 backlog/补发 →
将来的真实 consumer。旧 gateway 不读新表，因此向前兼容。

代码回滚时保留新表/列，停止 completion publisher/sweep 即可；不删除已有
pending 事件。恢复新代码后由 sweep 补发。如果发现无界重复，只暂停
`ingest-completion` publish/consumer，不停 ingestion 真相写入。
