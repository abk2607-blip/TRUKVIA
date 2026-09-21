# Phase 6 · Slice 2c, unit 4 — the `driver_payment` projection

One source type. Follows [unit 3](PHASE6-SLICE2C-UNIT3-SUPPLIER-PAYMENT.md)
(`f214577`).

The ledger maths here is the smallest of the four party payments. The risk is
entirely in **how the type is reached**.

## Inspection

### The Iter150I monkey-patch

The bottom of `services_fin_txn.py` rewrites the module after defining it:

```python
if "driver_payment" not in SUPPORTED_SOURCE_TYPES:
    SUPPORTED_SOURCE_TYPES.append("driver_payment")
_iter150i_orig_reproject_source = reproject_source
async def _iter150i_reproject_source(uid, cid, source_type, source_id, *, ...):
    if source_type != "driver_payment":
        return await _iter150i_orig_reproject_source(...)
    ...
reproject_source = _iter150i_reproject_source
```

So `driver_payment` never reaches the dispatcher's if/elif chain on the Python
side — the wrapper intercepts it and does its own delete, read and persist.

**The binding was verified from the running interpreter, not reasoned about:**

```
module reproject_source : _iter150i_reproject_source
hooks-bound             : _iter150i_reproject_source
same object             : True
driver_payment in SUPPORTED_SOURCE_TYPES : True, at index 12
```

Both importers — `services_fin_txn_hooks` and `routers/fin_day_book` — use
`from services_fin_txn import reproject_source`, which binds at import time.
Because the patch runs during that module's own execution, both get the
**patched** function. There is no stale pre-patch reference anywhere.

### The projection itself

`project_driver_payment` **is** a plain `_party_payment_legs` call:

```python
_party_payment_legs(dp, ap_code="DRIVER_OUTFLOW", party_type="driver",
                    party_id_key="driver_id", src_type="driver_payment",
                    txn_type_prefix="driver")
```

No `is_historical` guard, no `trip_id` — the mechanic shape with a different
payable account. Guards are `is_deleted`, `is_reversed` and `amount <= 0` after
`_q2`. Narration is `"Driver {typ} · {ref_no}".strip(" ·")`. Leg order,
`ref_source_key` and the `fintxn_` id rule are the shared ones.

`DRIVER_OUTFLOW` is the account behind the **13-vs-14 `fin_accounts` split**
slice 2a documented. It is in the seed catalog on both sides, so projecting
into a 13-account scope seeds it — the same lazy self-healing Python performs,
not a normalisation.

### Entry points

`reproject_source` has callers that do **not** go through the hook: the admin
`POST /api/fin/reproject` bridge, and `replay_pending_failures`. The
delegation gate added in unit 2 lives inside `hook_after_source_write`, so
those callers would have kept projecting locally while the hook delegated —
one source type with two owners depending on the door used.

Nothing calls `reproject_source` with `delete_existing=False` or a pre-built
`code_to_id`; those parameters exist only in the signature and the wrapper's
pass-through.

## Implementation

**TypeScript.** `projectDriverPayment` is a five-line `partyPaymentLegs` call.
The dispatcher, `PORTED_SOURCE_TYPES` and the reverse-bridge allowlist gained
the type. Nothing else changed.

**Python.** The bridge helpers moved out of `services_fin_txn_hooks` into a new
`backend/services_fin_node_bridge.py`, because `services_fin_txn` cannot import
from the hook module without a cycle and both now need them. A second
delegation layer wraps `reproject_source`, so a type owned by NestJS is owned
from **every** entry point:

- it refuses to delegate for any non-default call shape (`delete_existing=False`
  or a supplied `code_to_id`), so a future caller keeps the local semantics;
- a transport failure falls back locally, so the ledger is never stale;
- a well-formed `ok=false` **raises**, which is exactly how a local projection
  failure signals itself, so every existing caller's error handling still
  applies.

The hook returns before ever calling `reproject_source`, so the two layers are
mutually exclusive — never both for one request. With the env unset,
`node_bridge_ready()` is `False` and both layers are straight pass-throughs.

