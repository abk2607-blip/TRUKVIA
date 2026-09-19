# Phase 4 · Gate 9f — Cutover infrastructure, routing and production readiness

**Status:** the infrastructure is implemented in the repository and **OFF**. No production traffic has been switched.
Production cutover, Gate 9g and Writer/Maker-Checker are **not started**.

Legend used below:
- **[REPO]** implemented in this repository
- **[VERIFIED]** proven by a local/integration harness against throwaway data
- **[PLATFORM]** must be configured outside the repository; not present in it

## 1. What production routing actually is (discovered)

| Fact | Evidence |
|---|---|
| Hosting is an Emergent Kubernetes pod (`fastapi_react_mongo_shadcn_base_image_cloud_arm`) | `.emergent/emergent.yml` |
| The Python API runs as supervisord program `backend` (uvicorn :8001); the restart procedure is `sudo supervisorctl restart backend` | `DEPLOY.md`, `memory/PRD.md`, `regression-guard.yml` |
| A platform-managed Kubernetes ingress (behind the Cloudflare edge) sends `/api/*` to that process and sets `X-Forwarded-For` | `backend/server.py` save-health comments, `memory/PRD.md` |
| The frontend calls `${REACT_APP_BACKEND_URL}/api` — one origin for every API call | `frontend/src/api.js` |
| The supervisord program files and the ingress rules are **not** in the repository | (absent) |
| There is no reverse proxy, Dockerfile, compose file, nginx/Caddy or Kubernetes manifest | (absent) |

**Decision: (c) forwarding from the Python layer.**
- Options (a) reverse proxy/ingress and (b) platform path routing would need ingress rules that the repository cannot see
  or verify.
- Python stays the front door. A pure-ASGI middleware, `backend/node_router.py`, is installed as the **outermost** user
  middleware. It forwards only frozen-allowlist GET/HEAD requests to Node on `127.0.0.1:8002`; everything else is served
  by Python exactly as today.
- The ingress needs **no change**.
- **Trade-off:** routed requests still pass through the Python process (one extra loopback hop), so Python load is not
  removed during the migration. Moving routing to the ingress later requires platform capabilities that are not
  verifiable today (§12).

## 2. Selective routing [REPO][VERIFIED]

A request goes to Node only if **all** of these hold:
1. `NODE_ROUTING_MODE=on`, `NODE_ROUTING_ROUTES` is non-empty, and `NODE_ROUTING_PERCENT > 0`. With the default env,
   nothing is forwarded.
2. The kill-switch file does not exist.
3. The method is GET or HEAD.
4. The **first** Python route that FULL-matches the request for GET is on `backend-node/.migration-allowlist`, not on
   `.migration-deferred`, and is selected in `NODE_ROUTING_ROUTES`.
   - This decision is made by Starlette's own router over the real `app.routes`: no prefix matching and no catch-all.
   - A Python-owned route can never reach Node, and a Node 404 can never pull a request away from Python.
5. The stable bucket (hash of session token + route) is below `NODE_ROUTING_PERCENT`.
6. The circuit breaker is closed.

**Startup validation (fail-safe).** Routing is disabled, and Python serves everything, in any of these cases:
- an allowlist entry does not map to exactly one Python GET route;
- a deferred route is requested;
- `NODE_ROUTING_ROUTES` names a path that is not on the frozen allowlist;
- the allowlist cannot be read.

No route enters Node through Gate 9f. The allowlist (66) and the deferred list (8) are unchanged.

## 3. Kill switch [REPO][VERIFIED]

- **Instant, no restart:** `touch /app/backend/.node-routing-kill`. Every request is then served by Python. The file is
  checked on every request (cached ≤ 1 s) and is git-ignored.
- **Persistent:** `NODE_ROUTING_MODE=off` (the default), or `NODE_ROUTING_PERCENT=0`, in `backend/.env`, followed by
  `sudo supervisorctl restart backend`.
- **Default production state:** Python-only. The switch can only turn Node **off**. It cannot enable a route outside
  the frozen allowlist.

## 4. Per-route and percentage rollout [REPO][VERIFIED]

