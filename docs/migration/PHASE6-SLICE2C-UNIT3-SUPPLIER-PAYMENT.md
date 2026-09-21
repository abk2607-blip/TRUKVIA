# Phase 6 · Slice 2c, unit 3 — the `supplier_payment` projection

One source type. Follows [unit 2](PHASE6-SLICE2C-UNIT2-MECHANIC-PAYMENT.md)
(`9fa97ee`).

## Inspection

**`project_supplier_payment` is NOT a `_party_payment_legs` call.** Python keeps
it as a standalone function, and it is not merely a rename — it differs in
exactly two ways:

1. an extra guard, `if sp.get("is_historical"): return []`;
2. `trip_id=sp.get("trip_id") or ""` in the common leg fields.

Everything else is structurally identical to the vendor and mechanic cases:

| | |
| --- | --- |
| payable account | `AP_SUPPLIER`, a fixed literal |
| money side | `_mode_account(mode or "Bank")` |
| direction default | `type or "payment_out"` |
| leg order | `payment_out` → `ap_debit`, `bank_credit`; otherwise `bank_debit`, `ap_credit` |
| txn types | `supplier_payment_out` / `supplier_receipt_in` |
| narration | `f"Supplier {typ} · {ref_no}".strip(" ·")` |

Python's literal `"Supplier"` equals the shared helper's `party_type.title()`
for `"supplier"`, so the narration matches without special-casing.

Other findings:

- **Source reads: one.** The dispatcher branch is a single
  `supplier_payments.find_one({user_id, company_id, id})`. No cascade in
  `_delete_by_source`, no paired-document lookup.
- **Accounts already covered.** `AP_SUPPLIER` is in `FIN_SYSTEM_ACCOUNTS`
  (`backend/models.py:1531`) and in the TypeScript seeder, so nothing about
  account resolution changes — which matters, because
  `GET /api/fin/accounts` is out of bounds.
- **No settlement-recovery flag.** `is_supplier_settlement_recovery` is set
  only by `project_expense`; this projection never sets it and every leg
  carries the `_leg` default of `False`.
- **All three guard fields are real** on the `SupplierPayment` model:
  `is_deleted`, `is_reversed` and `is_historical`.
- **The same choke-point delegation works.** Nothing about this source type is
  special at the hook layer, so `hook_after_source_write` needs no change.

Not materially more complex than expected — the two differences are small,
explicit and testable.

## Implementation

The shared `partyPaymentLegs` gained two **optional** parameters that default
to the existing behaviour, so vendor and mechanic are provably unchanged:

```ts
skipIfHistorical?: boolean   // supplier only
tripIdKey?: string           // supplier only
```

`projectSupplierPayment` is a five-line call. The ledger maths stays in one
place; duplicating the leg construction would have put a second copy of this
shape in the tree, and drift there is a wrong ledger rather than a failing
type.

Wired the same way as `mechanic_payment`: the dispatcher gained a
`supplier_payments` branch, `PORTED_SOURCE_TYPES` and the reverse-bridge
allowlist gained the type, and Python delegation stays behind the existing
env gate — **off by default**, with no change to the gate itself.

## Parity

`scripts/fin-supplier-parity.ts`, against three throwaway databases (Python
native as the reference, the NestJS port in-process, and Python **delegating
to a live NestJS**):

```
fin_txn rows: python 64, typescript 64
checks 17   PASS 17   FAIL 0
```

Every document is reprojected **twice** per side, so delete-then-insert
idempotency is part of the comparison. Rows are compared in full — generated
ids, `ref_source_key`, `account_id`, `account_code`, `counter_account_*`,
amounts, direction, narration, party fields, `trip_id`, `txn_type`, `status`,
`is_supplier_settlement_recovery` — with only the two wall-clock stamps masked.

40 fixtures cover both directions, every mode including an unknown one, blank
and missing `mode` and `type`, the guards, zero/negative/null/missing amounts,
an amount that rounds to zero, a numeric-string amount, `2.675`, `0.125`,
`0.375` and `1.005`, a 500-character ref against the 400-character narration
cap, unicode, missing `supplier_id`/`date`, present/blank/absent `trip_id`, and
the same id under a second tenant.

Explicit assertions beyond the row comparison: historical documents project
nothing while a *falsy or absent* `is_historical` still projects; supplier legs
carry `trip_id` while a blank one becomes `""`; `payment_out` uses
`AP_SUPPLIER` with the documented `ref_source_key` and leg order; generated ids
follow `fintxn_` + `ref_source_key` with `:`→`_` truncated at 60; every leg
carries `party_type: "supplier"`.

### Delegation and fallback

| | |
| --- | --- |
| Python → live NestJS | matches Python native exactly |
| a type **not** in `TRUKVIA_FIN_NODE_SOURCE_TYPES` | does not delegate |
| **no env set at all** | does not delegate — the default |
| NestJS unreachable | falls back to the local projection, identical output |
| a well-formed `ok=false` | does **not** fall back; nothing is written locally |

That last one is the one worth stating plainly: NestJS has already recorded
that failure in `fin_hook_failures`, so projecting again in Python would
double-handle it and hide a real problem behind a silent success. Only a
**transport** failure falls back. It is tested with an HTTP stub, because a
stub is the only way to produce a deterministic `ok=false`.

## Harness consolidation

The unit-2 harness was a single-purpose script. Its orchestration now lives in
`scripts/lib/party-payment-parity.ts` and both source types are thin fixture
files. The mechanic run was re-executed against the shared runner and is
unchanged at 12/12, which is what makes the refactor safe to keep.

The mechanic fixtures also gained two **negative** assertions — a historical
mechanic payment still projects, and mechanic legs carry no `trip_id` — so a
future change to the shared helper cannot silently give vendor and mechanic
the supplier-only behaviours.

## Bugs fixed

**None in the product.** Supplier parity was green on the first run, including
every guard and rounding case.

One bug in the **harness** was found and fixed while adding the `ok=false`
check: the Python driver was invoked with `execFileSync`, which blocks the Node
event loop, so the in-process HTTP stub could never accept a connection. Python
sat on its own 10-second timeout for every document instead, turning a fast
check into a ten-minute hang. The driver call is now spawned and awaited, which
keeps the loop free.

## What is switched over

`supplier_payment`, and only when Python is configured for it. The other
eleven source types are untouched: nine still project in Python, and
`vendor_payment`, `vendor_bill` and `mechanic_payment` keep the directions they
had. The forward bridge is not retired.

## Results

```
scripts/fin-supplier-parity.ts     17 checks, 0 failures, 64 legs identical
scripts/fin-mechanic-parity.ts     12 checks, 0 failures, 50 legs identical
scripts/fin-projection-parity.ts   936 vendor ledger rows, 0 mismatches
scripts/fin-hook-parity.ts         34 checks, 0 failures
vitest                             233 tests passing
```

## What remains for 2c

- Nine unported projections: `invoice` (+ the `invoice_payment` cascade),
  `credit_debit_note`, `expense`, `mechanic_work_order`,
  `trip_customer_receipt`, `wallet_recharge`, `wallet_transfer`,
  `wallet_adjustment`, `driver_payment`.
- `replay_pending_failures`, the retry driver.
- Deciding when to switch `vendor_payment` and `vendor_bill` onto the reverse
  bridge, and retiring the forward bridge afterwards.
- Out of 2c scope: reconciliation, `GET /api/fin/accounts`, `backfill_tenant`.
