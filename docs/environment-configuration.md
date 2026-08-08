# Environment configuration / 环境配置

这份文档是 Notebook Agent 环境变量的开发者入口。先选择运行场景，复制最小配置；需要调优或排障时，再查后面的[变量参考](#变量参考)。

> 安全规则：真实凭据只能进入未提交的 `.env`、进程环境或 secret manager。不要把 token、API key、DSN、HMAC secret、MiXer capability URL 粘贴到仓库、日志、截图或工单。

## 先选运行场景

| 你要做什么 | 需要的进程 | 从这里开始 |
| --- | --- | --- |
| 本地问答、库存查看、MCP Inspector/源码评测 | PostgreSQL、Notebook Agent stdio MCP | [A. 本地只读 MCP](#a-本地只读-mcp) |
| 保存 URL、重试 ingestion、更新/删除/恢复知识条目 | PostgreSQL、Redis、MinIO、Celery worker、Celery beat、Notebook Agent | [B. 完整本地 MCP](#b-完整本地-mcp) |
| 给 MiXer 或其他远程 MCP client 提供 HTTPS endpoint | 场景 A 或 B 的依赖、Streamable HTTP、TLS reverse proxy | [C. Streamable HTTP / MiXer](#c-streamable-http--mixer) |
| 接入 Telegram/微信 | gateway-server、已安装的 LangBot bridge plugin、LangBot core/adapters | [D. 可选 LangBot 渠道](#d-可选-langbot-渠道) |

四个容易混淆的配置位置：

| 位置 | 放什么 | 不放什么 |
| --- | --- | --- |
| 项目根目录 `.env` | Notebook Agent、CLI、worker 使用的数据库/provider/功能配置 | 不放 LangBot bot UUID 映射；不提交 |
| stdio MCP 进程环境 `MCP_TOKEN` | 当前 stdio 进程使用的一次 bearer | 不写入 `.env.example`，不提交 |
| 已安装 LangBot plugin 目录下的私有 `.env` | bridge 的 `CHANNEL_GATEWAY_SECRET`、URL、bot UUID 映射 | 不放 Agent provider key 或数据库 DSN |
| reverse proxy / secret manager | 公网 TLS、访问日志策略、生产 secret | 不把 URL capability 记录到普通 access log |

## 共同准备

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

`.env.example` 是完整本地 superset。下面的片段用于说明最小必需值；可以删除 `.env` 中当前场景不需要的可选配置，但不要改动代码默认值来代替显式生产配置。

生成随机 secret：

```bash
openssl rand -hex 32
```

命令输出只写入本地 secret 存储或私有环境文件。

## A. 本地只读 MCP

适合自然语言问答、`list_saved_items`、`get_saved_item`、MCP Inspector 和源码评测。它不需要 Redis、MinIO、Celery worker 或 beat。

### 根 `.env` 最小配置

```dotenv
# PostgreSQL；也可以只设置一个 DATABASE_URL。
POSTGRES_USER=postgres
POSTGRES_PASSWORD=replace-with-a-local-password
POSTGRES_DB=kb
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Query embedding。
ZHIPU_API_KEY=replace-with-zhipu-key
EMBEDDING_MODEL=embedding-3
EMBEDDING_ENDPOINT=https://open.bigmodel.cn/api/paas/v4/embeddings
EMBEDDING_DIMENSIONS=1536

# PydanticAI model provider。
AGENT_MODEL=openai:gpt-5-mini
AGENT_API_KEY=replace-with-model-key
# AGENT_BASE_URL=https://openai-compatible.example/v1

NOTEBOOK_AGENT_ENV=development
NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=false
AGENT_SAVE_ENABLED=false
AGENT_ITEM_MANAGEMENT_ENABLED=false
```

启动数据库并升级 schema：

```bash
docker compose up -d postgres
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

创建用户和只读 grant；原始 token 只显示一次：

```bash
.venv/bin/python -m app.cli users create
.venv/bin/python -m app.cli mcp-grant issue --user-id <user-id> --scope read --label local-stdio
```

启动 stdio MCP。`MCP_TOKEN` 是进程级 bearer，不要把它加入 `.env.example`：

```bash
MCP_TOKEN='<raw-token>' \
  .venv/bin/python -m app.cli mcp-server --transport stdio
```

通过条件：官方 MCP client 完成 `initialize`，`tools/list` 只显示 `ask_notebook_agent`、`list_saved_items`、`get_saved_item`，自然语言 `tools/call` 能进入真实 Agent。

## B. 完整本地 MCP

完整 profile 在场景 A 上增加保存、更新、删除/恢复、ingestion retry。服务端只有在 PostgreSQL、Redis、MinIO、maintenance 配置和 Celery worker 均 ready 时才公布 mutation tools。

### 根 `.env` 增量

保留场景 A 的 provider 与数据库配置，再加入：

```dotenv
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=replace-with-a-local-minio-password
MINIO_ENDPOINT_URL=http://localhost:9000
MINIO_BUCKET=kb-raw

# First rollout stays fail-closed. Enable only after the checks below pass.
AGENT_SAVE_ENABLED=false
AGENT_ITEM_MANAGEMENT_ENABLED=false
TRASH_RETENTION_DAYS=30
TRASH_PURGE_INTERVAL_SECONDS=3600
```

首次 rollout 时先保持两个 feature flag 为 `false`。依赖、migration 和 worker 检查通过后，再设为 `true` 并重启 Notebook Agent 进程。

启动依赖和 worker：

```bash
docker compose up -d
.venv/bin/alembic upgrade head

.venv/bin/celery -A app.ingest.tasks.celery_app worker \
  --loglevel=INFO --queues=ingest,maintenance
```

另一个终端只启动一个 beat：

```bash
.venv/bin/celery -A app.ingest.tasks.celery_app beat --loglevel=INFO
```

检查 worker：

```bash
.venv/bin/celery -A app.ingest.tasks.celery_app inspect ping
.venv/bin/celery -A app.ingest.tasks.celery_app inspect active_queues
```

至少一个 worker 必须返回 `pong`，并同时监听 `ingest`、`maintenance`。`ingest-completion`
由 producer 声明为 durable queue；真实 consumer 部署前不要让 worker 监听它，否则
没有业务 handler 的 worker 会 ack 并丢弃事件。随后签发 full grant：

```bash
.venv/bin/python -m app.cli mcp-grant issue --user-id <user-id> --scope full --label local-full
```

把根 `.env` 的两个 flag 改为 `true`，再启动 full stdio MCP：

```dotenv
AGENT_SAVE_ENABLED=true
AGENT_ITEM_MANAGEMENT_ENABLED=true
```

```bash
MCP_TOKEN='<raw-token>' \
  .venv/bin/python -m app.cli mcp-server --transport stdio
```

通过条件：`tools/list` 显示 10 个 MCP tools；如果仍只有 3 个，先查 readiness，不要绕过检查或把失败 probe 当作 healthy。

## C. Streamable HTTP / MiXer

HTTP 服务使用与场景 A/B 相同的根 `.env`。grant scope 决定 read/full；full 仍受 mutation readiness 限制。

### 根 `.env` 增量

```dotenv
MCP_HOST=127.0.0.1
MCP_PORT=8000
MCP_PATH=/mcp
MCP_URL_TOKEN_MODE=false
```

启动：

```bash
.venv/bin/python -m app.cli mcp-server --transport streamable-http
```

正常客户端使用：

```text
POST https://agent.example/mcp
Authorization: Bearer <raw-token>
```

生产 endpoint 必须放在 TLS reverse proxy 后；应用仍建议绑定 loopback。不要在服务器环境中设置 `MCP_TOKEN`：HTTP token 来自每个请求，而不是一个固定全局用户。

### MiXer 只有 URL 输入框时

仅当客户端无法发送 Authorization header 时设置：

```dotenv
MCP_URL_TOKEN_MODE=true
```

MiXer URL：

```text
https://agent.example/mcp/c/<raw-token>
```

要求：

- 只接受 HTTPS；`http://` path token 会被拒绝。
- 永远不接受 `?token=<raw-token>`。
- reverse proxy、应用错误日志和 analytics 必须省略或脱敏原始 request URI。
- MiXer 和基础设施仍可能保存完整 URL；疑似暴露后立即 rotate/revoke。
- 验收必须走 `initialize -> tools/list -> tools/call`，不能只看 endpoint 可连接。

常用运维命令：

```bash
.venv/bin/python -m app.cli mcp-grant list --limit 100 --offset 0
.venv/bin/python -m app.cli mcp-grant show <grant-id>
.venv/bin/python -m app.cli mcp-grant rotate <grant-id>
.venv/bin/python -m app.cli mcp-grant revoke <grant-id>
.venv/bin/python -m app.cli mcp-grant disable <grant-id>
```

`list`、`show`、`revoke`、`disable` 不显示 raw token。rotate 会显示一个新 token，并立即使旧 token 失效。

## D. 可选 LangBot 渠道

LangBot 不是 MCP 的依赖。只有接入 Telegram/微信时才需要 gateway 和 bridge 配置。

### Notebook Agent 根 `.env`

```dotenv
CHANNEL_GATEWAY_SECRET=replace-with-at-least-32-random-characters
CHANNEL_GATEWAY_HOST=127.0.0.1
CHANNEL_GATEWAY_PORT=8765
```

启动：

```bash
.venv/bin/python -m app.cli gateway-server
curl --fail http://127.0.0.1:8765/health
```

### 已安装 plugin 的私有 `.env`

不要写到项目根 `.env`。复制到 LangBot 实际安装目录并限制权限：

```bash
cp integrations/langbot_kb_plugin/.env.example \
  /path/to/langbot/data/plugins/notebook-agent__notebook-knowledge-agent/.env
chmod 600 \
  /path/to/langbot/data/plugins/notebook-agent__notebook-knowledge-agent/.env
```

内容：

```dotenv
CHANNEL_GATEWAY_SECRET=与-Notebook-Agent-根-env-完全相同
CHANNEL_GATEWAY_URL=http://127.0.0.1:8765/v1/messages
KB_BOT_CHANNELS={"telegram-bot-uuid":"telegram","wechat-bot-uuid":"wechat"}
```

`KB_BOT_CHANNELS` 的 key 是 LangBot bot UUID，不是 Telegram 用户 ID、微信昵称或 `AppUser.id`。bridge pipeline 还必须显式绑定 required plugin；完整步骤见[部署手册的 LangBot 章节](deployment.md#7-安装-langbot-桥接可选)。

## 变量参考

“重启”表示修改后哪些进程必须重新读取环境。数据库/对象存储自身凭据变化还可能需要单独的数据服务操作，不等于只重启应用即可完成轮换。

### PostgreSQL

| 变量 | 消费者 | 默认值/示例 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `DATABASE_URL` | app、CLI、worker、Alembic | 未设置；优先于 `POSTGRES_*` | 托管/外部 PostgreSQL | 是，通常含密码 | app、worker、CLI 新进程 |
| `POSTGRES_USER` | Compose、URL fallback | `postgres` | 本地 Compose | 否 | PostgreSQL 与所有 DB client |
| `POSTGRES_PASSWORD` | Compose、URL fallback | `changeme` 仅占位 | 本地 Compose 必填 | 是 | PostgreSQL 与所有 DB client |
| `POSTGRES_DB` | Compose、URL fallback | `kb` | 本地 Compose | 否 | PostgreSQL 与所有 DB client |
| `POSTGRES_HOST` | URL fallback | `localhost` | 未设置 `DATABASE_URL` | 否 | app、worker、CLI 新进程 |
| `POSTGRES_PORT` | Compose host port、URL fallback | `5432` | 本地/自定义端口 | 否 | PostgreSQL 与所有 DB client |

### Redis 与 broker

| 变量 | 消费者 | 默认值/示例 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `REDIS_URL` | app、Celery worker/beat | 未设置；优先于分项值 | full profile；远程 Redis | 可能含凭据 | app、worker、beat |
| `REDIS_HOST` | URL fallback | `localhost` | full profile | 否 | app、worker、beat |
| `REDIS_PORT` | Compose host port、URL fallback | `6379` | full profile | 否 | Redis 与 client |
| `REDIS_DB` | URL fallback | `0` | full profile | 否 | app、worker、beat |
| `BROKER_PUBLISH_TIMEOUT_SECONDS` | app submission | `5` | full profile tuning | 否 | app |
| `BROKER_PUBLISH_MAX_RETRIES` | app submission | `1` | full profile tuning | 否 | app |

本地 Compose Redis 固定使用持久卷、AOF 和 `appendfsync=always`。配置远程
`REDIS_URL` 时，托管服务必须提供等价的“broker 返回写入成功前已经持久化”保证；
定期 snapshot 可能在故障时丢失已经确认的 `ingest-completion` 消息，不能满足
完成 outbox 的 at-least-once 合同。

### MinIO / S3-compatible storage

| 变量 | 消费者 | 默认值/示例 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `MINIO_ROOT_USER` | Compose、app、worker | `minioadmin` 仅本地示例 | full profile | 是 | MinIO、app、worker |
| `MINIO_ROOT_PASSWORD` | Compose、app、worker | `changeme12345` 仅占位 | full profile | 是 | MinIO、app、worker |
| `MINIO_ENDPOINT_URL` | app、worker | `http://localhost:9000` | full profile | 否 | app、worker |
| `MINIO_BUCKET` | app、worker | `kb-raw` | full profile | 否 | app、worker |
| `MINIO_API_PORT` | Compose only | `9000` | 本地 Compose port mapping | 否 | MinIO |
| `MINIO_CONSOLE_PORT` | Compose only | `9001` | 本地 Console port mapping | 否 | MinIO |

### Embedding、模型与 TLS

| 变量 | 消费者 | 默认值/示例 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `ZHIPU_API_KEY` | app query embedding、worker ingestion | 空 | 问答与 ingestion | 是 | app、worker |
| `EMBEDDING_MODEL` | app、worker | `embedding-3` | 问答与 ingestion | 否 | app、worker |
| `EMBEDDING_ENDPOINT` | app、worker | Zhipu embeddings URL | 自定义 endpoint | 否 | app、worker |
| `EMBEDDING_DIMENSIONS` | app、worker、DB contract | `1536` | 始终保持与向量列一致 | 否 | app、worker；数据迁移另议 |
| `EMBEDDING_BATCH_SIZE` | app、worker | `64` | provider tuning | 否 | app、worker |
| `AGENT_MODEL` | app/CLI | `openai:gpt-5-mini` | 自然语言问答 | 否 | app/CLI 新进程 |
| `AGENT_API_KEY` | app/CLI | 空 | provider 要求时 | 是 | app/CLI 新进程 |
| `AGENT_BASE_URL` | app/CLI | 未设置 | OpenAI-compatible endpoint | 否；URL 若含凭据则按 secret | app/CLI 新进程 |
| `TLS_CA_BUNDLE` | app、worker、LangBot patch（显式时） | 未设置 | 企业/私有 CA 或明确证书故障 | 否，但路径属环境信息 | 对应进程 |

`SSL_CERT_FILE` 和 `REQUESTS_CA_BUNDLE` 是标准库兼容 fallback，不需要复制到普通本地 `.env`。不要用 `ssl=False` 或 HTTP endpoint 绕过证书验证。

### Agent 安全预算与上下文

| 变量 | 消费者 | 默认值 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `AGENT_TIMEOUT_SECONDS` | Agent workflow | `45` | 可选 tuning | 否 | app |
| `AGENT_TOOL_TIMEOUT_SECONDS` | 单次 tool | `15` | 可选 tuning；小于外层 timeout | 否 | app |
| `AGENT_REQUEST_LIMIT` | planner/model | `8` | 安全上限 | 否 | app |
| `AGENT_TOOL_CALLS_LIMIT` | planner/tools | `10` | 安全上限 | 否 | app |
| `AGENT_OUTPUT_TOKEN_LIMIT` | planner/composer attempts | `2000` | 安全上限 | 否 | app |
| `AGENT_COMPOSER_MAX_TOKENS` | composer provider request | `1000` | provider cap | 否 | app |
| `CONTEXT_MAX_TURNS` | conversation history | `8` | 上下文 tuning | 否 | app |
| `CONTEXT_TOKEN_BUDGET` | conversation history | `6000` | 上下文 tuning | 否 | app |
| `CHANNEL_LINK_TTL_SECONDS` | cross-channel linking | `600` | 使用绑定码时 | 否 | app |

### 功能开关与回收站

| 变量 | 消费者 | 默认值 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `AGENT_SAVE_ENABLED` | app tool composition | `false` | full profile readiness 后开启 | 否 | app |
| `AGENT_ITEM_MANAGEMENT_ENABLED` | app tool composition | `false` | full profile readiness 后开启 | 否 | app |
| `TRASH_RETENTION_DAYS` | management/maintenance | `30` | item management | 否 | app、worker、beat |
| `TRASH_PURGE_INTERVAL_SECONDS` | Celery beat | `3600` | item management | 否 | beat |
| `TRASH_PURGE_BATCH_SIZE` | purge worker | `20` | item management | 否 | worker |
| `TRASH_PURGE_CLAIM_TIMEOUT_SECONDS` | purge worker | `1800` | item management | 否 | worker |
| `TRASH_PURGE_MAX_DURATION_SECONDS` | purge worker | `30` | item management | 否 | worker |
| `TRASH_PURGE_OBJECT_TIMEOUT_SECONDS` | purge object delete | `10` | item management | 否 | worker |
| `INGEST_COMPLETION_INTERVAL_SECONDS` | Celery beat | `60` | durable completion outbox repair | 否 | beat |
| `INGEST_COMPLETION_BATCH_SIZE` | maintenance worker | `20` | bounded completion repair | 否 | worker |
| `INGEST_COMPLETION_CLAIM_TIMEOUT_SECONDS` | maintenance worker | `300` | stale claim recovery | 否 | worker |
| `INGEST_COMPLETION_MAX_DURATION_SECONDS` | maintenance worker | `30` | bounded sweep wall-clock budget | 否 | worker |

关闭 management flag 不会关闭 deleted-content retrieval filters。

### 日志与运行环境

| 变量 | 消费者 | 默认值 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `NOTEBOOK_AGENT_LOG_DIR` | app/CLI | `.runtime/logs` | 文件日志位置 | 否 | app/CLI 新进程 |
| `NOTEBOOK_AGENT_LOG_MAX_BYTES` | app/CLI | `10485760` | 日志轮转 | 否 | app/CLI 新进程 |
| `NOTEBOOK_AGENT_LOG_BACKUP_COUNT` | app/CLI | `5` | 日志轮转 | 否 | app/CLI 新进程 |
| `NOTEBOOK_AGENT_ENV` | app | `production` | `development` 或 `production` | 否 | app |
| `NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT` | app | `false` | 仅本地且 env=development | 否；内容仍敏感 | app |

生产必须保持 `NOTEBOOK_AGENT_ENV=production` 与 `NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=false`。

### MCP transport

| 变量 | 消费者 | 默认值 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `MCP_HOST` | HTTP server | `127.0.0.1` | Streamable HTTP | 否 | MCP server |
| `MCP_PORT` | HTTP server | `8000` | Streamable HTTP | 否 | MCP server |
| `MCP_PATH` | HTTP server/proxy | `/mcp` | Streamable HTTP | 否 | MCP server、proxy |
| `MCP_URL_TOKEN_MODE` | HTTP auth middleware | `false` | URL-only client 才开启 | 否 | MCP server |
| `MCP_TOKEN` | stdio process only | 无 | 每个 stdio process | **是** | 重启该 stdio process |

HTTP 模式不设置固定 `MCP_TOKEN`；每个请求携带自己的 bearer grant。

### 可选 LangBot bridge

| 变量 | 消费者 | 默认值/示例 | 何时需要 | Secret | 重启 |
| --- | --- | --- | --- | --- | --- |
| `CHANNEL_GATEWAY_SECRET` | gateway + installed plugin | 空；至少 32 随机字符 | LangBot only | 是 | gateway、plugin runtime |
| `CHANNEL_GATEWAY_HOST` | gateway | `127.0.0.1` | LangBot only | 否 | gateway |
| `CHANNEL_GATEWAY_PORT` | gateway | `8765` | LangBot only | 否 | gateway、plugin URL 若改变 |
| `CHANNEL_GATEWAY_URL` | installed plugin only | `http://127.0.0.1:8765/v1/messages` | LangBot only | 否 | plugin runtime |
| `KB_BOT_CHANNELS` | installed plugin only | 无 | LangBot only | 含内部 bot UUID，按私有配置处理 | plugin runtime |

## 修改配置后的检查顺序

1. 确认改的是正确文件：根 `.env`、stdio process env、plugin private `.env` 或 proxy secret。
2. 重启表格中列出的消费者；环境变量不会自动热更新。
3. 运行 `.venv/bin/alembic current`，当前 head 应为 `f6a7b8c9d0e1`。
4. full profile 检查 Redis、MinIO、Celery `ping` 和 `active_queues`。
5. MCP 运行 `initialize -> tools/list -> tools/call`；只读应为 3 tools，ready full 应为 10 tools。
6. LangBot 先检查 gateway health，再确认 required plugin 为 `initialized`，最后做真实渠道 smoke。

更完整的启动顺序、systemd、日志、备份、回滚和故障处理见[部署手册](deployment.md)。
