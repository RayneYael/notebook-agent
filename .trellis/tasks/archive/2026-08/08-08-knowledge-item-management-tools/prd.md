# 知识库条目管理 Tools

## Goal

让用户通过现有自然语言 Agent 安全地查看和管理自己的知识库条目，不再把“我存了什么”错误地
降级成字幕语义检索；在现有批量保存能力之上补齐 tenant-scoped 的查询、收藏原因修改、可恢复
删除、恢复和失败摄取重试，并通过自动清理控制回收站容量。

## Background

- 当前新增入口为 `save_videos(urls, why_saved?)`，已经具备可信 tenant 注入、每批最多 10 个、
  去重、异步摄取和安全逐项结果；本任务复用现有 ingestion submission，不重写摄取链路。
- 当前 Agent 注册 `search_segments`、`get_neighbors`、`get_item`、`open_at` 及保存确认类工具，
  没有列出、修改、删除、恢复或重试知识库条目的管理工具
  （`app/agent/runtime.py:275-397`，`tests/test_agent_runtime.py:182-196`）。
- `search_segments` 查询 `Segment` 的字幕/正文并按相关度返回候选，不是库存查询，不能保证返回
  当前用户全部或按保存时间分页的条目（`app/agent/services.py:127-189`）。
- 现有 `get_item(item_id)` 只在语义检索产生可信 citation 后作为 expansion tool 暴露，不构成可
  独立使用的库存详情入口（`app/agent/runtime.py:297-327`）。
- `ContentItem` 已有 tenant、来源元数据、保存时间、`why_saved`、观看字段、摄取状态和原始对象键；
  `Segment` 与 `IngestDispatch` 通过外键依附 item
  （`app/models.py:231-375`）。
- 每个 `Segment` 保存 1536 维向量并进入 HNSW/GIN 索引；回收站容量的主要成本是 retained
  segments/indexes，不是 `ContentItem` 行。容量与清理证据见 `research/recycle-bin-capacity.md`。

## Requirements

### R1 — Trusted tenant and bounded contracts

- 所有管理服务从服务端 `TenantContext.app_user_id` 获取 tenant；模型 schema 不得接收 `user_id`、
  thread/message ID、request key、dispatch/task ID、存储 key或目标 tenant。
- item ID 可以作为 list/detail 返回后的对象引用，但每次服务操作都必须重新校验 tenant；不存在与
  跨 tenant ID 对外返回相同的 safe not-found，不能泄漏对象是否存在。
- 列表和批量管理均有固定上限、稳定顺序和有界 payload；模型不能用模糊标题直接对多个候选执行
  更新、删除、恢复或重试。
- 管理结果由应用根据真实 service outcome 生成最终文案；未验证的模型 action prose 不作为成功
  依据，也不持久化为事实。

### R2 — Inventory list and independent detail

- 新增 `list_saved_items`：按当前 tenant 查询 `ContentItem`，普通库存默认按
  `saved_at DESC, id DESC` 稳定排序，并支持有界 cursor 分页。
- list 支持按 `kind`、`platform`、摄取 `state` 过滤；“我存了哪些视频”固定映射为
  `kind=video`，不能调用 embedding 或 `search_segments` 伪装库存查询。
- list 默认排除回收站，并支持显式 `location=trash`；回收站按 `deleted_at DESC, id DESC`
  分页并返回派生的到期时间/可恢复状态。
- 新增 `get_saved_item` 作为独立库存详情 tool，不受 retrieval expansion gate 限制；普通详情默认
  不读取回收站条目。
- 列表/详情只返回有界公开元数据、`why_saved` 和安全摄取状态；不得返回 transcript、embedding、
  raw object key、Celery task ID、内部 `fail_reason` 原文或异常正文。
- 空库存和空回收站是成功的空列表，不是 retrieval failure、`not_found/no_evidence` 或“证据不足”。
- 不单列 `get_ingestion_status`；list/detail 已覆盖安全状态读取。

### R3 — Update only `why_saved`

- 新增 `update_saved_item(item_id, why_saved)`，MVP 只修改或清空用户自有的收藏原因 `why_saved`。
- 参数必须区分非空更新和显式 `null` 清空；服务负责有界长度、空白规范化和稳定结果。
- `watch_state`、`watch_pos_sec`、个人标题和个人标签均不纳入本任务。
- provider/ingestion 拥有的 `platform`、`platform_id`、canonical URL、来源标题/标签、作者、
  发布时间、时长、transcript、embedding 和摄取状态不得由模型 patch。
- 更新只允许普通库存条目；回收站、不存在和跨 tenant 条目不被修改。重复 delivery 必须幂等。

