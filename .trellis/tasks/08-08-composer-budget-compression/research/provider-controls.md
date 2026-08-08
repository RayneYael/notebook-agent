# Research: Composer Provider Limits and Thinking Controls

Date: 2026-08-08

## DeepSeek official API

Primary sources:

- Thinking Mode: https://api-docs.deepseek.com/guides/thinking_mode
- Chat Completions API: https://api-docs.deepseek.com/api/create-chat-completion
- Models & Pricing: https://api-docs.deepseek.com/quick_start/pricing

Findings:

- `deepseek-v4-flash` supports thinking and non-thinking modes; thinking is
  enabled by default at high effort.
- OpenAI-format Chat Completions disables thinking with:

  ```json
  {"thinking": {"type": "disabled"}}
  ```

  When using the OpenAI SDK, DeepSeek documents passing this field through
  `extra_body`.
- `reasoning_effort` accepts `low`, `high`, and `max`; the documented switch is
  `thinking.type`, not `reasoning_effort="none"`.
- The real Chat Completions generation cap field is `max_tokens`.
- The model-level maximum output is 384K, but that is a provider capability,
  not an appropriate application summary budget. The application should send
  its much smaller configured cap.

## PydanticAI 2.15.0 behavior

Primary sources:

- Settings API: https://ai.pydantic.dev/api/settings/
- Installed source:
  `.venv/lib/python3.11/site-packages/pydantic_ai/settings.py`
- Installed OpenAI model source:
  `.venv/lib/python3.11/site-packages/pydantic_ai/models/openai.py:1048-1089`
- Installed OpenAI profile source:
  `.venv/lib/python3.11/site-packages/pydantic_ai/profiles/openai.py:263-269`
- Installed DeepSeek provider source:
  `.venv/lib/python3.11/site-packages/pydantic_ai/providers/deepseek.py:44-66`

Findings:

- `ModelSettings.max_tokens` is the actual generation setting.
- The OpenAI Chat adapter maps that setting to either `max_completion_tokens`
  or `max_tokens` according to
  `openai_chat_supports_max_completion_tokens`; the default is the OpenAI field
  `max_completion_tokens`.
- DeepSeek's bundled provider profile correctly identifies
  `reasoning_content` and disallows required tool choice for V4, but does not
  currently override the max-token field mapping. This project therefore needs
  an explicit DeepSeek profile override for the documented `max_tokens` field.
- The generic `thinking=False` maps to OpenAI
  `reasoning_effort="none"`. That is suitable for compatible providers that
  support it, but it does not implement DeepSeek's documented toggle. DeepSeek
  must use `extra_body.thinking.type=disabled` instead.
- `UsageLimits.output_tokens_limit` is checked after provider responses. It is
  a safety budget, not a substitute for `ModelSettings.max_tokens`.

## Design consequence

Use two layers:

1. Provider-side `max_tokens=AGENT_COMPOSER_MAX_TOKENS` and disabled thinking
   prevent runaway summary generation.
2. PydanticAI `UsageLimits` remains a post-response safety net. When that net
   or provider-length structured-output handling trips, retry once using a
   smaller deterministic evidence prompt before falling back.

