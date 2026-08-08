# Notebook Agent 启动与部署手册

本文覆盖当前 P1 的受支持部署方式：PostgreSQL/pgvector、Redis、MinIO、
Notebook Agent gateway，以及 LangBot 4.10.6 的 Telegram/微信 adapter 与薄桥接插件。
真实平台验收步骤另见 Trellis 任务中的 `manual-acceptance.md`。

如果当前目标只是配置 `.env`、MCP 或可选 LangBot bridge，请先阅读
[环境配置指南](environment-configuration.md)。本手册保留拓扑、启动顺序、systemd、
日志、备份、回滚和故障排查等运维流程。

## 1. 部署拓扑

```text
Telegram --------\
                  LangBot core + enabled adapters
WeChat ----------/             |
                                v
                     LangBot plugin runtime
                                |
                    HTTP + HMAC over loopback
                                |
                  Notebook Agent gateway-server
                    |          |              |
                 Agent      query embedding  PostgreSQL
                  model          API          + pgvector
                                                  |
                                    durable ingest dispatch
                                                  |
                             Redis queue -> Celery worker
                                                  |
                                 MinIO + embedding API
```

安全边界有一个重要限制：`gateway-server` 只允许绑定 `127.0.0.1`、`::1` 或
`localhost`，插件也只允许调用 loopback URL。因此，**Notebook Agent gateway 与
LangBot plugin runtime 必须共享网络命名空间**。

受支持的放置方式：

- 本地验收：两者都作为宿主机进程运行。
- Linux 单机：两者都作为同一宿主机上的 systemd 服务运行。
- Kubernetes：两者作为同一个 Pod 内的两个 container，Pod 内共享 loopback。
- Docker：把两者放在同一 container，或让 plugin runtime 使用
  `network_mode: service:<agent-service>` 共享 Agent container 的网络命名空间。

不支持把 plugin runtime 放在普通独立 container、再把 gateway 暴露到公网或局域网。
如果未来必须跨主机部署，应另行设计 mTLS/private network 边界，不要放宽当前
loopback 检查。

## 2. 运行要求

- Python 3.11。
- Docker + Docker Compose，用于项目自带的 PostgreSQL 17/pgvector、Redis、MinIO。
- 一个监听 `ingest` queue 的兼容 Celery worker；保存功能不得由 gateway 同步抓取。
- LangBot 4.10.6 与 `langbot-plugin` 0.4.13。
- 一个 embedding provider；当前 segment 维度固定为 1536。
- 一个 PydanticAI 支持的模型 provider，或 OpenAI-compatible gateway。
- Telegram bot token；微信个人号验收使用 LangBot OpenClaw/iLink 扫码。

凭据只能进入未提交的 `.env`、systemd `EnvironmentFile`、容器 secret 或平台 secret
存储。不要把 Telegram token、微信二维码、模型 key、绑定码写入仓库或日志。

### macOS TLS CA

当前部署已经可以成功登录并持续轮询 WeChat；这是本 patch 必须保留的默认基线。没有显式 CA
覆盖时，OpenClaw 继续使用 LangBot/aiohttp/Python 原有的已验证 TLS 行为：不强制选择 certifi、
不改写 `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`，也不额外发送 TLS preflight GET。

通常不必手工配置 macOS。仅当部署需要企业/私有 CA，或 adapter readiness 显示
`certificate_verification_failed` 时，才在对应 OpenClaw bot 的 adapter config 设置
`tls_ca_bundle`，或在启动 LangBot 的环境设置 `TLS_CA_BUNDLE`。其值必须是可读的 PEM bundle；
patch 会创建只供该 OpenClaw client 使用的 `CERT_REQUIRED` / hostname-checked TLS context。
可用下列命令定位候选 CA 文件：

```bash
.venv/bin/python -c 'import certifi; print(certifi.where())'
```

将输出路径作为 `tls_ca_bundle` 或 `TLS_CA_BUNDLE` 的值后再启动 LangBot：

```dotenv
TLS_CA_BUNDLE=/absolute/path/to/certifi/cacert.pem
```

该变量不是 secret；不要把机器上的绝对路径当作可移植默认值提交到仓库。无效的显式覆盖会以
`certificate_verification_failed` fail closed；移除或修正该覆盖后再启动。Linux 镜像若已经有
正确 CA bundle，不需要添加任何覆盖。不要使用 `ssl=False`、unverified SSL context、HTTP
endpoint 或忽略证书异常作为临时修复。

Notebook Agent gateway 与独立 Celery worker 都会在各自进程中解析可信 CA：优先使用可读的
`TLS_CA_BUNDLE`，其次是已有的 `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`，最后是该
环境的 certifi bundle。gateway 将它用于 query embedding，worker 将它用于 ingestion
embedding；模型 provider 通过标准环境变量取得同一 bundle。两个进程必须显式获得一致配置，
不能因为 gateway 正常就假设 worker 自动继承其进程环境。
显式配置了不存在或不可读的 `TLS_CA_BUNDLE` 时，修正配置后再启动，绝不要用关闭 TLS
校验作为替代方案。

## 3. 首次安装

在项目根目录执行：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

不要从这份长手册逐项猜测 `.env`。先打开
[环境配置指南](environment-configuration.md)，选择一个运行场景并复制对应的最小配置：

