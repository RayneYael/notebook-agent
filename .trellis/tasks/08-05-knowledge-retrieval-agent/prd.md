# 自然语言知识库检索 Agent

## Goal

基于 P0 已建立的 pgvector embedding 数据库，让 Agent 通过自然语言自主调用只读检索工具，返回带证据片段和时间戳链接的答案。

## Background

- P0 已有 `segment.embedding`、HNSW 索引、向量检索和 BM25/trigram 检索代码。
- 当前交互入口是固定流程的 `ingest` / `search` CLI；`app/agent/` 仍为空目录，没有 Agent 运行时。
- 项目是 Python 3.11、SQLAlchemy、PostgreSQL/pgvector，embedding 已使用 OpenAI-compatible API。
- 本任务是父任务 `08-04-video-text-kb` 的 P1 子任务，优先于 Web UI、浏览器扩展和新增平台 Connector。

## Requirements

- 提供 `python -m app.cli ask "<自然语言问题>"` 入口。
- Agent 可以根据问题自主改写检索词、重复检索，并按需读取相邻片段或内容条目详情。
- P1 只开放只读工具：`search_segments`、`get_neighbors`、`get_item`、`open_at`；不得转录、写库或修改观看状态。
- 知识库内容回答必须来自实际工具结果，关键结论必须附标题、证据片段和时间戳链接。
- 无结果或证据不足时明确回答知识库中未找到，不得依靠模型记忆补写。
- 工具参数与返回值使用结构化类型，设置最大调用轮数、超时和异常边界。
- Agent 运行时不能侵入现有 retrieval 层；`app/agent/tools.py` 只封装并复用已有检索能力。
- 框架、模型接口和可观测方案必须基于官方资料完成技术选型，并记录取舍。
- Agent 模型层必须保持供应商可替换，支持多个直接 provider 或 OpenAI-compatible gateway；业务工具、prompt 和最终答案契约不能依赖某个模型厂商的专有类型。
- 多平台输入/输出必须通过 channel adapter 与 Agent 核心隔离。各平台负责把自身事件归一成统一请求，并把统一答案渲染成平台消息；Agent 运行时不得直接依赖具体平台 SDK。

## Acceptance Criteria

- [ ] 输入自然语言问题后，Agent 至少调用一次检索工具，并能定位只在某视频中段出现的概念。
- [ ] Agent 可以完成 `search_segments → get_neighbors/get_item → open_at` 的多步只读工具调用。
- [ ] 最终答案包含来源标题、原文证据和可点击时间戳；人工点击后内容与结论一致。
- [ ] mock 无结果时，Agent 明确返回未找到且不会生成无来源答案。
- [ ] mock 工具异常或持续空结果时，在最大轮数内停止并给出可理解的失败说明。
- [ ] 单元测试不依赖真实模型 API；真实数据库 + 真实模型另设一条可手动运行的端到端验收。
- [ ] 切换 primary provider/gateway 或启用 fallback 时，不修改 Agent prompt、工具实现和答案 schema；provider 专有代码只存在于模型配置/适配层。
- [ ] CLI 通过统一 `AgentRequest` / `AgentAnswer` 契约调用 Agent，Agent 核心不导入 CLI 或任何具体平台 SDK，为后续 Web、扩展和消息平台复用同一核心。

## Out of Scope

- Web UI、浏览器扩展和 HTTP API。
- RRF、cross-encoder rerank 等排序增强。
- ASR、自动标签、写操作工具和长期会话记忆。
- 多 Agent 协作、handoff 和复杂任务规划。

## Confirmed Decisions

- 模型供应商必须可替换；不采用 OpenAI-only 的 Agent 架构。
- Agent 框架需要能对接多个模型 provider / gateway，并为未来多平台输入输出保留稳定边界。

## Open Questions

- Agent 框架最终选择：PydanticAI、LangChain/LangGraph、Agno、Microsoft Agent Framework 或 OpenAI Agents SDK；调研对比见 `research/agent-framework-shortlist.md`。
- 首版是否需要多轮对话上下文，或只支持单次 `ask`。
- 首批需要接入哪些用户交互渠道；微信候选包括企业微信自建应用、微信公众号、微信客服和微信小程序，详见 `research/wechat-channel-options.md`。
- 多 provider/gateway 首版只要求配置切换，还是必须同时实现自动 fallback / routing。

## Notes

- 当前处于 Trellis planning；技术选型和需求收敛完成前不进入实现。
