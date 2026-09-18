# Gate 7p · Driver salary-masters list · Live parity harness

Shadow target: `GET /api/drivers/{did}/salary-masters`

## Scope

Class-C read-only shadow of `backend/routers/driver_ledger.py::_assert_driver`
(L78-85) + `list_salary_masters` (L91-99).

Order: auth → `_active_company_id` → driver pre-check → list:

```
drivers.find_one({id: did, user_id, company_id}, {_id:0, user_id:0})   → 404 "Driver not found"
driver_salary_masters.find({user_id, company_id, driver_id: did}, {_id:0})
  .sort([("effective_from", -1), ("version", -1)]).to_list(500)       → {"items": [...]}
```

Zero writes / audits / backfill. `POST /api/drivers/{did}/salary-masters`
(closes the prior open-ended master) and all driver-ledger writers remain
Python-authoritative and OUT OF SCOPE.

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE the driver pre-check |
| 404 literal | `{"detail": "Driver not found"}` — unknown / cross-user / cross-company / legacy driver without `company_id` |
| Projection | Salary masters `{_id: 0}` ONLY — **user_id PRESERVED**; driver pre-check `{_id:0, user_id:0}` |
| Sort | `effective_from` DESC, then `version` DESC — verified on real Mongo with mixed BSON types (string > number > null/missing; string version `"10"` > numbers) |
| Cap / wrapper | 500 (verified with 502 rows) · `{items}` |
| Empty segment / encoded slash | `//` or decoded `/` in `did` → 404 `{"detail":"Not Found"}` before auth (Starlette `[^/]+` params on the decoded path) |
| Tenant | Owned X-Company-Id / unowned fallback / default (locked `activeCompanyId`) |
| Neighbour | Gate 6y `/api/drivers/{did}/payments` re-checked in the same run |

## Framework-level gaps (NOT counted — owned by the dedicated framework gate)

| Request | Python | Node |
|---|---|---|
| Invalid UTF-8 escape (`%FF`) | handler 404 `Driver not found` | Fastify 400 `FST_ERR_BAD_URL` |
| Trailing slash | 307 redirect | Fastify default 404 |
| `did` > 100 chars | handler 404 | Fastify default 404 (`maxParamLength` 100) |
| `d1%2Fledger` (decodes onto DELETE-only `/drivers/{did}/ledger/{eid}`) | 405 `Method Not Allowed` | 404 `Not Found` |

## Ports

- Python (uvicorn): `8246`
- Node   (dist):    `8247`

## Zero-write proof

Per-case collection snapshots + MongoDB profiler level 2 on the disposable DB
attributed by driver `appName` (`trukvia-gate7p-node`). Any Node write command
fails the gate; Node reads on `drivers` and `driver_salary_masters` must be > 0.

## UAT data preservation

- Isolated DB: `trukvia_gate7p_parity_<unix_ts>`, dropped in `finally`; leftovers listed.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Run

```bash
cd backend-node
npm run build
python test/gate7p_parity/harness.py
```

Results: `<tempdir>/gate7p_parity_results.json`.

## Case matrix (30 fixed + zero-write aggregate)

Body compare: full deep-equal of parsed JSON AND identical key order.

| Group | Cases |
|---|---|
| Auth | none / invalid / expired; none + unknown driver |
| Hits | d1 mixed-type sort; empty list; 502 → 500 cap; special-char id; query string ignored |
| 404 Driver not found | unknown; cross-user; other company; legacy no company_id; u2 row with u1 company; case-sensitive id; `%20`; unicode |
| Not Found | encoded slash ± auth; empty `//` ± auth |
| Isolation | u2 same id; u2 own; owned alt; owned alt hides default; unowned; nonexistent; empty header; u2 with u1 company |
| Neighbour | Gate 6y payments route |

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
31 / 31 PASS. d1 order `m-strver, m3, m2, m-nover, m1, m-numfrom, m-nofrom,
m-nullfrom`. Node profiled ops 85 (`find` 83, `getMore` 1, `killCursors` 1),
write ops 0. Python snapshot-write cases 0. Informational framework block:
4 / 4 DIFF as documented above. Disposable DB dropped; 0 leftover
`trukvia_gate7p_parity_*` databases.
