# 修复 Agent 待确认上下文注入

## Goal

当当前可信 tenant/conversation 存在仍有效的待保存视频批次时，把“正在等待保存确认”这一服务器
状态恢复给 Agent，使用户回复“需要”“可以，保存吧”等自然语言肯定表达时由 Agent 调用
`confirm_video_save`，而不是错误进入知识检索并返回 `no_evidence`。否定表达仍由 Agent 调用
`cancel_video_save`。

## Confirmed evidence

- 微信截图中，裸 URL 正确返回“需要把这个视频保存到知识库吗？”。
- PostgreSQL 中对应 pending action 仍有效、未消费、未取消，URL 数量为 1。
- 第一轮 turn 为 `save_confirmation_required`；第二轮“需要”被错误持久化为
  `not_found/no_evidence`。
- action turn 为避免重放不可信模型 draft，`model_messages` 持久化为空；因此下一轮模型只看到
  孤立短回复，当前又没有可信 pending 状态注入。

## Requirements

- 保持“自然语言 → Agent 判断 → tool call”的产品语义；不得增加 `/save`、关键词表硬编码或绕过
  Agent 直接执行保存。
- Agent 每轮可获得一个只读、可信、tenant/thread-bound 的 pending-save snapshot；只包含是否有效和
  URL 数量，不包含 URL、外部身份、数据库 ID、token 或原消息正文。
- snapshot 查询必须验证当前 `TenantContext.app_user_id`、`channel_identity_id`、open thread、action kind、
  active state 和 10 分钟 expiry；不得消费、取消或刷新 expiry。
- live pending 存在时，动态 Agent instruction 必须明确：短肯定答复（包括“需要”）调用
  `confirm_video_save`，短否定答复调用 `cancel_video_save`，含糊答复继续澄清，明显无关的新问题按
  正常知识流程处理并保留 pending。
- live pending 不存在、已过期、跨 tenant 或跨 conversation 时不得注入“等待确认”状态；短答复不能
  创建 `ContentItem` 或 dispatch。
- action draft 继续完全丢弃；最终用户回复只来自真实 `ActionOutcome`，知识回答的 search/citation guard
  不得放宽。
- 同 platform message ID 重放继续 exactly-once；gateway/LangBot 重启后 live pending 仍可恢复。
- 不记录或返回 URL、消息正文、外部身份、connector/provider payload、secret 或 traceback。

## Out of scope

- 确定性保存命令、长期记忆、通用意图分类器和模型 provider fallback。
- Telegram adapter 创建或平台凭据配置。
- 修改 pending TTL、批量上限、tenant 绑定、submission/worker pipeline 或微信登录协议。

## Acceptance Criteria

- [ ] fake-model 测试证明 live pending 状态进入 trusted dynamic instruction；用户回复“需要”时调用
  `confirm_video_save`，只提交 server-stored URL 一次，不调用 `search_segments`。
- [ ] 肯定、否定、含糊和明显无关问题分别进入 confirm、cancel、澄清和正常知识分支；不使用本地
  关键词表直接执行副作用。
- [ ] PostgreSQL 测试证明 snapshot 查询只读、tenant/thread-bound、expiry-aware；查询前后
  `consumed_at/cancelled_at/expires_at` 不变。
- [ ] expired/missing/cross-tenant pending 不注入可信状态，短答复不创建 item/dispatch。
- [ ] signed ChannelService 回归覆盖裸 URL → “需要” → `queued`，以及 duplicate message exactly-once。
- [ ] explicit save、bare confirmation、cancel、citation guard、turn replay 和现有 save-action E2E 回归通过。
- [ ] 自动测试通过后仅重启 gateway/LangBot/worker，不重置微信 token、channel identity、用户内容或
  pending/action audit；最终微信复测由用户执行。

## Notes

- Parent: `08-06-agent-save-video-tool`.
- 当前验收失败属于上下文恢复边界，不是 pending persistence 或 ingestion failure。
