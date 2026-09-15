# Phase 3 · Gate 6f · Live Python↔Node parity harness

Covers exactly four read-only surfaces:

* `GET /api/credit-notes`
* `GET /api/credit-notes/{nid}`
* `GET /api/debit-notes`
* `GET /api/debit-notes/{nid}`

## Data safety

* Uses an **isolated timestamped disposable DB**:
  `trukvia_gate6f_parity_<timestamp>`
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

All four Python handlers are pure reads:

* No `_recompute_invoice`, no `_backfill_to_default`,
  no `_apply_effective_balance`, no `_log_audit`,
  no `hook_after_source_write`.
* No FinTxn / payments / audit / counters / approvals / reconciliation.

Both stacks must produce byte-identical JSON on every case AND zero
DB mutation.

## Feature flag

The harness spawns TWO Python/Node process pairs:

1. **Flag ON** (`ENABLE_CDN=1`): exercises the normal contract for all
   four routes.
2. **Flag OFF** (unset / `ENABLE_CDN=0`): asserts all four routes
   return `404 {"detail": "Not Found"}` on both stacks.

Node reads `process.env.ENABLE_CDN` at request-time (not cached at
boot), matching Python's `os.environ.get(...)` semantics.

## Deliberate quirks preserved

* `GET /api/credit-notes/{nid}` has NO `kind` clause — a debit-kind
  note is returned when its id matches. Parity case verifies both
  stacks return identical debit-kind body.
* `GET /api/debit-notes/{nid}` has an explicit `kind: "debit"` clause —
  a credit-kind note returns 404 on both stacks.
* `"Not Found"` (flag disabled) vs `"Not found"` (note missing) are
  distinct literals; asserted verbatim.

## Cases (flag ON)

1. credit list happy path (sort DESC, kind=credit only)
2. credit list — `customer_id` filter
3. credit list — `invoice_id` filter
4. credit list — `status` filter
5. credit list — combined filters
6. credit list — custom limit
7. credit list — limit > 500 → 422 status parity
8. credit list — non-integer limit → 422 status parity
9. credit list — empty filter values ignored
10. debit list happy path
11. debit list — customer_id + status filter
12. credit detail happy path
13. credit detail cross-kind quirk (fetches debit-kind body)
14. credit detail missing → 404 "Not found"
15. credit detail cross-tenant → 404 "Not found"
16. debit detail happy path
17. debit detail credit-kind rejected → 404 "Not found"
18. no auth → 401
19. invalid bearer → 401
20. expired session → 401

## Cases (flag OFF)

21. credit list → 404 "Not Found"
22. credit detail → 404 "Not Found"
23. debit list → 404 "Not Found"
24. debit detail → 404 "Not Found"

## Zero-business-write assertion

Between each Python and Node request the harness snapshots the tracked
collections (user_sessions, users, companies, customers, trips,
invoices, credit_debit_notes, fin_txn, audit_logs, payment_corrections,
approvals, counters, driver_ledger_entries, expenses, vehicles,
suppliers, fin_hook_failures) and asserts that Node performs zero
change across every case in both phases.

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6f_parity/harness.py
```

Result JSON is written to `/tmp/gate6f_parity_results.json`.
