# Phase 3 · Gate 6c · Live Python ↔ Node parity harness

Purpose-built for the invoice-detail read surface:

* `GET /api/invoices/{iid}`
* `GET /api/invoices/{iid}/notes`
* `GET /api/invoices/next-preview`

**Class-B observation (Gate-6c)** — Python's `_recompute_invoice` performs
an on-read `db.invoices.update_one` `$set` on `subtotal`, tax fields,
totals, `amount_paid`, and `balance_due` whenever the linked trips
drift from stored values. Node intentionally does NOT reproduce this
write. To keep responses byte-identical the parity fixtures satisfy
invariants I1–I11 (see the Gate-6c pre-flight report), so Python's
`$set` writes back the same values already stored and the observation
becomes a no-op.

The harness ALSO exercises `/api/invoices/{iid}/notes` (feature-flag
bypass, unowned-→-[]) and `/api/invoices/next-preview` (pure-read
company counter preservation). Node write events across all cases
must remain **0**.

**UAT-data preservation** — this harness never touches the shared
`test_database` or any existing TRUKVIA tenant. It creates an
isolated, timestamp-suffixed DB (`trukvia_gate6c_parity_<ts>`), seeds
fresh fixtures, and drops it in `finally`. Any existing login / UAT
dataset remains untouched.

## Run

```
python3 backend-node/test/gate6c_parity/harness.py
```
