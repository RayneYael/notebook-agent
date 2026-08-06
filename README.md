# Notebook Agent

一个按用户隔离的私有知识库 Agent。它从 PostgreSQL/pgvector 中检索真实片段，
通过 PydanticAI 组织多步只读工具调用，并由 LangBot 同时接入 Telegram、微信，
未来可按同一边界增加 Slack。

## 当前能力

- 渠道身份首次发消息即可自助注册，无需管理员预先创建。
- 每个 `AppUser` 只检索自己的 `ContentItem` / `Segment`。
- 第二渠道通过短期、单次绑定码接入同一私有知识库。
- Telegram、微信等已启用渠道可以同时运行；单个 adapter 故障不改变 Agent 核心。
- 会话最近几轮保存在 PostgreSQL，服务重启后可以恢复；不同渠道默认不混合历史。
- Agent 只有 `search_segments`、`get_neighbors`、`get_item`、`open_at` 四个只读工具。
- 无检索、无证据或伪造引用编号的模型答案会被拒绝。

## 本地启动

完整的本地、Linux 单机、容器同网络命名空间部署、升级回滚、备份和排障说明见
[`docs/deployment.md`](docs/deployment.md)。

```bash
cp .env.example .env
# 填写数据库、embedding、Agent provider 和 CHANNEL_GATEWAY_SECRET
python -m pip install -e '.[dev]'
docker compose up -d
alembic upgrade head
```

模型可使用 PydanticAI 支持的直接 provider；OpenAI-compatible 网关只需同时配置：

```dotenv
AGENT_MODEL=openai:your-model-name
AGENT_API_KEY=...
AGENT_BASE_URL=https://your-gateway.example/v1
```

`AGENT_BASE_URL` 只影响 provider 适配层，不会改变工具、prompt 或答案结构。

## 用户、导入与提问

正常用户在 Telegram/微信首次发送 `/start` 或普通问题时，系统会原子创建
`AppUser + ChannelIdentity`；回复会给出内部用户编号。`/whoami` 可以再次查看。
管理员不是正常注册的必经角色。

本地 CLI 测试可显式创建一个用户：

```bash
python -m app.cli users create
python -m app.cli ingest --user-id 12 'https://youtu.be/...'
python -m app.cli search --user-id 12 '查询词'
python -m app.cli ask --user-id 12 --thread demo '自然语言问题'
```

禁用与恢复只属于运维：

```bash
python -m app.cli users disable --user-id 12
python -m app.cli users enable --user-id 12
# 仅用于人工纠错；会改变该渠道身份可访问的私有知识库
python -m app.cli users rebind-identity --identity-id 34 --user-id 12
```

渠道内 `/new` 开启新会话，不再加载旧上下文。不同 Telegram/微信会话即使绑定
同一个用户，也默认分别恢复自己的历史。

## 绑定第二渠道

在已登录渠道发送 `/link wechat`（或 `/link telegram`），然后在目标渠道发送
`/link <绑定码>`。绑定码只存哈希、短期有效且只能消费一次。直接在第二渠道
开始使用而不输入绑定码，会创建另一个独立私有用户，系统不会按昵称自动合并。

## LangBot 多渠道桥接

固定验证版本为 LangBot 4.10.6。桥接插件位于
`integrations/langbot_kb_plugin/`，只负责把可信平台事件转换成
`ChannelEnvelope` 并路由回复；用户、会话、模型和检索权限仍由本项目管理。

1. 为应用与插件配置相同的 `CHANNEL_GATEWAY_SECRET`（至少 32 字符）。
2. 在 LangBot 中同时启用 Telegram 与 OpenClaw/iLink 微信 bot。
3. 用 `KB_BOT_CHANNELS` 把每个 LangBot bot UUID 明确映射为 `telegram` 或 `wechat`。
4. 应用 `integrations/langbot-4.10.6-redact-monitoring.patch`，避免 LangBot monitoring
   复制私聊正文和外部身份；未应用时隐私验收不得通过。
5. 启动 `python -m app.cli gateway-server`，再启动 LangBot 与 plugin runtime。

桥接仅接受 loopback HTTP，并校验 HMAC、时间戳与 nonce，重放请求会被拒绝。
Slack 后续只需增加并配置一个 `channel="slack"` adapter，不修改 Agent/retrieval。

## 验证

```bash
pytest -q
alembic downgrade -1
alembic upgrade head
python -m app.cli ask --help
python -m app.cli users --help
```

真实 Telegram、微信和真实模型不会进入自动测试。完整人工步骤见
`.trellis/tasks/08-05-knowledge-retrieval-agent/manual-acceptance.md`。
