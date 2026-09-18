# Gate 7o · Fin day-status · Live parity harness

Shadow target: `GET /api/fin/day-status?date=YYYY-MM-DD`

## Scope

Class-C read-only shadow of `backend/routers/fin_day_closing.py::day_status`
(L326-362).

Order: auth → required `date` → `if not date` → `_parse_iso_date(date,
field="date")` → `_active_company_id` → closure probe → optional late-entry
probe:

```
fin_day_closures.find_one({user_id, company_id, close_date: date},
  {_id:0, status:1, closed_at:1, closed_by:1, reopened_at:1, reopened_by:1})
fin_txn.find_one({user_id, company_id, status:"active",
  txn_date:{$lte: date}, created_at:{$gt: closed_at}}, {_id:0, id:1})
```

Zero writes / audits / snapshot capture / backfill. Day-closing writers and
`/fin/day-closures/{d}/late-entries` remain Python-authoritative and OUT OF
SCOPE.

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE all validation (missing / blank / invalid date → 401 when unauthenticated) |
| Required param | Missing `date` → 422 `{"detail":[{"type":"missing","loc":["query","date"],"msg":"Field required","input":null,"url":".../2.13/v/missing"}]}` |
| 400 literals | blank → `date is required (YYYY-MM-DD)`; invalid → `date must be ISO YYYY-MM-DD` |
| Date validation | CPython 3.11 C `date.fromisoformat` (identical to Gate 7n, local copy) |
| `if not doc` | Projected closure `{}` (none of the 5 fields) → not-found shape `{date, is_closed:false}` |
| Late probe gate | Only when `status == "closed"` (case-sensitive) AND `closed_at` Python-truthy (`""`, `0`, `[]`, `false`, `null` falsy) |
| `bool(find_one)` | Matching fin_txn without `id` projects to `{}` → `false` |
| Response | Found → `{date, is_closed, status, closed_at, closed_by, reopened_at, reopened_by, has_late_entries}` in this key order; missing `status` → `null`, other missing → `""`; present `null` stays `null` |
| Raw date | Query value used verbatim in both filters (compact / ISO-week stored dates match only verbatim) |
| Repeated keys | Last occurrence wins |
| Tenant | Owned X-Company-Id / unowned fallback / default (locked `activeCompanyId`) |

## Ports

- Python (uvicorn): `8244`
- Node   (dist):    `8245`

## Zero-write proof

Per-case collection snapshots + MongoDB profiler level 2 on the disposable DB
attributed by driver `appName` (`trukvia-gate7o-node`). Any Node write command
fails the gate; Node reads on both `fin_day_closures` and `fin_txn` must be > 0.

## UAT data preservation

- Isolated DB: `trukvia_gate7o_parity_<unix_ts>`, dropped in `finally`; leftovers listed.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Run

```bash
cd backend-node
npm run build
python test/gate7o_parity/harness.py
```

Results: `<tempdir>/gate7o_parity_results.json`.

## Case matrix

50 fixed cases + 300 deterministic fuzz dates (seed 7000015) + 1 zero-write
aggregate. Body compare: full deep-equal of parsed JSON AND identical key
order for object bodies.

| Group | Cases |
|---|---|
| Auth + precedence | none / invalid / expired; none + missing; none + blank; expired + invalid |
| Validation | missing; other key only; blank; bare `?date`; text; unpadded; non-leap; year 0; space; raw `+`; datetime; `%FF`; `2026-05-%FF`; `%00` |
| Shapes | no closure; closed + late; closed no late; reopened; `closed_at` `""`/`0`/`5`/`[]`/`{k:1}`/`true`; projects-to-`{}`; missing reopened_* + null closed_by; id-less late txn; `CLOSED`; `status` null; compact stored; compact ≠ ISO; ISO-week stored; week not stored; extra key; repeated keys (valid / invalid / blank last) |
| Isolation | u2 same date; default hides alt; owned alt; unowned; empty header; u2 with u1's company id; u2 probe scoping |

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
351 / 351 PASS (50 fixed + 300 fuzz + 1 zero-write; fuzz py status mix
200×82, 400×218). Node profiled ops 583 (`find` 583: user_sessions 347,
companies 112, fin_day_closures 110, fin_txn 14), write ops 0. Python
snapshot-write cases 1 — `user_sessions` rolling refresh inside
`get_current_user`. Disposable DB dropped; 0 leftover
`trukvia_gate7o_parity_*` databases.
