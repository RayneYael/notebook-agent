# Design: YouTube subtitle trusted CA initialization

## Problem statement

The real ingestion path stores YouTube metadata and sets the content item state
to `fetching` before downloading a selected subtitle track. On this macOS Python
runtime, OpenSSL has no usable default CA file. The metadata subprocess succeeds,
but the isolated `urllib` subtitle downloader fails certificate validation.

The project already owns `configure_trusted_ca()`, which validates a configured
or certifi CA bundle and exports it through `SSL_CERT_FILE` and
`REQUESTS_CA_BUNDLE`. Worker ingestion currently calls it only when constructing
the embedding client, after subtitle download. The ordering therefore leaves the
first outbound subtitle request outside the trusted composition boundary.

## Chosen boundary

Resolve trusted CA configuration in the worker's real YouTube connector
composition path, before constructing or invoking `YouTubeConnector`.

The connector builder is the narrowest shared boundary that covers:

- Celery `fetch_text_task` execution;
- synchronous/CLI ingestion that uses the real connector;
- yt-dlp metadata subprocess inheritance; and
- the later isolated `app.connectors.bounded_fetch` subprocess inheritance.

`configure_trusted_ca(settings.tls_ca_bundle)` returns a verified context and
exports the same readable bundle through standard environment variables. The
YouTube connector does not need to disable verification or receive a private
copy of the CA material. Both subprocesses inherit the worker environment
because their runners intentionally do not replace `env`.

## Alternatives considered

### Celery worker-process signal

Rejected as the only fix because it would miss synchronous ingestion and direct
connector use outside the worker lifecycle. Signal behavior also varies between
solo and prefork execution.

### Configure CA at module import

Rejected because imports must not freeze settings or mutate process environment
before the operator-owned environment is loaded.

### Disable verification or retry certificate errors

Rejected. Certificate validation failures are configuration failures, not a
reason to use unverified HTTPS or spend the transient network retry budget.

### Pass raw CA contents to the subtitle subprocess

Rejected because the existing contract already uses a validated readable path,
and copying PEM contents through request payloads adds unnecessary surface area.

## Error and privacy behavior

- An unreadable explicit bundle raises `TLSConfigurationError` and fails closed.
- Provider-generated signed subtitle URLs, request headers, certificate text,
  transcript content, and exception messages remain absent from durable logs.
- Existing `process_dispatch` sanitization remains responsible for the public
  task failure surface.
- The bounded-fetch child retains its allowlisted HTTPS hosts, safe header set,
  byte bound, socket timeout, and isolated process boundary.

## Compatibility

- No database migration or schema change.
- No frontend/OpenAPI change.
- No environment variable rename. Existing `TLS_CA_BUNDLE`, `SSL_CERT_FILE`,
  and `REQUESTS_CA_BUNDLE` behavior is preserved.
- Existing deployments with valid standard CA variables continue to use them
  according to the current precedence rules.

## Validation strategy

1. Unit-test CA initialization ordering in the real worker connector builder.
2. Unit-test that the subtitle subprocess call observes the exported standard
   CA environment without exposing its provider URL.
3. Run TLS, YouTube connector, task, and deployment-focused tests.
4. Run the full Python suite and diff checks.
5. Run one live dev ingest using the previously failing curated video and record
   only lifecycle, object-key presence, segment count/timing validity, embedding
   dimensions/finite status, and coarse latency.

## Rollback

The code change is local to worker connector composition and its tests/specs.
Rollback reverts that call and related tests. No persisted data or migration
requires reversal; a failed test item remains safely retryable through the
existing library action.
