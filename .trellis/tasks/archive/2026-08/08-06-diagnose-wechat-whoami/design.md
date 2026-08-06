# 微信 `/whoami` 无响应诊断设计

## 边界与数据流

诊断按单向链路建立可验证检查点：

1. 微信 iLink adapter 收到私聊事件。
2. LangBot 根据 bot 的 `use_pipeline_uuid` 创建 query。
3. pipeline 只向 `notebook-agent/notebook-knowledge-agent` 发出 `PersonMessageReceived`。
4. 插件从可信事件字段构造 `ChannelEnvelope`，HMAC 签名后请求 loopback gateway。
5. gateway 解析或原子创建 `AppUser` 与 `ChannelIdentity`，执行 `/whoami`。
6. 插件把 `AgentAnswer.text` 写入 reply message chain，由 adapter 发回微信。

任何检查点都只记录内部 bot UUID、内部 user ID、相关性哈希、状态码和耗时；不记录消息正文或外部身份明文。

## 诊断策略

- 先做只读状态检查：进程、health、bot enable、pipeline UUID、pipeline extension binding、plugin initialized 状态。
- 再使用一条由人工发送的 `/whoami` 作为唯一真实平台探针，并以时间窗口关联各层证据。
- 若消息未进入 adapter，检查 iLink 长轮询、授权状态与 adapter 运行日志。
- 若出现 `No pipeline_uuid`，检查数据库持久化和 bot runtime reload，而不是只修改前端状态。
- 若 plugin 未触发，检查 pipeline 的 bound plugin 格式、事件种类和插件 runtime 初始化。
- 若 plugin 触发但 gateway 无请求，验证子进程环境继承、bot UUID 映射和 loopback 网络命名空间。
- 若 gateway 返回但微信无回复，检查 `prevent_default` / `prevent_postorder` 与 reply chain 的 LangBot 4.10.6 事件语义。

## 兼容与安全

- 固定 LangBot 4.10.6 与 plugin SDK 0.4.13。
- 保留 monitoring 脱敏补丁；修复不得恢复 LangBot 默认 MessageProcessor 处理私聊正文。
- 不增加默认用户、昵称匹配或跨渠道自动合并。
- 不配置 LangBot 内置 Agent；pipeline 的存在只用于事件路由。

## 回滚

- 配置回滚：暂时禁用微信 bot，保留扫码 token、pipeline 和已安装插件以便继续诊断。
- 代码回滚：撤回本子任务的最小插件修复并重新打包安装；Notebook Agent 数据模型和用户知识库不回滚。
- 若可信 sender 身份不稳定，停止实测并报告阻塞，不降级为共享身份。