- 本地只读/stdio MCP：PostgreSQL、embedding、Agent provider；不需要 Redis、MinIO 或 worker。
- 完整 MCP：再加入 Redis、MinIO、Celery worker/beat 和 management feature flags。
- Streamable HTTP / MiXer：配置 MCP listener、TLS proxy 和每用户 grant。
- LangBot：额外配置 gateway，以及安装插件目录中的独立私有 `.env`。

指南后半部分是完整变量字典，标明消费者、默认值、适用场景、secret 属性和重启范围。
根 `.env`、stdio 的进程级 `MCP_TOKEN`、LangBot plugin 私有 `.env` 是三个不同边界，
不得互相复制整份内容。

## 4. 数据服务与 migration

启动项目自带基础服务：

```bash
docker compose up -d
docker compose ps
```

等待 postgres、redis、minio 都显示 healthy，然后执行：

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
```

当前 head 应为 `e5f6a7b8c9d0`，`alembic check` 应显示没有新的 upgrade operation。

如果 Agent 自身也容器化，数据库主机应使用 Compose service 名 `postgres`；如果
Agent 运行在宿主机，使用当前示例中的 `localhost:5432`。

## 5. 模型与 embedding 配置

直接 provider 使用 PydanticAI 的模型名和该 provider 所需凭据。OpenAI-compatible
gateway 示例：

```dotenv
AGENT_MODEL=openai:your-model-name
AGENT_API_KEY=replace-me
AGENT_BASE_URL=https://gateway.example/v1
```

首版不做模型 provider 自动 fallback。更换 provider 只修改配置，不修改 Agent
prompt、tool schema、tenant dependency 或 `AgentAnswer`。

embedding 的模型和维度必须与已写入数据库的 `segment.embedding vector(1536)` 保持一致：

```dotenv
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSIONS=1536
EMBEDDING_BATCH_SIZE=64
```

普通知识问题在进入 BM25/pgvector 前会先生成并校验 query embedding；缺少 key、provider
故障、响应维度不符或含非有限数值时，请求会以“查询能力暂时不可用”结束，**不会**降级成
看似成功的纯词法回答。`/start`、`/whoami`、`/link`、`/new` 是确定性身份/会话命令，
不调用模型或 embedding，因此仍可用。成功但没有 tenant-owned 证据时，回复会说明知识库
没有足够证据；这与“查询能力暂时不可用”是两种不同状态，排障时不要混淆。

## 6. 启动 ingestion worker 与 Notebook Agent gateway

### 6.1 readiness 与 Celery worker

保持 `AGENT_SAVE_ENABLED=false` 与 `AGENT_ITEM_MANAGEMENT_ENABLED=false`。先确认三个依赖均 ready：

```bash
docker compose ps
docker compose exec -T redis redis-cli ping
curl --fail http://127.0.0.1:9000/minio/health/ready
.venv/bin/alembic current
```

通过条件分别为 postgres/redis/minio healthy、Redis 返回 `PONG`、MinIO ready endpoint
返回成功、schema 为 `e5f6a7b8c9d0 (head)`。若 worker 不与 Redis 位于同一主机，必须在
worker 的私有环境中显式设置完整 `REDIS_URL`；不要依赖示例的 localhost 默认值。

在独立终端或受管理服务中启动消费 `ingest` 与 `maintenance` queue 的 worker：

```bash
.venv/bin/celery -A app.ingest.tasks.celery_app worker \
  --loglevel=INFO --queues=ingest,maintenance

# 只启动一个 beat 实例，定期投递有界 maintenance purge task。
.venv/bin/celery -A app.ingest.tasks.celery_app beat --loglevel=INFO
```

从同一环境检查 worker：

```bash
.venv/bin/celery -A app.ingest.tasks.celery_app inspect ping
.venv/bin/celery -A app.ingest.tasks.celery_app inspect active_queues
```

至少一个目标 worker 必须返回 `pong`，且 active queue 包含 `ingest` 与 `maintenance`。worker 必须拥有
PostgreSQL、Redis、MinIO、`ZHIPU_API_KEY` 和可信 CA 配置；不得在 gateway 请求进程内同步
执行 metadata、字幕、MinIO、chunk 或 embedding。worker 的任务参数只应是内部 dispatch ID。

### 6.2 gateway

前台启动，适合首次排错：

```bash
.venv/bin/python -m app.cli gateway-server
```

另一个终端检查：

```bash
curl --fail http://127.0.0.1:8765/health
```

预期返回 `{"status": "ok"}`。该 endpoint 是进程存活检查，不会主动调用模型或
数据库；数据库检查使用 `alembic current`，真实模型/检索检查使用后面的 CLI smoke。

只有 migration、worker、Redis、MinIO 和 gateway 均 ready 后，才把 gateway 私有环境中的
feature flag 改为：

```dotenv
AGENT_SAVE_ENABLED=true
AGENT_ITEM_MANAGEMENT_ENABLED=true
```

然后只重启 gateway 使配置生效；不要重置 LangBot channel identity、微信登录或已有 content。

生产环境不要把 8765 端口映射到公网。保持：

```dotenv
CHANNEL_GATEWAY_HOST=127.0.0.1
CHANNEL_GATEWAY_PORT=8765
```

## 6.5 MCP 核心入口（无需 LangBot）

MCP 是 Notebook Agent 的核心评测入口，LangBot 只负责可选的个人微信/Telegram
渠道适配。安装 `.[dev]` 会固定官方 Python SDK `mcp==2.0.0`；`app/` 不导入
LangBot SDK，删除 `integrations/` 不影响 MCP 或 CLI。

### 6.5.1 stdio 本地验收

stdio 的 stdout 只能包含 MCP 协议字节，应用诊断会写入 stderr 和受限的私有日志。
先为目标用户签发 grant，再把 raw token 只传给该 stdio 进程：

```bash
.venv/bin/python -m app.cli mcp-grant issue --user-id 12 --scope read --label local-stdio
MCP_TOKEN='<raw-token>' \
  .venv/bin/python -m app.cli mcp-server --transport stdio
