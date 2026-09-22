# Phase 6 · Slice 2c, unit 5 — the `credit_debit_note` projection

One source type, and the **first non party-payment projection**. Follows
[unit 4](PHASE6-SLICE2C-UNIT4-DRIVER-PAYMENT.md) (`b6c701e`).

## Inspection

`project_credit_debit_note` is standalone — **not** a `_party_payment_legs`
call, and not a variant of one. It has no money side at all: both legs are the
fixed pair **AR / SALES**, so no `mode` is read and no bank account is
resolved. A credit note reverses the customer's receivable; a debit note adds
to it.

| | |
| --- | --- |
| dispatcher | one `credit_debit_notes.find_one({user_id, company_id, id})` |
| cascade / paired lookup | none |
| accounts | `AR` and `SALES`, both fixed literals |
| legs | 2, always |
| CN order | `AR` out (`ar_credit`), `SALES` in (`sales_debit`), `credit_note_issue` |
| DN order | `AR` in (`ar_debit`), `SALES` out (`sales_credit`), `debit_note_issue` |
| amount | `_q2(total_amount or 0)`, must be `> 0` |
| party | `party_type="customer"`, `party_id=customer_id` |

### Five things that differ from every projection ported so far

Each was verified against the running interpreter, not inferred.

1. **The guards are `status != "issued"` and `is_historical`.** There is **no
   `is_deleted` and no `is_reversed` check** — and that is correct, not an
   oversight: neither field exists on the `CreditDebitNote` model. A withdrawn
   note carries `status: "cancelled"`, which the status guard already rejects.
   `draft` is rejected the same way.
2. **The amount field is `total_amount`**, not `amount`, and the date field is
   **`note_date`**, not `date`. A stray `amount` on the document is ignored
   entirely.
3. **`kind` selects by `== "credit"`.** A falsy kind defaults to credit; *any*
   other value — `"debit"`, `"CREDIT"`, `"weird"` — takes the debit branch.
   Crucially the `or` is PYTHON truthiness and the comparison is against the
   RAW value, so a truthy non-string (`5`, `True`, `['x']`, `{'a': 1}`) also
   takes the debit branch, while an empty list or dict is falsy and defaults to
   credit. See the bug below.
4. **The narration is NOT stripped.** Every projection before this one ends
   with `.strip(" ·")`. This one does not:

   ```python
   f"{'CN' if kind == 'credit' else 'DN'} {note_number} · Inv {invoice_number_snapshot}"
   ```

   With both references empty, Python produces exactly `"CN  · Inv "` — two
   spaces and a dangling separator. Trimming it would be a silent difference in
   a field that reaches the day-book.
5. No `trip_id`, no `vehicle_id`, no `category` on any leg.

### Everything else is unchanged

`AR` and `SALES` are both already in `FIN_SYSTEM_ACCOUNTS` (`models.py:1530`
and `:1534`) and in the TypeScript seeder, so account resolution needed no
change — which matters, because `GET /api/fin/accounts` is out of bounds.
`ref_source_key`, the `fintxn_` id rule with its 60-character truncation, the
400-character narration cap, tenant scoping, delete-then-insert and the upsert
are the shared ones.

The Iter150I wrapper passes every non-`driver_payment` type straight through to
the original `reproject_source`, so `credit_debit_note` reaches the normal
dispatcher. Both delegation layers — the hook, and the `reproject_source` layer
added in unit 4 — are generic over source type, so **no special routing was
needed**.

## Implementation

A standalone `projectCreditDebitNote` mirroring Python's standalone function,
built on the shared `leg()` factory and `q2`. Reusing `partyPaymentLegs` was
considered and rejected: the shapes genuinely differ (no mode, no bank, fixed
account pair, different guards, different field names, no strip), so forcing
them together would have meant four more option flags on a helper that three
verified projections depend on.

The dispatcher gained a `credit_debit_notes` branch; `PORTED_SOURCE_TYPES` and
the reverse-bridge allowlist gained the type. The Python env gate is unchanged
and still OFF by default.

## Parity

`scripts/fin-cdn-parity.ts`, three throwaway databases (Python native as the
reference, the NestJS port in-process, and Python **delegating to a live
NestJS**):

```
fin_txn rows: python 60, typescript 60
checks 22   PASS 22   FAIL 0
```

