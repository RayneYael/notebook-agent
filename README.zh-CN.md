# Notebook Agent

[English](README.md) | [简体中文](README.zh-CN.md)

> 让你的私人知识，在每一个聊天入口触手可及。

**EAZO Global Hackathon Project**

Notebook Agent 是一个面向个人的多渠道私有知识库 Agent。用户只需在 Telegram 或微信中发送视频链接，就能把内容沉淀为可检索的知识；之后直接用自然语言提问，Agent 会从用户自己的知识库中寻找证据，并返回带标题、原文片段和视频时间戳的回答。

它希望解决一个很常见的问题：我们收藏了大量视频和内容，却很难在真正需要时重新找到其中的某句话、某个观点或某段解释。

## Demo：从收藏到答案

1. **保存内容**：向机器人发送“帮我保存 `<YouTube URL>`”。
2. **自动处理**：系统异步获取元数据与字幕，完成语义切分、向量化和索引。
3. **随时提问**：例如“我收藏的视频里，谁讲过如何验证产品需求？”
4. **回到原文**：回答附带真实来源与时间戳，可直接跳转到视频对应位置。

```text
用户：帮我保存 https://youtu.be/...
Agent：已加入处理队列，完成后即可检索。

用户：这个视频对 AI Agent 的可靠性有什么建议？
Agent：……
       [1] 视频标题 · 08:42 · 原文片段
```

## 核心功能

| 能力 | 说明 |
| --- | --- |
| 对话式收藏 | 通过自然语言保存 1–10 个明确的视频链接；只发送裸链接时会先请求确认，避免误操作。 |
| 视频知识化 | 自动提取 YouTube 元数据和字幕，按语义与时间边界切分，并生成向量索引。 |
| 混合检索 | 结合关键词检索与 pgvector 语义检索，在表达不同但语义相关时也能找到内容。 |
| 可追溯回答 | 回答只能引用本次检索得到的真实证据，并附带标题、片段与时间戳链接。 |
| 多步 Agent | Agent 可搜索片段、展开上下文、读取内容详情，并跳转到具体位置。 |
| 多渠道访问 | 通过 LangBot 同时连接 Telegram 与微信；渠道层和 Agent 核心相互独立。 |
| 私有知识空间 | 数据按用户隔离，模型工具无法传入或修改 `user_id`，跨用户资源统一不可见。 |
| 跨渠道身份绑定 | 使用短期、单次绑定码，让同一用户在不同渠道访问同一份知识库。 |
| 持久化会话 | 最近对话保存在 PostgreSQL 中，服务重启后仍可恢复；`/new` 可随时开启新会话。 |
| 异步处理 | Redis + Celery 在后台完成抓取、切分与 embedding，不阻塞聊天请求。 |

## 为什么不只是一个 RAG Demo

Notebook Agent 把“能回答”之外的可靠性和隐私边界也作为产品能力：

- **Evidence first**：普通知识问答必须先生成 query embedding 并检索知识库；检索不可用时明确失败，不会退化成模型凭记忆作答。
- **引用防幻觉**：最终答案只能使用服务端允许的真实片段 ID。模型伪造引用时会被拒绝并重新生成，修复失败也不会返回未经验证的草稿。
- **Tenant by construction**：用户身份由可信渠道事件解析并固定在依赖中，Agent 的工具 schema 不暴露租户参数。
- **安全渠道桥接**：LangBot bridge 只监听 loopback，并使用 HMAC、时间戳和 nonce 验证请求；重放和重复消息不会触发重复回答。
- **安全确认机制**：待确认操作绑定当前用户与会话，十分钟后过期，且只能消费一次。
- **可恢复执行**：内容任务拥有持久化 dispatch 与幂等边界，重复投递不会重复执行完整 ingestion。

## 系统架构

```mermaid
flowchart LR
    U["User"] --> TG["Telegram"]
    U --> WX["WeChat"]
    TG --> LB["LangBot + Bridge Plugin"]
    WX --> LB
    LB --> GW["Notebook Agent Gateway"]
    GW --> ID["Identity & Conversation"]
    GW --> AG["PydanticAI Agent"]
    AG --> RET["Tenant-scoped Retrieval"]
    RET --> PG["PostgreSQL + pgvector"]
    AG --> Q["Save Action"]
    Q --> RD["Redis + Celery"]
    RD --> ING["YouTube Ingestion"]
    ING --> S3["MinIO Raw Storage"]
    ING --> EMB["Embedding Provider"]
    ING --> PG
```

