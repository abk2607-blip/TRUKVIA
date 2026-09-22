# Phase 6 · Slice 2c, unit 7 — the `mechanic_work_order` projection

One source type, and the first that consults **another collection**. Follows
[unit 6](PHASE6-SLICE2C-UNIT6-EXPENSE.md) (`f8774ee`).

## Inspection

### The coupling, answered first

The brief was right to flag it and right not to assume it harmless — so it was
checked rather than argued:

```python
async def _has_paired_expense(uid, cid, *, vendor_bill_id="", mechanic_work_order_id=""):
    q = {"user_id": uid, "company_id": cid,
         "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True}}
    ...
    return bool(await db.expenses.find_one(q, {"_id": 0, "id": 1}))
```

**It reads `db.expenses` — the SOURCE collection — not `fin_txn`.** Pairing
therefore does not depend on who owns the expense *projection*. MongoDB owns
`expenses` whether Python, NestJS or nobody has projected it. No change to the
expense projection or to any shared helper was required, and none was made.

That is the argument; the measurement is in §Mixed ownership below.

### What makes an expense "paired"

Two details are **Mongo** semantics, not Python ones, and both were verified
against a live server:

- `$ne: true` excludes **only BSON `true`**. An expense with `is_deleted: 1`,
  `"false"`, `0`, `null`, or the field absent still counts as paired. Measured:
  of `absent, null, false, 0, 1, true, "", "false"`, only `true` is excluded.
- The probe checks **neither `is_historical` nor the amount**.

The consequence is worth stating plainly: an expense that projects *nothing* —
because `pyTruthy(1)` skips it, or because it is historical, or zero-amount —
still **suppresses** its work order. Both documents end with zero legs. That is
Python's behaviour, and the port reproduces it.

### The projection

```
guards:  is_deleted (Python truthiness)  →  has_paired_expense  →  amount <= 0
legs:    SUSPENSE in  (suspense_debit)  /  AP_MECHANIC out  (ap_credit)
txn_type: mechanic_wo_orphan  on both legs
```

Orphan-only by design: in the canonical flow the Expense carries the real cost,
so projecting both would double-count `AP_MECHANIC`. When unpaired, the cost is
parked in `SUSPENSE` where it stays visible.

**What is NOT here matters as much as what is.** There is **no `is_reversed`
guard and no `is_historical` guard** — unlike every projection ported before
it. Verified in the interpreter: a reversed or historical work order still
projects. Adding either guard "for consistency" would silently drop orphan
costs from the ledger.

Other exact semantics: the date field is **`work_date`**, not `date`; the
narration is a fixed `f"WO {id} (orphan)"` with no fallback and no strip, capped
at 400 by `_leg`; no `source_key` and no `category` are set; party is the
mechanic (`mechanic_id` / `mechanic_name`) with `vehicle_id` and `trip_id`
carried. Two reads per reproject — the work order, then the pairing probe. No
cascade. Both accounts are already seeded.

## Implementation

`projectMechanicWorkOrder(wo, hasPaired)` — its own function on the shared
`leg()` factory and `q2`. Not folded into `partyPaymentLegs`: there is no
party-payment shape here at all.

`hasPairedExpense` was generalised from its hardcoded vendor-bill form to
Python's exact two-keyword shape, applying each key only when truthy. That is a
parameterisation, not a behaviour change, and the 936-row vendor ledger run
covers the vendor_bill caller.

The dispatcher gained a `mechanic_work_orders` branch performing both reads;
`PORTED_SOURCE_TYPES` and the reverse-bridge allowlist gained the type. The
Python env gate is unchanged and still OFF by default.

## Parity

`scripts/fin-workorder-parity.ts`, three throwaway databases, `verifyRouting`
on:

```
fin_txn rows: python 54, typescript 54
checks 31   PASS 31   FAIL 0
```

