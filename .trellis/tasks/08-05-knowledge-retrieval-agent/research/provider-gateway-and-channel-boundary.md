# 多 Provider / Gateway 与多渠道边界

调研日期：2026-08-05

## 结论

使用 **PydanticAI 作为 Agent runtime 和模型抽象**，应用维护显式的 model/provider registry。P1 不额外部署 LiteLLM Proxy 或绑定 Pydantic AI Gateway；两者都可以作为未来 gateway endpoint 接入，但不是 Agent 正确运行的前置条件。

PydanticAI 官方支持：

- OpenAI、Anthropic、Gemini、Bedrock、Mistral、OpenRouter 等多个原生 provider。
- 通过 `OpenAIChatModel` + `OpenAIProvider(base_url=...)` 接任意 OpenAI-compatible gateway。
- 通过不同 Provider 类处理同一模型接口下的认证、endpoint 和模型 profile 差异。
- 通过 `FallbackModel(primary, *fallbacks)` 在 API 异常或指定语义失败时顺序回退。
- Pydantic AI Gateway、LiteLLM、Vercel AI Gateway 等均可作为可选 endpoint，而不是业务代码依赖。

## 推荐模型配置边界

```text
Settings / environment
  → ModelRouteConfig
      primary: provider + model + endpoint/key ref
      fallbacks: [provider + model + endpoint/key ref]
  → build_model(config)
  → PydanticAI Model / FallbackModel
  → 同一个 Agent、同一组 tools、同一个 AgentAnswer
```

建议新增的配置概念（字段名在 design 阶段最终确定）：

```text
AGENT_MODEL_PRIMARY
AGENT_MODEL_FALLBACKS
AGENT_MODEL_MAX_REQUESTS
AGENT_MODEL_TIMEOUT_SEC
```

API key 继续使用各 provider 自己的环境变量或 secret reference，不把明文 key 塞进通用 JSON 配置。

## 首版不建议加入独立 Gateway 服务

P1 是单用户、低频、单进程 CLI。此时部署 LiteLLM Proxy 或托管 gateway 会新增网络跳点、配置面和故障面，但尚无统一计费、团队密钥治理、复杂路由或集中限额的刚需。

先由 PydanticAI 直接连接 provider/gateway endpoint，保持以下升级路径：

1. 本地显式 primary + fallback。
2. 需要跨应用统一密钥、预算、速率限制和路由时，再把 primary 指向独立 gateway。
3. 工具、prompt、AgentAnswer 和渠道适配器无需变化。

## 多平台输入/输出不是模型 Gateway

两者必须解耦：

```text
CLI / Web / Browser Extension / Messaging Platform
                 ↓
           Channel Adapter
                 ↓
             AgentRequest
                 ↓
            Agent Service
                 ↓
             AgentAnswer
                 ↓
     Channel-specific rendering / streaming
```

统一契约的最低字段建议：

```python
AgentRequest(
    channel: str,
    user_id: int,
    conversation_id: str | None,
    text: str,
    attachments: list[AttachmentRef],
    metadata: dict[str, JSONValue],
)

AgentAnswer(
    text: str,
    citations: list[Citation],
    status: AnswerStatus,
    usage: UsageSummary | None,
)
```

P1 只实现 CLI adapter，但 CLI 也必须走这套契约，不能直接调用框架的 `Agent.run_sync()` 后打印字符串。这样后续 Web/SSE、扩展消息、Telegram/Slack/微信等只负责事件解析和渲染，不会复制 Agent 逻辑。

## 仍需决策

- P1 的“多 gateway”是只需显式配置切换，还是必须交付自动 fallback。
- 首个非 CLI 渠道是什么；该答案会影响是否需要在 P1 就设计 streaming event contract。

## 官方资料

- [PydanticAI Models and Providers](https://pydantic.dev/docs/ai/models/overview/)
- [PydanticAI OpenAI-compatible providers](https://pydantic.dev/docs/ai/models/openai/)
- [PydanticAI FallbackModel](https://pydantic.dev/docs/ai/api/models/fallback/)
- [Pydantic AI Gateway](https://pydantic.dev/docs/ai/overview/gateway/)
- [PydanticAI AG-UI adapter](https://pydantic.dev/docs/ai/api/ui/ag_ui/)

