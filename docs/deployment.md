# Notebook Agent 启动与部署手册

本文覆盖当前 P1 的受支持部署方式：PostgreSQL/pgvector、Redis、MinIO、
Notebook Agent gateway，以及 LangBot 4.10.6 的 Telegram/微信 adapter 与薄桥接插件。
真实平台验收步骤另见 Trellis 任务中的 `manual-acceptance.md`。

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
                    |          |           |
                 Agent      embedding   PostgreSQL
                  model       API       + pgvector
                                           |
                                      Redis / MinIO
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
- LangBot 4.10.6 与 `langbot-plugin` 0.4.13。
- 一个 embedding provider；当前 segment 维度固定为 1536。
- 一个 PydanticAI 支持的模型 provider，或 OpenAI-compatible gateway。
- Telegram bot token；微信个人号验收使用 LangBot OpenClaw/iLink 扫码。

凭据只能进入未提交的 `.env`、systemd `EnvironmentFile`、容器 secret 或平台 secret
存储。不要把 Telegram token、微信二维码、模型 key、绑定码写入仓库或日志。

### macOS TLS CA

部分 macOS Python 环境无法从系统钥匙串提供 OpenClaw/iLink 所需的 CA 链。若 LangBot
日志出现 `SSLCertVerificationError`，先在**启动 LangBot 的同一个环境**中定位 certifi：

```bash
.venv/bin/python -c 'import certifi; print(certifi.where())'
```

把输出路径作为两个环境变量的值后再启动 LangBot：

```dotenv
SSL_CERT_FILE=/absolute/path/to/certifi/cacert.pem
REQUESTS_CA_BUNDLE=/absolute/path/to/certifi/cacert.pem
```

这两个变量不是 secret；不要把机器上的绝对路径当作可移植默认值提交到仓库。Linux
镜像若已经有正确 CA bundle，不需要强行添加它们。

## 3. 首次安装

在项目根目录执行：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

编辑 `.env` 后至少替换：

| 配置 | 必需 | 说明 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | 是 | PostgreSQL 密码，不能保留示例值 |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | 是 | 原始文本对象存储凭据 |
| `ZHIPU_API_KEY` | 生产检索需要 | query 与 segment embedding |
| `AGENT_MODEL` | 是 | PydanticAI 模型名 |
| `AGENT_API_KEY` | 视 provider | 模型凭据 |
| `AGENT_BASE_URL` | OpenAI-compatible 时 | 以 `/v1` 结尾的兼容接口根地址 |
| `CHANNEL_GATEWAY_SECRET` | 是 | 至少 32 字符的随机共享密钥 |

生成共享密钥时可使用系统密码管理器或：

```bash
openssl rand -hex 32
```

不要把生成结果粘贴到 shell 历史以外的公开位置。应用与 LangBot plugin runtime
必须使用完全相同的值。

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

当前 head 应为 `9a6b2c4d8e10`，`alembic check` 应显示没有新的 upgrade operation。

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

embedding 维度必须与数据库 `segment.embedding vector(1536)` 保持一致：

```dotenv
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSIONS=1536
EMBEDDING_BATCH_SIZE=64
```

## 6. 启动 Notebook Agent gateway

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

生产环境不要把 8765 端口映射到公网。保持：

```dotenv
CHANNEL_GATEWAY_HOST=127.0.0.1
CHANNEL_GATEWAY_PORT=8765
```

## 7. 安装 LangBot 桥接

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

平台配置参考：

- Telegram：https://docs.langbot.app/en/usage/platforms/telegram
- 微信个人号：https://docs.langbot.app/en/usage/platforms/wechat/weixin

## 8. 完整启动与停止顺序

日常启动：

1. PostgreSQL、Redis、MinIO。
2. `alembic upgrade head`。
3. Notebook Agent `gateway-server`。
4. 检查 gateway health；若使用 macOS CA workaround，同时向 LangBot 进程注入
   `SSL_CERT_FILE` 与 `REQUESTS_CA_BUNDLE`。
5. Docker/WebSocket 模式先启动 plugin runtime；stdio 模式由 LangBot core 启动它。
6. 启动 LangBot core。patched core 会先连接 runtime、检查 bridge plugin 为
   `initialized`，**之后**才启动每个 enabled adapter；不要手工改变这个顺序。
7. 检查 readiness，再做 Telegram `/whoami` 和微信私聊 smoke。

readiness 检查不使用“等待 N 秒”。在 LangBot 进程日志中确认
`Required plugins initialized; message adapters may start.`，再确认：

```bash
curl --fail http://127.0.0.1:<LangBot API port>/healthz
```

HTTP `healthz` 只有在 application 已通过启动 gate 并创建 HTTP task 后才会返回成功。
管理面板的 plugin 详情还必须显示 bridge status 为 `initialized`；若 deadline 超时，先
检查 plugin package、其私有 `.env` 权限、gateway health 和 CA，再重启 LangBot。不要
先启动 adapter 试图“等它自己恢复”。

日常停止采用相反顺序：

1. 停 LangBot adapters/core，停止接收新消息。
2. 停 plugin runtime。
3. 停 Notebook Agent gateway。
4. 确认没有 ingestion 工作后，再按需停止数据服务。

不要在消息处理中直接执行 migration downgrade。

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
ExecStart=/opt/notebook-agent/.venv/bin/python -m app.cli gateway-server
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

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
| Agent 进程 | `GET http://127.0.0.1:8765/health` | HTTP 200、status ok |
| LangBot readiness | 日志 marker + `GET /healthz` | required bridge 为 `initialized` 后 API 才可用 |
| bridge runtime | LangBot plugin detail | `notebook-agent/notebook-knowledge-agent` 为 `initialized` |
| 模型与检索 | CLI `ask` smoke | 有工具证据和时间戳 |
| Telegram | `/whoami` | 返回稳定内部用户编号 |
| 微信 | 私聊 `/whoami` | 返回绑定后的同一编号 |
| 多渠道 | 两端交错发送 | 回复来源正确、历史不串线 |

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

## 13. 升级与回滚

升级顺序：

1. 停止 LangBot adapters/plugin，阻止新请求。
2. 备份 PostgreSQL、MinIO 与 LangBot 配置。
3. 安装新的 Python 依赖。
4. 执行 `alembic upgrade head`。
5. 启动 gateway，检查 health、schema 和 CLI ask。
6. 启动 plugin/LangBot，再做双渠道 smoke。

代码回滚时，优先保持数据库向前兼容。只有确认旧代码不认识新 schema 且已有备份，
才执行指定 revision 的 downgrade。本任务 migration 的 downgrade 会删除渠道身份、
绑定 token 和 conversation 表，虽然不删除 content/segment/embedding，但会丢失渠道
绑定和恢复上下文；生产环境不得把它当作普通重启步骤。

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
