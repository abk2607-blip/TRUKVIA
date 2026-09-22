# Phase 6 — Slice 2c, step 7: narration fidelity (`pyStr`)

Status: **COMPLETE and GREEN.** The gap recorded back in unit 5 is closed, and
it turned out to be a real ledger defect rather than the cosmetic cleanup it
was filed as.

## What the gap actually was

Python builds most narrations with an f-string over `.get(key, '')`:

```python
narration=f"{party_type.title()} {typ} · {p.get('ref_no', '')}".strip(" ·")
```

The `''` default applies **only when the key is absent**. A key that is
present with value `None` is interpolated by the f-string as the literal text
`"None"`. The port used a `str()` helper that mapped `undefined` and `null`
alike to `''`, silently collapsing two different ledger rows into one:

```
python : Vendor payment_out · None
port   : Vendor payment_out
```

It is not cosmetic. `narration` is a persisted `fin_txn` column that users
read in the ledger.

## Where it was found

Not by inspection — by `scripts/fin-vendorpay-bridge-parity.ts` failing on its
first run against the real Python implementation, during the step 6 vendor
certification. That is why the fix landed in the step 6 commit for the two
vendor-path instances: they blocked step 6's own green bar.

## Every site, and its verdict

The full inventory of Python narration constructions, each checked against the
port:

| Python | construct | verdict |
| --- | --- | --- |
| `Invoice {inv.get('invoice_number','')}` | f-string | already `pyInterp` (unit 12) |
| `Receipt {p.get('reference','')} · Inv {…}` | f-string | already `pyInterp` (unit 12) |
| `{'CN'/'DN'} {note.get('note_number','')} · Inv {note.get('invoice_number_snapshot','')}` | f-string | **FIXED here** |
| `Supplier {typ} · {sp.get('ref_no','')}` | f-string | **FIXED** via the shared helper |
| `{party_type.title()} {typ} · {p.get('ref_no','')}` | f-string | **FIXED** (vendor, mechanic, driver) |
| `VendorBill {vb.get('bill_number','')} (orphan)` | f-string | **FIXED** |
| `WO {wo['id']} (orphan)` | direct index | safe — the id is the key the source was found by |
| `Trip customer {rtype} receipt` | computed | safe — `rtype` is derived, never null |
| `Wallet recharge · {wr.get('reference','')}` | f-string | already `pyInterp` (unit 10) |
| `Wallet transfer {src} → {dst}` | f-string | safe — both codes are guarded non-empty |
| `Wallet adjustment ({sign}) · {wa.get('reason','')}` | f-string | already `pyInterp` (unit 8) |
| expense: `(exp.get("narration") or exp.get("category") or "")[:400]` | `or` chain | safe — `str()` semantics are CORRECT here |

The last row is the one worth stating explicitly: an `or` chain really does
flatten `None` and `''` together, so `str()` is right there and changing it
would have introduced the bug rather than fixed it. The same applies to every
`party_name`, `vehicle_id`, `trip_id` and `category` field, all of which use
`or ""`.

## The second defect the same fix corrected

`typ = p.get("type") or "payment_out"` keeps the **raw** value, and Python then
compares that raw value to the string. The port had already coerced it with
`str()`, so:

- a numeric `type: 5` rendered as `5` in Python but `5` in the port only by
  accident of `String()`, and
- a boolean `type: true` rendered as `True` in Python and `true` in the port,
- while the branch test `typ == "payment_out"` can never match a non-string in
  Python, so such a document always takes the **receipt** branch.

The port now keeps the raw value, interpolates it with `pyInterp`, and
compares it raw.

## Why no real ledger row changed

`scripts/fin-projection-parity.ts` reruns clean over the production restore:
**936 ledger rows compared, 0 mismatches, 0 account mismatches** across 400
vendor payments and 400 vendor bills. No restored document carries a
present-`None` in any of these fields, which is exactly why slices 2a–2c never
surfaced it. The fix is corrective on the null branch and behaviour-preserving
everywhere else.

## Verification

```
npx tsx scripts/fin-vendorpay-bridge-parity.ts    # 32/32
npx tsx scripts/fin-vendorbill-bridge-parity.ts   # 34/34
npx tsx scripts/fin-cdn-parity.ts                 # 26/26, +3 null documents
npx tsx scripts/fin-mechanic-parity.ts            # 12/12
npx tsx scripts/fin-supplier-parity.ts            # 17/17
npx tsx scripts/fin-driver-parity.ts              # 22/22
npx tsx scripts/fin-projection-parity.ts          # 936 rows, 0 mismatches
npx vitest run test/fin-party-narration.test.ts   # 46 tests
```

`test/fin-party-narration.test.ts` pins the corrected behaviour for all four
party payments and for `vendor_bill`, because they share one helper and a
regression in it would otherwise be silent.

## Not done here

- No ledger mathematics changed; only the text of the narration column.
- No historical data normalised. Rows already written with the old narration
  are not rewritten — a reprojection of the source will correct them, which is
  the normal path.
- `str()` is deliberately left in place everywhere Python uses `or ""`.
