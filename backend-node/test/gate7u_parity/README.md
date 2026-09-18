# Gate 7u · API root ping · Live parity harness

Shadow target: `GET /api/`

## Python source contract

`backend/server.py::root` (L92-94), registered directly on the app:

```python
@app.get("/api/")
async def root():
    return {"message": "Bitumen Transport Accounting API"}
```

No authentication dependency, no parameters, no DB handle, no service call.
Class-C safety verified at runtime: 0 Python DB operations per request
(profiler, appName-attributed) and no collection checksum change.

| Aspect | Python (verified live) | Node |
|---|---|---|
| Status | 200 | 200 |
| Body bytes | `{"message":"Bitumen Transport Accounting API"}` (46 bytes) | identical |
| Content-Type | `application/json` (no charset) | identical (Buffer payload) |
| Auth | none — bearer / cookie / garbage token all ignored | identical, no auth lookup |
| Query string | ignored | ignored |
| `HEAD /api/` | 405 · `allow: GET` · `application/json` · length 31 · empty body (FastAPI APIRoute registers only GET) | Fastify auto-HEAD disabled for this route; explicit HEAD reproduces the 405 exactly |

## Framework-level differences (NOT counted — framework gate)

| Request | Python | Node |
|---|---|---|
| `GET /api` (no trailing slash) | 307 → `/api/` (redirect_slashes) | Fastify 404 |
| `POST /api/` | 405 `{"detail":"Method Not Allowed"}`, `allow: GET` | Fastify 404 |
| Global security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS, CSP, Permissions-Policy) | added by middleware on every response | not added (app-level) |

New cross-gate finding recorded by this gate: every OTHER Node GET route
still auto-exposes HEAD → 200, while Python answers HEAD on its GET routes
with 405. Only `/api/` is corrected here; the rest belongs to the framework gate.

## Architecture changes required by this path

- The API root is the first allowlist entry with a trailing slash
  (`/api/`); `/api` and `/api/` are different routes in both frameworks.
- The CI guard's literal regex was `'/api/[^'"]+'` — it could not see the
  bare `'/api/'` literal. Relaxed to `'/api/[^'"]*'` so the root is guarded
  (negative test: removing `/api/` from the allowlist now fails the guard).
- Locked Gate-7t test updated accordingly (scan regex, allowlist count 56 → 57).

## Ports

- Python (uvicorn): `8262`
- Node   (dist):    `8263`

## Run

```bash
cd backend-node
npm run build
python test/gate7u_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
15 / 15 PASS byte-exact (8 GET request forms + HEAD + 5 repeats + zero-write).
DB operations per request: Python 0, Node 0 (profiler). Node write ops 0.
First run: 14 / 15 — HEAD mismatch (Python 405 vs Fastify auto-HEAD 200),
repaired in Node and the full matrix re-run. Disposable DB dropped;
0 leftover `trukvia_gate7u_parity_*` databases.