- `NODE_ROUTING_ROUTES` takes a comma list of frozen allowlist paths (for example `/api/vendors,/api/vendors/:vid`), or
  `all`.
- `NODE_ROUTING_PERCENT` is 0–100. The bucket is `sha256(first Authorization/Cookie value + route)`, so it is stable per
  user and route. Measured over 2000 tokens at 30 %, the share was within 25–35 %.
- Changes need `supervisorctl restart backend`, because they are read at startup. The kill switch does not.
- No traffic was switched in Gate 9f.

## 5. Fallback [REPO][VERIFIED]

**Infrastructure failures → the request is served by Python in-process.** These are:
- connect error or connect timeout (0.5 s);
- read timeout (15 s);
- an HTTP protocol error;
- Node status 502, 503, 504 or 431.

Fallback is safe because routed requests are GET/HEAD reads and Node never writes.

**Circuit breaker:** 5 consecutive infrastructure failures open it for 30 s; Node is not contacted while it is open.

**A genuine Node response is returned as-is** — any other status, including 4xx and 500. It is dispatched exactly once:
there is no fallback, and Python's `ApprovalGateMiddleware` double-dispatch is not reproduced.

**Limitations:**
- A timeout can occur after Node has already read the database. That is harmless because Node does reads only.
- Fallback cannot help when Python itself is down, because Python is the front door.

## 6. Parser / transport edge (the earlier Gate 9f items) [VERIFIED]

Because the ingress sends every request to uvicorn/h11 first, **Python's own parser handles all traffic before any
forwarding**:

| Earlier item | Result with the Python front door |
|---|---|
| obs-fold continuation lines | h11 joins them before routing, and the forwarded request carries the normalised value. Live: response identical to Python. |
| unknown or lower-case methods (`FOO`, `get`) | Python answers 405; they are never forwarded (only GET/HEAD are eligible). |
| very long request heads | h11 decides. If a forwarded head exceeds Node's 16 KB limit, Node's 431 triggers a Python fallback. Live: identical. |
| non-ASCII targets | h11 400; never forwarded. |
| `server: uvicorn` vs Node `x-request-id` | uvicorn adds `server`/`date` to every response. The router strips Node's `date`, `server`, `x-request-id` and hop-by-hop headers. Live: header set identical to Python. |

Node's parser is **not** weakened. `insecureHTTPParser` stays off, and Gate 9d's `http-edge.ts` is unchanged.

## 7. Process supervision [REPO template][PLATFORM]

- `deploy/supervisor/backend-node.conf` defines supervisord program `backend-node`:
  - `autostart`, `autorestart`, `startretries=10`, `stopsignal=TERM`, `stopasgroup`/`killasgroup`;
  - rotated logs in `/var/log/supervisor/backend-node.*.log`.
- `deploy/supervisor/run-backend-node.sh`:
  - loads the git-ignored `/app/backend-node/.env`;
  - refuses a non-loopback `NODE_HOST`, missing secrets or a missing build;
  - `exec`s node in the **foreground**, so supervisord owns it. It is never an unmanaged background process.
  - Verified locally: refusal paths exit 64/66/non-zero, and the happy path reaches readiness 200.
- **[PLATFORM]** The pod's `/etc/supervisor/conf.d` is image-managed and not persistent in `/app`. The platform must
  install the program, or provide an equivalent managed process, and run the build on deploy:
  `cd /app/backend-node && <install deps> && npm run build`. `dist/` is git-ignored.

## 8. Production configuration [REPO templates][PLATFORM]

- `deploy/env/backend-node.production.env.example` — Node settings; **no secrets**. Every value is validated by
  `src/config.ts`, fails loud, and has no silent production defaults:
  - `NODE_HOST=127.0.0.1` and `NODE_PORT=8002`
  - `NODE_LOG_LEVEL=info`
  - `NODE_TRUST_INCOMING_REQUEST_ID=true` (safe: loopback-only, and the router overwrites the id)
  - `NODE_CORS_ORIGINS` **must equal** Python's `CORS_ORIGINS`
