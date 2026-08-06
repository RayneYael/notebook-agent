# Provider TLS and Request Diagnostics

## Scenario: verified model/embedding HTTPS with redacted live-path diagnostics

### 1. Scope / Trigger

Use this contract when the gateway composes an HTTPS model or query-embedding
provider, or when one channel request must be traced through Agent, embedding,
retrieval, citation validation, and response rendering. Some macOS Python
installations have no usable default OpenSSL CA file even though certifi is
installed.

### 2. Signatures

```python
def configure_trusted_ca(configured_bundle: str | None = None) -> TrustedCA: ...

class TrustedCA:
    bundle_path: str
    ssl_context: ssl.SSLContext

class RequestDiagnostics:
    @classmethod
    def start(cls, request_id: str, tenant_id: int) -> RequestDiagnostics: ...
    def event(
        self,
        stage: str,
        *,
        error_code: str | None = None,
        exception: BaseException | None = None,
    ) -> None: ...
```

Environment:

```text
TLS_CA_BUNDLE          optional explicit readable PEM bundle
SSL_CERT_FILE          standard client fallback
REQUESTS_CA_BUNDLE     standard requests/provider fallback
```

### 3. Contracts

- CA precedence is explicit `TLS_CA_BUNDLE`, existing `SSL_CERT_FILE`, existing
  `REQUESTS_CA_BUNDLE`, then the current interpreter's certifi bundle.
- The resolved path must be a readable file and load through
  `ssl.create_default_context(cafile=...)`. Certificate and hostname
  verification remain enabled.
- Gateway composition resolves CA before constructing model/provider clients.
  Query embedding receives the verified `SSLContext` explicitly; provider SDKs
  that construct their own client receive the same bundle through standard
  environment variables.
- One internally generated request ID flows from the authenticated HTTP
  boundary through `ChannelService`, `AgentRequest`, `KnowledgeAgent`, and
  `KnowledgeServices`. HTTP payload values never choose this ID.
- Diagnostic records contain only stage, internal request/tenant identifiers,
  stable error code, exception class, and duration. They never interpolate an
  exception message.
- `not_found/no_evidence`, `embedding_unavailable`,
  `retrieval_unavailable`, and `search_required` remain distinct outcomes.
  Provider/database failure never becomes a lexical-only success.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| explicit CA missing/unreadable | fail static composition with `TLSConfigurationError` |
| CA cannot be loaded | fail composition; never create an unverified context |
| provider TLS/HTTP/vector validation fails | `failed/embedding_unavailable` |
| PostgreSQL/pgvector execution fails | `failed/retrieval_unavailable` |
| embedding + retrieval succeed with zero tenant hits | `not_found/no_evidence` |
| required search was not called | `failed/search_required` |
| external request supplies `request_id` | overwrite it at the trusted HTTP boundary |

### 5. Good / Base / Bad Cases

- Good: production composition resolves certifi, a real provider returns one
  finite configured-dimension vector, and stage logs identify embedding versus
  retrieval failure without payloads.
- Base: a deployment with a valid system/default CA explicitly configures a
  readable bundle; deterministic identity/session commands remain available
  when a provider request later fails.
- Bad: pass `ssl=False`, use an unverified context, log exception text/query
  payloads, trust a channel-provided correlation ID, or silently return lexical
  evidence after query embedding fails.

### 6. Tests Required

- CA resolution rejects missing bundles and produces `CERT_REQUIRED` with
  hostname checks enabled.
- `ZhipuEmbedder.urlopen` receives the resolved SSL context.
- the authenticated gateway overwrites an input request ID;
- diagnostics include only allowed fields and exclude private exception text;
- Agent/service tests distinguish zero hits, embedding failure, retrieval
  failure, and missing search;
- PostgreSQL integration crosses Agent tool invocation, deterministic query
  embedding, real tenant-scoped pgvector SQL, and Citation hydration;
- a controlled live provider smoke records only vector count/dimension/finite
  status and coarse latency, never vector values or input text.

### 7. Wrong vs Correct

#### Wrong

```python
urlopen(request, context=ssl._create_unverified_context())
logger.exception("provider failed for %s", query)
```

#### Correct

```python
trusted = configure_trusted_ca(settings.tls_ca_bundle)
embedder = ZhipuEmbedder(..., ssl_context=trusted.ssl_context)
diagnostics.event(
    "embedding_failed",
    error_code="embedding_unavailable",
    exception=exc,  # only type(exc).__name__ is logged
)
```
