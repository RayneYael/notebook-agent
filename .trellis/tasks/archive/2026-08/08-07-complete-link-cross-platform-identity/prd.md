# 完成跨平台身份验证与关联

## Goal

让同一自然人在不同消息平台上的可信渠道账号关联到同一个内部 `AppUser`，从任一已关联平台访问同一份私有知识库，同时保持不同用户之间的租户隔离。

## Background

- 应用已使用 `(channel, account_id, external_user_id)` 识别可信渠道身份，并以 `AppUser` 作为知识库 tenant 根。
- 后端已有一次性 `/link` token 初版，但只能把一个**从未注册过**的目标渠道身份绑定到来源用户；目标账号一旦发过任意其他消息而被自动注册，绑定就会失败。
- Telegram 与微信通过同一 `ChannelEnvelope` 和 LangBot bridge 进入应用；关联流程必须保持框架无关，不能依赖昵称、消息文本中的自报身份或模型判断。
- 现有实现审计和文件定位见 `research/current-link-audit.md`。

## Requirements

### R1. 双端持有验证

- 用户必须先在一个已绑定的来源账号请求关联，再在目标平台账号提交短期凭证，以证明同时控制两个账号。
- 关联命令必须是确定性业务逻辑，不调用 LLM、embedding 或 retrieval。
- 凭证必须高熵、仅存哈希、有明确 TTL、只能成功消费一次，并限定目标 channel。
- 无效、过期、已使用、目标 channel 不匹配、来源用户或身份被禁用时必须 fail closed，且不得改变任何身份或知识库归属。

### R2. 统一租户访问

- 关联成功后，来源身份和目标身份解析到同一个 `AppUser.id`。
- 两端后续的检索、保存和其他 tenant-scoped 操作都只能访问该统一用户的内容。
- 关联不合并跨渠道 conversation history；每个 channel identity / conversation 继续维护自己的会话上下文。
- 同一用户可以关联多个渠道身份；不同用户不能因昵称、展示名、相同平台数值 ID 或模型输出而自动合并。

### R3. 已注册目标账号

- 正常流程必须覆盖目标账号已被当前“首次消息自动注册”机制绑定到另一个 `AppUser` 的情况，不能继续要求用户只能在目标平台的第一条消息中输入 token。
- 即使来源和目标 `AppUser` 都已经拥有知识内容，也必须允许用户通过双端持有验证完成自助关联，不要求管理员手工 rebind。
- 关联必须把两个租户的知识内容、全部渠道身份、渠道内 conversation、pending action 和必要运行状态归并到一个存续 `AppUser`，不能只移动当前目标 identity。
- `/start`、`/whoami` 或普通消息产生的空目标账号使用同一归并路径处理，不保留只对空账号生效的旁路。
- 两个租户保存了同一 `(platform, platform_id)` 内容时必须自动处理唯一键冲突，并明确内容、用户侧元数据、segment 和 ingest dispatch 的保留规则。
- 重复内容必须收敛为一条可见记录并合并双方信息：`saved_at` 取最早值，去重保留双方非空 `why_saved`，观看状态与进度取信息更完整的一侧；内容处理结果优先保留 `ready` 且 segment 更完整的记录，不能仅因来源 tenant 优先而覆盖更完整结果。
- 归并时存在 pending/enqueued/running ingestion 的情况必须有确定策略；worker 不能在归并提交后继续把结果写入已废弃的 tenant 或重复内容记录。
- 任何归属变化必须在单个数据库事务中完成；并发注册、重复消费或跨进程竞争不得产生一个身份对应多个用户、部分迁移或 token 被重复使用。

### R4. 用户反馈与隐私

- 来源端应明确返回目标平台、有效期和目标端操作；目标端应明确返回成功或可行动的失败原因。
- 用户可通过 `/whoami` 在关联前后验证内部用户归属稳定且一致。
- 日志、monitoring、任务证据和异常信息不得记录绑定码、私聊正文、昵称、外部 sender ID 或完整身份映射。
- 平台消息本身必然承载绑定码；应用不得把该消息写入 conversation history 或发送给模型。

### R5. 兼容与清理

- 保持 `ChannelEnvelope -> TenantContext -> tenant-scoped services` 的授权边界，模型工具 schema 仍不得包含 `user_id`。
- 保持现有 Telegram、微信 bridge 协议；未来 Slack 继续使用同一领域流程。
- 新实现必须覆盖或删除 `app/channels/identity.py` 与 `app/channels/service.py` 中当前不可完成常见场景的初版 `/link` 分支，不保留两套相互竞争的关联逻辑。
- 数据库演进必须提供向前迁移、兼容既有 identity/token 数据的策略，以及不删除知识内容的回滚说明。

## Acceptance Criteria

- [x] AC1：来源账号请求关联后，目标平台账号使用有效凭证，两个身份的 `/whoami` 返回同一内部用户编号。
- [x] AC2：关联后从任一平台检索或保存内容都使用同一 tenant；另一个未关联用户始终无法访问这些内容。
- [x] AC3：目标账号已经先发过 `/start`、`/whoami` 或普通消息时，关联流程仍按最终产品决策得到确定、可解释的结果，而不是当前的占位式冲突错误。
- [x] AC4：无效、过期、重放、错误 channel、禁用来源/目标、已关联同一用户和已关联不同用户均有显式结果；失败路径不调用模型且不改变数据。
- [x] AC5：并发消费同一凭证时最多一个请求成功；并发自动注册与绑定不会留下孤立用户、重复 identity 或半迁移数据。
- [x] AC6：两个非空知识库完成自动归并；非重复内容全部可见，重复内容按已确认规则收敛，conversation、pending action、token、segment 和 dispatch 引用保持一致。
- [x] AC7：关联成功后各渠道 conversation history 仍彼此独立；`/new` 和消息幂等行为不回归。
- [x] AC8：自动测试覆盖领域服务、ChannelService 命令、PostgreSQL 并发/迁移和 tenant 隔离；真实 Telegram/微信各完成一次人工双端关联 smoke。
- [x] AC9：README/部署文档不再声称目标账号必须“从未使用”，并说明正常关联、冲突处理、TTL、单次消费和隐私限制。
- [x] AC10：代码库只保留一套生产关联路径；现有占位实现已被覆盖或删除。

## Out of Scope

- 通过昵称、手机号、邮箱或模型推断自动识别同一用户。
- Web 账号中心、OAuth/OIDC、邮件或短信验证。
- 跨渠道共享聊天历史或长期记忆。
- 用户自助解绑、账号找回和被盗账号申诉；这些需要独立的恢复与审计设计。
- 改造 LangBot 内置 Agent/session，或放宽现有 loopback HMAC bridge 和日志脱敏要求。

## Confirmed Product Decisions

- 发起绑定码的来源 `AppUser` 是存续 tenant，因此来源端 `/whoami` 保持稳定；目标账号已注册时，其 tenant 完整归并到来源 tenant。
- 重复内容只保留一条用户可见记录，并合并双方信息，避免丢失保存理由、保存时间、观看进度或更完整的已处理内容。
- 关联成功不共享跨渠道聊天上下文；成功归并不可由用户自动撤销，解绑与账号恢复仍属于独立功能。
