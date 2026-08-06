# 执行计划

## 1. 固定上游基线与失败测试

- [ ] 取得 LangBot 4.10.6 固定 wheel/source，核对既有研究记录中的 SHA-256；临时
  上游源码不得提交凭据、数据库或运行日志。
- [ ] 增加 patch 可应用测试：对干净 4.10.6 source 先 `patch --dry-run`，再应用到隔离
  临时目录。
- [ ] 用 fake connector、plugin status、event context、adapter 与 processor 写出失败
  测试：早到消息、运行中断线、插件未 emitted、未 prevent default、双 adapter。
- [ ] 加 canary 隐私断言，覆盖 monitoring、EventLogger、processor 和 diagnostic payload。

验证点：测试在 readiness patch 之前应精确失败于 adapter 提前启动或默认 processor 被
调用，而不是失败于 fixture/依赖导入。

## 2. 实现配置与启动 readiness

- [ ] 在固定版本 patch 中为 config template 增加 `required_plugins` 列表和可配置
  readiness deadline；实现严格解析和向后兼容空列表。
- [ ] 在 `PluginRuntimeConnector` 中增加 connection/required-plugin readiness 状态和
  专用 exception；disconnect 时同步清除 ready。
- [ ] 实现 `initialize_plugins()`：按实际 runtime 连接与插件 `initialized` 状态等待，
  条件满足立即返回，deadline 到期失败，不使用盲目固定等待。
- [ ] 保持 `Application.run()` 在 readiness 成功后才创建 `platform-manager` task；确认
  所有 enabled adapters 仍各自启动。

聚焦验证：

```bash
pytest -q tests/test_langbot_startup_patch.py -k 'startup or adapters'
```

## 3. 实现每消息 fail closed 与日志脱敏

- [ ] 只对显式绑定 configured required plugin 的 pipeline 启用严格门。
- [ ] 校验 `emitted_plugins` 和 `prevent_default()`；runtime error 或证据缺失时在
  `_execute_from_stage()` 前终止，并 best-effort 返回固定不可用提示。
- [ ] 扩展固定版本 patch：私聊 EventLogger、MessageProcessor、monitoring 和 plugin
  diagnostic 均不保存正文、昵称、外部 sender ID 或 message preview。
- [ ] 确认错误日志只含内部 query/bot ID、plugin ref、状态、错误类型和耗时。

聚焦验证：

```bash
pytest -q tests/test_langbot_startup_patch.py -k 'fail_closed or privacy'
pytest -q tests/test_langbot_bridge_plugin.py
```

## 4. 更新部署文档

- [ ] 更新 `docs/deployment.md`：固定版本/patch、private plugin `.env` 与 `chmod 600`、
  certifi CA、gateway/plugin/LangBot readiness、plugin-first/adapter-second 顺序。
- [ ] 补充微信首次扫码、二维码过期、token 失效重登录、安全重启、stdio 断线、deadline
  超时、回滚与排障；明确不使用固定 sleep 或内置模型 fallback。
- [ ] 更新 `integrations/langbot_kb_plugin/README.md` 和 `.env.example`，示例只用占位值，
  明确多个 bot UUID 可以同时映射。
- [ ] 同步父任务人工验收文档中的 patch 文件名/步骤，但不提前勾选人工验收项。

## 5. 自动验证与本地运行副本

- [ ] 对干净 4.10.6 source 重跑 patch dry-run、实际应用和聚焦测试。
- [ ] 运行项目回归：

```bash
pytest -q tests/test_langbot_startup_patch.py tests/test_langbot_bridge_plugin.py
pytest -q tests/test_http_gateway.py tests/test_channel_supervisor.py tests/test_multiuser_integration.py
```

- [ ] 只在仓库 patch 通过后，将同一 patch 同步到被忽略的本地
  `.runtime/langbot/patched_site`，复核运行版本和配置存在性，输出不得包含 secret。
- [ ] 检查 git diff：提交物只包括 task artifacts、固定版本 patch、测试和文档；不包含
  `.runtime`、日志、二维码或平台身份。

## 6. 验收交接与完成门

- [x] 已启动 gateway 与 LangBot，并检查 gateway health、required plugin initialized 与
  两个 adapters 的 readiness；这些自动检查的结果记录在 `validation.md`。
- [x] 经用户确认，本子任务只交付 LangBot 启动竞态修复、fail-closed 保护、脱敏和部署
  文档；不重复执行真实平台验收。
- [x] 微信个人号连续 `/whoami`、安全重启回归和日志人工复查移交给直接父任务
  `08-06-diagnose-wechat-whoami`。
- [x] Telegram 完整端到端移交给 `08-05-knowledge-retrieval-agent` 的总体验收清单。
- [x] 自动验证、spec 更新与提交完成后即可归档本子任务；父任务不会因本子任务归档而
  自动完成。

## Rollback points

- 配置/启动门失败：保持 adapters 未启动，撤销 required plugin 配置并恢复已备份的
  LangBot runtime；不得通过配置 Local Agent 继续收消息。
- patch 应用失败：停止，不对半应用 source 启动服务；从干净固定 wheel/source 重建。
- 本地 smoke 回归：停 LangBot adapters，保留 Notebook Agent 数据库与 gateway，撤回
  LangBot patch/runtime 变更；无 schema downgrade。
