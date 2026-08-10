# Root cause: subtitle fetch misses trusted CA initialization

## Observed behavior

- Browser email login, item submission, remote dev database persistence, Redis
  publication, yt-dlp metadata, cover image, author, duration, description, and
  chapters all succeeded.
- The item then remained in the processing lifecycle, which the frontend maps
  to an approximate fixed 65 percent.
- Celery exhausted its automatic `TransientFetchError` retry budget and marked
  the item failed. A manual retry reproduced the same result.

## Sanitized diagnostic

The same selected track was requested outside the task wrapper with a temporary
diagnostic that emitted no URL, headers, transcript, certificate data, or
environment values.

Without an explicit standard CA bundle:

```json
{"error_type":"URLError","reason_type":"SSLCertVerificationError","source":"official_cc","language":"en","stage":"subtitle_download"}
```

With both standard variables pointing to the current interpreter's certifi
bundle:

```json
{"result":"ok","response_bytes":46010,"source":"official_cc","language":"en","stage":"subtitle_download"}
```

The response byte count is recorded only to prove a bounded non-empty response;
the subtitle body was not persisted in the repository or included in logs.

## Code-path finding

`process_item()` stores metadata, sets `item.state = "fetching"`, commits, and
then calls `connector.fetch_text()`. `build_worker_embedder()` resolves trusted
CA configuration later, after transcript retrieval, so its environment export
cannot help the subtitle child process.

The Python runtime reports no usable default OpenSSL CA file, while the project's
certifi bundle is readable. `configure_trusted_ca()` already implements the
required precedence, validation, verified context, and standard-environment
export; the missing behavior is invoking it before the worker's YouTube
connector subprocesses.

## Constraints carried into implementation

- Do not disable certificate or hostname verification.
- Do not log signed subtitle URLs, provider headers, transcript content, CA
  contents, or exception messages in production task surfaces.
- Preserve the bounded-fetch process, URL/header allowlists, byte limit, and
  timeout.
- Cover both direct Celery startup and managed deployment profiles without
  depending on Agent/model composition order.