### 内容处理链路

```text
URL → 元数据/字幕 → 内容校验 → 原文归档 → 语义切分 → Embedding → pgvector → 可检索
```

当前可完整导入 YouTube 视频。数据模型已为 Bilibili 和微信公众号文章预留统一的内容与片段结构，但对应 connector 尚未完成，因此不将它们列为当前可用功能。

## 技术栈

- **Agent**：PydanticAI，支持其原生模型 provider 与 OpenAI-compatible 网关
- **Database**：PostgreSQL 17、pgvector、SQLAlchemy、Alembic
- **Retrieval**：向量余弦检索 + PostgreSQL 全文检索 / 中文 trigram 检索
- **Ingestion**：yt-dlp、Celery、Redis
- **Object Storage**：MinIO / S3-compatible storage
- **Channels**：LangBot 4.10.6、Telegram、微信 OpenClaw/iLink
- **Embedding**：智谱 Embedding-3（1536 dimensions）
- **Quality**：Pytest、结构化诊断日志、幂等与租户隔离测试

## 快速开始

### 1. 环境要求

- Python 3.11+
- Docker 与 Docker Compose
- 一键生命周期启动器支持 Linux/macOS（依赖 `fcntl`、`ps`、signal 与进程组）；Windows
  继续使用文档中的直接启动命令
- 可用的 Agent model API 与智谱 Embedding API
- 如需真实聊天渠道：LangBot 4.10.6 以及 Telegram / 微信账号配置

### 2. 安装与初始化

```bash
git clone YOUR_REPOSITORY_URL
cd notebook-agent

python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# 交互模式只询问 Embedding 与 Agent provider key；本地数据库、对象存储密码和
# full/langbot 所需的 gateway secret 会随机生成到被 git 忽略且权限为 0600 的 .env.runtime。
./scripts/notebook-agent init --profile read
./scripts/notebook-agent start
```

`read` 只启动 Streamable HTTP MCP；`full` 启动 MCP、私有 LangBot gateway、Redis、MinIO、
一个同时监听 `ingest,maintenance` 的 worker 和唯一的 Beat；`langbot` 使用相同后台运行时
但只启动私有 gateway，不启动 MCP。非交互部署应在执行 `init` 前通过进程环境提供
`ZHIPU_API_KEY`；模型 provider 需要时再提供 `AGENT_API_KEY` 或该 provider 的原生凭据
变量。已有进程环境和用户维护的 `.env` 优先于生成配置。

常用生命周期命令只管理本启动器拥有的应用进程，不删除 Compose volume，也不停止外部服务：

```bash
./scripts/notebook-agent status
./scripts/notebook-agent logs mcp
./scripts/notebook-agent stop
./scripts/notebook-agent restart
```

### 3. 启动核心 MCP 服务（无需 LangBot）

核心评测入口使用官方 `mcp==2.0.0`，支持 stdio 与 Streamable HTTP；`app/` 不依赖
LangBot。stdio 的 stdout 仅保留协议字节，诊断写入 stderr。先签发 grant，再把 raw
token 只传给该 stdio 进程：

```bash
.venv/bin/python -m app.cli mcp-grant issue --user-id <user-id> --scope read --label local-stdio
MCP_TOKEN='<raw-token>' \
  .venv/bin/python -m app.cli mcp-server --transport stdio
```

缺少或无效 token 会 fail closed，不会暴露一个固定全局用户。

托管 HTTP 服务默认监听 `127.0.0.1:8000/mcp`，公开部署必须使用 TLS。优先使用
`Authorization: Bearer <token>`；URL-only 的兼容路径 `/mcp/c/<opaque-token>` 只有在
显式设置 `MCP_URL_TOKEN_MODE=true` 时启用，永远拒绝 `?token=`。使用
`mcp-grant issue|rotate|revoke` 管理权限；原始 token 只在 issue/rotate 时显示，数据库
只保存哈希。`read` grant 只能问答/查看库存，`full` grant 才能保存、删除确认、恢复和
重试。`tools/list` 只证明 MCP 连通，评测还应调用自然语言的
`ask_notebook_agent` 以验证真实模型路径。

