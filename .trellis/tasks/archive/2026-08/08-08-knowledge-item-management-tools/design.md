# 知识库条目管理 Tools：技术设计

## 1. Boundary and invariants

本任务扩展现有：

```text
ChannelService
  → KnowledgeAgent planner
  → trusted tenant-bound services
  → canonical AgentAnswer / persisted ActionOutcome
```

不增加第二套 HTTP/CLI 管理 API，也不让模型执行 SQL、选择 tenant 或组织 Celery payload。

核心不变量：

1. list/detail/CRUD/retry 每次在 SQL 层强制 `ContentItem.user_id == TenantContext.app_user_id`。
2. 管理读写是可信 operation outcome，不进入 citation Composer；知识回答仍必须 search/citation。
3. 每个 Agent run 最多接受一个 terminal management/action outcome；混合 tool batch 中真实 outcome
   胜出，模型 prose 丢弃。
4. 删除先持久化确认，确认前不改变 item；恢复、更新和 retry 不需要破坏性确认。
5. 软删除条目立即从所有普通读取和 retrieval path 消失；物理 purge 与 MinIO/worker 协调。
6. 生产诊断只记录 allow-listed 名称、计数、稳定状态和错误码，不记录对象/内容数据。

## 2. Data model and migration

为 `content_item` 增加：

```text
deleted_at          timestamptz nullable
purge_claimed_at    timestamptz nullable
purge_attempts      integer not null default 0
purge_error_code    text nullable
```

`state` 继续只表达 ingestion state，不能复用成 trash/purge state。

索引：

```sql
CREATE INDEX ... ON content_item(user_id, saved_at DESC, id DESC)
WHERE deleted_at IS NULL;

CREATE INDEX ... ON content_item(user_id, deleted_at DESC, id DESC)
WHERE deleted_at IS NOT NULL;

CREATE INDEX ... ON content_item(deleted_at, id)
WHERE deleted_at IS NOT NULL;
```

现有 `(user_id, platform, platform_id)` unique constraint 保留。它使回收站中的相同 URL 仍指向原
item，submission service 必须识别并自动恢复，而不是插入重复行。

迁移后所有现有行的新增 nullable 字段为 null，继续普通可见。`Segment.item_id` 与
`IngestDispatch.item_id` 已有 `ON DELETE CASCADE`，无需复制 cascade；MinIO 不在数据库事务内，
由 purge service 显式删除。

## 3. Public item projections

新增独立的管理 contract，不复用 `Citation` 或 retrieval `ItemDetails`：

```python
class SavedItem(BaseModel):
    item_id: int
    platform: Literal["youtube", "bilibili", "wechat_mp"]
    kind: Literal["video", "article"]
    title: str
    author: str | None
    url: str
    duration_sec: int | None
    saved_at: datetime
    why_saved: str | None
    ingestion_state: str
    safe_error_code: str | None
    deleted_at: datetime | None = None
    expires_at: datetime | None = None
    restorable: bool | None = None

class SavedItemPage(BaseModel):
    items: list[SavedItem]
    next_cursor: str | None
```

不返回 `content_hash`、`raw_object_key`、`fail_reason` 原文、chapters、tags、transcript、vector、
dispatch/task/request key。`title` 缺失时使用现有 `_title()` 规则的 safe platform-ID fallback。

失败状态只映射固定 safe code，例如 `ingestion_failed` / `transient_fetch_failed` /
`queue_unavailable`；未知内部 reason 映射 `ingestion_failed`。

## 4. List and cursor contract

`list_saved_items` schema：

```python
list_saved_items(
    kind: Literal["video", "article"] | None = None,
    platform: Literal[...] | None = None,
    state: Literal[...] | None = None,
    location: Literal["library", "trash"] = "library",
    limit: int = 20,
    cursor: str | None = None,
) -> ManagementToolPayload
```

- `limit` clamp 到 `1..50`，service 使用 `limit + 1` 判断下一页，不执行无界 count。
- library order/keyset：`(saved_at DESC, id DESC)`；trash：`(deleted_at DESC, id DESC)`。
- cursor 是版本化 opaque base64 JSON，含 `v/location/order_timestamp/id/filter fingerprint`，不含 tenant。
  它不是授权凭据；解析失败或与 filters/location 不匹配返回 `invalid_cursor`。所有查询仍独立加 tenant。
- trash 行的 `expires_at = deleted_at + retention`；`restorable` 仅在数据库当前时间早于 expiry、且未被
  purge claim 时为 true。
- `get_saved_item(item_id)` 只读普通库存。回收站详情通过 trash list 的 bounded projection 获取，避免
  普通详情意外绕过删除边界。

## 5. Management service boundaries

新增 `KnowledgeItemManagementService`：

```python
list_items(tenant, filters, cursor, limit) -> SavedItemPage
get_item(tenant, item_id) -> SavedItem
update_why_saved(tenant, item_id, why_saved) -> ItemOperationResult
request_delete_targets(tenant, item_ids) -> tuple[int, ...]
soft_delete(tenant, item_ids) -> BatchItemOperationResult
restore(tenant, item_ids) -> BatchItemOperationResult
```

