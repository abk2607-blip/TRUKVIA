# Gate 7k · Toll-import lookup · Live parity harness

Shadow target: `GET /api/toll-import/lookup`

## Scope

Class-C read-only shadow of `backend/routers/toll_import.py::toll_import_lookup`
(L59-85). Two sequential `expenses.find_one` reads at most: primary by
`source_txn_ref` (with optional lowercase `source: vendor` predicate),
fallback by `source_key` (no `source_type`/`source`). 400 when
`txn_ref` is falsy (after auth + activeCompanyId). 404 with Python
`repr()`-formatted `source_txn_ref` when both reads miss.

Zero writes / audits / backfill / recompute / hooks. Toll-import
writers (`preview` / `commit` / `reconcile`) remain
Python-authoritative and OUT OF SCOPE.

## Query contract

| Param | Type | Default | Constraint |
|---|---|---|---|
| `txn_ref` | str | "" | Falsy → 400 (after auth). NO 422. |
| `vendor` | str | "" | Truthy → add `source: vendor.lower()` to primary filter. NO 422. |

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE handler logic. Missing/blank `txn_ref` + no bearer → 401 (auth wins), not 400. |
| 401 literals | `Not authenticated` / `Invalid session` / `Session expired` |
| 400 literal | `{"detail": "txn_ref query param is required"}` |
| Tenant | Owned X-Company-Id override / unowned fallback / no-header default (locked `activeCompanyId`) |
| Primary filter | `{user_id, company_id, source_type: "fastag_import", source_txn_ref: <raw>, [source: vendor.lower()]}` |
| Fallback filter | `{user_id, company_id, source_key: <raw>}` (drops `source_type`/`source`) |
| Projection | `{_id: 0, user_id: 0}` — strips both from returned document |
| Response | Single document object (not array) |
| 404 detail | `f"No canonical Expense with source_txn_ref={txn_ref!r}. The row was never committed — check the source file and re-import."` |
| `repr()` semantics | Single-quote wrap by default; switches to double-quote wrap when the string contains `'` and no `"`; escapes `\\` → `\\\\`, matching quote → `\\'` or `\\"`, `\\n` / `\\r` / `\\t`, control chars `\\xNN` |

## UAT data preservation

- Isolated DB: `trukvia_gate7k_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Ports

- Python (uvicorn): `8228`
- Node   (dist):    `8229`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7k_parity/harness.py
```

Results file: `/tmp/gate7k_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (22 cases + zero-write aggregate)

| # | Description | Expected |
|---|---|---|
| 1  | no bearer + valid query → 401 Not authenticated | 401 body |
| 2  | invalid bearer → 401 Invalid session | 401 body |
| 3  | expired bearer → 401 Session expired | 401 body |
| 4  | missing txn_ref → 400 required message | 400 body |
| 5  | blank txn_ref= → 400 required message | 400 body |
| 6  | no bearer + missing txn_ref → 401 (auth wins) | 401 body |
| 7  | primary hit by source_txn_ref (no vendor) | 200 body |
| 8  | primary hit with vendor=idfc | 200 body |
| 9  | vendor lowercased: vendor=IDFC → source=idfc match | 200 body |
| 10 | vendor=livq wrong-vendor → 404 repr TXN-IDFC-100 | 404 body |
| 11 | primary miss + fallback hit via source_key | 200 body |
| 12 | both miss → 404 repr 'NOPE' | 404 body |
| 13 | 404 repr single-quote wrap → double-quote wrap | 404 body |
| 14 | 404 repr with double-quote → single-quote wrap | 404 body |
| 15 | 404 repr with backslash | 404 body |
| 16 | 404 repr with newline | 404 body |
| 17 | 404 repr with space | 404 body |
| 18 | 404 repr with tab | 404 body |
| 19 | wrong user u2 cannot see u1 rows → 404 | 404 body |
| 20 | u1 default co-a cannot see co-a-alt TXN-ALT-1 → 404 | 404 body |
| 21 | owned X-Company-Id co-a-alt → e-alt visible | 200 body |
| 22 | unowned X-Company-Id co-b → fallback co-a → e-idfc-1 visible | 200 body |
| 23 | Node write events across all cases | 0 |

Body compare mode: `full` deep-equal for every case.

## Observed results

Filled in at run time — see `/tmp/gate7k_parity_results.json`.
