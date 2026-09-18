# TRUKVIA · Phase 3 · Class-C Read Migration — Formal Freeze Record

**PHASE 3 CLASS-C READ MIGRATION: COMPLETE / FROZEN**

| Field | Value |
|---|---|
| Date | 2026-09-18 |
| Frozen baseline (HEAD at freeze) | `209f6f94a828b48e82538f83ee899b0785d70133` (Gate 8e final lock) |
| Branch | `migration/node-typescript-v2` (not pushed; remote still at `866bd67`) |
| `origin/main` | `1d9211a110a14485083cc0f6e655bab9d34d2c42` (unchanged) |
| Class-C READY remaining | **0** |
| Material Class-C blockers | **0** |
| Python business-write authority | **INTACT** |
| Node Class-C cutover | **NOT YET ENABLED** (Node serves no production traffic; frontend remains on Python) |
| Pre-cutover framework work | **REQUIRED** (see §5) |

This file is documentation only. Nothing imports it at runtime.

---

## 1. Route classification at freeze (168 Python API GET routes, 0 unclassified)

The count comes from the live FastAPI route table. It excludes the four
documentation routes (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`,
`/redoc`).

| Class | Count | Status |
|---|---|---|
| Migrated Class-C | **67** | 66 on `backend-node/.migration-allowlist` (cutover-eligible), plus `GET /api/saved-trip-filters`, which is migrated and parity-locked but held on `.migration-deferred` because its POST writer is parked for the Writer phase |
| GET-time write / backfill | 33 | Excluded from Class-C; Writer phase |
| Complex / derived read-only | 53 | Later phase |
| Security / ops / auth / public | 15 | Not Class-C |

Every migrated route was:
- parity-locked in its own gate (focused Vitest suite plus a live Python↔Node harness under `backend-node/test/gate*_parity/`)
- committed as an implementation commit followed by a pure empty lock commit

## 2. List architecture (unchanged by this freeze)

- `backend-node/.migration-allowlist` has 66 entries. All are GET-only, and each has a Python GET counterpart.
- `backend-node/.migration-deferred` has 8 entries:
  - the GET-time-write shadows `trips`, `trips/:tid`, `invoices` and `invoices/:iid`
  - the parked writers `saved-trip-filters` (GET and POST) and `expenditure-types` (POST)
  - the precedence guards `trips/export` and `trips/recurring-suggestions`
- The two lists are disjoint. Every Node `/api` path appears in exactly one list, and the CI guard enforces this.

## 3. Write authority

- **Python owns every business write:** 193 non-GET API routes, plus the GET-time writers in §1.
- **Node Class-C routes only read**, from the same authoritative collections. They do not write, backfill, seed or recompute. That's shown by a static write scan, per-gate profiler runs (0 Node writes) and database checksums.
- **The only Node business writers** are `POST /api/saved-trip-filters` and `POST /api/expenditure-types`. Both are deferred, never cutover-eligible, and reserved for the Writer / Maker-Checker phase.
- **The `idempotency_keys` handling in Node** (index creation at startup, and claim rows for POST Bucket-B requests only) is infrastructure, not a business writer.

## 4. Shared Python responsibilities that must remain available before cutover

A. **`get_current_user`**: rolling session refresh, at most once every 30 s.
Node's auth does not refresh sessions.

B. **`_active_company_id` / `_get_or_create_default_company`**: creates the
default company, or repairs `is_default`, when required. Node's tenant
resolution is read-only.

Before any cutover, Python must stay on the login / first-contact path, or
both behaviours must be ported.

## 5. Pre-cutover framework / cleanup requirements (open — not fixed)

These are not Class-C migration blockers. Each must be scheduled before any
production Node cutover.

1. **Duplicate `X-Company-Id`:** Python uses the first header value, but Node `tenant.ts` joins the values and falls back to the default company. **Must be fixed before cutover.**
2. **HEAD behaviour on older routes:** Fastify auto-HEAD answers 200, where Python answers 405. Fixed only on the 11 routes from Gate 7u onward.
3. **Trailing slash:** Python redirects with 307; Node returns 404.
4. **Encoded slash / path decoding:** Starlette routes a decoded `%2F` path onto other handlers; Node returns 404.
5. **Invalid UTF-8 path escapes and segments over 100 characters:** Node answers `FST_ERR_BAD_URL` / 404.
6. **Global security headers:** added by Python middleware, absent in Node.
7. **Content-type charset:** the older routes send `application/json; charset=utf-8` instead of `application/json`.
8. **Number / BSON serialization on older routes:** whole-number floats are written `5` instead of `5.0`, and exotic BSON types (NaN, ObjectId, Decimal128) are not mapped to Python's 500.
9. **Tie order on capped older routes:** `.limit(n)` versus Python's `to_list(n)`. Confirmed on `audit-logs` and `policy-changes`; conditional elsewhere.
10. **Integer parsing on older routes:** `approvals`, `audit-logs` and `policy-changes` reject `1.0` and `1_000`, which Pydantic accepts.
11. **Python `ApprovalGateMiddleware` 500 re-dispatch:** a Python-side defect where every 500 runs twice. **Do NOT reproduce it in Node.**

Also recorded, but not blocking: POST and other methods on GET-only paths
(Python 405, Node 404), and 404 body text on double-slash paths.

## 6. Historical metadata note

The Gate 8e lock commit (`209f6f9`) has an invisible U+FEFF before its
subject line. This is non-blocking metadata only. The commit's tree, parent
(`52ac4a6`) and emptiness are correct. It is intentionally not amended.

## 7. Next phase

**Phase 4 has NOT started.** Its scope is a separate, explicit decision
between:

- **A.** a Writer + Maker-Checker phase (the 33 GET-time writers and the 2 parked Node writers)
- **B.** a derived / complex read phase (the 53 complex reads)

Before any production Node cutover:
- the framework / tenant cleanup gate must be scheduled
- the duplicate `X-Company-Id` issue must be resolved
- the Python login and company responsibilities in §4 must remain available, or be ported