### R4 — Recycle-bin delete and restore

- 新增 `delete_saved_items`，将当前 tenant 的一个或最多 10 个条目软删除到回收站；首次删除不物理
  清除 `ContentItem`、segments、dispatch 或 MinIO 原始对象。
- 删除是高风险副作用，必须先写入 tenant/thread-bound 的持久化 pending action，再由用户明确
  确认后单次消费；取消、含糊回答、过期、跨 conversation、迟到确认或重复 delivery 不得误删。
- 新增 `restore_saved_items`，恢复当前 tenant 回收站中一个或最多 10 个尚未过期的条目；恢复不
  创建重复 item、segment 或 dispatch，并且幂等。
- 删除后条目立即从默认库存、详情、更新、retry、semantic/vector/BM25 检索及 citation hydration
  中消失。运行中或晚到 worker 不得让软删除条目重新可见。
- 用户明确保存仍在回收站中的相同 URL 时自动恢复原 item；本次提供 `why_saved` 时更新收藏原因，
  未提供时保留原值。已物理清理的 URL 按全新保存处理。
- 一个 conversation 仍最多只有一个 active pending action；新的保存或删除确认请求替换旧 pending
  action，`/new` 取消所有 active pending action。模型不能从自由文本历史重构删除目标。

### R5 — Automatic physical purge

- 回收站默认保留 30 天，并通过正数服务端配置调整；到期即不可恢复，即使后台物理清理尚未完成。
- 定时后台任务按 `(deleted_at, id)` 稳定扫描到期条目，使用可并发 claim 的小批量、可重试处理；
  不得一次加载/删除全部到期行，不得形成无界事务、锁表或 broker 消息。
- 物理清理只处理没有 active ingestion dispatch 的条目；active/stuck worker 导致的延期必须可观测，
  不能以删除数据库行换取 MinIO orphan 或晚到写入。
- MinIO object delete 必须幂等；只有外部对象删除成功或对象已不存在后，才物理删除 `ContentItem`，
  再由已有外键 cascade 删除 segments 与 dispatch。进程在两步间崩溃后可安全重试。
- PostgreSQL autovacuum 负责让 dead tuple 空间可复用；记录 table/index size、dead tuples、最老垃圾、
  purge backlog/失败与 MinIO delete failure，依据实测决定 `REINDEX` 等维护，不在请求路径执行重维护。

### R6 — Explicit ingestion retry

- 新增 `retry_item_ingestion(item_id)` 并纳入 MVP，只允许当前 tenant、非回收站且稳定 `failed`
  状态的 item 创建下一次 durable dispatch。
- `pending`、处理中、`ready`、`no_text`、`needs_asr` 和 `needs_extension` 返回稳定 no-op/不可重试，
  不盲目重投。
- retry 复用现有 submission/dispatch 幂等、attempt 和 bounded broker publish 逻辑；模型不得传 URL、
  request key、attempt 或 task ID。重复 tool call、重复消息和并发请求不能创建多个 active dispatch。

### R7 — Agent routing, persistence and diagnostics

- Agent 明确区分：内容问答使用 semantic retrieval；库存查看使用 list/detail；管理操作使用
  update/delete/restore/retry。管理读写成功不需要 citation，也不能触发 Composer。
- list/detail 与管理动作都以可信 canonical management outcome 跳过 `search_required`；普通无 tool
  模型文本仍然 fail closed，现有 citation guard 保持不变。
- action outcome 可持久化并由重复 channel message 幂等重放；删除确认 target 仅存在版本化 pending
  payload，不进入模型历史。
- 新工具加入诊断 allow-list，只记录工具名、调用序号、安全结果数量/状态和稳定错误码。生产日志
  不记录消息、标题、URL、`why_saved`、item ID、pending payload、字幕、secret、DSN 或异常正文。
- 修正当前 `UnexpectedModelBehavior` retrieval failure 未记录异常 class 的诊断盲点，但生产仍不得
  记录异常 message/body。

### R8 — Compatibility and rollout

- 保持现有 `save_videos`、裸 URL 确认、异步摄取、知识检索、citation Composer、conversation
  persistence 和 `/new` 行为兼容。
- 管理 service/tool、必要 Alembic migration、周期任务配置、worker/gateway 部署、诊断、测试和文档
  属于本任务；不新增独立 Web UI 或用户必须记忆的 slash command。
- 当前数据迁移后 `deleted_at`/purge claim 均为 null，所有既有条目保持普通可见；关闭新管理功能时
  现有保存与检索仍可运行，并始终排除已经软删除的内容。

## Final MVP Tool Set

