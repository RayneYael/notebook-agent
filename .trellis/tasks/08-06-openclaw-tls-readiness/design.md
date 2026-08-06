# OpenClaw TLS 与 adapter readiness 设计

## 1. Boundary

版本化改动只落在 LangBot 4.10.6 patch、Notebook Agent launcher/config、测试和部署文档。
`.runtime/langbot/patched_site` 是生成产物，可以用于 smoke，但不是修复的 source of truth。

## 2. CA resolution

在启动 OpenClaw adapter 前按确定顺序解析 CA：

1. 已显式配置且可读的部署 CA；
2. LangBot 当前 Python 环境的 certifi bundle；
3. Python/OpenSSL 已配置的默认 CA（若真实存在）。

将结果应用到 aiohttp 使用的 verified SSL context，或在 client 创建前注入其实际识别的标准
变量。预检路径存在性/可读性，并用真实 TLS handshake 证明证书链可验证。禁止关闭验证。

## 3. Adapter state machine

```text
starting
  → authenticating
  → polling
  → healthy
       ↘ transient failure → degraded/retrying → polling
  → certificate/config failure → failed
  → stopped
```

`run_async()` 启动 background task 只表示 started，不能设置 healthy。第一次成功 login/poll 后才
healthy；每次 poll 成功更新 last-success。异常按类别映射稳定错误码，证书错误直接标记 failed
或让 preflight 阻止 adapter 启动。暂时错误允许有界指数退避，状态保持 degraded。

## 4. Health contract

通过现有可扩展的 adapter health/management status 暴露：adapter、state、stable error code、
last-success age、retry count/next retry 和 exception class。若现有 `/healthz` 只能表达进程级状态，
不得破坏其兼容格式；新增 detail/readiness 或管理状态，并在部署文档解释差异。

required plugin readiness 与 adapter readiness 是两个独立条件：前者阻止 bridge 未就绪时启动
channels，后者证明特定 channel 能与上游平台交换数据。

## 5. Error and privacy contract

| Error | State | Code | Retry |
| --- | --- | --- | --- |
| CA missing/unreadable | failed | `certificate_verification_failed` | configuration change required |
| certificate chain/hostname failure | failed | `certificate_verification_failed` | no blind retry loop |
| timeout/reset/DNS | degraded | `upstream_unavailable` | bounded backoff |
| auth/login expiry | degraded or failed per existing protocol | existing safe auth code | preserve existing relogin behavior |

日志不包含 token、QR payload、cookie、message、nickname 或 external ID。完整 traceback 可以保留在
受控 debug 级别，但常规错误必须有单行 stable diagnostic。

## 6. Compatibility and rollback

不改变 OpenClaw API request/response、login 或 message handling。Telegram 与 required plugin 流程
应保持不变。若 health reporting 有兼容风险，可回滚展示层，但必须保留 verified CA 和“不在 TLS
永久失败时报告 healthy”的安全性质。
