# Phase 6 · Slice 2c, unit 9 — the `trip_customer_receipt` projection

One source type, and the **first with a prefix cascade**. Follows
[unit 8](PHASE6-SLICE2C-UNIT8-WALLET-ADJUSTMENT.md) (`d8d8197`).

## Inspection

Money received from a customer against a specific trip — advance or diesel —
**outside** the invoice flow:

```
BANK/CASH        in   (bank_debit)
CUSTOMER_ADVANCE out  (cust_adv_credit)
txn_type   trip_customer_{type}_receipt
```

It deliberately does **not** credit AR. `Invoice.total_amount` is already net
of these deductions, so crediting AR here would double-reduce it; the offset
lives in the invoice projection instead.

### The cascade, and its scope

The source document is the **trip**, and the reproject key is the trip id — but
each embedded receipt gets its own compound `source_id`, `{trip_id}:{rid}`.
Nothing would ever match an exact-match delete on the trip id, so
`reproject_source` performs a prefix delete first:

```python
if source_type == "trip_customer_receipt":
    deleted += await _delete_by_source(uid, cid, "trip_customer_receipt", f"{source_id}:*")
deleted += await _delete_by_source(uid, cid, source_type, source_id)
```

`_delete_by_source` turns the `:*` form into `{"$regex": f"^{prefix}"}` with
**no escaping**. That is reproduced deliberately — escaping would change which
rows a source id containing a regex metacharacter deletes. The filter still
carries `source_type`, so **a cascade can never reach another projection's
rows**; it is scoped to `trip_customer_receipt` alone. That is what makes this
an isolated unit rather than a coupled ownership boundary.

### Three behaviours that a naive port gets wrong

1. **The key falls back to the ORIGINAL ARRAY POSITION.** Legacy receipts carry
   no `id`, so the key becomes `idx0`, `idx1`, … Crucially, a **skipped**
   receipt does not renumber the ones after it: an array of
   `[100, 0, 50]` yields `idx0` and `idx2`. Filtering before enumerating would
   rewrite every downstream key and break idempotency on the next reproject.
2. **A bad receipt is skipped, not fatal.** A zero, negative, null, missing or
   rounds-to-zero amount drops that receipt and the rest of the array still
   projects.
3. **The receipt `type` is interpolated into both `txn_type` and `category`**,
   so the txn_type is dynamic: `trip_customer_advance_receipt`,
   `trip_customer_diesel_receipt`, and whatever else the data holds.

### Other exact semantics

- Guards are `is_historical` on the trip and an empty receipts array. There is
  **no `is_deleted` guard on the trip** — verified against the interpreter.
- Date resolution: the receipt's date, else the trip's, else `""`.
- Mode resolution is the shared `_mode_account`, defaulting to `Bank`.
- Every leg carries `party_type: "customer"`, the trip's `customer_id` and the
  `trip_id`.
- `ref_source_key` is `trip_customer_receipt:{trip}:{rid}:{leg}` — the source id
  itself contains a colon, which is what makes the 60-character `fintxn_`
  truncation actually bite on a long receipt id.

## Parity

`scripts/fin-tripreceipt-parity.ts`, three throwaway databases,
`verifyRouting` on:

```
fin_txn rows: python 78, typescript 78
checks 41   PASS 41   FAIL 0
```

Green on the first run. 39 trips, every document reprojected **twice** per
side. Explicit assertions beyond the row comparison:

```
PASS  a receipt debits the bank and credits CUSTOMER_ADVANCE
PASS  a skipped receipt does NOT renumber the ones after it
PASS  explicit ids and index fallbacks coexist at their own positions
PASS  null, missing and rounds-to-zero amounts are each skipped individually
PASS  the receipt type reaches both txn_type and category
PASS  the receipt date wins / falls back to the trip date / else empty
PASS  a historical trip projects nothing
PASS  there is NO is_deleted guard on the trip
PASS  a long receipt id truncates the generated fin_txn id at 60 characters
```

### Delegation, fallback, default-OFF and routing

Python → live NestJS matches native; a type outside
`TRUKVIA_FIN_NODE_SOURCE_TYPES` does not delegate; **no env at all** does not
delegate from either entry point; an unreachable NestJS falls back locally with
identical output; a well-formed `ok=false` does not fall back; and the hook and
`reproject_source` each delegate exactly once and land on identical rows.

## Duplicate-write verification

78 rows on both sides after projecting every trip **twice** — which for this
source type also proves the prefix cascade deletes exactly its own rows before
reinserting them.

## Bugs fixed

**None.** Parity was green on the first run.

## What is switched over

`trip_customer_receipt`, and only when Python is configured for it. The three
remaining unported types are untouched and the nine already ported keep the
directions they had. The forward bridge is not retired.

## What remains for 2c

- **Three** unported projections: `invoice` (+ the `invoice_payment` cascade),
  `wallet_recharge`, `wallet_transfer`.
- `replay_pending_failures`.
- The vendor reverse-bridge switch, then forward-bridge retirement.
- The deferred `pyStr()` fidelity question.
