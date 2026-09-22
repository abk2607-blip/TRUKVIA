# Phase 6 · Slice 2c, unit 8 — the `wallet_adjustment` projection

One source type, and the first whose **account code comes from the document**
rather than a literal. Follows
[unit 7](PHASE6-SLICE2C-UNIT7-MECHANIC-WORK-ORDER.md) (`2161510`).

## Inspection

A real financial adjustment booked against `SUSPENSE`, so the correction stays
visible on both sides instead of vanishing into the wallet:

```
increase -> wallet_code in  (wallet_debit)   / SUSPENSE out (suspense_credit)
decrease -> wallet_code out (wallet_credit)  / SUSPENSE in  (suspense_debit)
txn_type    wallet_adjustment_increase / wallet_adjustment_decrease
```

One read from `wallet_adjustments`. No cascade, no paired lookup, no
cross-module dependency, and **no dependency on either other wallet
projection**.

### Guards, in order

1. `is_deleted` — Python truthiness
2. `amount <= 0` after `_q2`
3. `not wallet_code or direction not in ("increase", "decrease")`

`direction` matching is **exact**: `"INCREASE"`, `"Increase"` and
`"increase "` are all rejected. There is **no `is_reversed` and no
`is_historical` guard** — neither field exists on the model. A reversal is a
separate document with the opposite direction, and `reverses_id` is ignored, so
both stay projected for a net-zero effect with the history intact.

### The dynamic account — and why it is safe in isolation

`wallet_code` is read from the document and used directly as the leg's
`account_code`. That sounds like the riskiest thing in the slice so far, and it
was checked rather than assumed:

- **The model constrains it** to `Literal["WALLET_FASTAG", "WALLET_FUEL"]`, and
  **both are already in the seed catalog**.
- **The projection self-guards.** An empty, absent or null `wallet_code`
  returns no legs — it never reaches the persist layer.
- **Nothing here creates an account.** `_persist_legs` only *looks up* the code
  in the map `ensure_system_accounts` built. There is no lazy-seeding path, and
  therefore **no dependency on `GET /api/fin/accounts`** and nothing that could
  normalise `fin_accounts`.

A `wallet_code` that is non-empty but **not** in the catalog passes the guard
and makes `_persist_legs` raise — a projection **failure** recorded in
`fin_hook_failures`, not a silent skip. Only reachable from legacy or imported
data, never through the API, and the port preserves it by using the same
persist path.

### Two details that would break byte parity invisibly

**The decrease sign is U+2212 MINUS SIGN**, not an ASCII hyphen-minus. The two
are visually identical; a well-meaning find-and-replace would corrupt every
decrease narration. There is a unit test asserting the codepoint.

**A `reason` present as `null` interpolates as the literal text `"None"`.**
Python's `.get("reason", "")` default applies only to an *absent* key —

```
key absent          -> ""    -> "Wallet adjustment (+)"
key present as None -> None  -> "Wallet adjustment (+) · None"
```

`str()` would give `""` for both and silently lose the difference, so this unit
uses a small `pyInterp` helper that reproduces Python's f-string rendering for
the types a document can hold. (The wider `pyStr()` question across the older
projections is still the separate unit recorded in
[unit 5](PHASE6-SLICE2C-UNIT5-CREDIT-DEBIT-NOTE.md); this is not a retrofit.)

The narration does end with `.strip(" ·")`, so an empty reason — or a reason
that is just `"·"` — strips back to `Wallet adjustment (+)`.

No party, trip, vehicle, category or `source_key` on any leg.

## Suitable for isolated migration?

**Yes.** No account creation, no dependency on `wallet_recharge` or
`wallet_transfer`, no cascade, one read, and a self-guard that keeps a
malformed code away from the persist layer. Nothing was deferred or
substituted.

## Implementation

`projectWalletAdjustment` on the shared `leg()` factory and `q2`, plus the
local `pyInterp` helper. No option flags were added to any shared helper. The
dispatcher gained a `wallet_adjustments` branch; `PORTED_SOURCE_TYPES` and the
reverse-bridge allowlist gained the type. The Python env gate is unchanged and
still OFF by default.

## Parity

`scripts/fin-walletadj-parity.ts`, three throwaway databases, `verifyRouting`
on:

```
fin_txn rows: python 50, typescript 50
checks 31   PASS 31   FAIL 0
```

38 fixtures; every document reprojected **twice** per side. Coverage: both
directions on both allowed wallets; seven rejected direction spellings; the
empty/absent/null `wallet_code` self-guard; two in-catalog codes outside the
wallet pair; all guards including the two that do *not* exist; a reversal
document; the four midpoint roundings and a numeric-string amount; the full
narration matrix including `null`, a bare separator, 500 characters and
unicode; and the same id under a second tenant.

Explicit assertions beyond the row comparison:

```
PASS  an increase debits the wallet and credits SUSPENSE
PASS  a decrease is the exact mirror
PASS  the wallet account is read from the document, not a literal
PASS  only the exact strings "increase" and "decrease" project
PASS  is_reversed and is_historical are not guards here — both still project
PASS  a reversal document projects on its own, with reverses_id ignored
PASS  the decrease sign is U+2212 MINUS SIGN, not an ASCII hyphen
PASS  a reason present as null interpolates as the literal "None"
PASS  wallet adjustment legs carry no party, trip, vehicle, category or source_key
```

### Account-seeding side effects

`fin_accounts identical` passes, so the seeded catalog is the same on both
sides after the run. That is the whole of the account behaviour here: the only
writer is `ensure_system_accounts`, which every projection already calls, and
this unit adds no new account and no new code path into it.

### Delegation, fallback, default-OFF and routing

| | |
| --- | --- |
| Python → live NestJS | matches Python native exactly |
| type not in `TRUKVIA_FIN_NODE_SOURCE_TYPES` | does not delegate |
| **no env set at all** | does not delegate, from both entry points |
| NestJS unreachable | falls back locally, identical output |
| a well-formed `ok=false` | does not fall back; nothing written locally |
| hook / `reproject_source` | each delegates exactly once, two legs, identical rows |

## Duplicate-write verification

50 rows on both sides after projecting every document **twice**, plus the
per-entry-point counters.

## Bugs fixed

**None in the product.** Parity was green on the first run.

## What is switched over

`wallet_adjustment`, and only when Python is configured for it. The four
remaining unported types are untouched, and the eight already ported keep the
directions they had. The forward bridge is not retired.

## Results

```
scripts/fin-walletadj-parity.ts    31 checks, 0 failures, 50 legs identical
scripts/fin-workorder-parity.ts    31 checks, 0 failures
vitest                             416 tests passing
```

## What remains for 2c

- **Four** unported projections: `invoice` (+ the `invoice_payment` cascade),
  `trip_customer_receipt`, `wallet_recharge`, `wallet_transfer`.
- `replay_pending_failures`, the retry driver.
- Deciding when to switch `vendor_payment` and `vendor_bill` onto the reverse
  bridge, and retiring the forward bridge afterwards.
- The deferred `pyStr()` narration fidelity fix from unit 5 — now with one
  concrete precedent, since `pyInterp` shows what the faithful version looks
  like.
- Out of 2c scope: reconciliation, `GET /api/fin/accounts`, `backfill_tenant`.

A note for whoever takes `wallet_recharge` next: unlike this unit it has **no
self-guard on its wallet code**, so an empty `wallet_code` reaches
`_persist_legs` and raises rather than returning no legs. That difference is
worth confirming before porting it.
