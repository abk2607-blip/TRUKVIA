# Phase 3 · Gate 6e · Live Python↔Node parity harness

Covers exactly **one** read-only surface:

* `GET /api/invoices/{iid}/ship-to`

## Data safety

* Uses an **isolated timestamped disposable DB**:
  `trukvia_gate6e_parity_<timestamp>`
* The DB is dropped in the `finally` block **regardless of pass/fail**.
* Never touches `test_database`, `trukvia_uat`, or any real UAT tenant.
* Never mutates the login/account/company mapping.

## Class-C stance

The Python route `get_invoice_ship_to` is itself pure-read:

* No `_recompute_invoice`, no `_backfill_to_default`, no
  `_apply_effective_balance`.
* No FinTxn / payments / audit / counters / approvals / reconciliation.

The resolver `ship_to_resolver.resolve_invoice_ship_to` is pure/in-memory
(regex + dict/list manipulation). No Mongo / file / network side effects.

Therefore parity holds when the seeded fixtures match — Python performs
**zero writes** on this route, so byte-for-byte response equality with
Node is achievable without any Class-B backing.

## Cases covered

Resolver-driven cases:

1. explicit `ship_site_id` (linked)
2. R1 name-equality unique inference
3. R2 pincode unique inference
4. R3 whole-token-in-address unique inference
5. ambiguous (>1 matches) → fallback
6. zero-match → fallback
7. empty `ship_sites`
8. missing customer → `{}` semantics
9. GSTIN normalization on render
10. historical trip pass-through
11. `invoice.trip_ids` order preservation
12. missing trip id silently dropped
13. mixed identities → `mixed=true`, `common=null`
14. common identity → `common != null`
15. empty `trip_ids` → skip trips query, return `per_trip=[]`
16. tuple → JSON array identity serialization

Auth / scope:

17. no auth → 401 `Not authenticated`
18. invalid bearer → 401 `Invalid session`
19. expired session → 401 `Session expired`
20. wrong tenant → 404 `Invoice not found`
21. X-Company-Id is **not consulted** — passing an unowned/wrong header
    returns the same result as no header.

## Zero-business-write assertion

Between each Python and Node request the harness snapshots the tracked
collections (invoices, trips, customers, credit_debit_notes, fin_txn,
audit_logs, payment_corrections, approvals, counters,
driver_ledger_entries, expenses, vehicles, suppliers, fin_hook_failures,
user_sessions, users, companies) and asserts that **Node performs no
change** across every case.

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6e_parity/harness.py
```

Result JSON is written to `/tmp/gate6e_parity_results.json`.
