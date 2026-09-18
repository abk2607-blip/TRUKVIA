# Gate 7r · Fin day-closure late-entries · Live parity harness

Shadow target: `GET /api/fin/day-closures/{close_date}/late-entries`

(The gate request named `GET /api/fin/late-entries`; no such route exists in
the repository. This is the only late-entries route —
`backend/routers/fin_day_closing.py:274`, consumed by
`frontend/src/pages/FinDayClosing.jsx:38`.)

## Scope

Class-C read-only shadow of `fin_day_closing.py::late_entries` (L274-323) +
`_bucket` (L267-271). Order: auth → `_parse_iso_date` → `_active_company_id`
→ closure probe → late legs → in-memory aggregation:

```
fin_day_closures.find_one({user_id, company_id, close_date}, {_id:0, closed_at:1})   → 404
fin_txn.find({user_id, company_id, status:"active", txn_date:{$lte: close_date},
              created_at:{$gt: closed_at or ""}}, {_id:0, user_id:0})
       .sort("txn_date", -1).to_list(5000)
```

Class-C safety: two reads only; `r["days_late"] = …` mutates the in-memory
row. No insert / update / upsert / delete / backfill / audit.

## Money and serialisation contract (verified on the live Python server)

| Axis | Python behaviour reproduced |
|---|---|
| Amount | `float(r.get("amount") or 0)`: falsy → 0.0; bool → 1.0; int32/int64/double; str and bson `Code` (str subclass) via PyFloat_FromString (Unicode-14 digit/space transform, underscore rules, ASCII strip, inf/infinity/nan); bson `Binary` (bytes subclass) via the bytes path; Decimal128 / datetime / ObjectId / non-empty list or dict → 500 |
| Rounding | `round(x, 2)` = exact round-half-even on the binary value (BigInt reproduction of CPython `double_round`); `net = round(round(in) − round(out))`; accumulation in cursor order |
| NaN / ±Infinity | anywhere in the response (totals, rows, keys) → `json.dumps(allow_nan=False)` → **500 `Internal Server Error` (text/plain)** |
| `by_source_type` | dict insertion order; hash merging (`True == 1 == 1.0`, first key text kept); unhashable (list, dict, Code) → 500; jsonable_encoder re-keys by encoded key (bytes / datetime → str collide with equal str keys; numeric keys stay numeric → `{"1":2,"1":1}` duplicates) |
| `by_days_late_bucket` | fixed order `0-7, 8-30, 31-90, 90+` |
| days_late | `max(0, (date(close_date) − date(txn_date[:10])).days)`; `[:10]` by code point; non-str / invalid → 0; ISO-week / compact close dates resolved to the real date |
| Closure | projection `{closed_at:1}`: closure without `closed_at` → `{}` → 404; `closed_at` falsy → `""` |
| Cap | Motor `to_list(5000)` sends NO server limit → Node reads ≤5000 from the fully sorted cursor (a `.limit()` reorders txn_date ties — caught live) |
| Body bytes | FastAPI jsonable_encoder + `json.dumps(ensure_ascii=False, separators=(",",":"))` rebuilt from typed documents (`promoteValues:false`): float repr (`5.0`, `1e+16`, `-0.0`), exact int64, naive-UTC datetime isoformat, Binary → UTF-8, Code → code string; ObjectId / Decimal128 / Timestamp / Regex / Min-MaxKey / DBRef / invalid-UTF-8 Binary → 500 |
| Errors | 401 literals; 400 `close_date must be ISO YYYY-MM-DD`; 404 `No closure exists for <raw>`; empty segment / decoded `/` → 404 `Not Found` before auth |

Header note (not body): Python sends `content-type: application/json`,
Fastify `application/json; charset=utf-8` — identical on every Node route; the
harness compares the base media type.

## Framework-level gaps (NOT counted — owned by the dedicated framework gate)

