# Agent 自然语言批量保存视频：技术设计

## 1. Design boundary

本任务在现有 `ChannelService → KnowledgeAgent → tenant-scoped services` 路径上增加有证据的
action tools，不增加 `/save` 命令，也不创建第二套 ingestion pipeline。

核心安全不变量：

1. Agent 决定意图；应用代码解析/规范化 URL 并执行副作用。
2. 模型工具 schema 不包含 `user_id`；tenant 只来自可信 `AgentRequest.tenant`。
3. 知识回答仍需要真实 search/citation；保存动作只凭真实 action result 成功。
4. channel 请求只提交任务，不执行 metadata、字幕、分块或 embedding 网络工作。
5. 每条消息最多 10 个 URL，批次超限在任何 ingestion side effect 前拒绝。

## 2. Target flow

```text
signed channel message
  → trusted ChannelEnvelope / TenantContext / ConversationThread
  → KnowledgeAgent intent + tools
      ├─ explicit save + current-message URLs
      │    → save_videos(urls, why_saved?)
      ├─ bare URL batch
      │    → request_save_confirmation(urls)
      ├─ affirmative answer with live pending action
      │    → confirm_video_save()
      └─ negative answer with live pending action
           → cancel_video_save()
  → tenant-bound IngestSubmissionService
  → normalize ItemReference (no remote fetch)
  → idempotent ContentItem + durable dispatch claim
  → Celery worker
  → metadata → transcript → chunks → embedding → ready
```

未来收藏夹路径只在 submission service 之前增加异步 enumerator：

```text
import_collection → collection enumerator/cursor → ItemReference[]
                  → same IngestSubmissionService
```

## 3. Agent tool contracts

Agent 暴露四个 action tools；所有 tool deps 都绑定当前 request/thread/tenant：

```python
request_save_confirmation(urls: list[str]) -> ConfirmationResult
save_videos(urls: list[str], why_saved: str | None = None) -> BatchSaveResult
confirm_video_save() -> BatchSaveResult
cancel_video_save() -> ActionResult
```

- `save_videos` 只接受当前用户消息中出现的 URL；应用从原消息独立提取并核对，模型不能注入
  未出现的第三方 URL。
- `confirm_video_save` 不接受 URL 参数，只能原子消费当前 thread 内未过期的 pending batch，防止
  模型从历史自由文本重构或替换目标。
- `request_save_confirmation` 允许写 pending conversation state，但不能创建 `ContentItem`、
  dispatch 或 Celery task。
- `cancel_video_save` 清除当前 pending batch；无 pending 时返回稳定 `confirmation_missing`。
- batch 长度必须在规范化和副作用前验证；`>10` 返回 `batch_too_large`，整批无写入。

Agent instructions 明确区分：

| User intent | Required tool behavior |
| --- | --- |
| “保存/收藏这些 URL” | immediate `save_videos` |
| only 1–10 URLs | `request_save_confirmation` |
| asks what linked video says | do not save; normal knowledge behavior |
| “是/保存吧” with live pending | `confirm_video_save` |
| negative answer with live pending | `cancel_video_save` |
| confirmation missing/expired | ask user to resend URL; no ingestion side effect |

同一 run 最多接受一个 terminal action outcome。模型重试时再次调用相同 action tool，由
request-scoped cache 和数据库幂等键返回原结果，不重复投递。

## 4. Pending-action persistence

新增 `pending_channel_action`，而不是只依赖 model history：

```text
id                    bigint PK
thread_id             FK conversation_thread
kind                  text  # save_videos
payload               jsonb # versioned normalized URL list, <=10
expires_at            timestamptz
consumed_at           timestamptz nullable
consumed_message_id   text nullable
cancelled_at           timestamptz nullable
created_at            timestamptz
```

- partial unique index 保证一个 thread 最多一个 active pending action。
- 新裸 URL batch 在事务中 cancel 旧 active row、插入新 row；不合并两个批次。
- confirm 使用 `SELECT ... FOR UPDATE` 校验 thread ownership、kind、expiry 和 active state，再以当前
  message ID 单次消费。相同 message ID 重放得到同一消费结果；其他迟到确认失败。
- `/new` 在关闭旧 thread 时取消 active pending row。重启不影响数据库中的未过期状态。
- payload 只保存规范化 URL 和 schema version，不保存外部 identity、整条消息或模型文本。

## 5. Submission and queue idempotency

新增应用服务边界：

```python
class IngestSubmissionService:
    def submit_urls(
        self,
        tenant: TenantContext,
        urls: list[str],
        *,
        why_saved: str | None,
        request_key: str,
    ) -> BatchSaveResult: ...
```

`request_key` 由可信 thread/message/action position 生成，模型不可提供。service 先把 URL 转成
`ItemReference(platform, platform_id, canonical_url)`；这个步骤只做本地解析，不访问远端。

每个 URL 独立 savepoint，结果按输入顺序返回。使用现有
`(user_id, platform, platform_id)` unique constraint 作为内容幂等根，并增加 durable dispatch claim：

```text
ingest_dispatch
  id / public_id
  item_id
  request_key
  attempt
  state: pending | enqueued | running | completed | failed
  task_id
  error_code nullable
  timestamps
```