- `why_saved` 参数无默认值：字符串表示更新，JSON null 表示清空；trim 后空字符串规范成 null，最大
  500 字符。service 不暴露通用 patch dict。
- update SQL 必须同时检查 tenant 与 `deleted_at IS NULL`。相同值返回成功 no-op，保持幂等。
- batch delete/restore 限 1..10，输入去重但保留首次顺序。确认请求采用 all-or-nothing target
  validation；任一 ID 不存在、跨 tenant 或已在 trash 时不创建 pending action。
- `soft_delete` 在确认消费后重新 tenant-check/row-lock。并发期间已经删除的目标返回
  `already_deleted`，其余写同一个数据库 `now()`；不会碰 segments/raw object。
- `restore` row-lock 目标，只恢复 `now < deleted_at + retention` 且 `purge_claimed_at IS NULL` 的行，
  清空 delete/purge 字段。已经普通可见返回 `already_restored`；到期或跨 tenant 返回 safe not-found。

## 6. Pending delete confirmation

保留现有 `pending_channel_action` 表与“一 thread 一个 active action”partial unique index，泛化
`PendingConfirmationService`，不新增第二张 pending 表。

删除 payload：

```json
{"version": 1, "item_ids": [12, 19], "kind": "delete_saved_items"}
```

payload 只保存经过 tenant service 验证的内部 item ID，最多 10 个；不保存 title、URL、消息或 tenant。
tenant/thread ownership 每次 inspect/confirm/cancel 都通过 join/lock 重新验证。

新增模型 tools：

```text
delete_saved_items(item_ids)       # 只创建 pending confirmation
confirm_item_deletion()            # 不接受 item IDs，消费可信 payload
clarify_item_deletion()            # 不消费
cancel_item_deletion()             # 取消
```

delete pending 使用与 save pending 相同的 10 分钟 TTL。`PendingActionSnapshot` 只向 instructions 暴露
`kind + count`，不暴露 IDs。新的 save/delete request 原子 cancel 任意旧 active pending action，再创建
新 action；错误调用不匹配 kind 的 confirm tool 时 fail closed。`/new` 现有通用 cancellation 保持有效。

## 7. Agent runtime integration

扩展 trusted runtime services：

```text
Agent runtime
  ├─ KnowledgeServices                 # retrieval only
  ├─ IngestSubmissionService           # save/retry dispatch
  ├─ PendingConfirmationService        # save/delete pending state
  └─ KnowledgeItemManagementService    # inventory CRUD/restore
```

管理 tools 通过现有 `execute_tool()` 记录安全边界，并把结果交给 `AgentActionRuntime` 生成 canonical
`ActionOutcome`。list/detail 也是 terminal read outcome：它们不需要 search/citation，也不调用
Composer。操作结果继续写 `ConversationTurn.action_results`，重复 message 由现有 turn replay 返回。

INSTRUCTIONS 增加明确路由：

- “存了什么/库存/回收站” → list；“第 N 条详情” → get；
- “为什么收藏/修改备注” → update；
- 删除 → 只 request confirmation；pending delete 的肯定/否定/含糊回复使用对应 tools；
- 恢复 → restore；处理失败后明确重试 → retry；
- “这个视频讲什么”仍走 semantic retrieval。

`AgentActionRuntime` 保持一个 terminal outcome。provider 混合调用时 canonical management/action outcome
胜出。现有 search budgets、Citation cache 和 tool-free Composer 不变。

新增 `AGENT_ITEM_MANAGEMENT_ENABLED=false|true` rollout flag；关闭时管理 tools 返回稳定 unavailable，
但 soft-delete retrieval filters 永远启用。save 与 management service availability 分开，不把只读库存
错误绑定到 `AGENT_SAVE_ENABLED`。

## 8. Save-time automatic restore

`IngestSubmissionService._submit_reference()` 查到 existing item 后先 row-lock：

1. `deleted_at IS NULL`：保留现有 already-exists/retry behavior；
2. trash 且未到期、无 purge claim：清除 delete/purge 字段；本次 `why_saved is not None` 时更新，null
   时保留旧值；
3. restored item 为 ready/active：返回 `restored`，不 enqueue；
4. restored item 为 failed：在同一请求继续创建下一 attempt 并 publish，结果为 restored+queued；
5. 已到期或已 purge-claimed：不恢复；purge 完成后 unique row 消失，后续请求创建新 item。若仍在
   purge 中，返回稳定 `purge_in_progress`，不与后台争抢。

并发 save/restore/purge 以 ContentItem row lock 和 unique constraint 收敛。

## 9. Explicit ingestion retry

在 `IngestSubmissionService` 增加 tenant-bound `retry_item(tenant, item_id, request_key)`，复用创建
`IngestDispatch`、attempt、publish 和 `_set_dispatch_state()` 的共同 helper：

- row-lock item；要求 tenant match、`deleted_at IS NULL`、`state == failed`；
- latest dispatch 不能是 pending/enqueued/running；否则 stable no-op；
- 原子重置 item 到 pending、清 safe fail state、创建 `attempt + 1` dispatch；
- broker publish 有界；失败保留可再次重试的安全 dispatch/item 状态；
- request key 由 trusted thread/message/action 生成，重复 delivery 返回同一结果。