34 work orders plus 10 paired expenses; every document reprojected **twice**
per side. The pairing matrix covers: no expense; a live expense; an expense
deleted with `true` (unpairs) and with `1` (still pairs); reversed with `true`
(unpairs) and with `"false"` (still pairs); historical; zero-amount; two
matching expenses; and an expense carrying the same work-order id under a
**different tenant**, which must not pair across the boundary.

Explicit assertions beyond the row comparison:

```
PASS  an unpaired work order parks the cost in SUSPENSE against AP_MECHANIC
PASS  a paired work order projects nothing
PASS  a deleted, reversed or cross-tenant expense does NOT pair
PASS  is_deleted true unpairs, but is_deleted 1 still pairs ($ne matches only BSON true)
PASS  is_reversed true unpairs, but the string "false" still pairs
PASS  a historical expense projects nothing AND still suppresses its work order
PASS  a reversed or historical work order still projects — there is no guard for either
PASS  the narration is the fixed orphan form
PASS  the date comes from work_date, never a stray date field
PASS  no source_key and no category are set
```

## Mixed ownership — measured, not argued

The harness now pre-projects the paired expenses **with a different owner on
each database**, then projects the work orders and requires all three ledgers
to match:

| case | database | expense projected by | work order projected by |
| --- | --- | --- | --- |
| A | PY | Python | Python |
| B | TS | the NestJS port | the NestJS port |
| C | PY | Python | Python (the reference) |
| D | BRIDGE | **Python** (not in the delegation list) | **NestJS** via the reverse bridge |

All three ledgers are byte-identical, so the pairing answer is the same under
every ownership split — including case D, where the two sides of the
relationship are owned by different services at once.

### Delegation, fallback, default-OFF and routing

| | |
| --- | --- |
| Python → live NestJS | matches Python native exactly |
| type not in `TRUKVIA_FIN_NODE_SOURCE_TYPES` | does not delegate |
| **no env set at all** | does not delegate, from both entry points |
| NestJS unreachable | falls back locally, identical output |
| a well-formed `ok=false` | does not fall back; nothing written locally |
| hook / `reproject_source` entry points | each delegates exactly once, two legs, identical rows |

## Duplicate-write verification

54 rows on both sides after projecting every document **twice**, plus the
per-entry-point counters.

## Bugs fixed

**None in the product.** The projection was correct on the first run — all 21
substantive checks passed immediately, including every pairing state.

One bug in the **harness**, introduced by this unit's own `preProject` feature:
the three phases that wipe `fin_txn` before re-running (delegation-off-by-type,
delegation-off-by-default, and the unreachable-NestJS fallback) wiped the
pre-projected expense rows too, then compared a partial ledger against a full
reference. They now restore the dependency first. The failure was loud and in
the harness, not silent and in the ledger.

## What is switched over

`mechanic_work_order`, and only when Python is configured for it. The five
remaining unported types are untouched, and the seven already ported keep the
directions they had. **`expense` was not modified** — neither its projection
nor its behaviour. The forward bridge is not retired.

## Results

```
scripts/fin-workorder-parity.ts    31 checks, 0 failures, 54 legs identical
scripts/fin-expense-parity.ts      33 checks, 0 failures
vitest                             373 tests passing
```

## What remains for 2c

- **Five** unported projections: `invoice` (+ the `invoice_payment` cascade),
  `trip_customer_receipt`, `wallet_recharge`, `wallet_transfer`,
  `wallet_adjustment`.
- `replay_pending_failures`, the retry driver.
- Deciding when to switch `vendor_payment` and `vendor_bill` onto the reverse
  bridge, and retiring the forward bridge afterwards. `vendor_bill` is now the
  only remaining user of `_has_paired_expense`, and that helper is already
  ported and exercised.
- The deferred `pyStr()` narration fidelity fix from unit 5.
- Out of 2c scope: reconciliation, `GET /api/fin/accounts`, `backfill_tenant`.