- 同一 item 最多一个 active dispatch；并发 insert/claim 由数据库约束和 row lock 收敛。
- 新 item 以 `ContentItem.state=pending` 和最小 canonical metadata 写入；远端 metadata 不在请求路径。
- broker publish 成功返回 `queued`；已有 active/ready item 返回 `already_exists`，不重复 enqueue。
- broker publish 失败记录安全 `queue_unavailable`，不把 broker exception 交给 Agent。
- worker 以 dispatch row 原子 claim；重复 Celery delivery 看到 running/completed 后 no-op，从而避免
  重复处理。发布和状态更新使用 conditional transition，不能把快速 worker 的 running/completed
  状态写回 enqueued。
- 相同 request key 返回已记录的逐项结果；Agent output retry、bridge redelivery 和 HTTP retry 不会
  重新提交整批。

单个 URL 失败不回滚 peers。batch-level `batch_too_large` 是唯一整批前置拒绝。

## 6. Worker boundary

现有 `create_item()` 把 `fetch_meta()` 放在同步路径，必须拆分：

1. submission 只创建 minimal pending item + dispatch；
2. worker claim dispatch 后获取 metadata，并更新 title/author/duration 等；
3. 继续复用现有 transcript、validation、MinIO、chunk、embedding 和 Segment 写入；
4. success 原子标记 item ready + dispatch completed；最终 failure 标记安全 item/dispatch state；
5. worker 使用共享 embedding provider/trusted CA composition，保持 certificate 和 hostname
   verification，不能依赖 gateway 进程环境偶然存在。

`process_item()` 保持可从 CLI/测试调用，但 channel tool 只能 enqueue worker。CLI 同步入口是否保留
不改变本任务的 channel contract。

## 7. Action result and answer contract

每项结果为固定结构：

```text
result_id / input_index / status / item_id? / state? / safe_error_code?
```

允许的 per-item status：`queued`、`already_exists`、`unsupported_url`、`invalid_url`、
`queue_unavailable`、`create_failed`。异常 message、traceback、credential、task payload 不进入结果。

Agent runtime 记录 `ActionOutcome`，并按真实结果映射：

| Outcome | AgentAnswer.status | error_code |
| --- | --- | --- |
| pending confirmation created | `ok` | `save_confirmation_required` |
| all queued/already exists | `ok` | `save_accepted` |
| some queued/existing, some failed | `ok` | `save_partial` |
| all items failed | `failed` | `save_failed` |
| batch > 10 | `failed` | `batch_too_large` |
| confirmation cancelled | `ok` | `save_cancelled` |
| pending missing/expired | `failed` | `confirmation_missing` / `confirmation_expired` |

模型在 tool call 后生成的 action draft 完全丢弃，不进入用户回复或可恢复 history。应用只根据真实
`ActionOutcome` 生成 canonical ordered summary，分别统计 queued、already-exists 和 failed，并为每个
失败项映射安全、可执行的原因。action 分支不实现 `[A<n>]` output validator/repair；`result_id` 只作为
应用结果列表中的内部关联编号。这样 partial failure 不可能被模型改写成全成功。clarification/cancel
同样使用稳定应用文案。

知识回答分支维持现有 `[S<n>]` citation allow-list。只有真实 action outcome 才能跳过
`search_required`；普通无工具草稿仍 fail closed。若一条消息同时要求保存并解释尚未导入的视频，
本次 action 只报告已入队并提示 ready 后再查询，不使用模型记忆回答视频内容。

## 8. Turn persistence and duplicate replay

`ConversationTurn` 增加显式的 `answer_status`、`error_code` 和 `action_results` JSONB；existing
knowledge rows migration backfill 为 `ok`（有 sources）或 `not_found/no_evidence`（无 sources）。

`_answer_from_turn()` 从持久化 contract 重建原始 action/knowledge result，不再用“citations 为空”
推断 `not_found`。同一个 platform message ID 重放时不再调用 Agent/tool/queue。

action result payload 仅包含内部 item/result ID、safe code、state 和必要的 canonical URL reference；
不保存外部 identity、queue credential 或 exception text。

action turn 的 `model_messages` 保存为空列表；恢复和 duplicate replay 只依赖持久化的 canonical
assistant text、answer status、error code 与 action results，不重放被丢弃的模型 action draft。

## 9. Collection-import extension seam

当前 tool、Agent 和 channel 只依赖 `IngestSubmissionService`，不依赖 YouTube connector 或 Celery
细节。未来 collection enumerator 输出 `ItemReference` 并通过异步 ImportJob 分页调用同一 service。

私有收藏夹需要独立 platform authorization/vault；`ChannelIdentity` 只证明渠道用户身份，不能当作
YouTube/Bilibili 授权。OAuth、cookie/token storage、collection cursor、ImportJob 和大批量限流
保持本任务 scope 外。

## 10. Compatibility, rollout, and rollback

- 增加 `AGENT_SAVE_ENABLED` feature flag；关闭时不执行 action side effect，并返回稳定 unavailable。
- rollout 顺序：migration → compatible worker → gateway/Agent → channel smoke。worker 未升级前不得
  开启 flag。
- migration 只增加表/列/index，不改现有 tenant/content ownership，不移动用户 1/57 数据。
- rollback 先关 feature flag，再回滚 gateway/worker；新增表保留以避免丢失 pending/action audit，
  后续单独清理，不做 destructive downgrade。
- 任何 tenant leak、重复无界 enqueue 或 action branch 绕过 citation guard 都是 stop-ship。