```

用官方 MCP client/Inspector 初始化后执行 `tools/list`，再调用
`ask_notebook_agent` 的自然语言问题。仅调用 `tools/list` 不能证明 Notebook
Agent 的模型执行。

### 6.5.2 Streamable HTTP 与授权

默认配置是 `MCP_HOST=127.0.0.1`、`MCP_PORT=8000`、`MCP_PATH=/mcp`。公开部署必须
使用 HTTPS 和反向代理，优先传 `Authorization: Bearer <token>`：

```bash
.venv/bin/python -m app.cli mcp-grant issue --user-id 12 --scope full --label mixer
.venv/bin/python -m app.cli mcp-server --transport streamable-http
```

grant 的原始 token 只在 issue/rotate 时显示；数据库只存哈希，`list`/`show` 不会
显示 bearer。每个 grant 映射一个稳定 MCP principal、一个 `AppUser` 和 `read` 或
`full` scope；服务端每次请求都检查禁用、撤销和可选过期。浏览器/demo 使用
`read` grant，且应为每个浏览器会话生成新的高熵 `conversation_id`。

MiXer 等 URL-only 客户端只有在显式设置 `MCP_URL_TOKEN_MODE=true` 后才能使用
`/mcp/c/<opaque-token>`。仅接受 HTTPS 动态路径，随后内部改写为 `/mcp`；不接受
`?token=`，应用和代理访问日志必须省略或 redaction 完整 request URI。竞赛结束或
疑似泄露后立即 rotate/revoke。

MCP 进程可用性不等于数据库、模型、embedding、Redis、MinIO、Celery 或 maintenance
readiness。read-only 问答可以不启动 Redis/MinIO/worker；启用 full 的保存、重试和
回收站操作前，必须检查相应依赖和 migration `e5f6a7b8c9d0 (head)`。

## 7. 安装 LangBot 桥接（可选）

### 7.1 应用启动就绪与隐私补丁

在固定版本 LangBot 4.10.6 源码根目录执行：

```bash
patch --dry-run -p1 < /absolute/path/to/notebook-agent/integrations/langbot-4.10.6-redact-monitoring.patch
patch -p1 < /absolute/path/to/notebook-agent/integrations/langbot-4.10.6-redact-monitoring.patch
```

文件名因兼容性保留 `redact-monitoring`，但补丁同时实现三件事：

1. monitoring、adapter 日志、MessageProcessor 与 plugin diagnostic 不复制私聊正文、
   昵称、外部 sender ID 或 message preview；
2. 当 `plugin.required_plugins` 非空时，LangBot 只会在这些插件的 runtime 状态全部为
   `initialized` 后启动任何 enabled adapter；
3. 对显式绑定 required plugin 的 pipeline，每条消息都必须确认该插件处理了早期 event
   并调用 `prevent_default()`。runtime 断线、插件缺席或未阻止默认处理时，LangBot
   只返回固定“渠道暂时不可用”提示，绝不回退到 Local Agent。
4. OpenClaw/iLink 的普通登录和长轮询保持 upstream 已验证 TLS 行为；只有显式设置
   `tls_ca_bundle` 或 `TLS_CA_BUNDLE` 时才为该 client 创建可追踪的 verified CA context。
   无论使用哪条路径，都只有成功完成 `getUpdates` poll 才将微信 adapter 标为 `healthy`。

把下列配置写入 LangBot 的 `data/config.yaml`。本项目必须明确配置 bridge plugin；留空
会保留上游兼容行为，但不会得到本部署的启动保护。

```yaml
plugin:
  required_plugins:
    - notebook-agent/notebook-knowledge-agent
  required_plugins_ready_timeout_seconds: 30
```

deadline 是最长等待时间，不是启动延迟：状态首次达到 `initialized` 会立即开放全部
adapter；30 秒仍未达到时 LangBot 退出且 adapter 不会启动。由 systemd/Docker 重启或
人工排障，**不要添加固定 `sleep`，也不要配置 LangBot 内置模型作为 fallback**。

环境变量部署可使用等价的 `PLUGIN__REQUIRED_PLUGINS`（逗号分隔）和
`PLUGIN__REQUIRED_PLUGINS_READY_TIMEOUT_SECONDS`。变更后必须重启 LangBot；不要编辑
被忽略的 `.runtime/langbot/patched_site` 作为长期配置来源。

补丁只支持 wheel SHA-256 为
`ee950fd6a687cb8c7cfe646d2b9a92cfbf09b3ddfbaf8f43ea0613905d3ffbff` 的
LangBot 4.10.6。升级版本时重新取得上游 source、先做 `--dry-run`，再重新审查全部 hunk。
未应用补丁时不得通过隐私或渠道可用性验收。

启动时必须使用应用了该补丁的同一份 Python package。仅仅在另一个源码目录执行
`patch`，不会改变已安装的 `langbot` 命令；这种情况下旧版的 readiness gate 可能仍是
空实现，而 `/healthz` 仍会返回 200。源码树或本机生成的 patched package 需要显式放到
运行时搜索路径，例如：

```bash
PYTHONPATH=/absolute/path/to/patched_site \
  /absolute/path/to/langbot-venv/bin/langbot
