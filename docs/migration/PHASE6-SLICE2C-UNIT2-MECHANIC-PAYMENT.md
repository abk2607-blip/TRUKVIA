# Phase 6 · Slice 2c, unit 2 — the `mechanic_payment` projection

One source type. It is the first projection actually to cross the reverse
bridge, and the first place a Python write path can be configured to delegate
to NestJS.

Follows [unit 1](PHASE6-SLICE2C-UNIT1-PROJECTION-HOOK.md) (`f45caec`).

## Selection

Eleven source types remained. The choice was made from the code, not from the
names.

| Candidate | Source reads | Cascade | Notes |
| --- | --- | --- | --- |
| **`mechanic_payment`** | **1** | **none** | **6-line delegation to `_party_payment_legs`, already ported for vendors** |
| `driver_payment` | 1 | none | same helper, but reached only through the Iter150I monkey-patched `reproject_source` |
| `wallet_recharge` / `_transfer` / `_adjustment` | 1 | none | introduce `wallet_code` as a *dynamic* account code, which couples them to account seeding |
| `credit_debit_note` | 1 | none | status and `is_historical` gates, two kinds, ~43 lines |
| `supplier_payment` | 1 | none | carries `is_supplier_settlement_recovery` |
| `expense` | 1 | none | ~98 lines, the largest |
| `mechanic_work_order` | **2** | none | needs `_has_paired_expense` |
| `trip_customer_receipt` | 1 | **yes** | `{tid}:*` prefix delete |
| `invoice` | 1 | **yes** | `{id}:*` cascade into `invoice_payment` |

`mechanic_payment` wins on every criterion at once:

```python
def project_mechanic_payment(mp: dict) -> List[dict]:
    return _party_payment_legs(
        mp, ap_code="AP_MECHANIC", party_type="mechanic",
        party_id_key="mechanic_id", src_type="mechanic_payment",
        txn_type_prefix="mechanic",
    )
```

It is a parameterisation of the helper `project_vendor_payment` already uses,
which this port had verified against 936 real ledger rows. Its dispatcher
branch is a single `mechanic_payments.find_one` with no cascade and no paired
lookup, and `AP_MECHANIC` was already in both account seeders — so no change to
account resolution was needed, which matters because
`GET /api/fin/accounts` is out of bounds.

## Implementation

**`partyPaymentLegs` extracted.** Python has one helper that vendor, mechanic
and driver payments each parameterise. The port had it inlined into
`projectVendorPayment`. Two copies of this shape would drift, and the drift
would be a wrong ledger rather than a failing type, so the helper is now shared
and `projectVendorPayment` delegates to it — verified unchanged by the 936-row
vendor regression.

`projectMechanicPayment` is the second caller. The dispatcher gained a
`mechanic_payments` branch; `PORTED_SOURCE_TYPES` and the reverse bridge's
allowlist gained the type.

**The Python side is wired, and off by default.** Rather than editing
`routers/mechanics.py`, the delegation sits at the single choke point all
sixteen callers already share — `hook_after_source_write`:

```
TRUKVIA_FIN_NODE_URL           NestJS POST /internal/fin/reproject
TRUKVIA_INTERNAL_TOKEN         the shared secret (>= 32 chars)
TRUKVIA_FIN_NODE_SOURCE_TYPES  comma-separated types to delegate
```

With none of these set the hook behaves exactly as before — that is the
rollback. A **transport** failure (unreachable, timeout, non-200) falls back to
the local projection, so a NestJS outage can never leave the ledger stale. A
well-formed `ok=false` is **not** retried locally: NestJS has already recorded
that failure in `fin_hook_failures`, and projecting again would double-handle
it.

### The asymmetry is deliberate

NestJS's internal endpoint accepts `mechanic_payment`; Python's still refuses
it. That is what lets Python delegate this one source type without NestJS being
able to bounce the work back. It is asserted in the hook harness, not assumed.

## Parity

`scripts/fin-mechanic-parity.ts` — three throwaway databases:

| | |
| --- | --- |
| `PY` | Python's real hook projects locally — the reference |
| `TS` | the NestJS port projects in-process |
| `BRIDGE` | Python's hook **delegates to a live NestJS**, so Python writes nothing |

```
fin_txn rows: python 48, typescript 48
checks 7   PASS 7   FAIL 0
```

Every document is reprojected **twice** on each side, so delete-then-insert
idempotency is part of the comparison rather than a separate test. Rows are
compared in full — ids, `ref_source_key`, `account_id`, `account_code`,
`counter_account_*`, amounts, direction, narration, party fields, `txn_type`,
`status` — with only the two wall-clock stamps masked.

The 30 fixtures target the guards and the edges, not the happy path: both
directions, every mode including an unknown one, blank and missing `mode` and
`type`, `is_deleted`, `is_reversed`, zero, negative, null and missing amounts, a
numeric-string amount, `2.675` and `0.125` for the rounding rule, a 500-char
ref for the 400-char narration cap, unicode, missing `mechanic_id`, missing
`date`, and the same id under a second tenant to prove scoping.

Also asserted: guarded documents project *zero* legs rather than a zero-amount
leg; the shared id projects separately under each tenant; and an unreachable
NestJS falls back to the local projection with identical output.

## Bug found and fixed

**`_q2` mis-rounded exact-midpoint doubles.** `projection.ts` used the
scale-by-100-and-compare shortcut, so a mechanic payment of `2.675` projected as
`2.68` where Python gives `2.67` — a one-paisa error in a real ledger leg. This
is the latent defect flagged in
[slice 2b](PHASE6-SLICE2B-FINANCE-WRITES.md#2-slice-2as-roundhalfeven2-mis-rounds-exact-midpoint-doubles);
it is no longer latent, because `_q2` is applied to arbitrary source amounts
rather than to values that already have two decimals. `q2` now delegates to
`pyRound2`, which decides in exact BigInt arithmetic.

It was caught by parity, not by inspection, and it affected the vendor
projections too — the 936-row regression confirms those were already correct on
real data and remain so.

## What is switched over

`mechanic_payment`, and only when Python is configured for it. The other twelve
source types are untouched: ten still project in Python, and `vendor_payment`
and `vendor_bill` keep the direction they had (Python-first via the forward
bridge, NestJS port as fallback). The forward bridge is not retired.

## Results

```
scripts/fin-mechanic-parity.ts    7 checks, 0 failures, 48 legs identical
scripts/fin-projection-parity.ts  936 vendor ledger rows, 0 mismatches
scripts/fin-hook-parity.ts        34 checks, 0 failures
vitest                            204 tests passing
```

Two hook-harness bridge cases now compare **status only**: the allowlist is
rendered into the 400 body, and NestJS's list legitimately has one more entry.
A new case asserts the asymmetry directly.

## What remains for 2c

- Ten unported projections: `invoice` (+ the `invoice_payment` cascade),
  `credit_debit_note`, `supplier_payment`, `expense`, `mechanic_work_order`,
  `trip_customer_receipt`, `wallet_recharge`, `wallet_transfer`,
  `wallet_adjustment`, `driver_payment`.
- `replay_pending_failures`, the retry driver.
- Deciding when to switch `vendor_payment` and `vendor_bill` onto the reverse
  bridge, and retiring the forward bridge afterwards.
- Out of 2c scope: reconciliation, `GET /api/fin/accounts`, `backfill_tenant`.
