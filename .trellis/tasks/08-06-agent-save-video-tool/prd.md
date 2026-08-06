# Agent 自然语言保存视频到私有知识库

## Goal

用户在微信、Telegram 等任一已启用渠道中，用自然语言表达“保存/收藏/加入知识库”并提供
支持的视频 URL；Agent 判断保存意图并调用有副作用的 `save_videos` 工具，将视频异步导入
当前可信 tenant 的私有知识库。用户不需要记忆 `/save` 等确定性命令。

## Confirmed Facts

- 当前 channel gateway 会把普通消息交给 `KnowledgeAgent`，但 Agent 只有四个只读工具；发送
  视频链接现在不会创建 `ContentItem`。
- 现有 ingestion 已支持 YouTube URL、tenant-scoped `ContentItem.user_id`、同一用户/平台/视频
  的唯一约束，以及 Celery `fetch_text_task`；但 CLI `ingest` 当前走同步 `ingest_url()`。
- 当前微信身份属于内部用户 57，而已有 ready 内容属于用户 1；两者必须继续视为不同用户，
  不允许重绑、共享或绕过 tenant filter。
- `/link` 是跨渠道身份绑定，不是视频保存命令；本任务不改变 `/link` 语义。

## Requirements

### R1 — Natural-language tool choice

- 不新增 `/save` 或其他用户必须记忆的确定性保存命令。
- Agent 必须根据用户自然语言中的明确保存意图和支持的视频 URL 决定是否调用
  `save_videos(urls, why_saved?)`；仅出现 URL、讨论 URL 或询问视频内容时不能自动保存。
- URL 缺失、平台不支持或意图含糊时，Agent 只能追问/说明，不能猜 URL 或静默创建内容。
- 当保存意图明确且 URL 有效时直接调用工具并入队，不要求二次确认；只有意图含糊时才追问，
  且追问轮次不得创建 `ContentItem` 或投递 ingestion 任务；允许写入恢复确认所需的会话状态。
- 用户只发送一个或多个支持的视频 URL、没有任何保存表达时，固定视为含糊意图。Agent 回复
  “需要把这个视频保存到知识库吗？”或带准确批次数量的等价问题，不得在用户肯定答复前调用
  ingestion submission。

### R2 — Trusted tenant and safe side effect

- `save_videos` 工具 schema 不包含 `user_id`；实际 `ContentItem.user_id` 只能来自服务端注入的
  `TenantContext.app_user_id`。
- 模型不得选择目标用户、channel identity、数据库 ID、Celery task ID 或存储 key。
- 同一 tenant 重复保存同一平台视频必须幂等，不能产生重复 item 或重复无界任务。
- 同一消息的重复 delivery、同一次 Agent run 的重复 tool call 和并发重复请求都必须复用同一
  submission 结果，不得重复投递已处于 active/ready 状态的 item。
- 保存用户 57 的视频绝不能出现在用户 1 的知识库，反之亦然。

### R2.1 — Batch save and partial success

- 一条明确保存消息可以包含多个支持的视频 URL；Agent 一次调用 `save_videos(urls, why_saved?)`
  批量提交，不要求用户逐条发送。
- 每条用户消息最多处理 10 个视频 URL。超过 10 个时整批拒绝，数据库和任务队列均无写入，
  Agent 要求用户拆分后重发；不得静默截断为前 10 个。
- 每个 URL 独立校验、去重、创建和投递。部分失败不回滚已经成功入队或已经存在的其他 URL。
- 工具按输入顺序返回每项的安全结构化结果，至少区分 `queued`、`already_exists`、
  `unsupported_url`、`invalid_url`、`queue_unavailable` 和 `create_failed`，并提供对应 item ID（若
  已安全创建）。不得把 traceback、connector/provider payload 或 backend credential 交给模型。
- Agent 基于真实工具结果汇总通知用户：总数、成功入队数、已存在数、失败数，以及每个失败项的
  可执行原因；不得把失败项编造成成功，也不得因部分失败重复投递整个批次。

### R3 — Asynchronous ingestion

- Agent 工具只完成 URL 校验、tenant-scoped item 创建/去重和异步任务投递；不得在微信请求的
  60 秒 bridge timeout 内同步抓字幕、分块和 embedding。
- metadata 获取也必须位于 worker；channel/Agent 请求路径不得同步调用远端 connector。
- 工具返回安全的内部 item ID、当前 state 和 `queued/already_exists` 结果；不得返回 task backend
  credential、原始字幕、外部身份或异常 traceback。
- 用户收到“已加入处理队列/已经保存”的最终回复；处理失败与未找到知识证据必须使用不同状态。
- Celery worker 的 embedding HTTPS 必须使用可信 CA 且保持证书/hostname 校验；不得因为 gateway
  query embedding 已修复就假设独立 worker 自动继承相同进程环境。

### R4 — Channel and ingestion compatibility

- 微信、Telegram 和其他启用渠道复用同一 Agent/tool，不增加 current-channel switch。
- 继续使用现有 connector、embedding、MinIO、PostgreSQL 与 Celery pipeline；不创建第二套 ingestion。
- query retrieval、citation guard、上下文恢复和确定性身份命令保持现有行为。

### R5 — Separate knowledge answers from action outcomes

- 现有“知识回答必须 search 且引用真实 citation”的 guard 继续严格生效，不能因为新增写工具而
  允许无证据知识回答。
- 保存意图澄清、`save_videos` 成功和已存在结果属于 action outcome，可以不调用
  `search_segments`、不带 citation，但必须有真实的 action/tool 状态作为成功依据。
- action outcome 至少区分 confirmation required、accepted、partial、failed 和 batch too large；
  部分成功属于成功交互，不得被统一改写为系统不可用。
