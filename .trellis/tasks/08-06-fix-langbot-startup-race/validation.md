# Automated validation record

Date: 2026-08-06

## Fixed upstream baseline

- Downloaded the public `langbot==4.10.6` wheel into an external temporary
  directory and verified SHA-256:
  `ee950fd6a687cb8c7cfe646d2b9a92cfbf09b3ddfbaf8f43ea0613905d3ffbff`.
- `integrations/langbot-4.10.6-redact-monitoring.patch` passed both
  `patch --dry-run -p1` and actual application against that wheel source.
- All patched Python modules compiled after application.

## Automated tests

```text
LANGBOT_4_10_6_WHEEL=<verified local wheel> .venv/bin/pytest -q
51 passed
```

This includes the fixed-wheel patch check, bridge early-event reply regression,
gateway, channel supervisor, and multi-user tests. No real Telegram or WeChat
message was sent by automated validation.

## Local runtime readiness

- The local LangBot `plugin.required_plugins` is set to
  `notebook-agent/notebook-knowledge-agent` with a 30-second deadline.
- The private installed-plugin `.env` exists with mode `0600`; its values were
  not read or recorded.
- The patched local startup emitted `Required plugins initialized; message
  adapters may start.` before the WebUI/5300 listener was announced.
- `GET http://127.0.0.1:5300/healthz` returned `{"code": 0, "msg": "ok"}`.
- `GET http://127.0.0.1:8765/health` returned `{"status": "ok"}`.
- macOS LangBot startup uses the project virtualenv's certifi CA path for both
  `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`; no certificate verification error
  was observed during this startup.

## Local rollback material

The original local runtime is retained at
`.runtime/langbot/patched_site.pre-readiness-20260806`. A separate
`.runtime/langbot/patched_site.bad-layout-20260806` directory records an
aborted staging layout and is not an active runtime. Both paths are ignored by
Git and contain no newly created credentials.

## Acceptance handoff

This task is complete after its automated patch, privacy, readiness, deployment
and local-health criteria pass. The user confirmed that real channel acceptance
must not be duplicated here:

- `08-06-diagnose-wechat-whoami` owns the WeChat personal-account private
  smoke (two stable `/whoami` replies), safe-restart regression and human
  log/monitoring review.
- `08-05-knowledge-retrieval-agent` owns the full Telegram end-to-end and
  cross-channel product acceptance.

No real Telegram or WeChat result is claimed by this task.
