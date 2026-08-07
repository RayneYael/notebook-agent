# 诊断微信单消息双回复

## Goal

定位并修复单个平台入站消息先收到 Notebook Agent 的稳定结果、随后又收到 LangBot
required-plugin fail-closed 文案的问题，保证 bridge 已成功处理并阻止默认 pipeline 时，
LangBot core 不再追加第二条回复。

## Requirements

- 修复必须作用于版本化的 LangBot 4.10.6 补丁源和自动测试，不能只改
  `.runtime/langbot/patched_site` 临时运行目录。
- required-plugin event 校验必须兼容 LangBot plugin runtime 实际返回的
  `PluginContainer.model_dump()` 结构；不得依赖错误的扁平 manifest 假设。
- bridge manifest 匹配且 `prevent_default()` 为真时，校验必须成功；plugin 缺席、runtime
  断开或未阻止默认 pipeline 时仍必须 fail closed。
- 同一个入站消息在 gateway 成功、`not_found`、`embedding_unavailable` 等业务结果下都只能
  产生一条平台回复；Agent 的失败状态不能被误判为 bridge transport failure。
- 诊断和测试只使用内部 query/correlation、plugin ref 与异常类型，不保存截图、消息正文、
  微信昵称、外部 sender ID、二维码或任何 secret。
- 修复后更新部署产物并重启 LangBot；gateway 无需因 core-only 修复再次重启。

## Acceptance Criteria

- [ ] 真实 `PluginContainer.model_dump()` 形状的 fake event 能识别
  `notebook-agent/notebook-knowledge-agent`，且不会调用 `_reply_fail_closed()`。
- [ ] 缺失 required plugin、runtime 断开和未调用 `prevent_default()` 的回归测试仍会 fail closed。
- [ ] pipeline 级测试证明 bridge 已回复任意合法 `AgentAnswer` 后，一个 query 只有一条 adapter
  reply；不会出现 bridge reply + core fail-closed reply。
- [ ] 固定 LangBot 4.10.6 wheel 的 patch dry-run、应用和 Python compile 验证通过。
- [ ] 本地部署重新生成/应用 patched runtime，重启 LangBot 后日志不再出现该消息对应的
  `RequiredPluginEventError`，由人工微信 smoke 确认只有一条回复。

## Notes

- Parent task: `08-06-connect-agent-embedding`.
- This is a lightweight compatibility bug fix; PRD plus root-cause research is sufficient planning.
