# Phase 3 · Gate 6g · Live Python↔Node parity harness

Covers exactly one read-only surface:

* `GET /api/customers/{cid}/ship-sites`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6g_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

The Python handler is pure-read:

* No `_backfill_to_default`, no `_recompute_invoice`, no
  `_apply_effective_balance`, no `_log_audit`, no writer hooks.
* Only `db.customers.find_one(...)` inside `_get_customer_or_404` and
  `db.companies.find_one(...)` inside `_active_company_id`.

Both stacks must produce byte-identical JSON on every case AND zero
DB mutation.

## Deliberate contracts preserved

* **Raw ship_sites**: returned as-stored. NO GSTIN normalization, NO
  state derivation, NO resolver call (contrast with Gate 6e).
* **`is_active !== false`**: only literal boolean `False` is filtered
  when `active_only=true`. `null`, missing, `true`, non-boolean truthy
  values remain visible.
* **X-Company-Id**: consulted via `_active_company_id`. Owned override
  honoured; unowned falls back to user's default company.
* **FastAPI/Pydantic v2 boolean coercion**: `true|t|1|yes|on` → true;
  `false|f|0|no|off|n` → false (case-insensitive). Anything else → 422.

## Cases

1. happy path (all 7 site variants)
2. empty ship_sites
3. missing ship_sites field
4. active_only omitted → false
5. active_only=true removes is_active=false only
6. active_only=false → no filter
7-16. boolean-token variants (true/True/YES/1/on/T ...)
17-22. false-token variants (false/False/NO/0/off/f/n/N ...)
23-25. invalid boolean → 422 (maybe, 2, 1.0)
26. missing customer → 404 "Customer not found"
27. cross-user isolation → 404
28. no auth → 401
29. invalid bearer → 401
30. expired session → 401
31. owned X-Company-Id override
32. unowned X-Company-Id → default fallback
33. raw stored values preserved (dirty GSTIN untouched)

## Zero-business-write assertion

Between each Python and Node request, snapshot the tracked collections
(user_sessions, users, companies, customers, trips, invoices,
credit_debit_notes, fin_txn, audit_logs, payment_corrections,
approvals, counters, driver_ledger_entries, expenses, vehicles,
suppliers, fin_hook_failures) and assert that Node performs zero
change across every case.

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6g_parity/harness.py
```

Result JSON is written to `/tmp/gate6g_parity_results.json`.
