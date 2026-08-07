# Agent 待确认上下文注入：技术设计

## 1. Boundary

修复只跨越 `PendingConfirmationService → AgentActionRuntime/AgentDeps → PydanticAI dynamic
instructions`。pending 数据库仍是唯一事实源；模型 history 不承担恢复 pending URL 的职责。

不在 ChannelService 中匹配“需要/是/可以”等关键词，也不直接调用 submission。Agent 仍解释自然
语言并选择 `confirm_video_save`、`cancel_video_save` 或其他路径；应用只提供可信状态。

## 2. Read-only pending snapshot

在 pending service 增加只读查询，例如：

```python
@dataclass(frozen=True)
class PendingSaveSnapshot:
    active: bool
    count: int = 0

def inspect_save(tenant: TenantContext, thread_id: int) -> PendingSaveSnapshot: ...
```

查询约束：

- thread 同时匹配 `thread_id`、tenant app user、channel identity 且未关闭；
- action kind 为 `save_videos`，未 consumed/cancelled，且 `expires_at > database now()`；
- payload version/URL list 结构合法且数量为 1–10；
- 不使用 `FOR UPDATE`，不写任何时间戳，不返回 URL/action ID。

数据库异常应 fail closed 为“无可用 snapshot”，不能把异常或 pending 内容交给模型。

## 3. Agent injection

`AgentActionRuntime` 每个 run 最多读取一次 snapshot 并缓存 count。PydanticAI 使用基于 deps 的动态
instruction 注入服务器状态，而不是修改 `AgentRequest.question` 或伪造用户/assistant history：

```text
可信服务器状态：当前 conversation 有 N 个视频等待保存确认。
把本条短回复作为确认语义判断：明确肯定调用 confirm_video_save；明确否定调用
cancel_video_save；含糊则澄清；明显无关的新问题按正常流程处理。不要为确认回复调用知识检索。
```

instruction 只暴露数量。最终 confirm tool 仍无 URL 参数，并由 pending service 原子消费 server-stored
batch；模型不能选择或重构目标。

## 4. Persistence and replay

模型 action draft 继续不持久化。canonical assistant text、answer status/error、action results 与 pending
row 共同支持恢复。相同 message ID 的 duplicate reply 继续由 ChannelService turn replay 拦截，不再次
运行 Agent/tool/broker。

## 5. Failure and compatibility

- snapshot missing/expired/malformed：不注入 pending 状态；现有 confirmation-missing 合同不变。
- snapshot DB failure：不泄露异常，Agent 按没有可信 pending 处理。
- unrelated knowledge question：仍必须 search/cite，pending 保持未消费。
- feature flag 关闭：不读取/注入 save pending，不执行 action side effect。
- rollout 只需 compatible gateway 代码；数据库 schema、worker task 和 LangBot patch 不变。

## 6. Rollback

关闭 `AGENT_SAVE_ENABLED` 或回滚 gateway 即可停止该注入；pending/action rows 保留。不得 downgrade、
删除 pending 或重置微信登录来处理此问题。