```

启动前可用下面的只读检查确认解释器加载了目标文件（不要打印环境变量或 secret）：

```bash
PYTHONPATH=/absolute/path/to/patched_site \
  /absolute/path/to/langbot-venv/bin/python -c \
  'import inspect; from langbot.pkg.plugin.connector import PluginRuntimeConnector; \
print(inspect.getsourcefile(PluginRuntimeConnector))'
```

输出必须指向已应用补丁的 `langbot/pkg/plugin/connector.py`；之后仍要以
`Required plugins initialized; message adapters may start.` 作为 readiness 判据。

### 7.2 安装 plugin

把整个目录复制或挂载到 LangBot plugin workspace：

```text
integrations/langbot_kb_plugin/
```

将 `.env.example` 复制到**LangBot 已安装插件目录**的 `.env`，而不是项目根目录的
`.env`。LangBot plugin worker 在非 Windows 环境从该安装目录加载其私有 `.env`：

```bash
cp /absolute/path/to/notebook-agent/integrations/langbot_kb_plugin/.env.example \
  /absolute/path/to/langbot/data/plugins/notebook-agent__notebook-knowledge-agent/.env
chmod 600 /absolute/path/to/langbot/data/plugins/notebook-agent__notebook-knowledge-agent/.env
```

plugin runtime 私有配置：

```dotenv
CHANNEL_GATEWAY_SECRET=与Notebook-Agent完全相同的值
CHANNEL_GATEWAY_URL=http://127.0.0.1:8765/v1/messages
KB_BOT_CHANNELS={"telegram-bot-uuid":"telegram","wechat-bot-uuid":"wechat"}
```

`KB_BOT_CHANNELS` 必须列出每个启用 bot 的 UUID；没有默认值，未映射的 bot 会
fail closed。UUID 来自 LangBot bot 配置，不是 Telegram 用户 ID 或微信昵称。
同一个私有 `.env` 可以同时映射 Telegram、微信和后续其他 adapter 的多个 bot UUID。
不要在 LangBot core 的日志、systemd unit、截图或工单中粘贴该文件内容。

### 7.3 配置并同时启用渠道

在 LangBot 中：

1. 新建并启用 Telegram bot adapter。
2. 新建并启用 OpenClaw/iLink 微信 adapter，完成个人号扫码。
3. 两个 bot 都绑定安装了 bridge plugin 的 pipeline。
4. 两个 adapter 保持 enabled；不要配置“当前渠道”开关。

bridge pipeline 必须关闭“启用全部插件”，并显式只绑定
`notebook-agent/notebook-knowledge-agent`。这正是运行时 fail-closed gate 的适用范围；
不要把 required bridge 仅靠全局自动发现绑定。

### 7.4 OpenClaw TLS 与 adapter readiness

`/healthz` 保持进程级兼容语义：它只说明 LangBot HTTP process 可响应，不能证明微信
上游仍可 poll。应用补丁后，登录管理面可通过受认证接口查看 adapter 级状态：

```bash
curl --fail -H 'Authorization: Bearer <LangBot-admin-token>' \
  http://127.0.0.1:<LangBot API port>/api/v1/platform/adapters/readiness