### Web 邮箱登录 API

Web API 与 Streamable HTTP MCP 共用同一条启动命令，但认证边界彼此独立：浏览器通过
`/api/v1/*` 的服务端 session Cookie 认证，`/mcp` 仍只接受 MCP bearer grant。

浏览器 Chat 的 `conversation_id`、服务端 `thread_id`、消息幂等与 reset 契约见
[Web 对话接口契约](docs/web-conversation-api.md)。

启用前，在项目根目录私有 `.env` 中设置以下值。不要提交邮件服务商凭据或 Web auth
secret；`WEB_PUBLIC_ORIGIN` 必须与浏览器实际访问的 HTTPS origin 完全一致，且末尾不能有
`/`。

```dotenv
WEB_AUTH_ENABLED=true
WEB_PUBLIC_ORIGIN=https://localhost:8443 //localhost 仅供本地测试，正式部署时切换为真实公网 IP
WEB_AUTH_SECRET=<用python生成一个至少32个字符的私有随机值>
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=<本地测试 Gmail 地址>
SMTP_PASSWORD=<本地 Gmail App Password>
SMTP_FROM_EMAIL=<本地测试 Gmail 地址>
```

先执行数据库迁移，再启动同一个长驻 HTTP 进程：

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli mcp-server --transport streamable-http
```

该进程必须放在 HTTPS 反向代理后。代理需原样转发 Cookie 和 `Origin` header，不得对
`/api/v1` 启用 CORS，并将 upstream read timeout 设为至少 60 秒。生产登录还依赖 Redis；
所选邮件服务商或 Redis 不可用时登录会 fail closed。当前本地开发使用上列 Gmail SMTP，
另加 `SMTP_TIMEOUT_SECONDS`（默认 `10`）；Gmail App Password 和测试地址只能保存在私有
本地 `.env`，绝不能提交。仍可通过 `EMAIL_PROVIDER=resend` 加上 `RESEND_API_KEY` 与
`RESEND_FROM_EMAIL` 使用 Resend，但当前环境不依赖它，也不以 DNS/发件域名验证为前置条件。
生产环境必须显式选择并完整配置 provider，最终生产 provider 尚未决定。开发/测试未配置
provider 时使用内存 Fake Sender，验证码不会写入日志或向 Postman 暴露，应使用自动化 Web
测试验证该路径。

### 4. 启动后台任务与 Gateway

一键启动的 `full` profile 会在同一个 supervisor 下启动 MCP、私有 gateway、worker 与唯一
的 Beat；`langbot` 启动相同的后台进程和 gateway，但不启动 MCP。各组件仍保持独立进程，
避免隐藏 Beat 故障或重复调度。下面的直接命令继续供高级进程管理器使用。

首次部署时先保持 `.env` 中的 `AGENT_SAVE_ENABLED=false`，启动 ingestion worker：

```bash
.venv/bin/celery -A app.ingest.tasks.celery_app worker --queues=ingest,maintenance
.venv/bin/celery -A app.ingest.tasks.celery_app beat
```

Worker 与 beat 也是完成通知恢复路径的一部分。ingestion 终态与 completion event 在同一
PostgreSQL transaction 中写入；beat 默认每 10 秒把无参数 notification poller 投递到
`maintenance`，由 delivery ledger claim 后通知原 bot + conversation。旧
`ingest-completion` Redis queue 已退役且不再生产新 envelope，不要让 worker 监听或重放它。
上线时检查 `notification_poller_heartbeat`、数据库 backlog 和 failed ledger；Redis 的持久化
仍用于 `ingest` broker task，但不是 completion notification 的 source of truth。

确认 worker ready 后，将 `AGENT_SAVE_ENABLED` 改为 `true`，再启动 Gateway：

```bash
.venv/bin/python -m app.cli gateway-server
```

先从[环境配置指南](docs/environment-configuration.md)选择可复制的只读、完整、
HTTP/MiXer 或可选 LangBot profile。进程启动顺序、Linux 服务、升级回滚、备份及
故障排查见[部署手册](docs/deployment.md)。

## 本地 CLI 体验

不接入聊天平台也可以通过 CLI 验证完整的数据与问答链路：

```bash
# 创建本地用户，并记下命令返回的 user 编号
python -m app.cli users create

