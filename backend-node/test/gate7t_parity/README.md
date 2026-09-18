# Gate 7t · Class-C integrity remediation · Live route-precedence verification

Gate 7t is a remediation gate, not a route migration. It resolves the three
material blockers found by the consolidated Class-C freeze audit.

## Cutover architecture (as found)

There is no runtime cutover mechanism in the repository — Node is not wired
to any ingress / proxy / supervisor. `.migration-allowlist` is consumed only
by the CI guard in `.github/workflows/backend-node.yml`, which requires every
`'/api/...'` literal in `backend-node/src/**` to be listed. It is the registry
of approved migrated routes from which a future traffic cutover is derived.

Gate 7t makes the split explicit:

| File | Meaning |
|---|---|
| `.migration-allowlist` | Class-C **cutover-eligible** read routes only (GET-only, parity-verified, no Python GET-time business write) — 62 → 56 entries |
| `.migration-deferred` (new) | Registered in `src/` but **never cutover-eligible**; Python stays authoritative — 8 entries |

The CI guard now requires every `src/` literal to appear in exactly one of
the two files (disjointness enforced).

## P1 · 6a–6d deferred (Python GET-time writes)

| Gate | Route | Python GET-time write |
|---|---|---|
| 6b | `GET /api/trips` | `trips.py::list_trips` → `_backfill_to_default` → `update_many` ×10 collections (company.py:48-58) |
| 6a | `GET /api/trips/{tid}` | `trips.py::get_trip` → `_lazy_migrate_supplier_entries` + `trips.update_one` (trips.py:1943-1952) |
| 6d | `GET /api/invoices` | `invoices.py::list_invoices` → `_backfill_to_default` (invoices.py:140) |
| 6c | `GET /api/invoices/{iid}` | `invoices.py::get_invoice` → `_recompute_invoice` → `invoices.update_one` (invoices.py:194, services.py:378) |

Moved from the allowlist to `.migration-deferred`. Implementations, tests and
historical lock commits are unchanged. Write-free siblings stay Class-C:
`/api/invoices/next-preview`, `/api/invoices/overdue`,
`/api/invoices/:iid/notes`, `/api/invoices/:iid/ship-to`.

## P2 · Node writers parked

| Route | Node write |
|---|---|
| `POST /api/saved-trip-filters` (Gate 4) | `saved_trip_filters.insertOne` + Bucket-B `idempotency_keys` claim rows (only when an `Idempotency-Key` header is sent) |
| `POST /api/expenditure-types` (Gate 5) | `expenditure_types.insertOne` |

Moved to `.migration-deferred`; implementations kept for the future
Writer / Maker-Checker phase. Every remaining allowlist path is a GET-only
registration (tested).

`idempotency_keys` startup write: `ensureIdempotencyIndex` issues
`createIndex({created_at:1}, {expireAfterSeconds: 86400, name: "ttl_created_at"})`
— identical to Python `idempotency.py:182` (`TTL_SECONDS = 24*3600`, same
name). Infrastructure, idempotent against the index Python already
maintains; not a business write. Unchanged.

## P3 · /api/trips static-route precedence

Python declares `/trips/export` (L321) and `/trips/recurring-suggestions`
(L1839) before `/trips/{tid}` (L1929). Node's 6a `/api/trips/:tid` captured
both. `src/routes/trips-static-precedence.ts` registers the two static GET
paths (Fastify prefers static over parametric segments); their handlers only
call `reply.callNotFound()` — no auth, no DB. Both paths are listed in
`.migration-deferred`; they are NOT migrated. The locked 6a file is untouched.

## Ports

- Python (uvicorn): `8258`
- Node   (dist):    `8259`

## Run

```bash
cd backend-node
npm run build
python test/gate7t_parity/harness.py
```

## Criteria

- Guard paths: Python serves its own static handler (content, or its
  auth-first 401); Node answers with the exact Fastify not-found body for the
  raw path and issues ZERO DB operations (profiler) — i.e. not captured.
- `:tid` paths: equal status and parsed-JSON equality (the Gate-6a lock
  criterion); byte equality reported.
- Zero-write: `dbHash` of every tracked collection around each Node request
  + profiler write-command count.

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
15 / 15 PASS (7 guard + 7 `:tid` + zero-write). Guards: Node 0 DB ops,
404 not-found; Python 200 CSV / XLSX / `[]` or 401. `:tid`: parsed-equal in
all 7; byte differences only whole-float text (`25.0` vs `25`,
`1200.0` vs `1200` — the documented pre-7r serialisation class). Node
profiled ops 18, write ops 0, dbHash-change cases 0. Disposable DB dropped;
0 leftover `trukvia_gate7t_parity_*` databases.