```

返回项只包含 adapter 名称、`state`、稳定 `error_code`、`exception_class`、最近一次成功 poll
的年龄、retry 次数/下次 retry，以及 CA bundle 路径；不会包含微信 token、二维码、昵称、外部
用户 ID、消息正文、cookie 或 provider payload。不同版本的 LangBot 管理认证 header 可能不同，
请使用该部署既有的管理员认证方式，且不要把 token 贴入终端历史、日志或工单。

状态解释：

| state | 含义与操作 |
| --- | --- |
| `starting` / `authenticating` | adapter 已开始但尚无成功 poll；它不是 healthy。等待登录或检查启动日志。 |
| `healthy` | 至少一次 `getUpdates` 成功；随后每次成功 poll 刷新 success age。验收需要连续三次成功 poll 或持续两分钟 healthy。 |
| `degraded` | DNS、timeout、reset 或临时 upstream 故障；adapter 以 1–10 秒的有界指数退避重试，状态包含安全的错误类别与 retry metadata。 |
| `failed` + `certificate_verification_failed` | 显式 CA 覆盖不可读/无效，或真实证书链/hostname 无法验证；不会无限 retry。修正或移除显式覆盖后安全重启 LangBot。 |
| `failed` + `authentication_failed` | 维持既有登录失败语义；检查受保护的登录管理流程，不要在健康接口或日志中复制二维码/token。 |
| `stopped` | 已按正常停止流程终止。 |

正常路径没有 CA preflight；真实 poll 的非证书网络失败会显示 `degraded/upstream_unavailable`，
再以 verified TLS 重试。若状态是 `certificate_verification_failed`，重新扫码不会修复根证书
问题。确认或移除显式 CA bundle 后只重启 LangBot core/adapter，不要重置 Telegram token、
微信登录、bot UUID、用户绑定、conversation history 或内容数据。

平台配置参考：

- Telegram：https://docs.langbot.app/en/usage/platforms/telegram
- 微信个人号：https://docs.langbot.app/en/usage/platforms/wechat/weixin

## 8. 完整启动与停止顺序

首次开启自然语言保存或升级：

1. PostgreSQL、Redis、MinIO。
2. 保持 `AGENT_SAVE_ENABLED=false` 与 `AGENT_ITEM_MANAGEMENT_ENABLED=false`，备份后执行 `alembic upgrade head` 并确认 current/check。
3. 部署并启动兼容 Celery worker，确认它监听 `ingest,maintenance`，并启动单一 beat 实例；CA/Redis/MinIO 均 ready。
4. 部署并启动 Notebook Agent `gateway-server`，检查 loopback health 与只读检索 smoke。
5. 设置 `AGENT_SAVE_ENABLED=true` 与 `AGENT_ITEM_MANAGEMENT_ENABLED=true` 并重启 gateway；不得重置 channel login、identity 或 content。
6. 确认已应用 TLS/readiness patch；保留已证实的默认登录/轮询路径。仅有企业 CA 需求或明确
   诊断时，在 LangBot 进程中设置 `tls_ca_bundle` 或 `TLS_CA_BUNDLE`。不要禁用 TLS verification。
7. Docker/WebSocket 模式先启动 plugin runtime；stdio 模式由 LangBot core 启动它。
8. 启动 LangBot core。patched core 会先连接 runtime、检查 bridge plugin 为
   `initialized`，**之后**才启动每个 enabled adapter；不要手工改变这个顺序。
9. 检查 readiness；自动化验证通过后，Telegram 完整 E2E 与微信保存 smoke 仍由人工执行。

readiness 检查不使用“等待 N 秒”。在 LangBot 进程日志中确认
`Required plugins initialized; message adapters may start.`，再确认：

```bash
curl --fail http://127.0.0.1:<LangBot API port>/healthz
```

HTTP `healthz` 只有在 application 已通过启动 gate 并创建 HTTP task 后才会返回成功，不能
替代微信 poll 检查。接着查询 `/api/v1/platform/adapters/readiness`：OpenClaw 必须是
`healthy`，并满足连续三次成功 poll 或保持两分钟 healthy；`starting`、`degraded` 或 `failed`
都不能作为微信可用证据。管理面板的 plugin 详情还必须显示 bridge status 为 `initialized`；
若 deadline 超时，先检查 plugin package、其私有 `.env` 权限、gateway health 和 CA，再重启
LangBot。不要先启动 adapter 试图“等它自己恢复”。

日常停止采用相反顺序：

1. 停 LangBot adapters/core，停止接收新消息。
2. 停 plugin runtime。
3. 关闭 `AGENT_SAVE_ENABLED` 与 `AGENT_ITEM_MANAGEMENT_ENABLED` 并重启/停止 Notebook Agent gateway，阻止新 submission/management calls；保留 maintenance worker/beat 以继续安全清理，或按需暂停 beat。
4. 让 active ingestion 完成；需要立即止损时再停止 Celery worker。
5. 确认没有 ingestion 工作后，再按需停止 Redis、MinIO 与 PostgreSQL。

不要在消息处理中直接执行 migration downgrade。生产 downgrade 前必须完成 PostgreSQL/MinIO
备份，关闭 `AGENT_ITEM_MANAGEMENT_ENABLED` 与 Celery beat，确认所有回收站条目已经逐项恢复或
完成对象删除 + 数据库 purge，并执行普通库存与 semantic/BM25 检索 smoke，确认没有软删除内容
复活。migration 会在发现任何 `deleted_at IS NOT NULL` 行时主动拒绝 downgrade，不会通过删列使
回收站内容重新可见。

## 9. Linux systemd 示例

下面只管理 Notebook Agent gateway；LangBot 按其部署方式单独管理。把路径和用户
改成实际值，并把 secret 文件权限设为 `0600`。

```ini
[Unit]
Description=Notebook private knowledge Agent gateway
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=notebook-agent
Group=notebook-agent
WorkingDirectory=/opt/notebook-agent
EnvironmentFile=/etc/notebook-agent/notebook-agent.env
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=NOTEBOOK_AGENT_LOG_DIR=/var/log/notebook-agent
Environment=NOTEBOOK_AGENT_ENV=production
Environment=NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=false
ExecStart=/opt/notebook-agent/.venv/bin/python -m app.cli gateway-server
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
LogsDirectory=notebook-agent
LogsDirectoryMode=0750
UMask=0027

[Install]
WantedBy=multi-user.target
```

安装后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now notebook-agent-gateway
sudo systemctl status notebook-agent-gateway
```

systemd 日志中不应出现问题正文、证据全文、平台 token 或外部身份映射。

## 9.1 安全诊断日志

### 路径与所有权

三个进程各自管理日志，不共同写一个文件：

| 组件 | 本地路径或入口 | Linux 服务器路径或入口 | 说明 |
| --- | --- | --- | --- |
| LangBot core | `<LangBot data>/logs/langbot-YYYY-MM-DD.log` 与启动终端 | `data/logs/langbot-YYYY-MM-DD.log` 与 LangBot 自身 stdout | 由 LangBot 自己写入和轮转；Notebook Agent 不写这个文件。当前仓库的本地运行目录通常是 `.runtime/langbot/data/logs/`。 |
| Notebook Agent gateway / CLI | `.runtime/logs/notebook-agent-YYYY-MM-DD.log` 与启动终端 | `/var/log/notebook-agent/notebook-agent-YYYY-MM-DD.log` 与 systemd journal | 同一条结构化 INFO 事件同时写 stdout 和每日文件。`NOTEBOOK_AGENT_LOG_DIR` 只控制 Notebook Agent 文件目录。 |
| LangBot bridge plugin | LangBot plugin 详情页中的有界 stderr 日志 | 同左 | bridge 是独立子进程，**没有 bridge 日志文件**，也不把事件复制进 LangBot core 每日文件。 |

