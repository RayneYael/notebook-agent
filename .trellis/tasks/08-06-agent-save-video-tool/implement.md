# 实施计划

## Dependency gate

- [ ] 先完成并提交/归档 `08-06-agent-retrieval-live-path`，因为它与本任务共同修改 Agent runtime、
  ChannelService、turn persistence 和部署文档；不得在未收敛 dirty diff 上并行实现。
- [ ] 确认当前 migration head、worker/gateway 启动方式和 Redis/MinIO/PostgreSQL readiness。
- [ ] 保存全部已有 dirty path 清单，禁止覆盖用户改动或兄弟任务的 LangBot patch。

## 1. Fail-first contracts

- [ ] fake model：明确保存意图调用 `save_videos`；纯 URL 调 confirmation tool；链接内容问题不调用
  write tool；肯定/否定确认分别 confirm/cancel。
- [ ] 证明当前 `search_required` guard 会拒绝 clarification/action outcome，且空 citations 的 duplicate
  turn 会被错误重建为 `not_found`，作为 action contract 修复前的回归证据。
- [ ] batch 前置测试：0/1/10/11 URLs、同批重复 URL、invalid/unsupported、输入顺序和无 side effect。
- [ ] tenant 测试：tool schema 不含 `user_id`，用户 57 submission 不能写入/读取用户 1。

## 2. Persistence and migration

- [ ] 新增 `pending_channel_action` model/migration，包含 versioned payload、10 分钟 expiry、
  consumed/cancelled state 和每 thread 单 active partial unique index。
- [ ] 新增 `ingest_dispatch` model/migration，定义 request key、attempt、task ID、state 和安全 error code；
  约束同 item 最多一个 active dispatch。
- [ ] 为 `ConversationTurn` 增加 `answer_status`、`error_code`、`action_results`，对现有 rows 做无损
  backfill；旧 knowledge turn 仍可恢复。
- [ ] migration upgrade/downgrade 在隔离数据库验证；downgrade 仅验证 schema mechanics，生产 rollback
  不自动删除 action/dispatch 数据。

## 3. Item normalization and submission service

- [ ] 提取 connector registry/item URL normalizer，产生 `ItemReference`；解析阶段无远端网络调用。
- [ ] 实现 `IngestSubmissionService.submit_urls(tenant, urls, why_saved, request_key)`；在任何写入前
  校验 batch `1..10`，模型不能提供 tenant/request key。
- [ ] 使用 per-item savepoint + unique constraint/row lock 收敛并发；逐项返回 ordered safe result。
- [ ] 新 item 写 minimal `pending` ContentItem + durable dispatch；active/ready item 返回
  `already_exists`，不 enqueue。
- [ ] broker publish 使用 bounded timeout；成功 conditional transition，失败记录
  `queue_unavailable`，不把 exception message 返回 Agent/日志。
- [ ] 相同 request key、重复 tool call、bridge redelivery 和并发 submit 返回相同 result，最多一个
  active dispatch。

## 4. Worker refactor

- [ ] 把 `fetch_meta()` 从 `create_item()`/channel submission 移入 worker，worker 更新 item metadata
  后继续复用 transcript/MinIO/chunk/embed/Segment pipeline。
- [ ] worker 原子 claim dispatch；重复 Celery delivery 对 running/completed no-op，不能重复删除/写入
  segments 或重复推进状态。
- [ ] final success/failure 同步更新 item + dispatch；retry 继续使用现有 transient backoff 上限。
- [ ] worker composition 使用 shared embedding config 和 trusted CA，验证 certificate/hostname 开启；
  不打印 URL content、字幕、vector、credential 或 provider payload。
- [ ] 保持 CLI ingestion 兼容；CLI 同步行为是否保留不影响 channel async contract。

## 5. Pending confirmation service

- [ ] 实现 request/replace、confirm、cancel、expire；所有操作按 trusted thread/tenant 查询并使用 DB
  time/row lock。
- [ ] bare 1 URL 返回固定 confirmation；2–10 URLs 返回准确数量；新 batch 整体替换旧 batch。
- [ ] confirm 无 URL 参数，原子消费 server-stored batch；同 message ID 重放幂等，迟到/跨 thread
  confirm 无 ingestion side effect。
- [ ] `/new` 取消旧 thread active pending；gateway/LangBot restart 后未过期 pending 可恢复。

## 6. Agent action tools and validation

