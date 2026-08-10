# YouTube Connector Contract

## Scenario: Original-language subtitle selection and yt-dlp runtime

### 1. Scope / Trigger

Trigger: the YouTube ingestion connector consumes externally shaped yt-dlp
metadata, depends on yt-dlp's optional impersonation runtime, and launches a
bounded subtitle subprocess. A translated `zh-Hans` track was selected for an
English video because selection preferred Chinese before the video's original
language. Worker-owned YouTube requests also failed when trusted CA
initialization happened only at the later embedding stage.

### 2. Signatures

```python
def _select_track(self, data: dict) -> tuple[str, str] | None: ...
def fetch_text(self, platform_id: str) -> TextResult | NeedsASR: ...
def _connector(url: str) -> YouTubeConnector: ...
```

Dependency contract in `pyproject.toml`:

```toml
"yt-dlp[default,curl-cffi]>=2026.7,<2026.9"
```

Environment contract:

```text
TLS_CA_BUNDLE          optional explicit readable PEM bundle
SSL_CERT_FILE          inherited by yt-dlp and subtitle children
REQUESTS_CA_BUNDLE     inherited by requests/provider clients and children
```

### 3. Contracts

- Input metadata uses `language`, `subtitles`, and `automatic_captions` from yt-dlp.
- `_select_track()` returns `(source, exact_track_key)` where `source` is `official_cc` or `auto_caption`; `None` means no caption tracks are available.
- Normalize language comparison with lowercase and `_` → `-`; retain the original track key when invoking yt-dlp.
- Rank candidates by original-language match, then source (`official_cc` before `auto_caption`), then matching precision, then metadata order.
- If the original language is unavailable or missing, fall back deterministically: `*-orig`, English, Chinese, then any track.
- `fetch_text()` maps no selection to `NeedsASR`, keeps empty-response validation, and reports the selected track's base language in `TextResult.lang`.
- The ingestion worker must call
  `configure_trusted_ca(settings.tls_ca_bundle)` before constructing the real
  `YouTubeConnector`. This exports the verified bundle to `SSL_CERT_FILE` and
  `REQUESTS_CA_BUNDLE` before any metadata or subtitle request.
- yt-dlp and the bounded subtitle process inherit the worker environment; do
  not pass a replacement `env` unless it preserves both standard CA variables.
  Certificate and hostname verification remain enabled. The later embedding
  composition still receives its explicit verified `SSLContext` independently.
- The local runtime must install the declared yt-dlp extras. `curl_cffi` must import and `python -m yt_dlp --list-impersonate-targets` must list a target before treating an impersonation warning as a YouTube issue.

### 4. Validation & Error Matrix

| Condition | Required outcome |
| --- | --- |
| Original-language track exists | Select it before any translated track. |
| Official and automatic original tracks both exist | Select the official track. |
| Only an automatic original track and an official translation exist | Select the automatic original track. |
| Metadata language missing | Prefer an explicit `*-orig` track. |
| No subtitle maps contain tracks | Return `NeedsASR`. |
| Explicit worker CA is missing or unreadable | Raise `TLSConfigurationError` before connector construction or any child process. |
| yt-dlp reports 429 | Raise `TransientFetchError`; do not mark ready. |
| json3 body is empty or has no text cues | Existing transcript guard fails ingestion. |

### 5. Good / Base / Bad Cases

- Good: `language='en-US'`, automatic tracks `zh-Hans` and `en-orig` → `('auto_caption', 'en-orig')`.
- Good: the worker resolves CA before connector construction and a real ingest
  reaches `ready` without a temporary `SSL_CERT_FILE` or
  `REQUESTS_CA_BUNDLE` workaround.
- Base: `language='en'`, official `en` and automatic `en-orig` → `('official_cc', 'en')`.
- Bad: choose `zh-Hans` just because it appears first or because it is official
  when an English original track exists; or initialize CA only when building
  the embedder after the YouTube fetch has already run.

### 6. Tests Required

- Unit-test each ranking case above through `YouTubeConnector._select_track()`.
- Test `fetch_text()` returns `NeedsASR` when both maps are empty.
- Test `_connector()` resolves CA before construction and fails closed for an
  invalid explicit bundle.
- Test the bounded subtitle child observes the resolved `SSL_CERT_FILE` and
  `REQUESTS_CA_BUNDLE` through real process inheritance.
- Keep tests for json3 parsing, URL matching, 429 classification, and the verified YouTube player client.
- After a dependency update, run the full pytest suite and a real ingest. Database acceptance must assert: ready state, null failure reason, non-empty raw object key/content hash, at least one segment, valid timings, and `vector_dims(embedding) = 1536` for all segments.

### 7. Wrong vs Correct

#### Wrong

```python
lang = next((key for key in languages if key.startswith("zh")), None)
lang = lang or next((key for key in languages if key.startswith("en")), None)
```

This ignores the video's original language and can request an unnecessary translated track.

#### Correct

```python
# Rank original-language candidates first; only then prefer official captions.
source, lang, _ = min(candidates, key=lambda candidate: candidate[2])
```

The ranking key encodes language group, source priority, match precision, and stable source order.

For worker composition, this is also wrong:

```python
connector = YouTubeConnector(...)
# Too late: metadata/subtitle HTTPS may already have failed.
trusted = configure_trusted_ca(settings.tls_ca_bundle)
```

The correct ordering is:

```python
configure_trusted_ca(settings.tls_ca_bundle)
connector = YouTubeConnector(...)
connector.match(url)
```

This ordering configures both the current process and all subsequently spawned
YouTube children without weakening TLS verification.
