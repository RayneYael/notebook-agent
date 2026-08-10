# Error Handling

> How errors are handled in this project.

---

## Overview

### FastAPI response construction

Route decorators such as `status_code=204` only supply a status when FastAPI
constructs the response. A handler that returns a concrete `Response` must
construct it with an explicit valid integer status code; the injected response
object can have `status_code=None` and must not be returned directly.

For state-changing session routes, create the explicit response first, attach
the cookie mutation to that same response, then return it. Cover the complete
ASGI contract in tests: authenticated request, legal HTTP status, cookie
mutation, and the authorization state observed by the next request.

<!--
Document your project's error handling conventions here.

Questions to answer:
- What error types do you define?
- How are errors propagated?
- How are errors logged?
- How are errors returned to clients?
-->

(To be filled by the team)

---

## Error Types

<!-- Custom error classes/types -->

(To be filled by the team)

---

## Error Handling Patterns

<!-- Try-catch patterns, error propagation -->

(To be filled by the team)

---

## API Error Responses

<!-- Standard error response format -->

(To be filled by the team)

---

## Common Mistakes

<!-- Error handling mistakes your team has made -->

(To be filled by the team)