Notebook Agent 文件目录权限为 `0750`，文件权限为 `0640`。文件按日期和大小轮转，默认单文件上限
10 MiB、保留 5 个备份，可通过 `NOTEBOOK_AGENT_LOG_MAX_BYTES` 与
`NOTEBOOK_AGENT_LOG_BACKUP_COUNT` 调整。文件初始化或后续写入失败时，gateway 继续运行，并在
stdout/journal 输出一次 `file_logging_unavailable`；成功启用时可看到 `runtime_logging_enabled`。

### 启动模式

生产和普通本地运行使用安全默认值：

```dotenv
NOTEBOOK_AGENT_ENV=production
NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=false
```

只有本地排查检索链路时，才同时显式设置下面两个值并重启 gateway：

```bash
NOTEBOOK_AGENT_ENV=development \
NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=true \
.venv/bin/python -m app.cli gateway-server
```

不能根据日志目录、TTY、hostname 或是否在服务器上自动推断开发环境。`production + true` 或未知的
`NOTEBOOK_AGENT_ENV` 会在启动配置校验时失败，而不是静默开启或降级。排查完成后恢复
`production + false` 并重启；systemd 示例必须始终保持生产配置。

开发开关只豁免 Notebook Agent 的检索详情，包括 query、limit/radius、item/segment ID、标题、
作者/描述、URL、score、excerpt 与 start/anchor。历史、完整 prompt、模型输出、action/save payload、
embedding 向量、外部身份、provider payload、token/DSN/secret 和异常消息在开发模式中仍然禁止。
开发检索详情只进入 Notebook Agent 的 stdout 与 `.runtime/logs/`，不会发送给 bridge、LangBot core、
模型 provider、`AgentAnswer` 或 conversation store。

### 查看日志

本地跟踪 Notebook Agent 当日日志：

```bash
tail -f ".runtime/logs/notebook-agent-$(date +%F).log"
```

服务器同时查看 journal 与文件：

```bash
journalctl -u notebook-agent-gateway -f
sudo tail -f "/var/log/notebook-agent/notebook-agent-$(date +%F).log"
```

LangBot core 使用自己的日志文件；bridge 事件在管理界面的 plugin 详情/日志页查看：

```bash
tail -f "<LangBot data>/logs/langbot-$(date +%F).log"
```

不要为 bridge 创建 `bridge-*.log`，也不要让 Notebook Agent 写入 LangBot 的 `data/logs/`。

### 按请求联查

bridge 首次转发会生成随机 32 位 `trace_id`，gateway 再生成独立的 `request_id`。先在 bridge plugin
stderr 找到 `trace_id`，再用它查询 Notebook Agent；进入 gateway 后也可用 `request_id` 聚合该请求的
model、tool、embedding、retrieval、validation 与最终响应阶段：

```bash
rg '"trace_id":"<32位 trace ID>"' .runtime/logs/notebook-agent-*.log*
rg '"request_id":"<32位 request ID>"' .runtime/logs/notebook-agent-*.log*

journalctl -u notebook-agent-gateway | rg '"trace_id":"<32位 trace ID>"'
```

`trace_id` 只用于日志关联，不参与身份、tenant、授权、幂等或消息去重。日志中的普通安全事件仅包含
阶段、内部 request/tenant ID、trace ID、固定 route/tool/limit/error 枚举、计数、异常类和耗时；
生产日志不包含问题正文、检索词、证据、内部内容 ID 或 URL。

## 10. 首次启动 smoke

先验证本地用户与真实模型，不经过消息平台：

```bash
.venv/bin/python -m app.cli users create
.venv/bin/python -m app.cli ingest --user-id <返回的编号> 'https://youtu.be/...'
.venv/bin/python -m app.cli ask --user-id <编号> --thread deploy-smoke '询问视频中的独有概念'
```

答案必须含真实标题、证据片段和时间戳。然后在 Telegram 发送 `/start` 或
`/whoami`，再按人工验收清单测试两用户隔离、上下文重启恢复和微信 smoke。

## 11. 健康检查

| 检查 | 命令或入口 | 通过条件 |
| --- | --- | --- |
| 基础服务 | `docker compose ps` | postgres/redis/minio healthy |
| schema | `.venv/bin/alembic current` | 当前 revision 为 head |
| migration drift | `.venv/bin/alembic check` | 无新 upgrade operation |
| Redis | `redis-cli ping` | `PONG` |
| MinIO | `GET /minio/health/ready` | HTTP 200 |
| ingestion worker | Celery `inspect ping` + `active_queues` | worker pong 且监听 `ingest`、`maintenance` |
| Agent 进程 | `GET http://127.0.0.1:8765/health` | HTTP 200、status ok |
| LangBot process health | `GET /healthz` | required bridge 为 `initialized` 后 API 才可用；不代表微信 poll healthy |
| OpenClaw adapter readiness | `GET /api/v1/platform/adapters/readiness`（管理员认证） | `state=healthy`，连续三次成功 poll 或持续两分钟；无 `certificate_verification_failed` |
| bridge runtime | LangBot plugin detail | `notebook-agent/notebook-knowledge-agent` 为 `initialized` |
| 模型与检索 | CLI `ask` smoke | 有工具证据和时间戳 |
| Telegram | `/whoami` | 返回稳定内部用户编号 |
| 微信 | 私聊 `/whoami` | 返回绑定后的同一编号 |
| 多渠道 | 两端交错发送 | 回复来源正确、历史不串线 |

