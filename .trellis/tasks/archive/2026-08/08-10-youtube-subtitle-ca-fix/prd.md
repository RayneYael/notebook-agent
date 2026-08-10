# Fix YouTube subtitle trusted CA initialization

## Goal

Ensure every real YouTube ingestion can validate HTTPS certificates before
metadata or subtitle retrieval so videos with available captions do not remain
in the processing lifecycle because of a missing Python CA path.

## Requirements

- The worker-owned YouTube ingestion path must resolve the configured trusted
  CA before its first outbound YouTube request.
- The resolved CA must apply to both the yt-dlp metadata subprocess and the
  isolated bounded subtitle-download subprocess.
- CA precedence must remain `TLS_CA_BUNDLE`, existing `SSL_CERT_FILE`, existing
  `REQUESTS_CA_BUNDLE`, then the current interpreter's certifi bundle.
- Certificate and hostname verification must remain enabled. The fix must not
  introduce `ssl=False`, an unverified context, or a provider-specific bypass.
- The direct Celery worker path and the managed `full`/`langbot` profiles must
  work without requiring the Agent/model composition root to run first.
- Existing YouTube limits and privacy boundaries must remain intact: allowlisted
  hosts and headers, bounded response size and timeout, no cookies, no signed
  subtitle URL logging, and sanitized task failure surfaces.
- Missing or invalid explicit CA configuration must fail closed with a stable,
  non-secret failure; it must not silently fall back to unverified HTTPS.
- No frontend contract change is required. The existing approximate `65%`
  processing display should naturally clear when the backend reaches a terminal
  lifecycle.

## Acceptance Criteria

- [ ] A regression test proves trusted-CA resolution occurs before construction
      or execution of the real YouTube connector used by worker ingestion.
- [ ] A regression test proves the standard CA environment exported by trusted
      composition is visible to the isolated subtitle child process.
- [ ] Existing CA precedence, readability, `CERT_REQUIRED`, and hostname-check
      tests remain green.
- [ ] Existing YouTube selection, timeout, response-bound, 429, and error
      sanitization tests remain green.
- [ ] Focused backend tests and the full Python suite pass.
- [ ] A real dev-environment ingest of `aircAruvnKk` downloads the official
      English CC track, leaves the processing lifecycle, and reaches `ready`.
- [ ] Live acceptance confirms a non-empty raw object key/content hash, at least
      one transcript segment with valid timings, and 1536-dimensional finite
      embeddings without recording transcript text, vectors, signed URLs, or
      credentials in the test evidence.
- [ ] `git diff --check` passes and no secret-bearing files or generated live
      payloads are added to the repository.

## Notes

- Root-cause evidence is recorded in `research/subtitle-ca-root-cause.md`.
- This task does not redesign progress percentages, email delivery, ingestion
  retries, or provider selection.
