# Phase 4 · Gate 9g — Pre-production rehearsal and go/no-go readiness

**Status:** rehearsal only. **No production traffic was switched, nothing was installed on the live platform, and
nothing was pushed.** Writer/Maker-Checker is not started.

The frozen baseline was verified:
- The locks for 9b `6a16707`, 9c `7852872`, 9d `416a88c`, 9e `37bfa95` and 9f `782b527` are empty commits with a single
  parent, on linear history.
- The allowlist (66) and deferred list (8) have been unchanged since Gate 8e.
- The architecture is as in Gate 9f: Python stays the front door and forwards only frozen-allowlist GET/HEAD requests to
  Node on `127.0.0.1:8002`.

## 1. Rehearsal environment

| Component | Used in rehearsal | Production equivalent |
|---|---|---|
| MongoDB | A throwaway `mongod` 7.0 with `--auth` on :27018 and a temp dbpath. Users: `root` (Python), `node_ro` (strategy 1), `node_idx` (strategy 2). | Platform MongoDB |
| Python front door | uvicorn :8401 running the real `backend/server.py`. The router is configured per scenario. | supervisord `backend` (:8001) |
| Python reference | uvicorn :8400 with routing unset (today's production). | — |
| Node | Started by the **real** `deploy/supervisor/run-backend-node.sh`, with `NODE_ENV=production`, on `127.0.0.1:8002`. | supervisord `backend-node` (template) |
| Failure injection | `fake_upstream.py` on :8403 (hang, garbage, close, 502/503/504/431, genuine 404/500). | — |
| Supervisor | **Not runnable here.** supervisord is Unix-only and this host is Windows with no WSL or Docker. The template was validated with supervisor 4.2.5's own config parser. | Platform |

All application traffic was read-only. Business data lived only in the throwaway databases, which were removed.

## 2. Results

| Suite | Result |
|---|---|
| Rehearsal (`test/gate9g_rehearsal/rehearsal.py`), sections A–J | **716 / 716** (713 original + 3 observability checks added with the F2/F3 fixes) |
| Routing matrix (real 365-route table) | **34,699 / 34,699** |
| Router unit checks | **30 / 30** |
| Readiness failure modes (`gate9g-readiness-failures.test.ts`) | **3 / 3** |
| Supervisor template parsed by supervisor 4.2.5 | **17 / 17 settings** |
| Gate 9b / 9c / 9d / 9e / 9f-live regressions | see §9 |

Rehearsal sections:
- **A:** config and wrapper refusal
- **B:** database permission strategies
- **C:** liveness/readiness, including the database going away
- **D:** routing modes OFF / explicit set / percentage / kill switch / restart-off / misconfiguration
- **E:** failure injection
- **F:** circuit breaker, plus Node crash and restart
- **G:** CORS alignment
- **H:** forwarded headers
- **I:** correlation and log hygiene
- **J:** data safety

## 3. Findings and fixes

| ID | Finding | Before | After |
|---|---|---|---|
| **F1** (docs) | The wrapper sources `.env` with `sh`. An unquoted Mongo URL containing `&` is split, and a CRLF file leaves `\r` in values. | The template did not say to quote values. | `deploy/env/backend-node.production.env.example` now requires double-quoted values and LF endings. The rehearsal proves the wrapper refuses to start rather than truncating the URL. |
| **F2** (authorised fix) | Node request logging wrote the full URL. | `{"msg":"incoming request","req":{"method":"GET","url":"/api/vendors?<QUERY>","hostname":…}}` on every request (Fastify `disableRequestLogging: false`). | Fastify per-request logging is off. The single structured `request_completed` line keeps `request_id`, `method`, `route` (the template, or the path cut before `?`), `status` and `latency_ms`. It never contains a query string. |
| **F3** (authorised fix) | With routing on, httpx logged the upstream URL. | `INFO:httpx:HTTP Request: GET http://127.0.0.1:8002/api/vendors?<QUERY> "HTTP/1.1 200 OK"` | A filter on the `httpx` logger drops `HTTP Request:` records **only for the Node upstream**; other httpx users keep their logs. The `node_router` decision line still gives `request_id`, `method`, `route`, `target`, `status`, `latency_ms` and `reason`. |

After the fixes the rehearsal scanned every Python, Node and config-error log it produced:
- **query strings:** 0;
- **session tokens, cookie values, Authorization values:** 0;
- **Mongo passwords:** 0 in any log, including config and authentication failures;
- **request bodies:** none are ever logged.

Request ids correlate between the Python router and Node.

## 4. Routing proof

- The real Python table has 365 routes: 168 `/api` GET routes and 193 `/api` writer routes.
- Of the 168 GET routes, 66 are allowlisted. The other 102 include all 8 deferred routes and every GET-with-write route.
- The matrix covers every route × 7 methods, allowlist variants (query, trailing slash, double slash, encoded slash),
  precedence shadows, deferred routes, unknown `/api` paths, non-`/api` paths and all switch states: **34,699 / 34,699**.
- Only the 264 GET/HEAD and query forms of the 66 allowlisted patterns can reach Node. There is no prefix matching and no
  catch-all.
- Live (D2): with an explicit 4-route set, exactly those 4 routes reached Node, and 10 Python-owned requests never did.

## 5. Kill switch and modes (live)

| State | Result |
|---|---|
| A · default (`NODE_ROUTING_MODE` unset) | All 66 routes identical to Python; **Node received 0 requests**. |
| B · explicit route list + `PERCENT=100` | Only listed routes reach Node; responses byte-identical to Python. |
| B · `PERCENT=50` | 200 tokens × 2 passes; share within 40–60 % and stable per token; all 400 responses identical to Python. |
| C · kill file present | Python immediately (≤ 1.2 s), **no restart**; removing the file returns to Node. |
| Restart with routing unset | Python only. |
| Misconfiguration | Every case gives safe Python responses (42/42): deferred route listed, unknown route listed, percent not a number, `MODE=yes`, allowlist unreadable, upstream malformed, upstream not http. |

Router validation runs on the **first request** after start, and is logged as `node_router_enabled` or
`node_router_disabled`.

## 6. Failure / fallback and circuit breaker (live)

- **Infrastructure failures fall back to Python** exactly once. The Python route runs once (checked in the profiler) and
  the response is identical to Python's. Cases: connection refused, unroutable upstream, read timeout (hang), protocol
  error (garbage bytes, closed socket), and Node 502 / 503 / 504 / 431.
- **Genuine Node 404 and 500 are passed through once.** Python never re-runs the route (0 Python executions).
- **Circuit breaker:** after 5 consecutive failures, the next 7 requests go straight to Python and Node is not contacted.
  It closes after the 30 s cool-down.
- **Real Node crash:** all responses stayed correct through Python fallback. After Node was restarted (the harness acting
  as supervisor), routing resumed.
- The business-collection hash was unchanged across the whole failure section.

## 7. Supervision

| Item | Classification |
|---|---|
| `backend-node.conf` settings: command, directory, autostart, unconditional autorestart, startsecs 5, startretries 10, TERM, stopwaitsecs 20, stop/kill as group, 50 MB × 5 rotation for stdout/stderr | **IMPLEMENTED IN REPO**; **VERIFIED** with supervisor 4.2.5's own parser (17/17) |
| Wrapper refuses a public bind, unset host, missing secrets or a missing build; loads `.env`; runs Node in the foreground | **IMPLEMENTED IN REPO / VERIFIED IN REHEARSAL** |
| supervisord runtime: auto-start, auto-restart, retry back-off, SIGTERM stop, log rotation | **REQUIRES PLATFORM ACTION.** Not exercisable here; **not claimed as tested**. |

## 8. Database permission strategy

**Recommended: strategy 1 — rehearsed.**
1. The TTL index `idempotency_keys.ttl_created_at` must exist. Python creates it at startup, and the operator verifies
   it.
2. Node's user gets **only** `{ role: "read", db: "<DB_NAME>" }`.

Verified results:
- `node_ro` cannot insert (code 13) and cannot `createIndex` (code 13).
- Node's boot-time `createIndex` is refused and swallowed; Node boots and is ready with 66/66 routes.
- No new index appeared.

**Alternative: strategy 2 — also verified.** A custom role
`nodeStartupIndex = read + { resource: { db: "<DB_NAME>", collection: "idempotency_keys" }, actions: ["createIndex"] }`.
It can create only that index; inserts and `createIndex` elsewhere are refused.

No broad write permission is needed in either strategy.

## 9. Health / readiness and regressions

**Health / readiness:**
- `/health/live` returns 200 whenever the process is up.
- `/health/ready` returns 200 only when Mongo answers `ping` **and** all 66 allowlisted routes are registered. It makes
  `ping` commands only; no business collection is touched (profiler).
- **DB down after start:** `/health/ready` returns 503 and `/health/live` stays 200.
- **DB down at boot:** Node exits non-zero, so the supervisor retries.
- **Allowlist unreadable:** 503 `unknown`. **Allowlisted route missing:** 503 `missing` (vitest).

**Regressions (router installed, routing OFF) — final counts:**
- Gate 9b 155/155
- Gate 9c 1,595/1,595
- Gate 9d 3,468/3,468
- Gate 9e 221/221
- Gate 9f live routing harness 894/894

All counts are confirmed on the post-F2/F3 build. Also confirmed: routing matrix 34,699/34,699, router unit 30/30, and
the full vitest suite 1897/1897. Node writes were 0 in every run.

## 10. Data safety

- Node: 1,127 profiled operations in the rehearsal, **0 writes**.
- Every business-collection change during the rehearsal was written by a Python process: the known startup migrations and
  GET-time writes. **Python is the only business writer.**
- Deferred routes stayed with Python.
- Readiness and routing performed no writes.
- The kill switch returned all traffic to Python.

## 11. Known mismatches

| Mismatch | Allowlisted? | Reachable from the real frontend? | Classification |
|---|---|---|---|
| `GET /api/invoices/next-preview?invoice_date=20260501` (compact) and `2026-W18-5` (ISO week): Python 200, Node 400 | **Yes** | **No.** `InvoiceCreate.jsx` sends only `YYYY-MM-DD`, from `<input type="date">` or `toISOString().slice(0, 10)`. | **Does not block cutover; tracked.** Keep `/api/invoices/next-preview` out of early rollout route sets until a separately authorised gate aligns it. |

## 12. Platform cutover checklist (operator)

| # | Item | Repo complete | Rehearsed | Platform action required | Unresolved blocker |
|---|---|---|---|---|---|
| 1 | Install supervisord program `backend-node` from `deploy/supervisor/backend-node.conf` (with `/app/deploy/supervisor/run-backend-node.sh`), then `supervisorctl reread && supervisorctl update` | ✔ | parser ✔; runtime ✘ | ✔ | — |
| 2 | Build Node on every deploy: `cd /app/backend-node && npm ci && npm run build`. `dist/` is git-ignored. | ✔ | ✔ (local build) | ✔ | **U1: no lockfile.** Transitive dependencies (for example `find-my-way ^8`) can drift and break the verified byte parity. A committed lockfile needs separate authorisation. |
| 3 | Provision `/app/backend-node/.env` from `deploy/env/backend-node.production.env.example`: double-quoted values, LF endings, `NODE_HOST=127.0.0.1`, `NODE_PORT=8002`, `NODE_ENV=production`, `NODE_LOG_LEVEL=info` | ✔ | ✔ | ✔ | **U2:** confirm the production `DB_NAME`. Node refuses `NODE_ENV=production` when the name contains "prod"; if it does, a separately authorised change is required. |
| 4 | Database: verify the `idempotency_keys.ttl_created_at` index exists; create user `node_ro` with `{role:"read", db:<DB_NAME>}` only (strategy 1) | ✔ | ✔ | ✔ | — |
| 5 | CORS: `NODE_CORS_ORIGINS` = Python `CORS_ORIGINS`, byte for byte | ✔ | ✔ (aligned identical, misaligned detected) | ✔ | — |
| 6 | Proxy: confirm the `backend` program's `FORWARDED_ALLOW_IPS`. Node needs nothing extra: the router overwrites `X-Forwarded-Proto` / `X-Request-Id`, and Node trusts only 127.0.0.1. | ✔ | ✔ (spoofed headers change nothing) | ✔ (confirm only) | — |
| 7 | Health: `curl -s http://127.0.0.1:8002/health/ready` must be 200 with `"routes":"ok","registered_routes":66` before any routing change | ✔ | ✔ | ✔ | — |
| 8 | Routing variables in `/app/backend/.env`: start from `deploy/env/python-node-routing.env.example`; stage 1 = `MODE=on`, a small explicit `ROUTES` set (excluding `/api/invoices/next-preview`), `PERCENT=5`; then `supervisorctl restart backend` | ✔ | ✔ | ✔ | — |
| 9 | Kill switch: `touch /app/backend/.node-routing-kill` (≤ 1 s, no restart); remove the file to resume | ✔ | ✔ | know it | — |
| 10 | Rollback: see §13 | ✔ | ✔ | ✔ | — |
| 11 | Monitoring and alerts from logs: `node_router` target/reason counts, fallback rate, `node_router_circuit_open`, p95 `latency_ms` by target, Node 5xx rate, `/health/ready` ≠ 200 | ✔ (log fields) | ✔ | ✔ (dashboards/alerts) | — |
| 12 | Python stays the front door and the fallback. The ingress is unchanged, and Node is never exposed beyond loopback. | ✔ | ✔ | — | — |

## 13. Rollback procedure

1. **Immediate** (seconds, no restart): `touch /app/backend/.node-routing-kill`. Confirm the `node_router` lines show
   `"reason": "kill-switch"`.
2. **Persistent:** set `NODE_ROUTING_MODE=off` (or `NODE_ROUTING_PERCENT=0`) in `/app/backend/.env`, then run
   `sudo supervisorctl restart backend`.
3. **Optional:** `sudo supervisorctl stop backend-node`. Python keeps serving; fallback covers any in-flight request.
4. **No data rollback is ever needed**, because Node performs no writes (enforced by the read-only database user).

## 14. Readiness state

**BLOCKED — not yet ready for platform cutover actions.** This is a rehearsal result, **not** permission to switch
traffic.

**Unresolved blockers:**
- **U1:** no dependency lockfile; a reproducible build needs separate authorisation.
- **U2:** production `DB_NAME` must be confirmed against Node's "prod" guard. If the name contains "prod", a separately
  authorised change is needed.

**Required platform actions:** checklist items 1–8 and 11.

Everything else rehearsed in this gate is green, including the F2/F3 fixes.
