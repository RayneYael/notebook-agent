# Competition demo hosting options

Research date: 2026-08-08

## Confirmed submission constraint

The competition submission UI requires a public HTTPS original-experience
page. A self-hosted public Streamable HTTP MCP endpoint is a separate optional
field that can add five points. Hosting only one of these does not inherently
provide the other.

## Codex Sites

The installed Sites runtime builds and hosts Cloudflare Worker-compatible web
applications. It supports public HTTPS deployment, server-side runtime values,
external requests, and optional D1/R2 bindings. It is therefore a good fit for
a small competition chat page and a server-side proxy that keeps a backend
credential out of browser JavaScript.

It is not a drop-in host for this repository's Python 3.11 process,
PostgreSQL/pgvector schema, Celery stack, or official Python MCP SDK. Moving the
whole Agent to Sites would require a material TypeScript/Worker rewrite and a
different persistence layer. That would make the displayed experience diverge
from the submitted Notebook Agent runtime.

Recommended Sites boundary:

```text
public Sites page -> Sites server-side proxy -> Notebook Agent public API
MiXer ---------------------------------------> Notebook Agent public /mcp
```

The Notebook Agent backend still needs an independently reachable runtime and
database, but it can use the read-only competition profile and omit LangBot,
Redis, MinIO, Celery, and ingestion workers.

## Coze / 扣子

The current official Coze web application exposes hosted chat/share surfaces,
web SDK capability, workflows, plugins, and MCP-plugin functionality. A Coze
Bot can therefore provide a fast public conversational page and can call an
external business API through a plugin/workflow.

That shape still requires Notebook Agent's business API to be reachable.
Rebuilding the knowledge base and Agent orchestration inside Coze would remove
the server requirement, but it would make Coze's Agent, model orchestration,
knowledge store, quotas, and platform behavior part of the evaluated product.
It would no longer prove that the submitted Notebook Agent Python path is what
the judge is experiencing. A Coze share link also does not by itself satisfy
the separate self-hosted Streamable HTTP MCP field.

Official entry point inspected: https://www.coze.cn/open/docs

## Vercel

Vercel's current official documentation confirms that Vercel Functions can
run Python ASGI/WSGI applications and recognizes FastAPI entrypoints. Python
functions support streaming responses. With Fluid Compute, the Hobby plan has
a documented maximum of 2 GB memory and 300 seconds per invocation; the
standard uncompressed Python bundle limit is 500 MB. FastAPI is packaged as a
single function.

Vercel does not provide an embedded PostgreSQL service. Its documented path is
to connect an external Postgres provider through the Marketplace; the old
Vercel Postgres product was migrated to Neon. Notebook Agent would therefore
need an external PostgreSQL service with the pgvector extension and prepared
demo data.

This makes the following competition-only deployment technically plausible:

```text
Vercel public HTTPS project
  - minimal chat page
  - Python ASGI chat API
  - stateless JSON Streamable HTTP /mcp
        |
        +-- external PostgreSQL/pgvector
        +-- remote model and embedding providers
```

It is not yet a proven deployment contract. A time-boxed compatibility spike
must prove that the official Python MCP SDK's stateless Streamable HTTP ASGI
application works behind one Vercel Function, that the dependency bundle stays
within limits, and that database connection handling is safe under serverless
reuse. Cold starts and China-to-Vercel/provider latency are especially relevant
because the competition scores response speed. Vercel documents Hong Kong,
Tokyo, and Singapore compute regions, while functions default to US East, so
the function and database regions must be intentionally co-located.

Official sources inspected:

- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/functions/limitations
- https://vercel.com/docs/storage/vercel-postgres
- https://vercel.com/docs/regions

### Current cost envelope

Official pricing checked on 2026-08-08:

- Vercel Hobby is $0 for non-commercial personal use. It includes 4 active
  CPU-hours, 360 GB-hours of provisioned memory, and 1,000,000 function
  invocations per month. Exceeding Hobby limits normally pauses usage rather
  than automatically billing overage.
- Vercel Pro has a $20/month platform fee for one deploying seat and includes
  $20/month of infrastructure usage credit. Additional deploying seats are
  $20/month each.
- Neon Free is $0 and includes 100 CU-hours and 0.5 GB storage per project.
  It must scale to zero after five idle minutes.
- Neon Launch has no base fee or minimum spend. Compute is $0.106/CU-hour,
  database storage is $0.35/GB-month, and retained instant-restore history is
  $0.20/GB-month. Scale-to-zero can be disabled.
