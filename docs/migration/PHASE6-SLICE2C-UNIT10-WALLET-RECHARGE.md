# Phase 6 · Slice 2c, unit 10 — the `wallet_recharge` projection

One source type. Follows
[unit 9](PHASE6-SLICE2C-UNIT9-TRIP-CUSTOMER-RECEIPT.md) (`895f086`).

## Inspection

BANK/CASH → WALLET, two legs:

```
wallet_code                    in  (wallet_debit)
_mode_account(funding_mode)    out (funding_credit)
txn_type  wallet_recharge_in
```

Guards are **`is_deleted` and `amount <= 0`, and nothing else**. Verified
against the interpreter: neither `is_historical` nor `is_reversed` is
consulted.

### The known risk, confirmed and preserved

Unlike `wallet_adjustment`, there is **no guard on `wallet_code`**. An empty,
absent, null or unknown code is not skipped — it becomes the leg's
`account_code`, and the failure surfaces later when `_persist_legs` cannot
resolve it and raises. That preserves a distinction the hook queue exists for:

| | outcome |
| --- | --- |
| projection guard (`is_deleted`, `amount <= 0`) | zero legs, `ok=true`, written 0 |
| persistence lookup failure (bad `wallet_code`) | **raises** → `ok=false` + a `fin_hook_failures` row |

Collapsing the second into the first would turn a recorded, retryable failure
into a silent no-op. The instruction not to "fix" this was followed exactly.

Guard precedence matters too: `is_deleted` and the amount are checked *before*
the code is read, so a bad code on a deleted or zero-amount document produces
no failure at all.

The model constrains the field to the two seeded wallets, so this is reachable
only from legacy or imported data. Nothing here creates an account, so there is
no dependency on `GET /api/fin/accounts` and nothing that normalises
`fin_accounts`.

Narration is `f"Wallet recharge · {reference}"` with `.strip(" ·")`, and a
`reference` present as `null` interpolates as the literal `"None"` — the same
`.get(k, "")` subtlety as unit 8, handled by the same `pyInterp` helper.

## Parity

`scripts/fin-walletrecharge-parity.ts`, three throwaway databases,
`verifyRouting` on:

```
fin_txn rows: python 46, typescript 46
fin_hook_failures identical (5 rows)
checks 33   PASS 33   FAIL 0
```

Green on the first run. 36 fixtures covering all six account cases the brief
asked for — a valid seeded wallet, empty, unknown, null, a non-string legacy
value, and a second tenant holding the same source id — plus every funding
mode, the guards, the midpoint roundings, and the full narration matrix.

The harness gained an `expectedFailures` mechanism for this unit: ids whose
projection is *meant* to fail are not treated as harness errors, and the
resulting queue rows are compared between the two sides. That is what turns
"the failure semantics match" into a measurement:

```
PASS  fin_hook_failures identical (5 rows)
PASS  every expected failure produced exactly one queue row
PASS  each failure row is queued as pending with retry_count 0
PASS  a document with an unresolvable wallet code writes NO ledger rows
PASS  a guard that fires first prevents the failure entirely
```

### Delegation, fallback, default-OFF and routing

Python → live NestJS matches native; a type outside
`TRUKVIA_FIN_NODE_SOURCE_TYPES` does not delegate; **no env at all** does not
delegate from either entry point; an unreachable NestJS falls back locally with
identical output; a well-formed `ok=false` does not fall back; and the hook and
`reproject_source` each delegate exactly once onto identical rows.

## Duplicate-write verification

46 rows on both sides after projecting every document **twice**, with the five
failing documents contributing none.

## Bugs fixed

**None.** Parity was green on the first run.

## What is switched over

`wallet_recharge`, and only when Python is configured for it. The remaining
unported types are untouched and the ten already ported keep the directions
they had. The forward bridge is not retired.
