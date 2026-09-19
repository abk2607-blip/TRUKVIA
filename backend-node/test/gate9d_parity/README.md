# Phase 4 · Gate 9d · HTTP-edge parity (live)

**Python authority.** The pinned stack is uvicorn 0.25 with h11 0.16, then Starlette 0.37.2 / FastAPI. The middleware
comes from `backend/server.py`. Request flow, outermost first:

1. h11 parser
2. ServerErrorMiddleware
3. save-health
4. idempotency
5. ApprovalGate
6. security headers (`setdefault`)
7. CORSMiddleware
8. Router

**Node implementation.** `backend-node/src/http-edge.ts`, wired in `src/app.ts`, runs over `src/python-route-table.ts`.
That table is generated from the real `server.app.routes` by `gen_python_route_table.py`: 365 routes in Starlette
dispatch order.

## What Node now reproduces

| Area | Behaviour |
|---|---|
| Security headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Strict-Transport-Security`, `Permissions-Policy` and `Content-Security-Policy`, with Python's exact values. They are added with setdefault semantics on every app response. The exceptions are the unhandled 500 (Python's ServerErrorMiddleware is outermost) and parser 400s. |
| CORS | `allow_credentials=False`, methods/headers `*`, expose `Content-Disposition`, `max_age` 600. Origins come from `NODE_CORS_ORIGINS`; empty means `*`, like Python's `CORS_ORIGINS` fallback. Preflight (Origin + OPTIONS + ACRM) is answered before routing. Simple-response headers go on every app response, including 404/405/307; with a Cookie under `*` the origin is echoed and `Vary: Origin` added. |
| Routing | Paths are decoded like uvicorn (`unquote(ascii)`, utf-8 with replacement), then matched by the Starlette Router over the Python table. |
| Routing outcomes | A FULL match on a Node-served route goes to a canonical URL, so the handler gets Python's decoded params. The first PARTIAL match gives 405 `{"detail":"Method Not Allowed"}` plus `allow`. A trailing-slash toggle gives 307 with Starlette's `location`. Otherwise 404 `{"detail":"Not Found"}`. |
| Routing details | HEAD on GET routes returns 405, because FastAPI never adds HEAD. `%2F`, `%FF`, `%0A` (Python `$`), `;`, `//` and long params behave exactly as in Python. |
| Content-Type | JSON responses are exactly `application/json`. Unhandled errors return `text/plain; charset=utf-8` "Internal Server Error". |
| Parser | Request targets outside `\x21-\x7e`, HTTP/1.1 without Host, duplicate Host headers and llhttp parse errors get h11's byte-exact 400 (`Invalid HTTP request received.`). |

## Harness

`harness.py` makes two passes: `CORS_ORIGINS` unset, then an explicit origin list. Both servers use one throwaway
database, dropped in `finally`.

**Comparison.** The full response head is compared: status line, raw body, and the header multiset (lower-case names,
exact values, `content-length` included).

**Transport headers excluded.** These are listed in the report, not hidden:
- `date`, `server: uvicorn` and `connection`
- `keep-alive`
- `transfer-encoding` (bodies are de-chunked)
- Node's own `x-request-id`

**Matrix.**
- All 66 allowlisted routes plus deferred controls × GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS, TRACE, PROPFIND.
- On GET: owner, accountant and viewer, plus Origin / bad-Origin+Cookie variants, the unhandled-500 user, and single
  and triple trailing slashes.
- Identities (owner, accountant, viewer, expired, invalid, missing user) × X-Company-Id variants: the Gate 9b/9c
  regression.
- 37 path/query edge cases × GET and HEAD+Origin.
- A preflight matrix: 5 origins × 5 methods × 4 header sets × 3 paths.
- Parser cases sent as raw bytes.

**Case classes.**
- **PARITY:** counted as pass or fail.
- **NOT-SERVED:** the method/path is FULL-matched by a Python handler that Node does not migrate (writers). It is sent
  unauthenticated only, so Python never writes. This is a routing concern for Gate 9f.
- **PARSER-GAP:** documented, never counted as a pass.

**Zero writes.** Node writes are counted from the profiler by `appName`, and the application collections' `dbHash`
must be unchanged.

**Run.** `python backend-node/test/gate9d_parity/harness.py` needs local MongoDB, the backend venv and
`npm run build`. Regenerate the table after any Python router change with
`python backend-node/test/gate9d_parity/gen_python_route_table.py`.

## Documented non-parity

**Parser grammar (llhttp vs h11).** No app-level code can reach these:
- **obs-fold header continuation:** h11 joins the lines with a single space and serves 200. llhttp rejects it, and
  Node answers with h11's 400 bytes. Node's `insecureHTTPParser` would accept it, but produces a different value
  (`"a  b"`, two spaces) and widens request-smuggling risk, so it is not enabled.
- **Unknown token methods** (`FOO`, lower-case `get`): h11 returns Starlette 405. llhttp rejects them with the h11-style
  400.
- **Size limits:** Python accepted a 17 KB request target arriving in one packet. Node rejects it with 431
  (`HPE_HEADER_OVERFLOW`), keeping Fastify's default.

**Transport.** Python sends `server: uvicorn`; Node does not. Node sends `x-request-id` and keep-alive framing.

**Proxy.** The `X-Forwarded-Proto` trust list is fixed to uvicorn's default of `127.0.0.1`. Production
`FORWARDED_ALLOW_IPS` and ingress settings belong to Gate 9f.

**Starlette docs routes** (`/docs`, `/openapi.json`, …): the `Allow` order is set-iteration order (hash-seed dependent).
These routes are outside `/api` and Node does not serve them.

**Older routes (Gate 9e).** `GET /api/files/usage` sends `"pct":0` where Python sends `0.0`.

## Result at lock

| Pass | Parity cases passed | Not-served (unauthenticated) | Parser gaps |
|---|---|---|---|
| `*` origins | 1729/1734 | 56 | 3 |
| Origin list | 1729/1734 | 56 | 3 |

- **Total:** 3468 parity cases, 3458 passed, 10 failed. All 10 failures are `files/usage` `pct` 0 vs 0.0 (Gate 9e).
- **Writes:** Node made 2422 operations per pass, all reads, 0 writes. The application collections are unchanged.
- **Regression:** Gate 9b harness 155/155 and Gate 9c harness 0 tenant failures. The charset-only content-type
  differences and 500 body-format differences both dropped to 0 in each harness.
