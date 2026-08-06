# 诊断微信 /whoami 无响应

## Goal

定位微信个人号私聊发送 `/whoami` 后没有回复的真实失败点，修复最小必要配置或代码，使该命令能够通过现有 LangBot 渠道桥接到 Notebook Agent，并返回稳定的内部用户编号。

## Requirements

- 诊断范围必须覆盖微信 OpenClaw/iLink adapter、LangBot bot 与 pipeline 绑定、私有知识库 Agent 插件、`127.0.0.1:8765` 签名网关以及回复回传。
- 区分“已发现但已修复的问题”和“本次无回复的最终根因”；不能仅凭历史 `No pipeline_uuid` 日志宣告完成。
- LangBot 只承担渠道职责；不得为修复问题而启用 LangBot 内置模型、知识库或第二套对话上下文。
- 首次可信微信身份仍应自助创建独立 `AppUser`；重复 `/whoami` 必须返回同一内部用户编号。
- 诊断和验证不得在日志、任务文档或提交中保存微信私聊正文、昵称、外部 sender ID、扫码二维码、bot token 或共享密钥。
- 保持 Telegram、Slack 的统一 `ChannelEnvelope` 合约不变，不引入微信专用的默认用户或权限旁路。

## Acceptance Criteria

- [ ] 形成一份按时间和层级记录的根因结论，说明消息最后到达的边界、失败机制和修复点。
- [ ] 微信 bot 已启用并绑定专用桥接 pipeline；该 pipeline 只启用 `notebook-agent/notebook-knowledge-agent` 插件。
- [ ] 插件运行时继承正确的 `KB_BOT_CHANNELS`、loopback gateway URL 和共享密钥，未映射 bot 继续 fail closed。
- [ ] Notebook Agent 网关健康，签名校验成功，`/whoami` 创建或解析可信微信身份并返回内部用户编号。
- [ ] 同一微信身份连续发送两次 `/whoami` 得到相同编号，不创建重复 `AppUser` 或 `ChannelIdentity`。
- [ ] LangBot monitoring、bot 日志、plugin 日志和任务证据中不出现私聊正文、昵称或外部 sender ID 明文。
- [ ] LangBot 或 gateway 重启后 pipeline/bot 绑定仍存在，`/whoami` 仍可回复。

## Notes

- 父任务：`08-05-knowledge-retrieval-agent`。
- 已知历史证据：LangBot 曾记录 `No pipeline_uuid for query ... query dropped`；随后已创建 `Notebook Agent Bridge` pipeline 并绑定微信 bot。该证据需要通过新消息重新验证，不能代替端到端验收。
