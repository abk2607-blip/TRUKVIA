# Gate 7n · Fin day-closure detail · Live parity harness

Shadow target: `GET /api/fin/day-closures/{close_date}`

## Scope

Class-C read-only shadow of `backend/routers/fin_day_closing.py::get_closure`
(L249-264).

Order: auth → `_parse_iso_date(close_date)` → `_active_company_id` →
`fin_day_closures.find_one({user_id, company_id, close_date}, {_id:0, user_id:0})`.
Bare document response.

Zero writes / audits / snapshot capture / FinTxn reads / backfill. Writers
(`POST /api/fin/day-closures`, `POST /api/fin/day-closures/{d}/reopen`) and
`GET /api/fin/day-closures/{d}/late-entries` remain Python-authoritative and
OUT OF SCOPE.

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE date validation — unauthenticated + malformed date → 401 |
| 401 literals | `Not authenticated` / `Invalid session` / `Session expired` |
| Date validation | CPython 3.11 C `date.fromisoformat`: UTF-8 byte length 7/8/10; ASCII digits; `YYYY[-]MM[-]DD` or `YYYY[-]Www[[-]D]` with consistent separator; trailing bytes of 10-byte compact forms ignored; result within 0001-01-01…9999-12-31 |
| 400 literal | `{"detail": "close_date must be ISO YYYY-MM-DD"}` |
| 404 literal | `{"detail": "No closure exists for <raw segment>"}` — raw, not normalised |
| Filter | `{user_id, company_id, close_date: <raw segment>}` |
| Projection | `{_id: 0, user_id: 0}` — user_id STRIPPED |
| Encoded slash | Segment decoding to contain `/` → 404 `{"detail":"Not Found"}` before auth (Starlette routes on the decoded path) |
| Tenant | Owned X-Company-Id / unowned fallback / default (locked `activeCompanyId`) |

## Framework-level gaps (NOT counted — owned by the dedicated framework gate)

Pre-existing on every Node param route (verified identical on locked Gate 7l
`/api/approvals/{aid}`); fixing them requires the protected `app.ts`:

| Request | Python | Node |
|---|---|---|
| Invalid UTF-8 escape (`%FF`) | handler (400 date literal / 401) | Fastify 400 `FST_ERR_BAD_URL` |
| Trailing slash | 307 redirect (redirect_slashes) | Fastify default 404 |
| Segment > 100 chars | handler 400 | Fastify default 404 (`maxParamLength` 100) |
| Encoded slash decoding onto another Python route (`<d>%2Flate-entries`) | late-entries handler | 404 `Not Found` |

The harness prints these as an informational block on every run.

## Ports

- Python (uvicorn): `8242`
- Node   (dist):    `8243`

## Zero-write proof

Per-case collection snapshots + MongoDB profiler level 2 on the disposable DB
attributed by driver `appName` (`trukvia-gate7n-node`); any Node write command
fails the gate; Node reads on `fin_day_closures` must be > 0.

## UAT data preservation

- Isolated DB: `trukvia_gate7n_parity_<unix_ts>`, dropped in `finally`; leftovers listed.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Run

```bash
cd backend-node
npm run build
python test/gate7n_parity/harness.py
```

Requests use `http.client` raw paths so percent-encoding reaches both servers
byte-for-byte. Results: `<tempdir>/gate7n_parity_results.json`.

## Case matrix

49 fixed cases + 400 deterministic fuzz segments (seed 7000014: random
digit/dash/W strings + structured date and ISO-week shapes around every
boundary) + 1 zero-write aggregate.

| Group | Cases |
|---|---|
| Auth + precedence | none / invalid / expired; none + invalid date; expired + invalid date |
| Hits | ISO date; reopened with history + unicode; empty snapshot + unicode notes; compact raw; ISO-week raw; `%2D`-encoded dashes; query string ignored |
| 404 literal | missing ISO; compact ≠ stored; week; compact week; 10-byte trailing-ignored; week 53; leap day; min; max; max week |
| 400 | text; unpadded; non-leap Feb 29; month 13; year 0; week overflow into 10000; week 54; inconsistent separator; leading space; fullwidth; Arabic-Indic; `%00`; `€`; datetime; `%20` |
| Encoded slash | with auth; without auth; multi-slash |
| Isolation | u2 same date; u2 vs u1 row; default hides alt; owned alt; unowned; nonexistent; empty header; u2 with u1's company id; upper-case header name |

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
450 / 450 PASS (49 fixed + 400 fuzz + 1 zero-write; fuzz py status mix 400×310,
404×90). Node profiled ops 679 (`find` 679), write ops 0. Python
snapshot-write cases 1 — `user_sessions` rolling refresh inside
`get_current_user`. Informational framework block: 4 / 4 DIFF as documented
above. Disposable DB dropped; 0 leftover `trukvia_gate7n_parity_*` databases.
