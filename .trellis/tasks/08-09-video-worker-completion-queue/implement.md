# 执行计划：视频解析 Worker 完成队列

## 1. Baseline and failing tests

- [ ] 记录当前 Alembic head，确认只有一个 head，检查 worktree 中已有用户改动。
- [ ] 先为终态事件映射、重入幂等、即时 publish 失败、stale claim 恢复、
  duplicate publish 和隐私 payload 写失败测试。
- [ ] 用 fake DB 快速覆盖纯转移契约，用 PostgreSQL 集成测试覆盖 transaction、
  unique constraint、row lock 和 `SKIP LOCKED`。

## 2. Schema and migration

- [ ] 在 `app.models` 新增 `IngestCompletionEvent`，落地 design 中的 FK、unique、
  check constraint 和 pending/stale-claim 索引。
- [ ] 从 `e5f6a7b8c9d0` 创建 Alembic revision，upgrade 创建表/索引，downgrade
  只删除新表与它的索引/约束。
- [ ] 同步 `vercel.json.env.EXPECTED_DATABASE_REVISION`，保持单一 migration head。

## 3. Atomic event creation

- [ ] 抽取“终态 dispatch + completion event”原子写入 helper，保持现有
  task ID/row-lock/item-deleted guard。
- [ ] `_complete_dispatch()` 对 `ready / needs_extension / needs_asr` 创建 completed
  event，并返回 event ID；duplicate/illegal transition 返回 `None`。
- [ ] `_mark_dispatch_failed()`/`IngestTask.on_failure()` 只在最终失败时创建
  failed event，重复 hook 复用已有事件。
- [ ] 保持 transient retry 的 `running → enqueued` 不创建事件，保持
  item/dispatch 原有失败 code 和 ready 保护。

## 4. Queue publish contract

- [ ] 在 Celery 配置中显式声明 durable `ingest-completion` queue；通过
  `send_task("app.ingest.completion.consume", args=[event_id], queue="ingest-completion")`
  发布 persistent task envelope，payload 只有 completion event ID。
- [ ] 当前 app 不注册该 consumer task，不添加 no-op handler，不把现有 worker
  扩大为监听 `ingest-completion`；测试证明 producer 使用稳定 task name/队列。
- [ ] 复用/抽取当前有界 producer 配置，避免 shared producer/connection pool
  无界等待；消息必须 persistent 且显式 declare queue。
- [ ] 成功 publish 用 claim token 条件回写 `enqueued_at/publish_task_id`；超时或
  异常只释放 outbox claim，不改 item/dispatch 终态。
- [ ] 在 success 返回和 final failure hook 后做一次 best-effort 立即发布，
  严格隔离发布错误与 ingestion task result。

## 5. Maintenance repair sweep

- [ ] 实现有界 `IngestCompletionPublisher`/service：使用 DB time、`FOR UPDATE
  SKIP LOCKED`、随机 claim token、claim timeout、批次上限和逐项隔离。
- [ ] 实现 `publish_pending_ingest_completion_events_task`，路由到
  `maintenance`，只返回安全 counters。
- [ ] 在 beat 中增加补偿周期；周期、batch size、claim timeout 可配置且有
  安全默认值，配置表面写入 `.env.example`/Settings 校验。
- [ ] 证明并发 sweep 不同时 claim 同一行，超时 claim 可恢复，publish-after-
  ack-before-DB-update 可产生同 ID 重复消息。

## 6. Diagnostics and docs

- [ ] 通过现有 safe diagnostic logger 记录 create/enqueue/failure/sweep，仅包含
  allow-listed stage/outcome/internal ID/error code/counters/duration。
- [ ] 增加敏感哨兵测试，确认 URL、title、transcript、why_saved、identity、
  broker/provider exception message 不进 broker payload、task result 或 production log。
- [ ] 更新 `README.zh-CN.md`、`docs/deployment.md` 和
  `docs/environment-configuration.md`：queue topology、beat 补偿、参数、readiness/
  backlog、部署顺序和回滚。
- [ ] 文档明确：真实 consumer 出现前不让现有 worker 监听
  `ingest-completion`。

## 7. Validation

实现时按新增测试文件名补齐精确命令，至少执行：

```bash
.venv/bin/pytest -q tests/test_tasks.py tests/test_ingest_submission.py
.venv/bin/pytest -q tests/test_ingest_submission_postgres.py
.venv/bin/pytest -q tests/test_migration_roundtrip_postgres.py tests/test_deployment_health.py
.venv/bin/pytest -q tests/test_item_management_tools.py tests/test_multiuser_integration.py
.venv/bin/pytest -q
.venv/bin/alembic heads
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade e5f6a7b8c9d0
.venv/bin/alembic upgrade head
git diff --check
python3 ./.trellis/scripts/task.py validate 08-09-video-worker-completion-queue
```

PostgreSQL roundtrip 必须使用本地/隔离数据库，不对共享 Neon main 做 destructive
downgrade。

## 8. Review gates and rollback points

- [ ] 实现后先做独立 Trellis check，修复 P1/P2 后再更新 spec/提交。
- [ ] 若终态/outbox 不能同事务，停止实现，不用“先 commit 再尽量发送”
  降级掩盖丢事件窗口。
- [ ] 若 completion publish 改变 ingestion 成功/失败语义，立即回滚该调用点，
  保留 pending outbox 供修复后补发。
- [ ] 若出现重复风暴，停止 completion publisher/consumer 而非 ingestion worker；
  保留事件表审计。
- [ ] 代码回滚保留 forward-compatible schema，不做 destructive table drop。
