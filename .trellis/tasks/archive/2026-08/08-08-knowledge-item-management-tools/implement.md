# 知识库条目管理 Tools：实施计划

## 0. Start gate

- [x] 用户审批最终 planning summary 后才运行 `task.py start`。
- [ ] 确认 PostgreSQL 与 MinIO 有可恢复备份；记录当前 migration head、worker/gateway 启动方式。
- [x] 读取 `prd.md`、`design.md`、context manifests 和 backend specs；确认 worktree 无冲突性用户改动。

## 1. Schema, configuration and contracts

- [x] 新增 Alembic migration：`content_item.deleted_at`、`purge_claimed_at`、`purge_attempts`、
  `purge_error_code` 及 library/trash/purge partial indexes；同步 `app/models.py`。
- [x] migration upgrade 保证既有行普通可见；downgrade 明确只做 schema rollback，不自动 restore/purge。
- [x] Settings 增加 `AGENT_ITEM_MANAGEMENT_ENABLED`、默认 30 天 retention、purge interval/batch/claim timeout，
  严格正数/上限验证；更新 `.env.example`。
- [x] 在 `app/agent/types.py` 或新的 focused module 定义 `SavedItem`、page/cursor、batch operation 和
  management tool payload；禁止复用 Citation 或暴露内部字段。
- [x] 实现版本化 cursor codec、filter fingerprint、limit clamp 与 safe error mapping 的单元测试。

## 2. Tenant-scoped management service

- [x] 新增 `KnowledgeItemManagementService`，实现 library/trash keyset list、独立 detail 和公开 projection。
- [x] 实现 `update_why_saved`：只接受必填 string/null，trim/空串规范化、最大 500 字符、tenant + active
  predicate、相同值幂等。
- [x] 实现 delete-target all-or-nothing validation、soft delete 与 restore；batch 1..10、输入顺序稳定、
  row locks、数据库 `now()`、expiry/purge claim gate、safe cross-tenant not-found。
- [x] 为 list/detail/update/delete/restore 增加 unit 与 PostgreSQL 双 tenant、pagination、concurrency 测试。

## 3. Pending delete lifecycle

- [x] 泛化 `PendingConfirmationService` 的 snapshot/active lookup，使一个 thread 的 save/delete pending
  能原子互相替换，同时保持现有 save payload v1 兼容。
- [x] 增加 versioned delete payload、request/inspect/confirm/clarify/cancel；confirm 不接受 item IDs，只
  消费 tenant/thread/message-bound 持久化目标。
- [x] 更新 pending action runtime instructions 和 canonical outcomes；`/new` 通用 cancel 保持有效。
- [x] 测试 save↔delete replacement、10 分钟 TTL、重启恢复、yes/no/ambiguous、过期、跨 thread/tenant、
  corrupted payload、重复 message 和并发 confirm。

## 4. Agent management tools and routing

- [x] 扩展 runtime service factory，把 save services 与 item management availability 分开，并保留一个
  terminal `ActionOutcome` contract。
- [x] 注册 `list_saved_items`、`get_saved_item`、`update_saved_item`、`delete_saved_items`、
  `confirm_item_deletion`、`clarify_item_deletion`、`cancel_item_deletion`、`restore_saved_items`、
  `retry_item_ingestion`；schema 不含 trusted identifiers。
- [x] 为 list/detail/update/delete/restore/retry 编写应用生成的 bounded canonical 文案和 action results；
  management reads 不调用 search/Composer。
- [x] 更新 instructions，区分库存、回收站、内容问答、修改收藏原因、删除确认、恢复和 retry；模糊标题
  不直接触发副作用。
- [x] 修正 `UnexpectedModelBehavior` diagnostics 记录 exception class 的盲点，保持生产 message/body 脱敏。
- [x] 扩展 diagnostics tool/error/stage allow-list 和隐私 sentinel 测试。

## 5. Save auto-restore and explicit retry

- [x] 重构 `IngestSubmissionService` 的 row-lock/dispatch creation/publish helper，保留现有 batch/idempotency
  contract。
- [x] existing item 在回收期内时自动 restore；有新 `why_saved` 则更新、null 则保留；ready/active 不
  enqueue，failed restore 后创建下一 attempt；purge-in-progress 返回稳定结果。
- [x] 实现 `retry_item`：仅 tenant active `failed`、无 active dispatch；trusted request key、attempt+1、
  bounded publish、queue failure safe mapping 和 duplicate replay。
- [x] 测试 concurrent save/restore/purge、同 URL unique constraint、failed retry、所有 disallowed states、
  broker unavailable 与重复 delivery。

## 6. Deleted-content gates

- [x] vector search、BM25、search hydration、neighbors、retrieval get-item、open-at 全部加
  `deleted_at IS NULL`，并补双 tenant/soft-delete retrieval 回归。