- 模型既未完成搜索也未执行/澄清受支持动作时，仍返回 `search_required`，不得借 action 分支
  输出模型记忆中的知识答案。
- action outcome 必须能被会话持久化和重复消息幂等重放，不能因为 citations 为空而被错误还原为
  `not_found/no_evidence`。

### R6 — Pending confirmation lifecycle

- 一个或多个裸 URL 的待确认状态绑定当前 tenant 和 conversation，按输入顺序保存最多 10 个
  规范化 URL，并由服务端结构化持久化；不得只依赖进程内存或让模型从自由文本历史中猜测目标。
- 待确认状态有效期为 10 分钟且只能消费一次。用户在有效期内回复明确肯定表达时，Agent 才可
  对该批 URL 调用 `save_videos`；成功消费后立即清除。多个裸 URL 使用一次批量确认，例如
  “需要把这 3 个视频保存到知识库吗？”。
- 同一 conversation 在待确认期间收到新的裸视频 URL 或 URL 批次时，新批次整体替换旧批次；
  旧批次之后不能被一句迟到的“是”保存。
- `/new` 清除当前 conversation 的待确认状态。状态过期、已消费或上下文不匹配时，“是/保存吧”
  不产生任何写入，Agent 要求用户重新发送链接。
- 重启 gateway、LangBot 或恢复会话后，只要仍在有效期内，确认流程应继续有效。

### R7 — Future collection-import seam

- `save_videos` 不直接编排 connector、数据库和 Celery；它调用 tenant-bound ingestion
  submission service。该 service 负责规范化、幂等 item 创建、队列投递和逐项安全结果。
- 当前 1–10 个 URL 和未来收藏夹枚举出的 item 必须复用同一 submission service，不允许为
  收藏夹复制第二套 `ContentItem` 创建、tenant 注入或 enqueue 逻辑。
- connector 保持单内容抓取职责；未来收藏夹/播放列表使用独立 collection enumerator，通过
  cursor/pagination 产生规范化 item references，再交给 submission service。
- 当前任务不实现收藏夹 OAuth、分页、ImportJob/进度和大批量限流，但不得把工具接口或服务依赖
  写死成只有 YouTube 单视频才能扩展的结构。

## Out of Scope

- 用户 1 与用户 57 的重绑、内容迁移或跨用户共享。
- 新的视频平台 connector、播放列表批量导入、文件上传、网页收藏和长期记忆。
- 收藏夹/播放列表的 OAuth 凭据存储、分页枚举、ImportJob 进度模型和大批量限流。
- 用渠道消息同步等待完整 ingestion，或让 Agent 直接执行 SQL/Celery backend 操作。

## Acceptance Criteria

- [ ] 自然语言“帮我保存这个视频 <URL>”会产生一次 `save_videos` tool call；“这个链接讲了什么
  <URL>”不会保存。
- [ ] 明确保存意图无需二次确认即可入队；含糊表达只返回澄清问题，允许持久化 pending
  conversation state，但没有 `ContentItem`、dispatch 或 Celery side effect。
- [ ] 裸视频 URL 固定回复“需要把这个视频保存到知识库吗？”，首次不创建 item、不 enqueue；
  用户在有效会话上下文中肯定后才保存同一 URL。
- [ ] pending URL 只在同 conversation 内有效 10 分钟且单次消费；新 URL 替换旧 URL，`/new`
  清除，重启后仍可恢复，过期/跨 conversation 的“是”不会创建 item 或 enqueue。
- [ ] 2–10 个裸 URL 产生一次包含准确数量的批量确认，确认后一次提交整批；新裸 URL 批次整体
  替换旧批次，不合并出超过 10 个的隐式批次。
- [ ] 工具 schema 不含 `user_id`，微信内部用户 57 创建的 item 只属于 57；跨 tenant 查询不可见。
- [ ] 首次保存返回 `queued`；重复 delivery、模型重复 tool call 和用户重复发送均返回同一
  item 的 `already_exists`，不会产生重复行或无界任务。
- [ ] 一条明确保存消息包含多个 URL 时产生一次批量 tool call；逐项结果保持输入顺序，部分失败
  不回滚成功项，Agent 汇总 queued/already-exists/failed 数量并说明每个失败项的安全原因。
- [ ] 10 个以内按批次处理；11 个或更多 URL 整批无写入地拒绝并提示拆分，不存在静默截断或
  前 10 个已入队的部分副作用。
- [ ] Agent 工具通过 tenant-bound submission service 提交；测试证明当前 URL batch 没有直接
  依赖 connector/Celery 细节，未来 collection enumerator 可复用同一逐项提交 contract。
- [ ] channel 请求在有界时间内返回，不等待字幕抓取/embedding 完成；后台任务可推进
  `fetching → chunking/embedding → ready` 或稳定失败状态。
- [ ] URL 缺失、不支持、含糊意图、queue unavailable 和 ingestion failure 使用不同安全提示；
  不泄露正文、外部身份、secret、DSN、task backend payload 或 traceback。
- [ ] channel 路径不执行远端 metadata/subtitle/embedding 请求；独立 worker 使用 verified CA，
  能把 queued item 推进到 ready 或稳定失败状态。
- [ ] fake-model 工具选择测试、两个 tenant 的 PostgreSQL 集成测试、Celery enqueue 测试、signed
  gateway 回归通过；最终微信自然语言保存 smoke 由人工验收。

## Notes

- Parent task: `08-05-knowledge-retrieval-agent`.
- Status remains `planning`; do not start implementation until `design.md`, `implement.md`, and context
  manifests are complete and reviewed.
