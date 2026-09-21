# Phase 6 · Slice 2c, unit 1 — the canonical projection hook

The first real 2c unit. It moves the **hook layer** — what happens around a
projection, and what happens when one fails — into NestJS, and adds the reverse
Python → NestJS bridge. It does **not** move ledger maths for any new source
type, and it switches nothing over.

Follows [2a](PHASE6-SLICE2A-FINANCE-READS.md) (`6d9be00`),
[2b](PHASE6-SLICE2B-FINANCE-WRITES.md) (`ef04583`) and
[the deferred reads](PHASE6-SLICE2A2-FINANCE-DEFERRED-READS.md) (`09eafe0`).

## Inspection

Two modules own the projection:

| | |
| --- | --- |
| `backend/services_fin_txn.py` | ledger maths — 13 `project_*` functions, `_leg`, `_persist_legs`, `_delete_by_source`, `reproject_source`, `ensure_system_accounts` |
| `backend/services_fin_txn_hooks.py` | the hook — `hook_after_source_write`, the `fin_hook_failures` queue, `replay_pending_failures` |

### Flow

`hook_after_source_write(uid, cid, source_type, source_id, action="upsert")`
rejects an unsupported `source_type` up front — that is a caller mistake, not a
projection failure, so nothing is enqueued — then delegates entirely to
`reproject_source`. On success it auto-resolves any lingering failure row. On
exception it records one and returns `ok=False`. **It never raises**: the source
document is authoritative and is never rolled back by a projection problem.

`reproject_source` is delete-then-insert. It deletes by `(user_id, company_id,
source_type, source_id)`, with two prefix cascades — `invoice` also clears
`invoice_payment` legs under `{id}:*`, and `trip_customer_receipt` clears its
own `{tid}:*` — then dispatches to the per-source projector and persists.

`_persist_legs` upserts each leg on `(user_id, company_id, ref_source_key)`, so
replay is structurally idempotent; there is no in-memory dedupe cache and no
multi-document transaction (the deployment is not a replica set). `id` is
`fintxn_` + `ref_source_key` with `:` → `_`, truncated to 60 characters.
`account_id` comes from the `code_to_id` map and an unknown code raises.

### Thirteen source types, not twelve

The literal `SUPPORTED_SOURCE_TYPES` lists twelve. The bottom of
`services_fin_txn.py` then monkey-patches the module at import time:

```python
if "driver_payment" not in SUPPORTED_SOURCE_TYPES:
    SUPPORTED_SOURCE_TYPES.append("driver_payment")
reproject_source = _iter150i_reproject_source
```

so `driver_payment` is appended at the end and `reproject_source` is replaced by
a wrapper. The hook renders this list verbatim into its unsupported-type error,
so the difference is visible in a response body — which is how the parity
harness caught it rather than anyone reading the file.

### Other confirmed semantics

- **Scoping** — every query carries `user_id` and `company_id`; there is no
  cross-tenant path.
- **Accounts** — `ensure_system_accounts` returns `code → id`; money side
  resolves through `_MODE_TO_ACCOUNT`, defaulting to `BANK_DEFAULT` for any
  unknown or missing mode, with `Cash` the only `CASH` entry.
- **Legs** — every projection emits balanced `in`/`out` pairs carrying
  `counter_account_code`; `ref_source_key` is `{source_type}:{source_id}:{leg}`.
- **Amounts** — `_q2` is `round(float(x or 0), 2)`, so falsy is `0.0` and
  rounding is half-to-even on the true binary value, which
  [`src/common/py-round.ts`](../../apps/api/src/common/py-round.ts) already
  reproduces exactly. Narration truncates at 400 characters.
- **Ordering and shape** — unchanged from 2a: `mongo_id` tie-breaking and the
  per-row `source_shape` remain the read-model's business; this unit writes
  through the same upsert Python uses, so neither is affected.
- **Failure semantics** — `fin_hook_failures` holds one row per source, never
  TTL'd. Errors truncate at 2000 characters. A pending/retrying row is only
  refreshed; a resolved or permanently_failed row is **reopened** with
  `retry_count` reset to 0 and its original `id` and `created_at` kept. Backoff
  is `min(60 · 2ⁿ, 86400)` seconds, `MAX_RETRIES` 8.
- **Audit** — the projection writes none. Auditing belongs to the source writer.

### The defect this unit exists to fix

The slice-1b vendor port recorded failures in its own shape:

```
{ user_id, company_id, source_type, source_id, error, failed_at, origin }
```