# 将下方的 12 替换为刚刚返回的 user 编号，然后导入视频
python -m app.cli ingest --user-id 12 'https://youtu.be/...'

# 对比关键词和向量检索结果
python -m app.cli search --user-id 12 '查询词'

# 使用 Agent 提问
python -m app.cli ask --user-id 12 --thread demo '这个视频的核心观点是什么？'
```

## 聊天渠道命令

| 命令 | 作用 |
| --- | --- |
| `/start` | 自动注册或确认当前账户，并返回内部用户编号。 |
| `/whoami` | 查看当前渠道绑定的内部用户编号。 |
| `/new` | 开启新会话，不再加载旧上下文。 |
| `/link wechat` | 在已登录渠道生成微信绑定码；Telegram 同理。 |
| `/link <code>` | 在指定目标渠道消费绑定码，接入同一份私有知识库。 |

本版本只支持 Telegram 与微信互相绑定。绑定码按配置的 TTL 过期（默认 10 分钟），限定指定目标渠道，且只能成功消费一次。目标账号可以已经使用过 `/start`、`/whoami`、普通对话或保存内容；系统会把其 tenant、全部身份、渠道会话和知识内容归并到生成绑定码的来源 tenant，并自动收敛重复内容。若目标账号仍有 ingestion 正在运行，请在处理完成后使用同一绑定码重试。

不同渠道即使绑定到同一个用户，也默认保留各自独立的聊天历史；它们共享知识库，但不会无意中混合上下文。完成归并后不能通过聊天命令撤销；部署前应正常备份 PostgreSQL，后续拆分只能走管理员恢复流程。绑定码必然出现在两端平台消息中，但应用只保存哈希，严禁把绑定码复制到日志。

## 模型配置

可以直接使用 PydanticAI 支持的 provider。使用 OpenAI-compatible 网关时配置：

```dotenv
AGENT_MODEL=openai:your-model-name
AGENT_API_KEY=...
AGENT_BASE_URL=https://your-gateway.example/v1
```

`AGENT_BASE_URL` 只改变 provider 连接方式，不会改变工具、prompt、租户边界或答案结构。

## LangBot 多渠道接入

桥接插件位于 [`integrations/langbot_kb_plugin/`](integrations/langbot_kb_plugin/)，负责将可信平台事件转换为统一的 `ChannelEnvelope` 并路由回复；身份、会话、模型与检索权限仍由 Notebook Agent 管理。

接入时需要：

1. 为 Notebook Agent 与插件配置相同的 `CHANNEL_GATEWAY_SECRET`（至少 32 字符）。
2. 在 LangBot 中启用 Telegram 与 OpenClaw/iLink 微信 adapter。
3. 使用 `KB_BOT_CHANNELS` 将 LangBot bot UUID 显式映射为 `telegram` 或 `wechat`。
4. 应用 [`integrations/langbot-4.10.6-redact-monitoring.patch`](integrations/langbot-4.10.6-redact-monitoring.patch)，避免 monitoring 路径复制私聊正文与外部身份。
5. 先启动 Notebook Agent Gateway 与 plugin runtime，再启动 LangBot。

具体配置与 readiness 验证请参考 [部署手册](docs/deployment.md#7-安装-langbot-桥接可选)。

## 项目结构

```text
app/
├── agent/          # Agent runtime、工具、provider 与回答契约
├── channels/       # 身份、会话、命令、确认状态与 HTTP Gateway
├── connectors/     # 内容平台 connector（当前为 YouTube）
├── ingest/         # 抓取、校验、切分、Embedding 与 Celery tasks
├── retrieval/      # 关键词与向量检索
├── cli.py          # 运维、本地导入与问答入口
└── models.py       # 多租户知识库与会话数据模型

integrations/       # LangBot bridge plugin 与安全补丁
migrations/         # Alembic 数据库迁移
docs/               # 部署、升级、回滚与排障文档
tests/              # 单元、集成、安全边界与 PostgreSQL 测试
```

## 验证

```bash
pytest -q
alembic current
alembic check
python -m app.cli ask --help
python -m app.cli users --help
```

数据库 migration 的 downgrade 自动测试只允许针对临时创建、可随时丢弃的 PostgreSQL 数据库运行，切勿对本地常用库或生产库执行破坏性降级验证。

---

Built for the **EAZO Global Hackathon** — turning scattered saved content into a private, searchable memory.