Every document is reprojected **twice** per side, so
delete-then-insert idempotency is part of the comparison. 41 fixtures cover
both branches, every `kind` resolution, every status value including
`"ISSUED"`, the historical guard in both directions,
zero/negative/null/missing/rounds-to-zero amounts, a stray `amount` field that
must be ignored, `2.675`, `0.125`, `0.375`, `1.005`, a numeric-string amount, a
500-character note number against the 400-character cap, unicode, missing
customer and date, and the same id under a second tenant.

Beyond the full row comparison it asserts the CN and DN leg shapes explicitly,
that a falsy kind defaults to credit while anything else goes debit, that the
narration keeps `"CN  · Inv "` intact, that only AR and SALES are touched, that
every leg is a customer leg with no trip or vehicle, and the id rule.

### Delegation, fallback and default-OFF

| | |
| --- | --- |
| Python → live NestJS | matches Python native exactly |
| type not in `TRUKVIA_FIN_NODE_SOURCE_TYPES` | does not delegate |
| **no env set at all** | does not delegate |
| NestJS unreachable | falls back locally, identical output |
| a well-formed `ok=false` | does not fall back; nothing written locally |

## Duplicate-write verification

Row counts match exactly (60 and 60) after each document is projected twice,
which is the direct check that delete-then-insert leaves no duplicates. The
per-entry-point routing counters added in unit 4 cover the two doors and remain
green there.

## Harness generalisation

`scripts/lib/party-payment-parity.ts` is now
`scripts/lib/projection-parity.ts`, and `runPartyPaymentParity` is
`runProjectionParity`. Nothing in it was ever party-payment specific — the
rename just stops the name lying now that a note reuses it unchanged. All three
party-payment runs were re-executed against the renamed module.

## Bugs fixed

**One, found by probing rather than by the harness.** The first cut resolved
the branch with `str(note['kind']) || 'credit'`. That is wrong for a truthy
NON-string kind: Python's `or` keeps the raw value and the `== "credit"` test
then fails, giving a DEBIT note — while stringifying first yields `""`, falls
back to `"credit"`, and **flips the sign of the note**. Confirmed against the
interpreter for `5`, `True`, `['x']` and `{'a': 1}`, all four of which Python
projects as `debit_note_issue`. The port now uses Python truthiness on the raw
value, which also gets the empty-list case right (falsy → credit). Four
fixtures and five unit tests were added to hold it.

The `kind` field is `Literal["credit", "debit"]` on the model, so this is not
reachable through the API — but a mis-signed ledger entry from a legacy or
imported document is not a risk worth carrying for one expression.

Two stale assertions in the unit-4 test file listed the ported and unported
source types exactly, so porting anything new broke them by design. The exact
remaining list now lives in the newest slice's tests — one place to update —
and the older file asserts the subset rule instead.

## A narrowing that was NOT fixed here, and why

The same probe showed that Python's f-string renders a non-string reference
literally: a `note_number` of `5` gives `"CN 5 · Inv I"`, and `None` gives the
literal text `"CN None · Inv I"`. The port's `str()` helper yields `""` for
both. This is **not specific to this slice** — the identical pattern is in all
four ported party payments for `ref_no`. Fixing it means a Python-faithful
`pyStr()` applied across five projections, which is outside this unit's scope,
so it is recorded rather than done. Like the `kind` case it is unreachable
through the API, because every one of these fields is typed `str` on its model.

## What is switched over

`credit_debit_note`, and only when Python is configured for it. The other seven
unported types are untouched, and the five already ported keep the directions
they had. The forward bridge is not retired.

## Results

```
scripts/fin-cdn-parity.ts          22 checks, 0 failures, 60 legs identical
scripts/fin-driver-parity.ts       22 checks, 0 failures
scripts/fin-supplier-parity.ts     17 checks, 0 failures
scripts/fin-mechanic-parity.ts     12 checks, 0 failures
scripts/fin-projection-parity.ts   936 vendor ledger rows, 0 mismatches
scripts/fin-hook-parity.ts         34 checks, 0 failures
vitest                             301 tests passing
```

## What remains for 2c

- **Seven** unported projections: `invoice` (+ the `invoice_payment` cascade),
  `expense`, `mechanic_work_order`, `trip_customer_receipt`,
  `wallet_recharge`, `wallet_transfer`, `wallet_adjustment`.
- `replay_pending_failures`, the retry driver. It calls `reproject_source`
  directly, so it delegates for an enabled type — worth knowing before turning
  one on in a live environment.
- Deciding when to switch `vendor_payment` and `vendor_bill` onto the reverse
  bridge, and retiring the forward bridge afterwards.
- Out of 2c scope: reconciliation, `GET /api/fin/accounts`, `backfill_tenant`.
