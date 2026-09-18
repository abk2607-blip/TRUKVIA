# Gate 7m · Fin day-closures list · Live parity harness

Shadow target: `GET /api/fin/day-closures`

## Scope

Class-C read-only shadow of `backend/routers/fin_day_closing.py::list_closures`
(L224-246).

Single read: `fin_day_closures.find(q, {_id:0, user_id:0}).sort("close_date", -1)
.to_list(int(max(1, min(limit, 5000))))`. Wrapper response `{rows, count}`.

Zero writes / audits / snapshot capture / FinTxn reads / backfill. Day-closing
writers (`POST /api/fin/day-closures`, `POST /api/fin/day-closures/{d}/reopen`)
and the sibling reads (`/{close_date}`, `/{close_date}/late-entries`,
`/fin/day-status`) remain Python-authoritative and OUT OF SCOPE.

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE query validation — unauthenticated + malformed `limit` → 401 |
| 401 literals | `Not authenticated` / `Invalid session` / `Session expired` |
| Tenant | Owned X-Company-Id override / unowned fallback / no-header default (locked `activeCompanyId`) |
| Filter | `{user_id, company_id}` + `close_date: {$gte?, $lte?}` only when `date_from`/`date_to` truthy + `status` only when truthy |
| Projection | `{_id: 0, user_id: 0}` — **user_id STRIPPED** (contrast Gate 7l) |
| Sort / cap | `close_date` DESC; cap `int(max(1, min(limit, 5000)))` |
| `limit` coercion | pydantic-core 2.46.4 `str_as_int` + jiter 0.14.0 `NumberInt::try_from`: accepts `1.0`, `1_000`, `+5`, `05`, Rust-whitespace trim (incl. U+0085/U+00A0, excl. U+FEFF) |
| `limit` 422 | `int_parsing` and `int_parsing_size` (strict JSON-int prefix whose digit run incl. sign exceeds 4300 bytes). No `ge`/`le` constraint → no range 422s |
| Repeated keys | Last occurrence wins (Starlette `MultiDict.get`) |
| Response | Wrapper `{rows, count}` |

## Ports

- Python (uvicorn): `8240`
- Node   (dist):    `8241`

## Zero-write proof

1. Per-case collection snapshots before/after each Node request.
2. MongoDB profiler level 2 on the disposable DB (256 MB capped
   `system.profile`), attributed by driver `appName`
   (`trukvia-gate7m-node`). Every Node-originated op across the live matrix
   is enumerated; any write command fails the gate. Node reads on
   `fin_day_closures` must be > 0 to prove attribution works.

## UAT data preservation

- Isolated DB: `trukvia_gate7m_parity_<unix_ts>`, dropped in `finally`.
- Leftover `trukvia_gate7m_parity_*` databases are listed after the drop.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Run

```bash
cd backend-node
npm run build
python test/gate7m_parity/harness.py
```

Results: `<tempdir>/gate7m_parity_results.json`. Exit 0 only when every case
passes and Node performed zero writes.

## Case matrix

58 fixed cases + 323 deterministic fuzz cases (`limit` grammar, seed
7000013) + 1 zero-write aggregate.

| Group | Cases |
|---|---|
| Auth + precedence | none / invalid / expired; none + `limit=abc`; expired + `limit=abc` |
| Primary | u1 default (incl. missing-`close_date` legacy row, non-padded date); u3 empty tenant; u4 5002-row tenant default cap 500 |
| Date / status | from; to; both; inverted; blanks; non-ISO lexical bound; unicode/quote bound; status closed / reopened / CLOSED; combined; unknown key |
| Repeated keys | status; limit `abc,2` → 200; limit `2,abc` → 422 |
| Clamp (u4, real rows) | 1; 0→1; -5→1; 5000; 5001→5000; ±20-digit; `1_000.0`→1000 |
| Coercion (u1) | `2`; `' 2 '`; raw `+2`; `%2B2`; `1.0`; `05`; NBSP; U+0085; `abc`; `''`; bare `?limit`; `1.5`; `1e3`; U+FEFF; Arabic-Indic; 4301 digits (size); `-`+4300 (size); `+`+4301 (int_parsing); 4300 digits; 4300 zeros + `5` |
| Isolation | u2 cross-user; owned alt; unowned; nonexistent; empty header; u2 with u1's company id; upper-case header name |

Body compare: full deep-equal of parsed JSON for every case.

## Observed results

Filled in at run time — see `<tempdir>/gate7m_parity_results.json`.

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
382 / 382 PASS (58 fixed + 323 fuzz + 1 zero-write). Node profiled ops 691
(`find` 674, `getMore` 17), write ops 0. Python snapshot-write cases 17 — all
`user_sessions` rolling refresh inside `get_current_user` (intentionally not
shadowed by the locked Node `auth.ts`). Disposable DB dropped; 0 leftover
`trukvia_gate7m_parity_*` databases.
