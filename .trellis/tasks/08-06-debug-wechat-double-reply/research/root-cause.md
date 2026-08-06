# Root Cause: Bridge Reply Followed by Core Fail-Closed Reply

Date: 2026-08-06

## Sanitized observation

A single private-channel inbound produced two replies: first a stable Notebook Agent result, then the
fixed LangBot channel-unavailable copy. No message content, platform identity, screenshot, or credential
is retained in this task.

The LangBot log contains a matching `RequiredPluginEventError` emitted by
`RuntimePipeline._reply_fail_closed()`. This proves the second reply came from the patched core guard,
not from a second gateway answer.

## Root cause

`langbot-plugin` 0.4.13 returns each emitted plugin using `PluginContainer.model_dump()`. Its manifest is
a serialized `ComponentManifest`, whose original YAML document is nested one level deeper:

```text
emitted_plugin
  └─ manifest                 # ComponentManifest dump
       ├─ owner
       ├─ rel_path
       └─ manifest            # original manifest.yaml document
            └─ metadata
                 ├─ author
                 └─ name
```

The current patched `validate_required_plugin_event()` instead reads:

```text
emitted_plugin.manifest.metadata
```

That lookup always misses the real author/name even though the bridge handler ran, called the gateway,
replied through `EventContext.reply(...)`, and set `is_prevent_default=True`. The validator therefore
raises `RequiredPluginEventError('required plugin did not handle the event')`; pipeline management catches
it and sends its own fail-closed reply.

The bridge-level message-ID deduplicator cannot prevent this because the second reply is sent directly by
LangBot core, outside the bridge process.

## Deployment verification note

Applying the patch to a source or generated tree is not sufficient if the `langbot` launcher resolves a
different installed package. An unpatched 4.10.6 package still has an empty `initialize_plugins()` and can
serve `/healthz` without enforcing the readiness gate. The local runtime must start with the patched package
on `PYTHONPATH` (or the patch must be applied in the exact environment used by the launcher), then emit
`Required plugins initialized; message adapters may start.` before platform smoke.

## Fix boundary

The versioned patch must decode the real nested manifest shape through a small defensive extractor and
test both the actual nested shape and malformed/missing variants. The strict checks for runtime connected,
required plugin present, and `prevent_default()` remain unchanged. The generated local patched runtime is
a deployment artifact, not the source-of-truth edit.
