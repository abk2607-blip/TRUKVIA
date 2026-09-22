# Phase 6 · Slice 2c, unit 6 — the `expense` projection

One source type, and by volume the most important in the whole slice: expenses
are roughly **79% of existing ledger rows**. Follows
[unit 5](PHASE6-SLICE2C-UNIT5-CREDIT-DEBIT-NOTE.md) (`6475ab2`).

## Inspection

`project_expense` is the canonical cost projection — every payable, vendor and
supplier-recovery leg is funnelled through it *precisely so* a paired
`VendorBill` or `MechanicWorkOrder` cannot double-count the same cost.

One source read (`expenses.find_one`), no cascade in `_delete_by_source`, and
**no paired lookup from this side**. (`_has_paired_expense` runs the other way
round — vendor_bill and mechanic_work_order consult it — so reprojecting an
expense does not reproject the bill. That coupling belongs to those two source
types, which are not in this unit.)

### The routing chain — top-down, first match wins

The debit side is **always** `EXPENSE_DEFAULT`. What varies is the credit side:

| # | condition | credit | txn_type |
| --- | --- | --- | --- |
| 1a | `supplier_owned_vehicle` ∧ mode `supplier_settlement_adjustment` | `AP_SUPPLIER` | `expense_supplier_settlement_recovery` |
| 1b | `supplier_owned_vehicle` ∧ mode `company_borne` | `CASH` | `expense_company_borne` |
| 2 | document `source_type == "fastag_import"` | `WALLET_FASTAG` | `expense_fastag_toll` |
| 3 | document `source_type == "fleet_card_import"` | `WALLET_FUEL` | `expense_fleet_diesel` |
| 4 | `vendor_bill_id` set | `AP_VENDOR` | `expense_vendor_payable` |
| 5 | `mechanic_work_order_id` set | `AP_MECHANIC` | `expense_mechanic_payable` |
| 6 | `settlement_mode == "cash_now"` | `CASH` | `expense_cash_now` |
| 7 | otherwise | `SUSPENSE` | `expense_unrouted` |

Branch 1a additionally **forces `party_type` to `"supplier"`**, overriding
whatever the document carried, and sets `is_supplier_settlement_recovery` — on
the **credit leg only**.

### Two traps, both verified in the interpreter and tested in both directions

**A supplier-owned vehicle whose mode is neither named case falls THROUGH.** It
does not land anywhere supplier-ish; rules 2–7 still apply. Confirmed:
`supplier_owned_vehicle=True, mode="weird"` → `SUSPENSE`; the same with
`source_type="fastag_import"` → `WALLET_FASTAG`; with a `vendor_bill_id` →
`AP_VENDOR`.

**`supplier_owned_vehicle` is read with `bool()`, not `== True`.** A non-empty
string is truthy in Python, so the literal string `"false"` **selects** the
supplier branch. A `=== true` test in the port would have silently rerouted
those rows to `SUSPENSE`. `pyTruthy` reproduces it; `0`, `""`, `None` and `[]`
are correctly falsy.

### Other exact semantics

- **Dynamic `ref_leg`.** The credit leg uses
  `f"{credit_code.lower()}_credit"`, so `ref_source_key` varies by branch:
  `ap_supplier_credit`, `cash_credit`, `wallet_fastag_credit`,
  `wallet_fuel_credit`, `ap_vendor_credit`, `ap_mechanic_credit`,
  `suspense_credit`. The debit leg is always `expense_debit`.
- **Guards:** `is_deleted`/`is_reversed`, then `amount <= 0` after `_q2`, then
  `is_historical`. All three flags read with Python truthiness.
- **Narration** is `(narration or category or "")[:400]`. The `category` field
  on the leg is **not** truncated — a 500-character category yields a
  400-character narration next to a 500-character category.
- **`source_key` is carried onto both legs.** This is the first ported
  projection that sets it; the party payments leave it empty.
- `vendor_bill_id` and `mechanic_work_order_id` are only ever *tested*, never
  emitted, so Python truthiness on the raw value is exactly right.
- **All eight accounts it can name are already in the seed catalog**, so no
  branch lazily creates anything — nothing about `GET /api/fin/accounts` is
  involved.
- Both entry points work unchanged: the Iter150I wrapper passes non-driver
  types straight through, and both delegation layers are generic over source
  type.

## Implementation

`projectExpense`, its own function on the shared `leg()` factory and `q2`. It
was **not** folded into `partyPaymentLegs`: there is no mode-to-bank
resolution, the credit account comes from a seven-rule chain, the `ref_leg` is
dynamic, and it carries `source_key` and a recovery flag. Adding four or five
option flags to a helper that four verified projections depend on would have
been the wrong trade.

