# State Management

> How browser state is divided by responsibility.

---

## Overview

There is no Redux, Zustand, persistent query cache, or browser-auth store. The server session cookie is the authentication source of truth, TanStack Query caches server DTOs in memory, and component state owns unsaved interaction details.

---

## State Categories

- **Server state:** session, capabilities, library pages, item detail, transcript pages, and mutation results. Owned by TanStack Query.
- **Local interaction state:** open dialog, draft URLs, save reason, current filters, edit mode, and form errors. Owned by `useState`.
- **URL state:** current route and public item ID. Owned by React Router.
- **Security state:** session and CSRF raw tokens. Owned by `Secure` cookies; the session cookie is `HttpOnly`.
- **Ephemeral login state:** email address, verification code, and current
  email/code step. Held only in `LoginPage` memory until navigation.

---

## When to Use Global State

Do not introduce application-global state for the current MVP. A new global store requires a demonstrated state owner that is neither server state, URL state, nor one component subtree.

The query client is global infrastructure, not the source of truth. Rotate it
after successful verification and seed only the returned canonical session.
Clear and replace it on confirmed logout or a `session_invalid` 401 before
another user can authenticate in the same browser. Operation-specific 401s,
such as an invalid verification code, stay in the owning form and must not
trigger global session teardown.

---

## Server State

- The API decides tenant scope from the server session.
- The API decides lifecycle and `available_actions`.
- The client never persists queries to `localStorage`, `sessionStorage`, IndexedDB, or a service worker.
- Add-video partial results remain in the open dialog while the library query is invalidated.
- Transcript cursors are opaque and only passed back to the API.
- Query cache contents are private tenant data and receive explicit teardown semantics.

---

## Common Mistakes

- Storing the session token, CSRF token, or challenge browser secret in Web Storage.
- Reusing cached library data after logout.
- Deriving retry/archive permissions from UI assumptions.
- Persisting a transcript cursor after the user leaves the detail session.
- Creating a second global source of truth for lifecycle labels.
- Treating every 401 as an expired browser session and destroying a recoverable
  login flow.
