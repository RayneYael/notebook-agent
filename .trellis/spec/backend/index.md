# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | Neon runtime URLs, migration-head synchronization, and deployment safety | Active |
| [Error Handling](./error-handling.md) | Error types, handling strategies | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |
| [YouTube Connector](./youtube-connector.md) | Subtitle-track selection and yt-dlp runtime contract | Active |
| [LangBot Channel Runtime](./langbot-channel-runtime.md) | Required bridge readiness, fail-closed routing, and channel privacy | Active |
| [Provider TLS and Request Diagnostics](./provider-tls-diagnostics.md) | Verified outbound CA composition and redacted Agent/retrieval stage diagnostics | Active |
| [Agent Retrieval Convergence](./agent-retrieval-convergence.md) | Server-enforced retrieval convergence, tool-free answer composition, evidence fallback, and Top-5 video-level sources | Active |
| [Channel Identity Linking](./channel-identity-linking.md) | Deterministic `/link` validation, single-use tokens, tenant merge and privacy boundaries | Active |
| [Knowledge Item Management](./knowledge-item-management.md) | Tenant-scoped inventory tools, durable destructive confirmation, recycle-bin lifecycle, retry, and bounded purge | Active |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
