# Sanitized live-path audit

Date: 2026-08-06

## Database evidence

Read-only checks against the configured local PostgreSQL instance returned:

```text
connectivity=ok
users=2
content_items=1
segments=291
embedded_segments=291
ready_content_items=1
tenant_1_content_items=1
```

No DSN, content title, segment text, external identity, or credential was recorded. The deployed failure
therefore cannot be attributed to an empty or unreachable database without additional evidence.

## Composition evidence

The existing path is assembled through `build_channel_service()` → `build_knowledge_agent()` → model and
embedding provider → `KnowledgeServices` → tenant-scoped BM25/vector search. `KnowledgeAgent` already has
stable branches for `embedding_unavailable`, `retrieval_unavailable`, and `not_found`.

The gap is operational proof and diagnostics: the running gateway suppresses unhandled details, and its
stdout/stderr is attached to another terminal, so the observed channel failure cannot currently be assigned
to model, embedding, or retrieval from a safe request correlation.

## TLS evidence

The project Python environment has a certifi CA file but no default OpenSSL CA file:

```text
certifi_bundle=present
python_default_cafile=none
SSL_CERT_FILE=unset
REQUESTS_CA_BUNDLE=unset
```

This is a plausible cause of outbound model/embedding TLS failures. It is not proof until a sanitized real
provider probe succeeds after trusted CA initialization. Disabling TLS verification is forbidden.

## Post-implementation live evidence

After trusted CA initialization, the production embedding builder completed one real HTTPS probe with the
following redacted result:

```text
provider_configured=yes
vector_count=1
configured_dimension=1536
actual_dimension=1536
all_finite=true
latency_bucket=under_1s
```

This proves the current query-embedding HTTPS path is usable. It does not by itself prove that missing CA
configuration caused every earlier Agent failure.

The production signed-gateway knowledge smoke is blocked by tenant data ownership, not by database
connectivity. A read-only internal ownership matrix found:

```text
internal_user=1 ready_items=1 embedded_segments=291 identities=0
internal_user=57 ready_items=0 embedded_segments=0 identities=1 channel=wechat
```

No external identity or content was recorded. There is no tenant that currently owns both a channel identity
and ready embedded content, so a real gateway request cannot return a tenant-owned citation without an
explicit data decision. Bypassing the tenant filter is forbidden. Valid options are to rebind the WeChat
identity only if both internal users are confirmed to represent the same person, ingest content under user 57,
or create a local CLI identity for user 1 solely for non-WeChat gateway verification.
