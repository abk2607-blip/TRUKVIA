# Phase 3 · Gate 6o · Live Python↔Node parity harness

Covers exactly one read-only surface:

* `GET /api/vendor-payments/{pid}/corrections`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6o_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

Python delegates to `services_payment_corrections.py::list_corrections`
(lines 328–333), which executes ONLY:

```python
db.payment_corrections.find(
    {"user_id": uid, "company_id": cid,
     "payment_type": "vendor", "payment_id": pid},
    {"_id": 0, "user_id": 0},
).sort("correction_index", 1).to_list(1000)
```

Zero writer hook, zero audit call, zero backfill, zero recompute, zero
effective-balance projection, zero FinTxn emission, zero
approvals/policy interaction. Both stacks must produce byte-identical
JSON on every case and Node must record zero DB mutation.

## Preserved semantics

* Filter EXACTLY `{ user_id, company_id, payment_type: "vendor", payment_id }`.
* Projection `{ _id: 0, user_id: 0 }`.
* Sort `correction_index` **ASC**.
* Cap `1000` (Python `.to_list(1000)`; Node MUST call `.limit(1000)`).
* No query params. No body. No path-param validation.
* Unknown `pid` → `200 []` (no payment-existence lookup on GET).
* Cross-payment-type isolation intrinsic via `payment_type: "vendor"`.

## Divergence from locked Gate-2

The locked `backend-node/src/routes/supplier-payments-corrections.ts`
uses an unbounded `.toArray()`. Gate-6o MUST use `.limit(1000)` to
match Python's `.to_list(1000)`. Gate-2 file remains locked and
untouched — its pre-existing property is a documented Gate-2
divergence that a future auth/limits gate will revisit.

## Cases (9 request cases + 1 aggregate)

1. happy list (vendor `pay-1` — three rows returned ASC by `correction_index`)
2. unknown pid → `200 []`
3. second pid (`pay-2`) returns its own vendor correction only
4. cross-user isolation (u2 view — u2's own single row)
5. owned `X-Company-Id` override → alt-company row only
6. unowned `X-Company-Id` → default fallback (co-a)
7. no auth → `401 { "detail": "Not authenticated" }`
8. invalid bearer → `401 { "detail": "Invalid session" }`
9. expired session → `401 { "detail": "Session expired" }`

AGGREGATE:
10. zero Node business writes across ALL cases (tracked collections
    include `payment_corrections`, `driver_payment_corrections`,
    `mechanic_payments`, `supplier_payments`, `vendor_payments`,
    `driver_payments`, `fin_txn`, `audit_logs`, and 18 other business
    collections). Python's rolling-refresh writes to `user_sessions`
    are expected and are excluded from the Node-write diff by using
    the post-Python snapshot as the Node-baseline.

## No role masking / no `team_members` divergence

`payment_corrections` documents contain no role-gated fields. Node's
`AuthUser` shape is sufficient; the Gate-6m documented
`team_members` reassignment deferral does NOT apply. Full 100%
byte-parity is expected across every case.

## Compare mode

* `full` — structural JSON equality between Python and Node bodies
  (Python `dict == dict` treats key-order as insignificant).

## Ports

Python: `8183`  ·  Node: `8184`  (non-overlapping with prior gates).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6o_parity/harness.py
```

Result JSON is written to `/tmp/gate6o_parity_results.json`.

## Writer boundary (Gate-7)

`POST /api/vendor-payments/{pid}/correct-amount` (Python
`apply_amount_reversal_new` → `hook_after_source_write` + ledger
reversal + audit) is OUT OF SCOPE for Gate 6o and remains
Python-authoritative until Gate 7 (Maker-Checker framework).
