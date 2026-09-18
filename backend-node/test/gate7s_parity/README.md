# Gate 7s · Fin Day Book · Live parity harness

Shadow target: `GET /api/fin/day-book`

## Scope

Class-C read-only shadow of `backend/routers/fin_day_book.py::day_book`
(L54-121). The router's `reproject_source` / `backfill_tenant` /
`ensure_system_accounts` imports serve `POST /fin/reproject` and
`GET /fin/accounts` only — the day-book handler performs:

```
_active_company_id(request, user)
fin_txn.find(q, {_id:0, user_id:0}).sort([("txn_date",-1),("created_at",-1)])
       .to_list(int(max(1, min(limit, 20000))))
→ per-account totals in memory
```

No insert / update / upsert / delete / backfill / audit.

## Contract (verified on the live Python server)

| Axis | Python behaviour reproduced |
|---|---|
| Order | auth 401 → FastAPI query validation 422 (one list: `missing` date_from, `missing` date_to, `int_parsing` / `int_parsing_size` limit) → `_active_company_id` → handler 400 `date_from and date_to are required (YYYY-MM-DD)` for `""` |
| Filter | `{user_id, company_id, txn_date:{$gte,$lte}, status:"active"}` + truthy account_code, account_id, source_type, party_id, vehicle_id, trip_id (that order); repeated keys → last wins |
| Sort / limit | txn_date DESC, created_at DESC; Motor `to_list(n)` sends NO server limit — Node reads ≤ n from the unlimited sorted cursor (profiler-verified: 0 fin_txn finds carry a limit); n = int(max(1, min(limit, 20000))) with pydantic str→int coercion |
| Amount | `float(amount or 0)` — CPython 3.11 PyFloat_FromString (Unicode-14 tables, underscores, ASCII strip, inf/nan), bson Binary → bytes path, bson Code → str path, TypeError types → 500 |
| Rounding | per account `round(in,2)`, `round(out,2)`, `net = round(in - out, 2)` — exact round-half-even (BigInt), accumulation in cursor order |
| NaN / ±Inf | anywhere (any account's totals, rows, keys) → 500 `Internal Server Error`, `text/plain; charset=utf-8` |
| Totals keys | `setdefault(account_code or "")`: insertion order of sorted rows; hash merging (True == 1 == 1.0, first text); unhashable (list, dict, Code) → 500; jsonable_encoder re-keying: bytes / datetime → str collide with equal str keys (first position, LAST value); numeric keys stay numeric → duplicate JSON keys (`{"1":…,"1":…}`) |
| Body | `{date_from, date_to, rows, totals, count}`; bytes = jsonable_encoder + `json.dumps(ensure_ascii=False, allow_nan=False, separators=(",",":"))` rebuilt from typed documents (float repr `5.0`/`1e+16`/`-0.0`, int64, naive datetime isoformat, Binary UTF-8, Code string; ObjectId / Decimal128 / Timestamp / Regex / Min-MaxKey / DBRef / invalid Binary → 500) |
| Content-type | every JSON response is exactly `application/json` (Python JSONResponse); sent as a Buffer so Fastify adds no charset — route-local, no global change |

## Ports

- Python (uvicorn): `8256`
- Node   (dist):    `8257`

## Zero-write proof

MongoDB `dbHash` of every tracked collection around each Python and Node
request + profiler level 2 attributed by driver `appName`
(`trukvia-gate7s-node`). The aggregate also asserts no Node `fin_txn` find
carried a server-side `limit`.

## UAT data preservation

- Isolated DB: `trukvia_gate7s_parity_<unix_ts>`, dropped in `finally`; leftovers listed.
- Every money case runs in its own company (`X-Company-Id`).

## Run

```bash
cd backend-node
npm run build
python test/gate7s_parity/harness.py
```

Results: `<tempdir>/gate7s_parity_results.json`. Comparison is BYTE-EXACT on
the body and EXACT on the full content-type header, plus status.

## Case matrix (161 fixed + 400 fuzz + aggregate)

| Group | Cases |
|---|---|
| Auth / validation | 3 × 401; 401 over 422 (missing dates, bad limit); 422 both / from / to / both+limit / limit / `limit=` / int_parsing_size; repeated limit; 400 × 3; 422 over 400 |
| Isolation | default (void excluded, leak hidden); u2; owned alt; unowned; nonexistent; empty header; u2 with u1 company; unicode/quote date echo |
| Sort / limit | 20 005-row tie-heavy tenant: default 5000, 20000, 99999 → 20000, 777, account filter + 1234 |
| Money shape | single; empty; multi-account order; duplicate aggregation; zero/negative/decimal; per-account net rounding |
| Rounding | 0.125 0.375 0.625 0.875 2.675 1.005 1.115 0.285 1.255 8.345 10.125 1234567.125 0.005 0.015 0.025 0.035 0.045 −0.125 −2.675 0.1250000000000001 0.12499999999999999 2.675000000000001 2.6749999999999994 2.5 1e15+0.125 4503599627370495.5 5e-324 2.2250738585072014e-308 max-double 0.1+0.2; 0.1×10; 0.01×100 across 2 accounts; large+small both orders; overflow; inf−inf; inf in another account |
| Amount types | 20 accepted · 18 → 500 |
| Direction | IN / missing / None / out / in |
| Keys | int·True·"1"; True·1.0; doubles; numeric-string order; 7 falsy; bytes→str and str→bytes collisions; datetime vs isoformat str; int64 · 7 → 500 |
| Ties | created_at tiebreak; fully identical sort keys; non-string txn_date excluded |
| Rows | field types · 5 → 500 |
| Filters / window / limit | 11 filter combos; 5 date windows; 8 limit coercions |
| Fuzz | 200 amount strings (seed 7000018) + 200 multi-account sets (seed 7000019) |

Framework note (not exercised here, owned by the framework gate): trailing
slash `/api/fin/day-book/` → Python 307 redirect vs Fastify 404.

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
562 / 562 PASS byte-exact with exact content-type on the first run (money
531 / 531; fuzz 400 / 400; py status mix 200×356, 500×175; largest body
4 242 431 bytes identical). Node profiled ops 1706 (`find` 1655, `getMore` 48,
`killCursors` 3), write ops 0, fin_txn finds with limit 0. Python dbHash-change
cases 5 — `user_sessions` rolling refresh. Disposable DB dropped; 0 leftover
`trukvia_gate7s_parity_*` databases.
