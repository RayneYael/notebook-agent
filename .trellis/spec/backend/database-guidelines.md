# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

Notebook Agent uses SQLAlchemy and Alembic with PostgreSQL. Hosted competition
runtime traffic uses a pooled Neon URL, while schema migrations use a direct
Neon URL outside the application build and request lifecycle.

## Scenario: Keep the hosted schema revision synchronized with Alembic

### 1. Scope / Trigger

Apply this contract whenever adding or merging an Alembic migration, changing
`vercel.json`, migrating the shared Neon development database, or deploying the
competition health endpoint. It prevents a migration from reaching `main`
while the health probe still expects the previous database revision.

### 2. Signatures

```dotenv
# Vercel request runtime; must be a pooled Neon URL.
DATABASE_URL=postgresql://ROLE:PASSWORD@HOST-pooler.REGION.neon.tech/DB?sslmode=require
EXPECTED_DATABASE_REVISION=<single Alembic head>

# Operator-only migration process; must use the direct hostname.
DATABASE_URL=postgresql+psycopg://ROLE:PASSWORD@HOST.REGION.neon.tech/DB?sslmode=require
```

```bash
alembic heads
alembic upgrade head
alembic current
```

### 3. Contracts

- The repository must have exactly one Alembic head.
- `vercel.json` `env.EXPECTED_DATABASE_REVISION` must equal that head in the
  same commit that adds a migration.
- `tests/test_deployment_health.py` derives the Alembic head and asserts this
  equality; do not replace it with two copied constants.
- Apply migrations with the direct Neon URL before promoting the corresponding
  commit to the Git-connected `main` deployment. Never run migrations from a
  Vercel build, import, or request handler.
- Vercel stores only the pooled URL. Direct URLs remain in an operator's ignored
  local environment or short-lived process environment.
- The shared development database has one designated migration operator at a
  time. Destructive tests use an isolated Neon branch or a local PostgreSQL
  database, not the shared `main` branch.
- Responses and logs may expose only the expected/verified revision, never a
  DSN, database password, provider exception message, or stack trace.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Vercel expected revision differs from Alembic head | deployment test fails before commit |
| repository has multiple Alembic heads | validation fails; do not deploy or migrate |
| database revision differs from Vercel expectation | health endpoint returns redacted HTTP 503 |
| runtime URL is direct, non-Neon, non-TLS, or not pooled | health endpoint returns redacted HTTP 503 |
| migration URL is pooled | operator stops and obtains the direct URL |
| migration or connection fails | preserve the last committed expectation; report only a safe failure category |

### 5. Good / Base / Bad Cases

- Good: a reviewed migration and the Vercel expected revision are committed
  together, the designated operator upgrades Neon through the direct URL, and
  the Git deployment returns the new revision with HTTP 200.
- Base: a code-only deployment has no new migration, so the expected revision
  and Neon schema remain unchanged.
- Bad: merge a migration while leaving the old revision in `vercel.json`, share
  the direct URL in chat, migrate through the pooler, or let every collaborator
  run `alembic upgrade head` concurrently.

### 6. Tests Required

- Load `vercel.json` and assert `EXPECTED_DATABASE_REVISION` equals
  `ScriptDirectory.from_config(...).get_current_head()`.
- Cover matching revision success and mismatched revision redacted 503 behavior.
- Cover missing, direct, non-TLS, and non-pooler runtime URLs.
- Before promotion, run `alembic heads`, migrate Neon, query
  `alembic_version.version_num`, and verify required extensions without printing
  the connection URL.

### 7. Wrong vs Correct

#### Wrong

```json
{"env":{"EXPECTED_DATABASE_REVISION":"<previous revision copied by hand>"}}
```

The migration can be on `main` while Vercel continues expecting the previous
schema, making every health request fail.

#### Correct

```python
config = json.loads((root / "vercel.json").read_text())
head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
assert config["env"]["EXPECTED_DATABASE_REVISION"] == head
```

The committed configuration is checked against Alembic's actual graph instead
of another duplicated revision constant.

---

## Query Patterns

<!-- How should queries be written? Batch operations? -->

(To be filled by the team)

---

## Migrations

<!-- How to create and run migrations -->

(To be filled by the team)

---

## Naming Conventions

<!-- Table names, column names, index names -->

(To be filled by the team)

---

## Common Mistakes

<!-- Database-related mistakes your team has made -->

(To be filled by the team)