跨渠道身份绑定只支持 Telegram 与微信。来源端发送 `/link <目标渠道>`，再在目标端发送返回的 `/link <绑定码>`；目标端即使已经自动注册并拥有内容，也会完整归并到来源端 `/whoami` 对应的 tenant。绑定码默认 10 分钟过期、限定目标渠道且只能成功消费一次。若返回“目标账户仍有内容正在处理”，等待 ingestion 完成后使用同一绑定码重试；该失败不会消费绑定码。

上线前运行 `bash scripts/smoke_identity_link.sh`，按固定检查点完成人工 Telegram -> 微信和微信 -> Telegram smoke。脚本只比较 `/whoami` 编号并记录固定 pass/fail，不接收、回显或保存绑定码、平台 sender identity 与消息正文。绑定完成后还要从两端分别验证同一条知识可检索，并确认两端对话历史不互相带入。

## 12. 备份与恢复

必须同时保护：

- PostgreSQL：用户、渠道身份、知识条目、segment/embedding、conversation history。
- MinIO：原始字幕/文本对象。
- LangBot 自身数据库与非仓库内平台配置。
- secret 管理系统中的凭据；不要把凭据打进普通备份压缩包。

PostgreSQL 逻辑备份示例：

```bash
docker compose exec -T postgres pg_dump -U postgres -Fc kb > kb-YYYYMMDD.dump
```

备份文件含私聊历史与私有知识内容，必须加密、限制访问并设置保留期。恢复演练应在
隔离环境进行；恢复前停止渠道入口，避免旧备份与新消息同时写入。MinIO volume
需要使用基础设施快照或 MinIO/S3 兼容备份工具另行备份，只有 PostgreSQL dump
不能恢复原始对象。

身份归并提交后不可通过用户命令拆分。回滚应用版本会保留已经归并的知识，但不会恢复原来的两个 tenant；如需拆分只能从正常 PostgreSQL 备份执行管理员恢复流程。

回收站容量巡检（在备份与 purge smoke 后执行）：

```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;
SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
       n_live_tup, n_dead_tup, last_autovacuum
FROM pg_stat_user_tables
WHERE relname IN ('content_item', 'segment', 'ingest_dispatch');
SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE relname IN ('content_item', 'segment');
SELECT count(*) AS trash_count,
       min(deleted_at) AS oldest_trash,
       count(*) FILTER (WHERE deleted_at <= now() - interval '30 days') AS expired
FROM content_item
WHERE deleted_at IS NOT NULL;
```

按 `purge_sweep` 的 claimed/completed/failed/deferred counters 与 oldest trash 观察 backlog；
不得在请求路径执行 `VACUUM FULL` 或 `REINDEX`，只在实测 dead tuples/index bloat 后安排维护。

## 13. 升级与回滚

升级顺序：

1. 停止 LangBot adapters/plugin，阻止新请求。
2. 备份 PostgreSQL、MinIO 与 LangBot 配置。
3. 设置 `AGENT_SAVE_ENABLED=false`、`AGENT_ITEM_MANAGEMENT_ENABLED=false` 并安装新的 Python 依赖。
4. 执行 `alembic upgrade head`，确认 revision `e5f6a7b8c9d0`。
5. 先启动 compatible worker（`ingest,maintenance`）与单一 beat，确认 queue、CA、Redis 与 MinIO readiness。
6. 再启动 gateway 并检查 health、schema 与 CLI ask。
7. 最后开启 `AGENT_SAVE_ENABLED` 与 `AGENT_ITEM_MANAGEMENT_ENABLED`、重启 gateway，再启动 plugin/LangBot。

保存路径异常时先把 `AGENT_SAVE_ENABLED=false` 与 `AGENT_ITEM_MANAGEMENT_ENABLED=false` 并重启 gateway。这会保留只读检索，同时
阻止新的 pending action、ContentItem 和 dispatch；不要删除或重绑用户数据。已在运行的 worker
任务可以安全完成；若出现 tenant mismatch 或无界重复 enqueue，再停止 worker intake，并保留
`ingest_dispatch` / `pending_channel_action` rows 供审计。

代码回滚时优先保持数据库向前兼容：回滚 gateway/worker binary，但保留新增列与表。只有在
隔离恢复演练中确认安全且已有备份时才执行指定 revision downgrade；生产回滚不得用 destructive
downgrade 删除 action/dispatch audit。回滚与重启都不得重置 Telegram/微信身份、微信扫码登录、
conversation history、已有 content 或 MinIO 对象。

LangBot 版本升级必须重新验证：sender ID、bot UUID、conversation ID、平台 message
ID、plugin event 顺序、monitoring 隐私补丁和两个 adapter 并发。不能假设 4.10.6
补丁可直接应用到后续版本。

## 14. 常见故障

### gateway 无法启动

- `CHANNEL_GATEWAY_SECRET is required`：应用 `.env` 未设置共享密钥。
- `must be at least 32 characters`：共享密钥过短。
- `must bind to loopback`：不要绑定 `0.0.0.0`；重新规划同网络命名空间部署。
- 数据库连接失败：检查 `POSTGRES_HOST`、端口、密码和 container health。
- 模型构造失败：检查 `AGENT_MODEL`、API key、base URL 与 provider 名称。

### plugin 回复“渠道暂时不可用”