## Routing verification

A counting HTTP proxy sits between Python and NestJS and records every bridge
call, then forwards it so rows are really written:

```
PASS  routing A: the hook delegates exactly once per call
PASS  routing A: two legs, no duplicates
PASS  routing B: the monkey-patched reproject_source delegates exactly once per call
PASS  routing B: two legs, no duplicates
PASS  routing: both entry points produce identical rows
PASS  routing: reproject_source does NOT delegate with no env set
```

Each entry point is driven twice over one document: two bridge calls, two legs,
no third call and no duplicate row. **No skipped projection, no duplicate
projection, from either door.**

## Parity

`scripts/fin-driver-parity.ts`, three throwaway databases:

```
fin_txn rows: python 58, typescript 58
checks 22   PASS 22   FAIL 0
```

Run twice end to end; both runs identical. 36 fixtures: both directions, every
mode including an unknown one, blank and missing `mode`/`type`, all guards, an
amount that rounds to zero, a numeric-string amount, `2.675`, `0.125`, `0.375`,
`1.005`, a 500-character ref against the 400-character cap, unicode, missing
`driver_id`/`date`, a `trip_id` that must be ignored, and the same id under a
second tenant.

Beyond the full row comparison it asserts the `DRIVER_OUTFLOW` leg order,
`ref_source_key` and `txn_type`; that a historical driver payment **still**
projects; that driver legs carry no `trip_id` even when the source has one; the
`fintxn_` id rule truncated at 60; and that `2.675` projects as `2.67`.

### Delegation, fallback and default-OFF

| | |
| --- | --- |
| Python → live NestJS | matches Python native exactly |
| type not in `TRUKVIA_FIN_NODE_SOURCE_TYPES` | does not delegate |
| **no env set at all** | does not delegate — from *both* entry points |
| NestJS unreachable | falls back locally, identical output |
| a well-formed `ok=false` | does not fall back; nothing written locally |

## Bugs fixed

**None in the product.** Driver parity was green on the first run.

One bug in the **harness**: the routing phase reused the bridge phase's port.
`child.kill()` on Windows kills the shell, not the node process underneath, so
`killPort` does the real work and there is a window where the old listener is
still serving — a late write from the previous phase landed in the bridge
database after the routing phase had cleared it, producing a phantom row-set
mismatch and a duplicated summary line. The routing phase now uses its own
port. Two consecutive clean runs confirm it.

That is worth recording precisely because it looked like a duplicate-write bug
in the thing under test, and was not.

## What is switched over

`driver_payment`, and only when Python is configured for it — now from both
entry points rather than one. The other eight source types are untouched, and
`vendor_payment`, `vendor_bill`, `mechanic_payment` and `supplier_payment` keep
the directions they had. The forward bridge is not retired.

## Results

```
scripts/fin-driver-parity.ts       22 checks, 0 failures, 58 legs identical (×2 runs)
scripts/fin-supplier-parity.ts     17 checks, 0 failures
scripts/fin-mechanic-parity.ts     12 checks, 0 failures
scripts/fin-projection-parity.ts   936 vendor ledger rows, 0 mismatches
scripts/fin-hook-parity.ts         34 checks, 0 failures
vitest                             259 tests passing
```

## What remains for 2c

- **Eight** unported projections: `invoice` (+ the `invoice_payment` cascade),
  `credit_debit_note`, `expense`, `mechanic_work_order`,
  `trip_customer_receipt`, `wallet_recharge`, `wallet_transfer`,
  `wallet_adjustment`. All four party payments are now done.
- `replay_pending_failures`, the retry driver. Note it calls `reproject_source`
  directly, so it now delegates for an enabled type — correct, but worth
  knowing before enabling one in a live environment.
- Deciding when to switch `vendor_payment` and `vendor_bill` onto the reverse
  bridge, and retiring the forward bridge afterwards.
- Out of 2c scope: reconciliation, `GET /api/fin/accounts`, `backfill_tenant`.
