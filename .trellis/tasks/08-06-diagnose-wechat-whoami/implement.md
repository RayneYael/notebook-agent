# 执行计划

## 1. 建立基线

- [x] 记录固定版本、gateway health、LangBot/plugin runtime 存活状态。
- [x] 读取微信 bot 的 enable、adapter、`use_pipeline_uuid`，以及 pipeline 的精确插件绑定。
- [x] 确认 plugin 子进程拥有 bot UUID → `wechat` 映射、loopback URL 和共享密钥存在性，只记录布尔结果。

## 2. 单消息链路追踪

- [x] 清空观察游标，不删除历史数据；请验收人发送一条 `/whoami`。
- [x] 按同一时间窗口检查 adapter → pipeline → plugin → gateway → reply 五个边界。
- [x] 将最后成功边界、首个失败边界和错误类型写入根因记录，禁止复制私聊正文和外部身份。

## 3. 最小修复

- [x] 配置不是本次根因；保留并复核既有 bot/pipeline/plugin runtime 持久化配置。
- [x] 确认为插件问题；先补失败路径测试，再修改回复回传，重新构建 `.lbpkg` 并安装。
- [x] 保持 LangBot 内置模型未配置，保持隐私补丁有效。

## 4. 验证

- [x] 人工发送 `/whoami`，确认收到内部用户编号。
- [x] 再发送一次，确认编号稳定且数据库无重复身份。
- [x] 重启 gateway 与 LangBot runtime 后复测一次。
- [x] 检查 monitoring、bot/plugin 日志和任务证据均无私聊正文、昵称或 sender ID 明文。
- [x] 运行受影响的自动测试，并把命令、结果与已知限制写入本任务。

## 5. 完成门

- [x] 由人工验收微信回复；自动检查不能替代真实微信收发。
- [x] 更新父任务人工验收清单的对应证据，但不提前勾选 Telegram E2E。
- [ ] 完成 Trellis check、必要的 spec 更新与提交后再归档子任务。