- gateway 未启动或 8765 不在 plugin runtime 的 loopback。
- 两边 `CHANNEL_GATEWAY_SECRET` 不一致。
- 系统时钟偏差超过 60 秒，HMAC 请求会被拒绝。
- bot UUID 未加入 `KB_BOT_CHANNELS`，或 channel 拼写不是 `telegram/wechat/slack`。

### LangBot 在 adapter 出现前退出或 readiness deadline 超时

- 检查 `plugin.required_plugins` 是否为精确的
  `notebook-agent/notebook-knowledge-agent`，bridge pipeline 是否显式绑定它。
- 在管理面板检查插件状态；`installed`、`starting` 或不存在都不是 `initialized`。
- 检查安装插件目录的私有 `.env` 是否存在且为 `0600`，但不要打印文件内容。
- 检查 gateway 的 loopback health、HMAC secret 是否两端一致，以及 macOS CA 设置。
- stdio plugin runtime 断线后，LangBot 4.10.6 不能安全自动重连；停止 LangBot core 后
  再按第 8 节顺序启动。Docker/WebSocket 重连期间消息会 fail closed，不会落入 Local Agent。

### 微信二维码过期或重新登录失败

1. 停止 LangBot core/adapters，保留 gateway、数据服务、bridge package 和私有 `.env`。
2. 在 LangBot 管理面板为 OpenClaw/iLink 微信 adapter 发起新的登录会话；只在本机受信任
   屏幕展示二维码，二维码不要截进仓库、日志或工单。
3. 使用微信个人号完成扫码，等待管理面板显示成功并持久化登录状态。
4. 重新启动 LangBot；先通过 required-plugin readiness，再做一次微信 `/whoami` smoke。
5. 若仍出现 `SSLCertVerificationError`，回到本章的 macOS TLS CA 配置，不要靠反复扫码
   或关闭 TLS 校验解决。

### HTTP 401

检查共享密钥、时钟、请求 nonce，以及请求体是否在签名后被代理修改。不要通过关闭
HMAC 或暴露未认证 endpoint 绕过。

### 能回复但没有知识结果

- 确认内容属于 `/whoami` 返回的同一 `AppUser.id`。
- 确认 `content_item.state` 已到 `ready`。
- 确认 embedding key、model 和 1536 维度一致。
- 不要把另一个用户的内部编号传给 ingest。

### 普通知识问题回复“查询能力暂时不可用”

- 检查 `ZHIPU_API_KEY` 是否只在应用的私有 `.env` / secret store 中配置，且 gateway 重启后已加载。
- 确认 `EMBEDDING_MODEL`、endpoint 和 `EMBEDDING_DIMENSIONS=1536` 与导入内容时使用的配置一致。
- provider 的超时、响应数量/维度错误或非有限数值会被安全拒绝；不要在日志中添加问题正文、
  vector、请求 payload 或 API key 来排查。
- gateway 的 `notebook_agent.runtime` 日志只记录内部 request ID、tenant ID、阶段、稳定
  错误码、异常类和耗时。用 request ID 区分 `embedding_failed` 与 `retrieval_failed`；不要
  为了排障记录问题正文、外部身份、证据内容、DSN、SQL、向量或 provider payload。
- 如果确定性命令也不可用，则先按“plugin 回复渠道暂时不可用”排查 gateway/bridge，而不是
  把问题归因于 embedding。

### 保存已入队但内容没有 ready

- 先确认 `AGENT_SAVE_ENABLED`、worker `inspect ping/active_queues`、Redis、MinIO 和 schema head；
  不要让用户反复发送同一 URL 作为重试机制。
- 用内部 request、tenant、item、dispatch ID 关联 gateway 与 worker，只记录 stage、duration 和
  `queue_unavailable`、`transient_fetch_failed`、`ingestion_failed` 等稳定错误码。
- 不得记录或返回消息正文、URL、`why_saved`、外部身份、DSN、secret、字幕、vector、Celery
  backend payload、provider payload、exception message 或 traceback。
- `pending/enqueued/running/completed/failed` 是 dispatch 状态；`ContentItem.ready` 才表示可检索。
  “数据库没有搜索结果”与 ingestion/queue/provider 失败必须保持不同用户提示。
- worker TLS 失败时修复 CA 并按新 request 的有界 retry 流程恢复；不得关闭证书或 hostname 校验。

### 重启后追问丢失

- 确认 PostgreSQL 中 conversation tables 存在且 migration 在 head。
- 确认 bot UUID、external user、conversation ID 没有变化。
- 确认没有发送 `/new`，并检查 `CONTEXT_MAX_TURNS` 与 `CONTEXT_TOKEN_BUDGET`。
- Telegram 与微信默认不共享历史，即使两者已绑定同一个 AppUser。

### 微信断线

微信 adapter 应独立恢复。不要停止 Telegram、gateway 或 Agent；先确认 Telegram
仍能问答，再单独处理 OpenClaw/iLink 登录。若 sender identity 发生变化，不要手工
回退到默认用户，应重新执行可信绑定或管理员纠错。

## 15. 部署完成定义

部署完成不等于产品验收完成。部署阶段通过条件是：服务健康、migration 在 head、
CLI 真实模型 smoke 成功、bridge plugin 为 `initialized` 后两个 LangBot adapter 同时
enabled、启动/隐私补丁生效。之后仍需
按 `manual-acceptance.md` 由人工核对 Telegram 完整 E2E、微信个人号 smoke、时间戳
准确性、两用户数据隔离和断线故障隔离。