- [ ] 注册 `request_save_confirmation`、`save_videos`、`confirm_video_save`、`cancel_video_save`；tool
  schema 不出现 user/thread/message/task identifiers。
- [ ] 将 trusted request context 和 submission/pending services 放入 AgentDeps；核对 `save_videos`
  URLs 必须来自当前 user message，confirm 只读 server pending payload。
- [ ] 增加 action outcome branch：confirmation/accepted/partial/failed/too-large/cancelled/missing/expired。
- [ ] action summary 要求 `[A<n>]` allow-list 且覆盖全部 tool results；应用追加 canonical ordered result
  list。marker mismatch 内部 retry，不重复执行副作用。
- [ ] 保持知识分支 `[S<n>]` citation、fresh-search repair 和 `search_required`；无 action evidence 的
  无来源知识草稿仍 fail closed。
- [ ] 混合“保存并总结未入库视频”只报告 submission，并提示 ready 后查询；不使用模型记忆补答。

## 7. Channel persistence and replay

- [ ] `ChannelService` 保存 answer status/error/action results；`_answer_from_turn()` 按原 contract 重建，
  不再通过 empty citations 推断所有结果为 `not_found`。
- [ ] failed/partial action 的持久化策略与 duplicate reply 保持 exactly-one；同 message ID replay 不再
  调 Agent、submission 或 broker。
- [ ] diagnostics 只记录 internal request/tenant/item/dispatch IDs、stage、safe code 和 duration；不记录
  message text、URL、external identity、why_saved、task payload 或 exception text。
- [ ] Telegram/WeChat 并发、HMAC request ID、deterministic commands 和 `/link` 语义不变。

## 8. Automated validation

- [ ] unit：intent/tool schema、URL normalization、batch cap、result mapping、marker validation、CA。
- [ ] PostgreSQL：pending expiry/replace/consume、migration backfill、tenant isolation、concurrent duplicate
  submission、per-item partial result、action turn replay。
- [ ] Celery fake broker/worker：publish success/failure、duplicate delivery claim、metadata moved off request、
  state progression and final failure。
- [ ] signed gateway：explicit single/batch save、bare batch + confirm、cancel/expired、11 URL rejection、
  mixed partial result、duplicate platform message exactly once。
- [ ] regression：knowledge search/citation repair、provider TLS、multiuser、ingestion、LangBot bridge、
  Telegram/WeChat required plugin patch。

建议命令（实现者按新增文件名补齐）：

```bash
.venv/bin/alembic upgrade head
.venv/bin/pytest -q tests/test_agent_runtime.py tests/test_multiuser_integration.py
.venv/bin/pytest -q tests/test_tasks.py tests/test_http_gateway.py
.venv/bin/pytest -q
.venv/bin/uv lock --locked
git diff --check
python3 ./.trellis/scripts/task.py validate 08-06-agent-save-video-tool
```

## 9. Deployment and human acceptance

- [ ] 更新 `.env.example`/部署文档：`AGENT_SAVE_ENABLED`、migration、worker CA、Redis/MinIO readiness、
  pending/action diagnostics、safe rollback。
- [ ] migration 后先部署/启动 compatible Celery worker，验证 ingest queue，再重启 gateway；最后开启
  feature flag。不得重置 channel login、identity 或已有 content。
- [ ] 自动 smoke 只输出 item/state/result counts 和 tenant ownership boolean，不输出消息、URL/title、
  transcript、identity 或 secret。
- [ ] 人工微信用户 57 验收：裸单 URL→确认→queued；明确 2 URL batch→queued；一个有效+一个无效
  → partial summary；重复消息不重复 enqueue；worker 最终 ready 后能从用户 57 检索 citation。
- [ ] 人工验收前不勾选最终 channel acceptance，不把用户 1 的现有内容用于用户 57。

## Rollback points

- Agent action branch 绕过 citation guard：立即关闭 `AGENT_SAVE_ENABLED`，保留 read-only retrieval。
- tenant mismatch：停止所有 write tools；保留数据库，不迁移/重绑用户数据。
- duplicate/unbounded enqueue：停止 gateway submissions 和 worker intake，保留 dispatch rows审计后修复。
- worker CA/provider failure：保持 items/dispatches stable failed/pending，不关闭 TLS verification。
- migration/old-turn replay 回归：停止 rollout，恢复旧 gateway；新增 schema/data 保留，不 destructive drop。