The dispatcher gained an `expenses` branch; `PORTED_SOURCE_TYPES` and the
reverse-bridge allowlist gained the type. The Python env gate is unchanged and
still OFF by default.

## Parity

`scripts/fin-expense-parity.ts`, three throwaway databases (Python native as
the reference, the NestJS port in-process, and Python **delegating to a live
NestJS**), with `verifyRouting` on because 79% of rows justify measuring the
entry points here too:

```
fin_txn rows: python 98, typescript 98
checks 33   PASS 33   FAIL 0
```

Green on the first run. 57 fixtures; every document reprojected **twice** per
side.

### Every branch covered

All seven rules, plus: the fall-through with three different landing rules; six
truthiness values for `supplier_owned_vehicle` on each side of the boundary;
four precedence pairs including one document that matches *every* rule at once;
a non-string `vendor_bill_id`; blank `vendor_bill_id`/`mechanic_work_order_id`
falling through; all eight guards; `2.675`, `0.125`, `0.375`, `1.005`, a
numeric-string amount; the full narration fallback chain; a 500-character
category; unicode; full, blank and absent denormalised fields; and the same id
under a second tenant.

Explicit assertions beyond the row comparison:

```
PASS  all 27 routing rules land correctly
PASS  every credit leg uses a ref_leg derived from its account code
PASS  every debit leg uses expense_debit
PASS  only the credit leg of a settlement recovery carries the flag
PASS  the DEBIT leg of a settlement recovery does not carry the flag
PASS  a settlement recovery overrides the document party_type with "supplier"
PASS  but party_id and party_name are left exactly as denormalised
PASS  a long category truncates only the NARRATION, never the category field
PASS  source_key is carried onto both legs
PASS  the debit side is always EXPENSE_DEFAULT
```

### Delegation, fallback, default-OFF and routing

| | |
| --- | --- |
| Python → live NestJS | matches Python native exactly |
| type not in `TRUKVIA_FIN_NODE_SOURCE_TYPES` | does not delegate |
| **no env set at all** | does not delegate, from both entry points |
| NestJS unreachable | falls back locally, identical output |
| a well-formed `ok=false` | does not fall back; nothing written locally |
| hook entry point | delegates exactly once per call, two legs |
| `reproject_source` entry point | delegates exactly once per call, two legs |
| both entry points | produce identical rows |

The hook returns before ever calling `reproject_source`, so the two can never
both project the same source — measured with a counting proxy, not assumed.

## Duplicate-write verification

98 rows on both sides after every document is projected **twice**, which is the
direct check that delete-then-insert leaves no duplicates, plus the
per-entry-point counters above.

## Bugs fixed

**None in the product.** Expense parity was green on the first run, including
every routing branch and both truthiness traps.

One **test fixture** broke as a direct consequence of this port: the
hook-parity harness used `"expense"` as its example of an unsupported source
type for the internal endpoint. The moment expense was ported, NestJS began
answering 200 where Python still answered 400. The fixture now uses a value
that will never be a source type, so the case tests the allowlist rather than
the porting schedule.

## What is switched over

`expense`, and only when Python is configured for it. The six remaining
unported types are untouched, and the six already ported keep the directions
they had. The forward bridge is not retired.

## Results

```
scripts/fin-expense-parity.ts      33 checks, 0 failures, 98 legs identical
scripts/fin-cdn-parity.ts          22 checks, 0 failures
scripts/fin-hook-parity.ts         34 checks, 0 failures
scripts/fin-projection-parity.ts   936 vendor ledger rows, 0 mismatches
vitest                             350 tests passing
```

The three party-payment harnesses were **not** re-run: no shared helper changed
in this unit, and the 936-row vendor ledger run already exercises the shared
`leg()` factory and `q2` end to end.

## What remains for 2c

- **Six** unported projections: `invoice` (+ the `invoice_payment` cascade),
  `mechanic_work_order`, `trip_customer_receipt`, `wallet_recharge`,
  `wallet_transfer`, `wallet_adjustment`.
- `replay_pending_failures`, the retry driver. It calls `reproject_source`
  directly, so it delegates for an enabled type — worth knowing before turning
  one on in a live environment.
- Deciding when to switch `vendor_payment` and `vendor_bill` onto the reverse
  bridge, and retiring the forward bridge afterwards.
- The deferred `pyStr()` narration fidelity fix, still recorded in
  [unit 5](PHASE6-SLICE2C-UNIT5-CREDIT-DEBIT-NOTE.md).
- Out of 2c scope: reconciliation, `GET /api/fin/accounts`, `backfill_tenant`.

A note on sequencing: `mechanic_work_order` and `vendor_bill` both depend on
`_has_paired_expense`, and expense is now ported while they are not. That does
not affect correctness today — the pairing is evaluated inside *their*
projection, whichever side runs it — but it is the coupling to think about when
choosing the next unit.
