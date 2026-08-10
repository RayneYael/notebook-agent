# Validation record

## Local implementation gates

- `python3 ./.trellis/scripts/task.py validate 08-10-youtube-ip-throttling`:
  passed with five real entries in each context manifest.
- Changed Python modules and focused tests compile with `py_compile`.
- Focused connector/config/task plus deployment tests: `119 passed`.
- `sh -n scripts/youtube-home-egress`: passed.
- `git diff --check`: passed.
- Trellis review found no worker-global proxy mutation, TLS bypass, raw stderr or
  signed-URL exception leakage, public listener, persistent Mac service, or
  unproxied retry path.

## Full-suite context

The repository `.env` enables development-only Agent flags, so the full suite
was rerun with production defaults explicitly restored. In the restricted
sandbox the result was `576 passed, 74 skipped, 2 failed`; both failures were
existing HTTP gateway tests denied permission to bind a loopback test socket.

The approved non-sandbox run completed with `636 passed, 9 skipped, 7 failed`.
None of the seven failures imports or exercises the changed YouTube connector,
bounded-fetch, configuration, helper, or deployment path:

- three remote PostgreSQL multiuser integration cases exceeded their hardcoded
  two-second Agent timeout and also failed when rerun alone;
- three logging-capture cases passed together when rerun in isolation;
- one PostgreSQL Web Auth test creates a 12-hour session at a fixed
  `2026-08-07` time and later validates it against the real current date.

No unrelated test or production code was changed to mask those failures.

## Mac and tunnel preflight

- Homebrew Core `tinyproxy 1.11.3` installed after explicit approval. No
  `brew services`, LaunchAgent, system proxy, or third-party tap trust change
  was made.
- Mac and `vps-d2a069a1` port `18080` were free before startup.
- Foreground helper reached ready state.
- Mac listener: `127.0.0.1:18080` only.
- Server reverse listener: `127.0.0.1:18080` only.
- A private comparison confirmed the Mac home and production direct public
  egress values differ; neither IP was printed or recorded.

## Public pre-activation canary

A single public video was fetched from the current production release with
temporary child-process proxy variables, before application configuration:

```text
canary_ok metadata=1 subtitle_bytes=8325 cues=61
```

No signed subtitle URL, subtitle content, proxy log, raw yt-dlp stderr, or
public IP was printed or persisted. Production release deployment and Worker
activation remain pending.
