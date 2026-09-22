# Phase 6 — Slice 2c, step 6: the vendor reverse-bridge certification

Status: **all ten vendor checks GREEN. The direction flip is NOT performed —
it hits a locked-gate constraint. See "Why the flip stops here".**

Production is untouched. Reverse delegation remains OFF by default, exactly as
it was before this step.

## Why this step existed

`vendor_payment` and `vendor_bill` were the FIRST projections ported, back
when the bridge only ran forward (NestJS → Python). Every later unit was built
with the reverse bridge in place and proved it as it went. The two vendor
types never were. Their ledger mathematics are verified against 400 real
restored production documents by `scripts/fin-projection-parity.ts`, and this
step deliberately does not touch that mathematics — what it certifies is the
**direction**.

## The ten checks, and where each is proved

| # | check | where |
| --- | --- | --- |
| 1 | vendor_payment parity | `fin-vendorpay-bridge-parity.ts` — 32/32 |
| 2 | vendor_bill parity | `fin-vendorbill-bridge-parity.ts` — 34/34 |
| 3 | mixed Python/NestJS ownership | `preProject` in both, different owner per database |
| 4 | direct reproject path | `verifyRouting` routing B |
| 5 | hook path | `verifyRouting` routing A |
| 6 | replay path | `fin-vendor-replay-bridge.ts` — 18/18 |
| 7 | failure behaviour | a well-formed `ok=false` does NOT fall back |
| 8 | fallback | an unreachable NestJS falls back to the local projection |
| 9 | no-env | delegation OFF with no env, and OFF for a type not in the list |
| 10 | no duplicate rows | every document reprojected twice; two replay drains |

### Mixed ownership is measured, not argued

Each script pre-projects the OTHER half under a different owner on each of the
three databases. `fin-vendorpay-bridge-parity.ts` pre-projects `vendor_bill`
(both touch AP_VENDOR); `fin-vendorbill-bridge-parity.ts` pre-projects
`expense`, whose presence decides whether a bill projects at all. If ownership
of the dependency could change the result, these would diverge. They do not.

### The replay path needed its own script

The shared runner proves the hook and a direct `reproject_source` each delegate
exactly once. The retry driver is a **third** entry point: it calls
`reproject_source` itself and reaches the bridge through
`_bridged_reproject_source` rather than the hook's gate. A counting proxy in
front of NestJS measures "exactly once per queued row", and a second drain
proves a resolved row is never reselected and no ledger row doubles.

Queue rows are seeded directly. That is not a shortcut around a real failure —
it is precisely the state a real failure leaves behind, and it is the only way
to queue a `vendor_payment` at all, because that projection has no branch that
can fail at persist: AP_VENDOR and every mode account always resolve.

## The real bug this step found

`fin-vendorpay-bridge-parity.ts` failed on its first run. Python:

```python
narration=f"{party_type.title()} {typ} · {p.get('ref_no', '')}".strip(" ·")
```

`.get('ref_no', '')` defaults **only when the key is absent**. A key present
with value `None` interpolates as the literal text `"None"` — and survives the
strip, because "None" ends in a letter. The port used `str()`, which flattens
both cases to `""`.

```
python : Vendor payment_out · None
port   : Vendor payment_out
```

A wrong narration on a real ledger row, not a cosmetic difference. Three
instances were found and fixed, all the same shape:

- `partyPaymentLegs` — shared by **vendor, mechanic, supplier and driver**
  payments. The same fix corrects a truthy non-string `type`, which Python
  renders as `5` or `True` and compares raw, so it can never equal
  `"payment_out"` and always takes the receipt branch.
- `projectVendorBill` — `vb.get('bill_number', '')`, with no strip, so an
  absent number keeps its double space and a null renders as `None`.
- `projectCreditDebitNote` — both `note_number` and
  `invoice_number_snapshot` (slice 2c step 7).

`party_name` is deliberately NOT changed: Python uses
`vb.get("vendor_name") or ""` there, a different construct that really does
flatten both cases.

### Why 2a–2c never saw it

The real-data harness reruns clean: **936 ledger rows compared, 0 mismatches**
across 400 payments and 400 bills. No restored production document carries a
present-`None` `ref_no` or `bill_number`. The fix is corrective on the null
branch and behaviour-preserving on every real row.

## Why the flip stops here

The remaining sub-step — "switch the normal direction to Python → NestJS" —
is **not performed**, and it is not a configuration toggle.

Reverse delegation makes NestJS the writer of `fin_txn` and
`fin_hook_failures`. The locked Gate 9g artifact forbids that, as a deliberate
production guarantee:

> Node's user gets **only** `{ role: "read", db: "<DB_NAME>" }`
> — PHASE4-GATE9G-REHEARSAL.md §114

> **Python is the only business writer.** — §151

> **No data rollback is ever needed**, because Node performs no writes
> (enforced by the read-only database user). — §186

`deploy/env/backend-node.production.env.example` says the same thing in the
configuration itself.

Performing the flip would therefore require, together:

1. a new **read-write** Mongo credential for Node — a deployment and secrets
   change;
2. **reopening Gate 9g**, because its rollback guarantee is stated as a
   consequence of Node performing no writes;
3. a **production-safety** decision about who owns ledger writes.

Those are three separate stop conditions. The certification above is what
makes that decision available — it is not a substitute for it.

The forward bridge is retained, untouched. It was never a candidate for
retirement in this step: the user's own instruction is not to retire it merely
because the reverse path exists, and the reverse path is not yet the normal
direction.

## How the switch WOULD be enabled, when it is decided

Nothing here is enabled by default. All three must be set, per process:

```
TRUKVIA_FIN_NODE_URL=http://127.0.0.1:<port>/internal/fin/reproject
TRUKVIA_INTERNAL_TOKEN=<>= 32 chars, never logged>
TRUKVIA_FIN_NODE_SOURCE_TYPES=vendor_payment,vendor_bill
```

Rollback is unsetting one of them. The bridge is loopback-only, the token is
compared in constant time, and anything shorter than 32 characters fails
closed.

## Verification

```
npx tsx scripts/fin-vendorpay-bridge-parity.ts    # 32/32
npx tsx scripts/fin-vendorbill-bridge-parity.ts   # 34/34
npx tsx scripts/fin-vendor-replay-bridge.ts       # 18/18
npx tsx scripts/fin-projection-parity.ts          # 936 rows, 0 mismatches
npx tsx scripts/fin-mechanic-parity.ts            # 12/12
npx tsx scripts/fin-supplier-parity.ts            # 17/17
npx tsx scripts/fin-driver-parity.ts              # 22/22
npx vitest run                                    # 560 tests, 16 files
```