`replay_pending_failures` selects on `status ∈ {pending, retrying}` and
`next_attempt_at`, then reads `row["retry_count"]`. A row without those fields
**is never selected**. So a projection that failed on the NestJS side was queued
into a table nothing drains — silently, for as long as the row existed. The same
code also never cleared a prior failure after a later success.

### Callers and current direction

Sixteen Python modules import the hook. NestJS owns vendor writes only, and its
direction today is Python-first: `hookConfigured()` → the forward bridge
(`hook-client.ts` → `POST /internal/fin/reproject` in Python), falling back to
the TypeScript port. That preference is unchanged by this unit.

## What was implemented

**`src/fin/fin-hook.ts`** — `hookAfterSourceWrite`, `recordFailure`,
`resolveFailure`, `computeNextAttempt`, `ensureHookIndexes`, and the 13-type
list. For the two TypeScript-ported source types it projects locally; for the
other eleven it delegates through the forward bridge, so the verified Python
implementation still owns them and an unreachable Python is queued as a genuine
projection failure.

**`src/fin/projection.ts`** — the failure-recording branch is gone;
`reprojectVendorSourceOrThrow` is the throwing form, so exactly one layer owns
the queue and the row cannot be double-written.

**`src/fin/internal-fin.controller.ts`** — the reverse bridge, mirroring
`backend/routers/internal_fin.py`: outside `/api`, loopback-only, constant-time
token compare, fail-closed below 32 characters, and the same two allowed source
types.

`vendor-txn-writes.service.ts` now calls the canonical hook in place of the old
recorder. Nothing else changed.

## Parity

`scripts/fin-hook-parity.ts` — two throwaway MongoDB databases, the same
scenario list driven through Python's **real** functions on one and the port on
the other, comparing every return value and every resulting document:

```
checks 33   PASS 33   FAIL 0
```

Covered: unsupported type, new failure, refresh while pending, resolve, resolve
with nothing to resolve, reopen from resolved, reopen from permanently_failed,
a successful projection auto-resolving a prior failure, 2000-character
truncation, the full backoff schedule, id and timestamp shape, and an explicit
assertion that every row carries `status`, `next_attempt_at` and `retry_count`
— the fields whose absence was the defect. Nine of the checks are the reverse
bridge over HTTP against the real Python endpoint, including a wrong token of
the same length.

### Comparison criteria, and why two are not byte-exact

`fin_hook_failures` rows are created by an upsert, and MongoDB builds the
document's first fields from the filter's equality terms. pymongo and the Node
driver hand the server that filter differently, so the four key fields land in a
different order for an identical call — and not even stably between runs:

```
py   : source_type, user_id, company_id, source_id, …
nest : source_id, source_type, company_id, user_id, …
```

Values are identical and the ten `$set` fields are in the same order on both
sides. This is the effect already documented for `fin_txn` in
`scripts/write-parity.ts`, so these documents are compared key-insensitively.
Return values stay **byte-exact**, with one exception: `recordFailure`'s refresh
branch returns `{**existing, …}`, and `existing` was read back from MongoDB, so
it carries the server-assigned order rather than anything the code chose.

## Reverse bridge status

Implemented, parity-tested, and **wired to nothing**. No Python write path calls
it. Flipping a source module to this direction is a later 2c unit and a
deliberate act.

## Results

```
scripts/fin-hook-parity.ts        33 checks, 0 failures
scripts/fin-projection-parity.ts  936 ledger rows, 0 mismatches, 0 account mismatches
scripts/write-parity.ts           76 cases, 0 failures, 1 known 2b divergence
vitest                            172 tests passing
```

## Bugs fixed

1. **Unusable failure rows** — the defect above. NestJS-recorded failures now
   have the shape Python's retry driver selects on, and a later success clears
   them.
2. **The thirteenth source type** — the port's list was built from the literal
   and was missing `driver_payment`, which the runtime monkey-patch appends.
   Visible in the hook's unsupported-type error body.

## What remains for 2c

- Eleven source projections with no TypeScript port: `invoice` (plus the
  `invoice_payment` cascade), `credit_debit_note`, `supplier_payment`,
  `mechanic_payment`, `expense`, `mechanic_work_order`,
  `trip_customer_receipt`, `wallet_recharge`, `wallet_transfer`,
  `wallet_adjustment`, `driver_payment`.
- `replay_pending_failures`, the retry driver.
- Choosing when to flip a source module onto the reverse bridge, and retiring
  the forward bridge afterwards.
- Still explicitly out of 2c scope: reconciliation, `GET /api/fin/accounts`,
  `backfill_tenant`.
