# Frontend Development Guidelines

> The implemented conventions for the Notebook Agent same-origin Web client.

---

## Overview

The frontend is a mobile-first React and TypeScript application under `web/`. It is a private video library, not a chat client. FastAPI owns authentication, tenant selection, lifecycle projection, validation, and the OpenAPI contract. React owns presentation, local interaction state, and cached server state.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Feature folders, API boundary, tests, and generated files | Active |
| [Component Guidelines](./component-guidelines.md) | Composition, props, native controls, and accessibility | Active |
| [Hook Guidelines](./hook-guidelines.md) | TanStack Query usage, polling, mutations, and effects | Active |
| [State Management](./state-management.md) | Local, URL, session, and tenant-cache ownership | Active |
| [Quality Guidelines](./quality-guidelines.md) | Required checks, security boundaries, and test expectations | Active |
| [Type Safety](./type-safety.md) | OpenAPI-generated types and runtime validation ownership | Active |

---

## Product Boundary

- Supported content: YouTube video URLs only.
- Supported routes: `/login`, `/library`, and `/videos/:id`.
- The first-empty Agent message is static copy and must never call an LLM.
- Search segments are not a transcript source. The detail page consumes the raw JSON3 transcript API.
- `summary` is optional and hidden when null. YouTube description is labeled as description, never summary.
- Browser requests never contain tenant, user, channel identity, queue task, object key, or internal database IDs.

All frontend specifications are written in English. User-facing copy remains concise Chinese.
