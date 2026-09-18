# Gate 7q · FinTxn detail · Live parity harness

Shadow target: `GET /api/fin/fin-txn/{txid}`

## Scope

Class-C read-only shadow of `backend/routers/fin_day_book.py::get_fin_txn`
(L124-162).

Order: auth → `_active_company_id` → primary read → 404 → best-effort source
back-reference (Python `try/except Exception: pass`):

```
fin_txn.find_one({id: txid, user_id, company_id}, {_id:0, user_id:0})   → 404 "FinTxn not found"
stype = row.source_type or "" ; sid = row.source_id or ""
if stype in coll_map:
    <coll_map[stype]>.find_one({user_id, company_id, id: sid}, {_id:0, user_id:0})
    if src: source = {collection, doc}
→ {"txn": row, "source": source | {}}
```

Zero writes / audits / reproject / backfill. The owner-only
`POST /api/fin/reproject` bridge in the same router is OUT OF SCOPE.

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE the primary read |
| 404 literal | `{"detail": "FinTxn not found"}` — unknown / cross-user / cross-company |
| coll_map | 12 exact string keys (invoice … wallet_adjustment); case-sensitive; prototype names (`toString`) not matched |
| Known gap | `driver_payment` is ABSENT from coll_map (Iter150C) → `source: {}`; reproduced verbatim, `driver_payments` never read |
| Best effort | unknown / list / int / null source_type, missing source doc, cross-company or cross-user source, lookup error → `source: {}` |
| `or ""` | falsy `source_id` (`""`, `null`, missing) → lookup with `id: ""` |
| Mongo semantics | int and array `source_id` values pass through to real Mongo equality unchanged |
| Projection | both reads strip `_id` AND `user_id` |
| Response | `{txn, source}` in this key order |
| Empty segment / encoded slash | `txid` empty or containing decoded `/` → 404 `{"detail":"Not Found"}` before auth |
| Tenant | Owned X-Company-Id (scopes BOTH reads) / unowned fallback / default |

## Framework-level gaps (NOT counted — owned by the dedicated framework gate)

| Request | Python | Node |
|---|---|---|
| Invalid UTF-8 escape (`%FF`) | handler 404 `FinTxn not found` | Fastify 400 `FST_ERR_BAD_URL` |
| Trailing slash | 307 redirect | Fastify default 404 |
| `txid` > 100 chars | handler 404 | Fastify default 404 (`maxParamLength` 100) |

## Ports

- Python (uvicorn): `8252`
- Node   (dist):    `8253`

## Zero-write proof

Per-case collection snapshots (all 12 mapped collections + fin_txn +
driver_payments + audit/approval/counter collections) + MongoDB profiler
level 2 attributed by driver `appName` (`trukvia-gate7q-node`). The aggregate
also asserts every mapped collection was read at least once and
`driver_payments` was never read by Node.

## UAT data preservation

- Isolated DB: `trukvia_gate7q_parity_<unix_ts>`, dropped in `finally`; leftovers listed.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Run

```bash
cd backend-node
npm run build
python test/gate7q_parity/harness.py
```

Results: `<tempdir>/gate7q_parity_results.json`.

## Case matrix (45 fixed + zero-write aggregate)

Body compare: full deep-equal of parsed JSON AND identical top-level key order.

| Group | Cases |
|---|---|
| Auth | none / invalid / expired; none + unknown txid |
| coll_map | all 12 source types resolve to their collection |
| `source: {}` | driver_payment; unknown; `Invoice`; `toString`; missing source; other-company source; other-user source; list / int / null type; no source fields |
| source_id | `""`; null; int 7; array |
| Misc | special-char txid; query string ignored |
| 404 | unknown; cross-user; other company; u2 row with u1 company; encoded slash ± auth |
| Isolation | owned alt (txn + source); owned alt hides default; unowned; empty header; u2 own; u2 with u1 company |

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
46 / 46 PASS. Node profiled ops 146 (`find` 146; all 12 mapped collections
read, driver_payments 0), write ops 0. Python snapshot-write cases 0.
Informational framework block: 3 / 3 DIFF as documented above. Disposable DB
dropped; 0 leftover `trukvia_gate7q_parity_*` databases.