- A continuously active minimum 0.25-CU Neon Launch database consumes about
  187.5 CU-hours in a 750-hour month, or about $19.88/month before storage.
- A seven-day always-on 0.25-CU competition window costs about $4.45 of Neon
  compute before storage. A low-usage scale-to-zero project can cost only a few
  dollars per month.

Representative infrastructure totals, excluding model and embedding calls:

| Profile | Approximate monthly cost |
| --- | ---: |
| Vercel Hobby + Neon Free | $0 |
| Vercel Hobby + low-usage Neon Launch | about $1-$5 |
| Vercel Hobby + always-on 0.25-CU Neon Launch | about $20-$22 |
| Vercel Pro + low-usage Neon Launch | about $21-$25 |
| Vercel Pro + always-on 0.25-CU Neon Launch | about $40-$42 |

The generated `vercel.app` domain and TLS are included. Provider-model and
embedding usage, optional custom-domain registration, and abuse-driven traffic
are separate. Vercel Pro does not by itself prove zero cold starts; measured
latency remains a deployment gate.

Official pricing sources:

- https://vercel.com/docs/plans/hobby
- https://vercel.com/docs/plans/pro
- https://neon.com/docs/introduction/plans

Using Vercel's generated public HTTPS deployment avoids pointing the demo
domain at a Tencent Cloud mainland server, so it avoids Tencent's unfiled or
unconnected-domain access interception. It does not guarantee good mainland
China reachability and is not a substitute for jurisdiction-specific legal
advice.

## Tencent Cloud ICP boundary

Tencent Cloud's official ICP documentation states that website ICP filing is
performed for the second-level domain; its third- and fourth-level subdomains
can be used after the second-level domain is filed. Adding an application path
or an internal backend port is therefore not a new domain filing event.

The separate risk is access-provider filing. Tencent states that a domain
filed through another provider must complete Tencent Cloud access filing before
it is pointed at Tencent Cloud mainland CVM/Lighthouse resources, otherwise
Tencent may intercept both HTTP and HTTPS access. Reusing a domain already
filed and accessed through Tencent Cloud is the low-risk case. Reusing port 443
and routing `/api/chat` and `/mcp` internally avoids exposing a new public port;
TLS certificates are hostname-scoped rather than port-scoped.

Official sources inspected:

- https://cloud.tencent.com/document/product/243/18905
- https://cloud.tencent.com/document/product/243/18907
- https://cloud.tencent.com/document/product/243/19024

### Existing instance resource envelope

The user's existing Tencent Cloud instance is 4 vCPU / 4 GB RAM / 40 GB system
disk. Its domain has already passed ICP filing and Tencent access checks in
production. Hermes Agent already consumes roughly half of total memory, leaving
about 2 GB apparent headroom. A 50 GB cloud data disk costs the user about RMB
20/month.

This headroom is sufficient only for a constrained read-only competition
profile, subject to measured acceptance gates. Expected additional steady-state
components are one Python Agent/chat/MCP process, a small PostgreSQL/pgvector
instance, and the existing HTTPS reverse proxy. Do not start LangBot, Redis,
MinIO, Celery, beat, ingestion, or multiple web workers in this profile.

The data disk solves storage pressure but does not increase memory. Place the
prepared PostgreSQL data, application environment, and bounded logs on the data
disk where operationally safe. Avoid moving shared Docker storage without a
separate review because Hermes may already depend on it.

Before choosing this as the scoring runtime, validate with server-observed
`MemAvailable` rather than a dashboard percentage. Required gates should
include stable Hermes behavior, no OOM events or sustained swap-in, bounded
PostgreSQL connections, a single application worker, at least 700-800 MB
available memory after warm-up, and a concurrent question soak test. If these
gates fail, offload PostgreSQL to Neon or use the Vercel/Neon fallback instead
of weakening isolation or enabling more local services.

## Recommendation

First run a time-boxed Vercel compatibility spike because it may host the
mandatory page, the existing Python Agent facade, and stateless `/mcp` in one
public HTTPS project while avoiding Tencent Cloud ICP access concerns. Use an
external managed PostgreSQL/pgvector database. If MCP compatibility, bundle
size, cold-start latency, or mainland reachability fails the spike, fall back
to Codex Sites for the page and a read-only Tencent backend reusing an already
filed/accessed domain on port 443. Keep Coze as a rapid fallback demo channel,
not the canonical competition experience or MCP runtime.

Before final submission, test the Sites URL, backend reachability, and latency
from the evaluator's likely network region. A public Sites URL does not remove
the need for organizer-compatible MCP authentication, rate limiting, and
availability.
