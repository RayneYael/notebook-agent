# Agent 技术选型调研（第一轮）

调研日期：2026-08-05

## 项目约束

- Python 3.11 + SQLAlchemy + PostgreSQL/pgvector。
- 现有 retrieval 层已经提供向量与词法检索；Agent 不应生成 SQL，只能调用封装后的只读工具。
- P1 只有一个 Agent、4 个左右的只读工具、一次运行通常在秒级完成。
- P1 不需要多 Agent、写操作审批、跨进程恢复、长期记忆或复杂分支图。
- 必须能在 pytest 中用确定性模型替身验证工具循环，不能让单元测试调用真实模型。

## 候选比较

| 候选 | 与本项目匹配的能力 | 主要代价/错配 | 初步结论 |
|---|---|---|---|
| **PydanticAI** | Python 原生；工具、依赖和最终输出强类型；内建 Agent 工具循环；支持多个模型供应商和 OpenAI-compatible 端点；提供 `TestModel` / `FunctionModel` 和禁止真实模型请求的测试开关 | 新增一套框架依赖；可观测性深度更偏向 Logfire 集成 | **当前首选**，尤其适合保持模型可替换和确定性测试 |
| **OpenAI Agents SDK** | SDK 管理 Agent loop；函数工具；会话、guardrail、最大运行边界；内置 tracing 可记录模型/工具/guardrail/handoff | 最顺滑路径以 OpenAI 平台为中心；当前 P1 不需要 session、handoff、approval 等较多能力 | 若产品明确接受 OpenAI-only，则是首选替代 |
| **直接使用 Responses API** | 依赖最少；完全控制工具 schema、调用循环、停止条件和响应状态 | 需要自行实现多轮 tool-call loop、错误映射、测试替身、运行记录与后续会话策略 | P1 规模虽小，但维护成本没有带来足够产品价值，不推荐 |
| **LangGraph** | durable execution、checkpoint、streaming、human-in-the-loop、持久状态和复杂图编排 | 官方将其定位为低层、长运行、有状态 orchestration；P1 的短时只读检索不使用这些核心能力 | **暂不采用**；未来出现可恢复长任务或复杂审批图时再评估 |

## 已确认的产品决策

- Agent 模型层必须保持供应商可替换。
- 架构需要支持多个 provider / gateway，并为后续多平台输入输出保留扩展边界。

因此 OpenAI-only 方案不适合作为默认路线。**PydanticAI 是当前领先候选，但框架尚未定案**；完整 shortlist 及用户调研维度见 `agent-framework-shortlist.md`。是否额外部署 LiteLLM 等独立 gateway，仍需根据 routing/fallback 需求单独判断。

## 当前领先候选（尚未定案）

如果优先考虑 P1 的小体量、强类型和可测试性，建议优先验证 **PydanticAI**；无论最终选择哪个框架，都把领域工具保持为普通 Python service：

```text
app/retrieval/*                 现有数据库检索能力
        ↑
app/agent/services.py           框架无关的只读领域函数
        ↑
app/agent/tools.py              PydanticAI 工具适配与结构化 schema
        ↑
app/agent/runtime.py            Agent、模型、轮数/usage 限制
        ↑
app/cli.py ask                  薄入口
```

这条边界保证将来即使从 PydanticAI 切换到 OpenAI Agents SDK，也只需替换 `tools.py` / `runtime.py`，数据库查询和返回契约不变。

## 模型初始候选

OpenAI 官方当前将 GPT-5.6 家族分为 `sol`（旗舰能力）、`terra`（质量/成本平衡）和 `luna`（高吞吐/高效率）。本项目工具少、主要难点是查询改写与证据归纳，建议：

- 默认基线：`gpt-5.6-terra` + `low` reasoning。
- 低成本/低延迟对照：`gpt-5.6-luna`。
- 仅当真实知识库评测显示复杂偏好查询明显受益时，再对照 `gpt-5.6-sol`。

最终模型不能只凭家族定位决定；至少使用 10–20 条真实问题比较工具选择正确率、证据完整率、延迟和 token 使用。

## 不随框架变化的设计约束

1. `search_segments` 在应用代码中完成 query embedding 和 pgvector 查询；模型不能接触 SQL。
2. 工具输出为有上限的结构化数据，包含 `item_id`、`segment_id`、标题、正文、定位信息和 score。
3. 知识库问答必须至少出现一次成功检索调用。该规则由运行后校验执行，不能只写在 prompt 里。
4. 设置最大模型请求数、工具超时和结果条数；空结果允许 Agent 改写后再查，但重试次数有上限。
5. 单元测试使用确定性模型替身；真实模型只用于显式的端到端验收。
6. P1 不保存长期会话状态，除非产品需求确认需要多轮追问。

## 官方资料

- [OpenAI Agents SDK 指南](https://developers.openai.com/api/docs/guides/agents)
- [OpenAI Function Calling 指南](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI Agents SDK observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)
- [OpenAI 当前模型选择指南](https://developers.openai.com/api/docs/guides/latest-model.md)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents)
- [PydanticAI Agents](https://pydantic.dev/docs/ai/core-concepts/agent/)
- [PydanticAI Function Tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/)
- [PydanticAI Testing](https://pydantic.dev/docs/ai/guides/testing/)
- [PydanticAI Models and Providers](https://pydantic.dev/docs/ai/models/overview/)

## 待用户决策

- 从 `agent-framework-shortlist.md` 的候选中完成框架调研和最终选择。
- 首批用户交互渠道范围，以及 P1 是否仍以 CLI 为唯一入口。
- 首版多 provider/gateway 只做显式配置切换，还是需要自动 fallback / routing。
