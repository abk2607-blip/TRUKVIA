# Phase 3 · Gate 6p · Live Python↔Node parity harness

Covers exactly one read-only surface:

* `GET /api/driver-payments/{pid}/corrections`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6p_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

Python handler (`backend/routers/driver_payments.py::list_driver_payment_corrections`,
lines 284–292) executes ONLY:

```python
db.driver_payment_corrections.find(
    {"user_id": uid, "company_id": cid, "payment_id": pid},
    {"_id": 0},
).sort("correction_index", 1)
return [d async for d in cur]
```

Zero writer hook, zero audit call, zero backfill, zero recompute, zero
effective-balance projection, zero FinTxn emission, zero
approvals/policy interaction. Both stacks must produce byte-identical
JSON on every case and Node must record zero DB mutation.

## Preserved semantics (bind precisely — differs from Gate 6n/6o)

| Dimension | Gate 6p (this gate) | Gate 6n / 6o (already locked) |
|-----------|--------------------|-------------------------------|
| Collection | `driver_payment_corrections` (dedicated) | `payment_corrections` (shared) |
| Filter keys | 3 · `{user_id, company_id, payment_id}` | 4 · adds `payment_type` |
| Projection | `{_id: 0}` — `user_id` **PRESENT** in response | `{_id: 0, user_id: 0}` — user_id absent |
| Cap | **NONE** (no `.limit(N)`) | `.limit(1000)` |
| Cross-payment-type isolation | intrinsic via dedicated collection | intrinsic via `payment_type` filter |

Additionally:
* No query params. No body. No path-param validation.
* Unknown `pid` → `200 []` (no payment-existence lookup on GET).
* No role masking. No `team_members` divergence concern.

## Cases (9 request cases + 1 aggregate)

1. happy list (driver `pay-1` — three rows returned ASC by `correction_index`)
2. unknown pid → `200 []`
3. second pid (`pay-2`) returns its own driver correction only
4. cross-user isolation (u2 view — u2's own single row)
5. owned `X-Company-Id` override → alt-company row only
6. unowned `X-Company-Id` → default fallback (co-a)
7. no auth → `401 { "detail": "Not authenticated" }`
8. invalid bearer → `401 { "detail": "Invalid session" }`
9. expired session → `401 { "detail": "Session expired" }`

AGGREGATE:
10. zero Node business writes across ALL cases (tracked collections
    include `driver_payment_corrections`, `payment_corrections`,
    `mechanic_payments`, `supplier_payments`, `vendor_payments`,
    `driver_payments`, `fin_txn`, `audit_logs`, and 18 other business
    collections). Python's rolling-refresh writes to `user_sessions`
    are expected and are excluded from the Node-write diff by using
    the post-Python snapshot as the Node-baseline.

## Collection isolation fixture

Fixtures seed BOTH the dedicated `driver_payment_corrections` collection
AND the shared `payment_corrections` collection with the same
`(user_id, company_id, payment_id)`, but the shared-collection rows
have `payment_type` (`vendor`/`mechanic`/`supplier`). Neither Python nor
Node should surface those shared-collection rows in the driver
response — proving that the read is scoped to the dedicated collection
only.

## Compare mode

* `full` — structural JSON equality between Python and Node bodies
  (Python `dict == dict` treats key-order as insignificant).

## Ports

Python: `8185`  ·  Node: `8186`  (non-overlapping with prior gates 6i–6o).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6p_parity/harness.py
```

Result JSON is written to `/tmp/gate6p_parity_results.json`.

## Writer boundary (Gate-7)

`POST /api/driver-payments/{pid}/correct-amount` (Python
`apply_amount_reversal_new` → `hook_after_source_write` + ledger
reversal + audit + `driver_payment_corrections.insert_one`) is OUT OF
SCOPE for Gate 6p and remains Python-authoritative until Gate 7
(Maker-Checker framework).