| Tool | Purpose |
| --- | --- |
| `save_videos` | 已有的批量新增视频；扩展为相同 URL 在回收站时自动恢复 |
| `list_saved_items` | 普通库存/回收站列表、过滤和 cursor 分页 |
| `get_saved_item` | 独立库存详情 |
| `update_saved_item` | 修改或清空 `why_saved` |
| `delete_saved_items` | 创建删除确认，不立即删除 |
| `confirm_item_deletion` | 消费可信 pending target 并移入回收站 |
| `clarify_item_deletion` | 保留 pending target 并要求明确决定 |
| `cancel_item_deletion` | 取消 pending 删除 |
| `restore_saved_items` | 恢复回收站条目 |
| `retry_item_ingestion` | 重试稳定 `failed` 摄取 |

现有 `search_segments`、`get_neighbors`、`get_item`、`open_at` 继续属于内容检索，不计入 CRUD 管理
tools。`get_ingestion_status`、`permanently_delete_items` 和 `empty_trash` 不在 MVP；永久清理由到期后台
任务负责。

## Out of Scope

- 个人标题、个人标签、观看状态/位置和播放器集成。
- 修改来源 metadata、字幕、章节、embedding 或 ingestion 内部状态。
- 用户手动永久删除/清空回收站、改变单条目的 retention 或恢复已物理清理数据。
- 跨 tenant 共享/转移、管理员代操作、批量导出、独立 Web/移动管理界面。
- 播放列表/收藏夹 OAuth 导入、文件上传、新 connector、ASR/extension 能力实现。
- 模糊标题命中多个条目时自动选择并执行副作用。

## Acceptance Criteria

- [ ] AC1：用户问“我现在存了什么视频”时调用 `list_saved_items(kind=video)`，不调用 embedding/search；
  结果按保存时间稳定分页，空库返回成功空列表且只包含当前 tenant。
- [ ] AC2：list 支持 kind/platform/state/location 过滤和有界 cursor；普通库与回收站翻页无重复/遗漏，
  回收站返回安全到期/可恢复状态。
- [ ] AC3：`get_saved_item` 可独立读取当前 tenant 普通条目；不存在、回收站和跨 tenant ID 使用相同
  safe not-found，不泄漏 transcript、vector、object/task key 或异常正文。
- [ ] AC4：`update_saved_item` 只更新/清空有界 `why_saved`，不能修改来源/摄取/观看字段；回收站和跨
  tenant 条目不变，重复 delivery 幂等。
- [ ] AC5：删除必须经过持久化确认；确认后至多 10 个目标进入回收站并立即从库存与所有检索路径
  消失。取消、过期、跨 conversation、迟到和重复确认不产生错误副作用。
- [ ] AC6：可分页列出并恢复未到期回收站条目；恢复幂等且不复制 item/segment/dispatch。明确重存同
  URL 自动恢复原 item 并按规则更新 `why_saved`；已物理清理的 URL 重新创建。
- [ ] AC7：默认 30 天、可配置的后台 purge 以稳定 claim 和有界批次清理到期项；失败可重试且不阻塞
  CRUD/检索，不遗留可检索 segment、MinIO orphan 或晚到 worker 写入。
- [ ] AC8：稳定 `failed` item 可创建一次新的 dispatch；active/ready/no_text/needs_asr/needs_extension、
  回收站和跨 tenant item 不会重投，broker 失败映射安全状态。
- [ ] AC9：知识问答、库存读取和管理动作路由互不混淆；只有真实 outcome 可跳过 citation guard，
  canonical action history/duplicate replay 正确，模型草稿和 pending payload 不进入历史。
- [ ] AC10：所有新 tool schema 不含可信标识符；生产诊断只包含 allow-listed 安全字段，并修复
  `UnexpectedModelBehavior` class 缺失而不泄漏 message/body。
- [ ] AC11：单元、PostgreSQL 双 tenant、cursor、并发/重复投递、pending confirmation、worker/purge、
  gateway 和自然语言 fake-model 测试通过；现有保存、检索、Composer 与 citation 回归保持通过。
- [ ] AC12：migration upgrade/downgrade、默认 30 天配置、Celery beat/worker 部署、容量指标、备份与
  rollback 文档齐全；既有数据升级后仍可见。

## Resolved Product Decisions

- 删除使用回收站，默认保留 30 天且可配置，到期自动物理清理。
- 回收期内明确重存相同 URL 自动恢复原 item；已物理清理后按新 item 保存。
- `update_saved_item` 只修改 `why_saved`；标题、标签、观看状态和位置不做。
- `retry_item_ingestion` 与 CRUD tools 一起进入 MVP，且只重试稳定 `failed` 状态。
