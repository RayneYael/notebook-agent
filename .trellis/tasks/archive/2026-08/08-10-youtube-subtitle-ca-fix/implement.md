# Implementation Plan: YouTube subtitle trusted CA initialization

## 1. Establish regression coverage

- [ ] Add a focused worker-connector test that records call order and proves
      `configure_trusted_ca(settings.tls_ca_bundle)` runs before the real
      `YouTubeConnector` is constructed or invoked.
- [ ] Extend subtitle child-process coverage to prove the standard CA variables
      exported by trusted composition are inherited without passing provider
      URLs or CA contents through logs.
- [ ] Add or adjust failure coverage for an unreadable explicit CA bundle if the
      new composition boundary changes the exception path.

Validation gate:

```bash
.venv/bin/python -m pytest -q tests/test_tls.py tests/test_youtube.py tests/test_tasks.py
```

## 2. Move CA initialization to the outbound YouTube boundary

- [ ] Resolve `Settings` once in the real worker connector builder.
- [ ] Call `configure_trusted_ca(settings.tls_ca_bundle)` before constructing
      the YouTube connector so both metadata and subtitle subprocesses inherit
      the verified standard environment.
- [ ] Keep the existing later embedding-context injection; it still provides an
      explicit `SSLContext` to `ZhipuEmbedder` and must not be weakened.
- [ ] Do not change bounded URL/header/size/timeout behavior or exception-text
      sanitization.

Validation gate:

```bash
.venv/bin/python -m pytest -q tests/test_youtube.py tests/test_tasks.py \
  tests/test_ingest_submission.py tests/test_ingest_notifications.py
```

## 3. Cross-runtime regression check

- [ ] Run deployment/profile tests to ensure direct and managed workers retain
      configuration precedence and redaction behavior.
- [ ] Run the complete Python suite.
- [ ] Run formatting/diff checks.

```bash
.venv/bin/python -m pytest -q tests/test_deployment_cli.py \
  tests/test_deployment_health.py tests/test_tls.py tests/test_youtube.py \
  tests/test_tasks.py
.venv/bin/python -m pytest -q
git diff --check
```

## 4. Live dev acceptance

- [ ] Build/start the same real dev stack with the fixed worker and existing
      remote dev database authorization.
- [ ] Retry or submit `https://youtu.be/aircAruvnKk` through the browser API.
- [ ] Observe queued/processing transition to `ready`, not repeated
      `transient_fetch_failed`.
- [ ] Validate only non-sensitive persistence facts: raw object key/hash are
      present, segment count is positive, timings are valid, and every embedding
      is finite with 1536 dimensions.
- [ ] Verify browser console/network errors remain empty and logout still returns
      204. Archive the dedicated QA item through the UI if cleanup is desired.

## 5. Review and documentation

- [ ] Run a full-scope backend review against task artifacts and all referenced
      specifications.
- [ ] Update the YouTube and provider-TLS specs with the new composition-order
      invariant.
- [ ] Prepare logical work/spec commits, then archive the Trellis task and record
      the session according to the repository workflow.

## Rollback points

- After step 1: tests only; revert test edits if the asserted boundary is wrong.
- After step 2: revert the connector-composition call if any runtime path cannot
  safely load settings before connector creation.
- Live test data requires no database rollback; the existing archive/retry
  lifecycle owns cleanup.