`no_text`、`needs_asr`、`needs_extension` 代表能力/内容状态，不等于 transient failed，不自动重投。

## 10. Retrieval and worker deletion gates

以下每条 SQL path 都补 `ContentItem.deleted_at IS NULL`：

- vector search、BM25/lexical search；
- search result hydration；
- `get_neighbors`、retrieval `get_item`、`open_at`；
- worker dispatch claim 与 finalization checks。

soft delete 不强制中断已经运行的远端 fetch；结果即使完成也保持不可见。worker 在 claim、写 MinIO 前、
写 segments/final ready 前重新检查 item 未进入 purge；发现 purge claim 时安全停止/取消 dispatch。

physical purge 只 claim 没有 pending/enqueued/running dispatch 的到期 item。若发现 active/stuck dispatch，
本轮 defer 并记录计数；不强杀数据库行，避免晚到 worker 在 MinIO delete 后重新 put orphan。

## 11. Automatic purge

配置：

```dotenv
TRASH_RETENTION_DAYS=30
TRASH_PURGE_INTERVAL_SECONDS=3600
TRASH_PURGE_BATCH_SIZE=20
TRASH_PURGE_CLAIM_TIMEOUT_SECONDS=1800
```

Settings 验证全为正数并 clamp batch 上限。Celery 增加 `maintenance` route、periodic
`purge_expired_items_task` 和 beat schedule；部署启动 beat，并让 worker 消费 `ingest,maintenance`（或
独立 maintenance worker）。

每次 sweep：

1. 使用数据库 `now()`、retention cutoff 和 `(deleted_at,id)` index，`FOR UPDATE SKIP LOCKED LIMIT batch`；
2. 只选无 active dispatch、claim 为空或已超时的 item，写 `purge_claimed_at=now`、attempt+1；
3. 每个 item 单独执行幂等 MinIO `delete_object(raw_object_key)`；key null/对象不存在视为成功；
4. 成功后新事务 row-lock 并验证仍是相同 claim/仍到期，然后删除 ContentItem，cascade children；
5. 外部删除失败写 fixed `purge_error_code`，保留 row，claim timeout 后重试；不保存异常 message；
6. crash after object delete/before row delete 时，下次 S3 delete no-op，然后完成 DB delete。

batch 同时受 item 数和单轮 elapsed-time 上限约束。任务只发安全计数/状态诊断；不记录 key/ID。

## 12. Diagnostics, errors and persistence

扩展 diagnostics `_TOOLS` 与 `_ERRORS` allow-list，覆盖 inventory/update/delete/restore/retry/purge 的固定
名称和 safe codes。后台 purge 事件使用固定 stage/counters，不复用 retrieval-content escape hatch。

修正 retrieval `except UnexpectedModelBehavior` 为 `except UnexpectedModelBehavior as exc` 并把 `exc`
传给 diagnostics，生产只保留 class；这解释现有 `runtime_error/error_class="-"` 盲点而不放宽隐私。

管理 errors 至少包含：`item_not_found`、`invalid_cursor`、`invalid_batch`、
`confirmation_required/missing/expired`、`item_deleted`、`item_expired`、`retry_not_allowed`、
`queue_unavailable`、`management_unavailable`。异常原文不进入 AgentAnswer 或生产日志。

## 13. Rollout and rollback

Rollout order：

1. 备份 PostgreSQL/MinIO；部署 migration 与始终生效的 deleted filter；
2. 部署兼容 worker、maintenance task 和 gateway，但保持 management flag off；
3. 启动/验证 Celery beat + maintenance queue；
4. 开启 management flag，先做 list/detail smoke，再 update/restore/retry，最后删除确认与到期 purge smoke；
5. 观察 DB/index size、dead tuples、oldest trash、purge backlog/failure 和 retrieval latency。

安全 rollback 是关闭 management flag 和 beat，同时保留 schema 与 deleted filters。不得直接 downgrade
删除 `deleted_at` 列，否则回收站内容会复活。只有在所有 soft-deleted rows 已明确 restore 或 purge、且
备份完成后才允许 schema downgrade。

## 14. Validation strategy

- Unit：cursor codec、projection/error mapping、why_saved null/length、pending kind/payload、tool schemas、
  canonical rendering、settings bounds、diagnostics privacy。
- PostgreSQL：双 tenant list/detail/update/delete/restore/retry；keyset pagination；row-lock concurrency；
  save auto-restore；expired restore rejection；cascade purge；active-dispatch defer。
- Worker/MinIO：object delete success/not-found/failure、crash window retry、claim timeout、late worker gates、
  batch/time bounds、beat/route static assertions。
- Agent：自然语言 routing、pending delete yes/no/ambiguous、action wins mixed batch、no Composer/search for
  management reads、duplicate message replay、existing knowledge answer regressions。
- Migration/deployment：upgrade keeps existing rows visible；feature flag/beat rollout；rollback retains hidden
  trash；full test suite and manual channel smoke。
