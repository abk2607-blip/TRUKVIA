# Phase 6 — Slice 2c, unit 12: `invoice` + `invoice_payment`

Status: **GREEN**. Parity `checks 47 PASS 47 FAIL 0`, `fin_txn rows: python 134, typescript 134`.

The final source type. With this unit **all thirteen** entries of
`SUPPORTED_SOURCE_TYPES` have a TypeScript projection and nothing is left with
Python. Production is untouched: reverse delegation stays off by default.

## Why the two are ONE unit

`invoice` and `invoice_payment` are not two projections. A single Python
function emits both: the payments are embedded in the invoice document, and a
payment leg is written under `source_type: 'invoice_payment'` with the
compound `source_id` `{invoice_id}:{payment_id}`. There is no separate
`invoice_payment` collection and no separate reprojection entry point — a
payment can only be reprojected by reprojecting its invoice.

That is also why `reprojectVendorSourceOrThrow` cascades: an `invoice`
reprojection first deletes `invoice_payment:{id}:*` before the exact-match
delete, so a payment that has since been removed from the document cannot
survive as an orphan row.

## The three leg pairs, in order

```
1. invoice:{id}:ar_debit             AR                 in    invoice_raise
   invoice:{id}:sales_credit         SALES              out   invoice_raise

2. invoice:{id}:advance_offset_debit CUSTOMER_ADVANCE   in    invoice_advance_offset
   invoice:{id}:sales_offset_credit  SALES              out   invoice_advance_offset
   (only when advance + diesel deductions are positive)

3. invoice_payment:{id}:{pid}:bank_in    CASH|BANK_*    in    invoice_receipt
   invoice_payment:{id}:{pid}:ar_credit  AR             out   invoice_receipt
   (one pair per payment)
```

## The four details that are easy to get wrong

**A payment with no id is dropped outright.** There is no index fallback here.
This differs from `trip_customer_receipt` (unit 9), which falls back to
`idx{n}`. Porting the receipt behaviour into the invoice would have invented
rows Python never writes.

**A non-positive total kills the whole document — payments included.** An
invoice whose `total_amount` is zero, negative, null or rounds to zero
projects *nothing*, even when it carries real, positive payments. This is the
most surprising branch in the unit and it is pinned by both parity and a unit
test.

**The offset is double-rounded.** `q2(q2(advance) + q2(diesel))`, not
`q2(advance + diesel)`. With both deductions at `0.005` the two differ:
`0.02` versus `0.01`.

**Neither narration is stripped.** `Invoice ` keeps its trailing space when
the number is blank, and a null number interpolates as the literal `None` —
Python f-string semantics, reproduced by `pyInterp`.

## Lifecycle

A projection that owns child rows has to be correct over *time*, not just on
one pass, so parity drives seven ordered lifecycle steps against both
databases and compares after each:

```
PASS  a payment added AFTER the invoice was already projected
PASS  that payment removed again — no orphan rows may survive
PASS  one of three payments deleted
PASS  a payment amount changed in place
PASS  the whole set reprojected twice more, unchanged
PASS  the offset appearing on an invoice that had none
PASS  the invoice going historical, which must clear every child row
```

The last one is the cascade's real test: a historical invoice projects nothing
at all, so every previously written payment row has to disappear.

## Verification

```
npx tsx scripts/fin-invoice-parity.ts              # 47/47, 134 legs
npx vitest run test/fin-invoice-projection.test.ts # 27 tests
```

The unit test also closes the loop on the whole slice: it asserts that
`PORTED_SOURCE_TYPES` and `SUPPORTED_SOURCE_TYPES` are now the same thirteen
entries.

## Not done here

- No ledger mathematics changed.
- No historical data normalised.
- The Python implementation remains in place as the rollback path; the
  forward bridge is retained.