| Request | Python | Node |
|---|---|---|
| Invalid UTF-8 escape (`%FF`) | handler 400 date literal | Fastify 400 `FST_ERR_BAD_URL` |
| Trailing slash | 307 redirect | Fastify default 404 |
| `close_date` > 100 chars | handler 400 | Fastify default 404 (`maxParamLength` 100) |

## Ports

- Python (uvicorn): `8254`
- Node   (dist):    `8255`

## Zero-write proof

MongoDB `dbHash` of every tracked collection around each Python and Node
request + profiler level 2 attributed by driver `appName`
(`trukvia-gate7r-node`). Any Node write command fails the gate.

## UAT data preservation

- Isolated DB: `trukvia_gate7r_parity_<unix_ts>`, dropped in `finally`; leftovers listed.
- Every money case runs in its own company (`X-Company-Id`) so fixtures never leak.

## Run

```bash
cd backend-node
npm run build
python test/gate7r_parity/harness.py
```

Results: `<tempdir>/gate7r_parity_results.json`. Comparison is BYTE-EXACT on
the body, plus status and base content-type.

## Case matrix (141 fixed + 400 fuzz + zero-write aggregate)

| Group | Cases |
|---|---|
| Auth / errors | 3 × 401; auth before 400; 400 × 3; 404 no closure; 404 compact echo; 404 u2 closure with u1 company; encoded slash ± auth; empty segment; query ignored |
| Isolation | u1 default; u2 own (reopened closure still served); owned alt; unowned; nonexistent; empty header; u2 with u1 company |
| Money shape | single; in+out; multi source types; empty; not-late; inactive; after close_date; zero; negative; decimal |
| Rounding | 0.125 0.375 0.625 0.875 2.675 1.005 1.115 0.285 1.255 8.345 10.125 1234567.125 0.005 0.015 0.025 0.035 0.045 −0.125 −2.675 0.1250000000000001 0.12499999999999999 2.5 1e15+0.125 4503599627370495.5 5e-324 max-double 0.1+0.2; net rounding; 0.1×10; large+small order; overflow → 500; inf−inf → 500 |
| Amount types | 21 accepted (str variants, int32, int64, bool, null, missing, empty list/dict, Binary, Code) · 21 → 500 (abc, `1,5`, 0x10, `1__0`, `\x1c1`, BOM, inf, −Infinity, nan, 1e400, NaN, ±inf doubles, Decimal128, datetime, ObjectId, list, dict, invalid Binary, `b'1 5'`, Timestamp) |
| Direction | IN / missing / out / None / in |
| Source keys | int·True·"1"; True·1.0; doubles; int64; numeric-string order; 7 falsy kinds; bytes·str collision; datetime · 7 → 500 (list, dict, Code, ObjectId, Decimal128, NaN, inf) |
| days_late | 8 bucket boundaries; `[:10]`; unparsable; array; astral char; ISO-week close; compact close; existing days_late position |
| closed_at | `""`; null; numeric; missing → 404 |
| Row serialisation | datetime ± ms, Binary, UUID Binary, Code w/ scope, int64, 8 double reprs, nested escapes, bools · 5 → 500 |
| Cap | 5002 legs with txn_date ties → 5000, identical tie order |
| Fuzz | 220 amount strings (seed 7000016) + 180 multi-leg rounding sets (seed 7000017) |

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
542 / 542 PASS byte-exact (money cases 520 / 520; fuzz 400 / 400, py status
mix 200×252, 500×148). Node profiled ops 2133 (`find` 2128, `getMore` 5),
write ops 0. Python dbHash-change cases 2 — `user_sessions` rolling refresh.
Informational framework block: 3 / 3 DIFF as documented. Disposable DB
dropped; 0 leftover `trukvia_gate7r_parity_*` databases.

First run: 540 / 542 — (1) `.limit(5000)` reordered txn_date ties under the
cap, (2) bytes/str key collision in jsonable_encoder. Node repaired; full
matrix re-run to 542 / 542.
