# Composer HTTP error analysis

## Observed failure

The first deployed two-stage smoke reached the answer composer with trusted
evidence, then returned deterministic evidence fallback. The safe runtime trace
for `request_id=04500bc0df8e4be89c88449d71c83794` showed:

- five successful retrieval-phase model attempts;
- one answer-phase model attempt at about 20.1 seconds;
- `agent_failed`, `agent_phase=answer`, `error_class=ModelHTTPError`,
  `error_code=answer_unavailable` at about 20.2 seconds;
- no timeout, usage-limit, citation-validation, embedding, or retrieval error.

`ModelHTTPError` contains a numeric `status_code`, but the current diagnostics
discard it and retain only the exception class. The historical record therefore
cannot distinguish 400/422 request rejection from 429 throttling or 500/503
provider failure.

## Provider contract research

DeepSeek's official 2026 documentation states:

- `deepseek-v4-flash`, base URL `https://api.deepseek.com`, function tools, and
  `tool_choice="required"` are supported;
- strict tool mode rejects unsupported schema constraints, including
  `minLength`, `maxLength`, `minItems`, and `maxItems`;
- documented HTTP failures include 400 invalid format, 422 invalid parameters,
  429 rate limit, 500 server error, and 503 overload.

Sources:

- https://api-docs.deepseek.com/guides/tool_calls
- https://api-docs.deepseek.com/guides/json_mode
- https://api-docs.deepseek.com/api/create-chat-completion
- https://api-docs.deepseek.com/quick_start/error_codes

The current Pydantic model schema contains `minLength`, `minItems`, and
`maxItems`, but PydanticAI sends the answer as a non-strict output tool. Two
synthetic live probes were sent without user content on 2026-08-08:

| Probe | Schema | HTTP | Finish reason |
| --- | --- | ---: | --- |
| original | current `AnswerDraft` schema | 200 | `tool_calls` |
| sanitized | unsupported strict-mode constraints removed | 200 | `tool_calls` |

This directly disproves the strong claim that the current schema is always
rejected. It does not prove the earlier request was transient, because its
status code was discarded.

## Bug Analysis: provider HTTP failures lose the discriminating status

### 1. Root Cause Category

- **Category**: B/D/E — cross-layer contract, test gap, and implicit assumption.
- **Specific cause**: the provider layer exposes a safe numeric status on
  `ModelHTTPError`, but runtime diagnostics project only `error_class`. Tests
  proved fallback behavior with generic exceptions without asserting the
  provider HTTP projection needed for live diagnosis.

### 2. Why earlier fixes did not close the loop

1. Tool-call convergence fixed backend fan-out but not provider error
   observability.
2. Independent composer usage fixed cumulative output-token exhaustion but
   converted all provider HTTP failures into the same evidence fallback.
3. The first logging contract correctly forbade exception messages and bodies,
   but over-redacted the safe status discriminator.
4. FunctionModel tests cannot reveal live OpenAI-compatible HTTP contract
   differences unless `ModelHTTPError` is constructed explicitly.

### 3. Prevention mechanisms

| Priority | Mechanism | Action | Status |
| --- | --- | --- | --- |
| P0 | Runtime diagnostics | Allow-list integer `http_status` in `[100, 599]` for provider HTTP failures | planned |
| P0 | Privacy | Never log `ModelHTTPError.body`, exception text, prompt, evidence, schema, URL, or API key | planned |
| P0 | Tests | Cover answer and retrieval `ModelHTTPError` with safe status projection and body sentinels | planned |
| P1 | Deployment smoke | Correlate answer fallback by trace/request ID and classify 4xx/429/5xx from status | planned |
| P1 | Spec | Record the cross-layer provider-error projection contract | planned |

### 4. Systematic expansion

- Embedding and other HTTP-backed providers can suffer the same over-redaction;
  safe numeric transport status should have one diagnostics owner.
- Retry policy must not be guessed from `error_class`; 400/422 are normally
  non-retryable, while 429/500/503 may be retryable under a bounded policy.
- The initial policy forbade response bodies even in development retrieval
  mode. The later live-400 follow-up below supersedes that local-development
  choice while retaining production redaction.

### 5. Bayesian update

| Hypothesis | Before probes | After probes | Reason |
| --- | ---: | ---: | --- |
| schema is categorically rejected | 45% | 10% | original schema returned HTTP 200 |
| transient 429/500/503 | 35% | 55% | one historical HTTP failure, later identical-shape success |
| request-specific 400/422 or resource condition | 15% | 30% | larger live evidence request was not reproduced |
| local timeout/connectivity | 5% | 5% | retrieval worked and error was HTTP, not timeout/connection |

Confidence remains below the threshold for changing composer schema or retry
policy. Adding `http_status` is the required discriminating observation. No
`src/templates/markdown/spec/` mirror exists in this repository, so the
project-local `.trellis/spec/` files are the only spec targets.

## Follow-up observation: live HTTP 400

After deploying status projection, request
`b3f368be11b245648df37217a3fbae80` / trace
`c3e62c40af754bfda7a7bd65431eb209` completed retrieval and failed on the first
answer-composer HTTP request with status 400. This rules out 429 throttling and
500/503 provider incidents for that run, but status alone does not distinguish
schema, model parameter, request-size, or input-specific validation errors.

The local operator explicitly chose full provider error observability in
`NOTEBOOK_AGENT_ENV=development`. Development events therefore preserve the
complete exception message, provider model and response body; production keeps
the prior class/status-only projection. Authentication headers and API keys are
not explicitly added to either event shape.

## Root cause confirmed from the development response body

After restarting with development diagnostics, request
`1573cbb3c89e4a05a65a56d41b36fb57` / trace
`a3c118905bf54711a63b219d48da5961` failed with:

```json
{
  "status": 400,
  "model": "deepseek-v4-flash",
  "type": "invalid_request_error",
  "code": "invalid_request_error",
  "message": "Thinking mode does not support this tool_choice"
}
```

The bare `output_type=AnswerDraft` is PydanticAI's tool-output mode. It creates
an output tool and forces `tool_choice=required`; the provider rejects that
choice while this model is in Thinking mode, before any draft or local Pydantic
validation exists. Retrieval succeeds because its ordinary function-tool path
does not force the same required output-tool choice.

The provider-independent repair candidate is
`output_type=PromptedOutput(AnswerDraft)`. It keeps JSON-schema prompting,
Pydantic parsing, the output validator and bounded retry without sending an
output tool or `tool_choice=required`. Disabling Thinking through a provider
private parameter is a less portable alternative. The earlier schema
sanitization hypothesis is now rejected for this failure.