- `deploy/env/python-node-routing.env.example` — Python router settings (all default to Python-only).
- **Secrets from the platform:** `NODE_MONGO_URL`. Use a **read-only** database user:
  - Node performs no business writes, so read-only makes that a database guarantee.
  - Node's boot-time `createIndex` (the same TTL index Python already creates) then fails and is swallowed.
- Existing Python CI uses `CORS_ORIGINS="*"`. The production value lives in the platform's `backend/.env`.

## 9. Health and readiness [REPO][VERIFIED]

- `GET /health/live` — the process is up.
- `GET /health/ready` — **200 only when Mongo answers `ping` AND all 66 frozen-allowlist routes are registered** as GET
  routes. It returns 503 otherwise, and fails closed if the allowlist is unreadable. It makes no business read or write
  (asserted: no collection access).
- Both are Node-only and bypass the Python router table.
- **[PLATFORM]** Poll `http://127.0.0.1:8002/health/ready` before enabling routing, and during rollout.

## 10. Observability [REPO]

**Python router log** (logger `node_router`, JSON, in the `backend` program's log). Each routed decision records:
- `request_id`, `method`, `route` (template)
- `target`: `node`, `python`, or `python-fallback`
- `status`, `latency_ms`
- `reason`: `eligible` / `percent` / `kill-switch` / `circuit-open` / exception class / `node-5xx`

Also logged: `node_router_enabled` / `node_router_disabled` at startup, and `node_router_circuit_open`.

**Node's pino log** carries the same `request_id`, which gives end-to-end correlation.

**Never logged:** headers, cookies, Authorization, tokens, query strings or bodies (pino redaction is also in place).

**Rollout metrics to derive from the logs:**
- count by target / route / status
- p50/p95 latency by target
- fallback count and reasons
- circuit-open events
- readiness polls

## 11. Forwarded / proxy headers [REPO][VERIFIED]

- uvicorn trusts `X-Forwarded-*` only from `FORWARDED_ALLOW_IPS`, which defaults to `127.0.0.1`. The production value is
  the platform's `backend` command/env **[PLATFORM, unknown]**.
- The router **replaces** any client `X-Forwarded-Proto` with the scheme uvicorn resolved, and **replaces** any client
  `X-Request-Id`. Node trusts `X-Forwarded-Proto` only from `127.0.0.1` (the router).
- Node therefore sees exactly Python's scheme, whatever the production `FORWARDED_ALLOW_IPS` is. Client-supplied
  forwarded headers change nothing (verified live with spoofed values).
- `X-Forwarded-For` is passed through untouched. No migrated route uses it.

## 12. Blockers before production cutover (Gate 9g decisions)

1. **[PLATFORM] Supervisor program and build step.** Node must be installed as a managed process and built on deploy
   (§7).
2. **Node refuses production database names.** `src/config.ts` refuses `NODE_ENV=production` when `NODE_DB_NAME`
   contains "prod". If the production `DB_NAME` contains "prod", lifting this guard is a deliberate, separately
   authorised change.
3. **No lockfile** (removed in Gate 7t). A production `npm install` is not reproducible; a lockfile must be restored.
4. **Read-only database user** for Node (§8) — strongly recommended.
5. **`NODE_CORS_ORIGINS` must equal `CORS_ORIGINS`**, both set by the platform.
6. **Python-only side effects stay in Python** (freeze §4): the rolling session refresh and default-company repair
   happen only on Python-served requests. The frontend's bootstrap `/api/auth/me` and `/api/companies` remain Python.
7. **Open parity item, not infrastructure:** `next-preview` accepts `YYYYMMDD` and ISO-week dates in Python (200) but
   not in Node (400). Recorded outside 9f.
8. **Extra hop:** routed requests still occupy the Python process (§1).

## 13. Proof artifacts

- `backend-node/test/gate9f_routing/routing_matrix.py` — deterministic matrix over the real 365-route Python table:
  34,699/34,699.
- `backend-node/test/gate9f_routing/router_unit.py` — forwarding contract, fallback, circuit breaker, kill switch:
  30/30.
- `backend-node/test/gate9f_routing/live_harness.py` — routing-off Python vs routing-on Python → Node, with a live
  kill switch and Node-down test: 894/894.
- `backend-node/test/gate9f-readiness.test.ts` — readiness: 4/4.
