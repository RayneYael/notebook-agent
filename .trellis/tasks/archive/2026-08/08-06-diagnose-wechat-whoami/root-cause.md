# `/whoami` 无回复根因记录

## 结论

失败点位于 LangBot 4.10.6 的早期事件回复回传，不在微信扫码登录、模型配置或
Notebook Agent gateway。

桥接插件监听 `PersonMessageReceived` 并调用 `prevent_default()`，这是为了在
LangBot 的后续消息处理器记录正文和外部身份之前截断默认流程。旧实现随后把回复
写入 `event.reply_message_chain`。但 `PipelineManager.process_query()` 在该早期事件
返回后检测到 default 已被阻止，会立刻返回，不会消费这个字段，因此回复被静默
丢弃。

这里不能简单改用更晚的 `PersonNormalMessageReceived`：那会先进入 LangBot 的
`MessageProcessor`，破坏私聊正文和外部身份不落日志的隐私要求。

## 最后成功与首个失败边界

- adapter 已启用，类型为 `openclaw-weixin`。
- bot 已精确绑定 `Notebook Agent Bridge` pipeline。
- pipeline 关闭“启用全部插件”，只绑定
  `notebook-agent/notebook-knowledge-agent`。
- 插件环境具备 loopback URL、共享密钥和 bot UUID → `wechat` 映射；证据只记录
  布尔值。
- 历史消息未创建任何 `wechat` identity，说明请求没有进入 gateway 的身份解析。
- 最后成功边界：插件的早期事件监听器收到并拦截消息。
- 首个失败边界：早期事件回复仅写入 `reply_message_chain`，随后 pipeline 提前返回。

## 修复

插件仍监听早期 `PersonMessageReceived`，仍阻止默认和后序处理，但改用
`await EventContext.reply(...)`。该 API 通过 LangBot 的 query-scoped
`REPLY_MESSAGE` action 直接调用当前 adapter 的 `reply_message()`，不依赖后续
pipeline 消费 `reply_message_chain`。

插件版本由 `0.1.0` 更新为 `0.1.1`，已重新构建并在本地 LangBot 安装。运行时日志
确认插件完成 mount、initialize；bot 与 pipeline 绑定在升级后保持不变。

## 自动验证

- `pytest -q tests/test_langbot_bridge_plugin.py`：2 passed。
- `pytest -q tests/test_http_gateway.py tests/test_channel_supervisor.py tests/test_langbot_bridge_plugin.py`：5 passed。
- `GET http://127.0.0.1:8765/health`：`status=ok`。
- 修复后、人工复测前数据库基线：users=1、identities=0、wechat identities=0。

## 人工验证结果

- 用户确认同一微信账号重复 `/whoami` 返回相同内部用户编号；任务记录不保存该编号。
- gateway 与 LangBot 按安全顺序重启后，required bridge 在 adapter 开放前达到
  `initialized`，两个 health endpoint 均正常；用户再次确认 `/whoami` 回复和内部编号
  均正常。
- 只读聚合查询确认重复微信身份键数量为 `0`，未读取或输出外部身份值。
- 本次重启后的 LangBot monitoring 没有保存消息或 error 记录，因此没有 `/whoami`
  正文落入 monitoring；用户随后在管理面板完成 monitoring 与 bot/plugin 日志复查，
  确认未发现私聊正文、昵称或外部 sender ID 明文。
