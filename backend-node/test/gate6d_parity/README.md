# Phase 3 · Gate 6d · Live Python ↔ Node parity harness

Purpose-built for the invoice-list read surfaces:

* `GET /api/invoices`
* `GET /api/invoices/overdue`

**Class-B observation (Gate-6d)** — Python's `list_invoices` invokes
`company._backfill_to_default(user_id)` on every read, which fan-outs
`update_many` across ten collections (`trips`, `invoices`, `files`,
`audit_logs`, `fuel`, `customers`, `vehicles`, `drivers`, `products`,
`parties`) to assign a default `company_id` to any legacy doc missing
one. This is a bounded non-financial legacy-migration write. Node
intentionally does NOT reproduce it. Parity fixtures pre-assign
`company_id` on every seeded row so Python's backfill matches zero
documents and the observation becomes a no-op. Identical protocol to
Gate-6b `list_trips`.

**Class-C observation (Gate-6d)** — `list_overdue_invoices` performs
zero writes. Its call chain (`_active_company_id`,
`_apply_effective_balance`, `customers.find` + in-memory merge, and
`age_days` arithmetic) is a pure read.

Node write events across all cases must remain **0**.

**UAT-data preservation** — this harness never touches the shared
`test_database` or any existing TRUKVIA tenant. It creates an isolated,
timestamp-suffixed DB (`trukvia_gate6d_parity_<ts>`), seeds fresh
fixtures, and drops it in `finally`. Any existing login / UAT dataset
remains untouched.

## Run

```
python3 backend-node/test/gate6d_parity/harness.py
```
