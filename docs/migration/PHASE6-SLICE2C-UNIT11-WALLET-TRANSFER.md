# Phase 6 — Slice 2c, unit 11: the `wallet_transfer` projection

Status: **GREEN**. Parity `checks 33 PASS 33 FAIL 0`.

The eleventh source type ported out of `services_fin_txn.reproject_source`
and into `apps/api/src/fin/projection.ts`. Production is untouched: reverse
delegation stays off by default, so Python still owns every live write.

## What it is

The only projection that reads **two** account codes out of the document. One
leg credits `source_wallet_code`, the other debits `destination_wallet_code`,
both under `txn_type: 'wallet_transfer'`.

```
wallet_transfer:{id}:src_credit   source_wallet_code        out
wallet_transfer:{id}:dst_debit    destination_wallet_code   in
```

## The guards, and the one it does not have

Unlike `wallet_recharge` (unit 10), this projection **does** self-guard its
codes: an empty, absent or null code on either side projects nothing, and a
transfer whose two codes are equal projects nothing. What it does not guard is
a code that is non-empty and simply **unknown** — that passes the projection
and fails later, inside `_persist_legs`, when the account cannot be resolved.

That distinction is load-bearing, so parity exercises both halves:

| document | outcome |
| --- | --- |
| `wt_same_wallet`, `wt_src_empty`, `wt_dst_null`, … | projection guard fires — 0 legs, **no** `fin_hook_failures` row |
| `wt_src_unknown`, `wt_both_unknown` | persist raises on the FIRST leg — 0 rows, failure queued |
| `wt_dst_unknown` | persist raises on the SECOND leg — **1 row survives**, failure queued |

### The partial write is real, and it is not a leak

`_persist_legs` upserts **one leg at a time**. An unresolvable *destination*
therefore leaves the already-written source leg behind. This is Python's
behaviour and the port reproduces it exactly; the harness originally asserted
an atomic rollback, and the **assertion** was corrected, not the code.

It does not leak, because the failure is recorded in `fin_hook_failures` and
the next attempt deletes by source before reinserting — a retry or a corrected
document cleans the stray row up.

## Guards this projection does NOT have

`is_historical` and `is_reversed` are not consulted. A reversed or historical
transfer still projects. Only `is_deleted` (Python-truthy) and a non-positive
amount suppress it.

## Narration

```
Wallet transfer WALLET_FASTAG → WALLET_FUEL
```

The separator is **U+2192 RIGHTWARDS ARROW**, not `->`. Parity asserts the
codepoint directly, because a mangled arrow would still compare equal to
itself on both sides of a careless test.

Neither code is stripped and the narration is capped at 400 characters, as
everywhere else.

## Verification

```
npx tsx scripts/fin-wallettransfer-parity.ts     # 33/33
npx vitest run test/fin-wallet-projection.test.ts
```

Parity runs three throwaway databases — Python-owned, TypeScript-owned and
one driven through the reverse bridge — reprojects every document twice, and
compares `fin_txn` and `fin_hook_failures` byte-exact. Routing is verified with
a counting proxy on its own port, so a delegated call cannot be miscounted.

## Not done here

- No ledger mathematics changed.
- `GET /api/fin/accounts` untouched; no account was created or normalised.
- The Python implementation remains in place as the rollback path.