- [x] worker claim、MinIO put 前和 final segment/ready 写入前检查 item 未进入 purge；soft-deleted item
  即使 worker 完成仍不可见。
- [x] purge selector 排除 pending/enqueued/running dispatch；active/stuck item defer 并产生安全计数。
- [x] 测试 soft delete 与正在运行/晚到 worker 的所有关键交错，不允许检索复活或 MinIO orphan。

## 7. Automatic purge

- [x] 为 `RawObjectStore` 增加幂等 delete；不存在对象视为成功，异常不泄漏 key/body。
- [x] 实现 expired-item claim：数据库 `now()`、keyset index、`FOR UPDATE SKIP LOCKED`、batch/elapsed-time
  bound、claim timeout、attempt/error safe state。
- [x] 实现单 item purge：delete object → 重新验证 claim/expiry → delete ContentItem → cascade children；
  crash window 可重试。
- [x] 注册 maintenance queue 的 `purge_expired_items_task` 与 Celery beat schedule；更新 worker/beat
  deployment and health instructions。
- [x] 测试 object success/not-found/failure、crash after object delete、stale claim、two sweepers、batch
  bound、cascade、active dispatch defer 和 retention config。

## 8. Persistence, compatibility and observability

- [x] 验证 management canonical outcome/action_results 被保存并由 duplicate channel message 重放；pending
  payload、模型 prose 和内部 fields 不进入 history/sources/logs。
- [x] 保持 `save_videos`/裸 URL 确认、`/new`、search/citation/composer、gateway single reply 回归通过。
- [x] 增加 purge/容量安全指标或 diagnostics：active/trash/expired counts、oldest trash、claim/completed/
  failed/deferred、batch duration；文档给出 DB/table/index size、dead tuples/autovacuum 查询。
- [x] 更新 README、deployment、migration/feature-flag rollout、beat/maintenance queue、备份、smoke 和
  rollback；强调关闭功能不能移除 deleted filters，不能直接 downgrade 让 trash 复活。

## 9. Validation commands

按实现阶段运行最小相关测试，再运行完整回归：

```bash
.venv/bin/python -m py_compile app/agent/*.py app/channels/*.py app/ingest/*.py
.venv/bin/pytest -q tests/test_agent_runtime.py tests/test_agent_actions.py
.venv/bin/pytest -q tests/test_knowledge_services.py tests/test_diagnostics.py
.venv/bin/pytest -q tests/test_pending_confirmation_postgres.py
.venv/bin/pytest -q tests/test_ingest_submission.py tests/test_ingest_submission_postgres.py tests/test_tasks.py
.venv/bin/pytest -q tests/test_multiuser_integration.py
.venv/bin/pytest -q
```

在 disposable PostgreSQL/MinIO 环境验证：

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
docker compose exec -T postgres psql -U postgres -d kb -c '\\d+ content_item'
```

人工 channel smoke：

1. “我存了什么视频”返回 inventory list，无 embedding/search；
2. 修改/清空收藏原因；
3. 请求删除两个 item → 含糊/取消不删 → 再请求并确认进入 trash；
4. 列 trash、恢复一个、明确重存另一个 URL 自动恢复；
5. failed item retry，ready/no_text retry 被拒；
6. 缩短 disposable retention，运行 purge，确认 MinIO object + item/segments/dispatch 清理且普通检索无复活。

## 10. Review and rollback gates

- [x] Implementation review：tenant predicates、cursor/batch bounds、pending target trust、worker/purge races、
  privacy、migration/rollout 顺序逐项对照 PRD AC。
- [ ] Rollback rehearsal：关闭 management flag + beat 后，save/search 仍工作且 trash 仍隐藏。
- [x] 不对含 soft-deleted rows 的环境执行删除 columns 的 downgrade；需要 schema downgrade 时先由用户明确
  选择 restore 或 purge，并完成备份。
- [x] `trellis-check` 与必要 spec update 已完成。
- [x] commit 与 finish-work 完成后归档任务。

## 11. Final validation record

- Local PostgreSQL upgraded from `c7e8a91b2d34` to `d4e5f6a7b8c9` and remains
  at the new head.
- Real PostgreSQL + HTTP integration subset: `26 passed`.
- Full suite outside the socket-restricted sandbox: `228 passed, 1 skipped`.
- Focused offline management/action/multiuser suite: `52 passed, 13 skipped`
  before the external PostgreSQL run; compilation and `git diff --check` pass.
- Independent reviewer round 7: clean, no code release blocker in scope.
- A live downgrade/upgrade rehearsal was intentionally not run against the
  shared development database because downgrade drops lifecycle columns. Run
  it only in a disposable database after confirming there are no trash rows.
- Real MinIO slow-connect/slow-response fault injection remains a deployment
  smoke item; offline adapter timeout, retry, fail-safe, and claim-recovery
  coverage passes.
