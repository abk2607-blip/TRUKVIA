# Phase 4 · Gate 9h — Node writer operations runbook

**Status: DOCUMENTATION HARD RULE — NOT A TECHNICAL CONTROL.** Nothing in this file is enforced by
any code path. See §7.

**Created:** 2026-09-23 · **Companion to:** `PHASE4-GATE9H-NODE-WRITER-DRAFT.md`, which remains
**DRAFT and NOT AUTHORIZED**. This runbook authorises nothing and opens no gate. It records only
rules and procedure that the U4 rehearsals actually established.

---

## 1. Scope

This runbook applies to Gate 9h **Node-writer activation, rollback and reprojection** operations.

Two controls are deliberately **outside** this runbook and must not be confused with it:

- **Business-write quiet window** — Gate 9h §5.5, **Option B**, a separate control. It coordinates
  business writes during the operation. It is coordination, not enforcement.
- **Node writer enable/disable** — Gate 9h **§11**, a separate control. Unsetting the reverse-bridge
  env stops Node writing; that is not what this runbook governs.

---

## 2. HARD RULE — source existence before reprojection

Reprojection is **delete-then-insert**. If the authoritative source document is absent, the delete
still happens and **nothing is inserted in its place**, so the ledger legs are destroyed rather than
repaired.

**Before any reprojection of an affected source set:**

1. **Identify the exact `source_id`s** to be reprojected. Not a source type. Not a tenant. A list.
2. **Verify the authoritative source document exists** for each `source_id`, using the mapping in
   §2.1 below, matched on `{user_id, company_id, id}` — the same triple `reproject_source` itself
   matches on.
3. **Exclude every source-less / orphan `source_id`** from the reprojection set.
4. **Escalate and report the orphan IDs** instead of reprojecting them. They are addressed only by
   the restore path (Gate 9h §5.3 step 5) or by a deliberate, recorded decision — never by
   reprojection.
5. **NEVER run a blind full-scope reprojection** merely because a source type or a tenant is
   affected.

An orphan is **not** the same thing as a reversed or voided record. A reversed or voided source
still **has** a document; it is not an orphan, and the check in step 2 passes for it.

### 2.0 Candidates and validation belong together

Proven in the Gate 9h §5.9 end-to-end rehearsal. Identification and validation are **two halves of
one step**, and neither is safe alone:

1. **Parity comparison produces the recovery candidates** — and the candidate set includes
   **pre-existing orphan discrepancies**, because a fresh Python reprojection produces no legs for a
   source that no longer exists, so every orphan shows up as a difference.
2. **Every candidate must pass source-existence validation (§2) before it is reprojected.** A
   candidate list is not a reprojection list.
3. **Orphan / source-less candidates are excluded and escalated.** In the §5.9 rehearsal, 34 of 36
   candidates were pre-existing orphans; reprojecting the list as-is would have destroyed their
   ledger legs.
4. **Source-backed candidates may be reprojected.** In that rehearsal the two source-backed
   candidates recovered byte-exact.
5. **If a residual discrepancy remains because the affected source document is absent, do NOT
   blind-reproject it.** Reprojection cannot repair it — it can only delete it.
6. **The fallback restore path is a separate recovery path** (Gate 9h §5.3 step 5) and **has NOT
   been rehearsed end to end.** A residual of this kind is where that path begins, not something to
   force through reprojection.

### 2.1 Source-type mapping

Taken from the dispatch in `backend/services_fin_txn.py` (`reproject_source`). It is not inferred.

| `source_type` | Authoritative source collection |
|---|---|
| `invoice` | `invoices` |
| `credit_debit_note` | `credit_debit_notes` |
| `supplier_payment` | `supplier_payments` |
| `vendor_payment` | `vendor_payments` |
| `mechanic_payment` | `mechanic_payments` |
| `driver_payment` | `driver_payments` |
| `expense` | `expenses` |
| `vendor_bill` | `vendor_bills` |
| `mechanic_work_order` | `mechanic_work_orders` |
| `wallet_recharge` | `wallet_recharges` |
| `wallet_transfer` | `wallet_transfers` |
| `wallet_adjustment` | `wallet_adjustments` |
| `trip_customer_receipt` | `trips` — **composite**, see below |
| `invoice_payment` | **no dispatch branch exists** — see below |

Two cases are **not** clean one-to-one lookups and must be treated under §6:

- **`trip_customer_receipt`** — `reproject_source` treats the `source_id` as the trip id, but stored
  ledger legs carry `"<trip_id>:<receipt_id>"`. The parent trip id is the prefix.
- **`invoice_payment`** — `reproject_source` has **no branch for it at all** and raises for that
  type. Its legs are produced by `project_invoice` and removed by the `"<invoice_id>:*"` cascade, so
  the parent invoice is the nearest authoritative source. **This is an interpretation, not a
  documented mapping.**

---

## 3. Detection and recovery

- **Parity is the primary check.** It is the only check that detected all four corruption shapes
  injected in the Gate 9h §5.7 rehearsal.
- **A timestamp scan alone is insufficient.** A bad write that *deletes* a ledger leg leaves no row
  behind, so there is nothing for the scan to match. In the rehearsal the timestamp scan found 3 of
  4 damaged sources, and reprojecting exactly that set left the ledger still wrong.
- **Row count can be fully masked.** A delete plus a ghost insert leaves the total unchanged. A count
  that has not moved is not evidence that nothing was written.
- **The relevant parity checks must be run as part of rollback verification** (Gate 9h §5.6 checks
  1–4, run together, parity decisive). They are not optional.

---

## 4. Reprojection is not restore

- **Reprojection is not a substitute for restore.** They are different mechanisms.
- **Restore is a separate recovery path** (Gate 9h §5.3 step 5). The restore mechanism itself was
  demonstrated on 2026-09-23 (Gate 9h §5.8).
- **Restore followed by reprojection is now VERIFIED end to end** on a disposable clone, to
  byte-exact recovery (Gate 9h §5.10, 2026-09-23).

### 4.1 Restore rolls back legitimate work too

Proven in Gate 9h §5.10:

1. **The restore is collection-level** — it replaces the whole of `fin_txn` and `fin_hook_failures`,
   not just the affected scope.
2. **Legitimate ledger activity recorded after the activation instant is rolled back with it.** This
   was observed directly, not inferred.
3. **A controlled reprojection of the legitimate, source-backed post-activation activity is therefore
   required after the restore.** The restore alone does not leave a correct ledger.
4. **The source-existence hard rule (§2) still applies** to that reprojection, and **no blind
   full-scope reprojection may be run** at any point.
5. **The U5 Option B quiet window matters here**, because it limits how much activity can occur
   during the restore-and-reprojection interval. It is **coordination, not technical enforcement**.

### 4.2 Identifying post-activation activity — `vendor_payment` ONLY

This rule covers the **first activation scope** (Gate 9h §8.1: `vendor_payment`, one tenant, one
controlled document) and **no other source type**.

After the restore, identify post-activation `vendor_payment` activity as the **union of four existing
source-side signals**, any one of which at or after the activation timestamp:

    created_at   ·   modified_at   ·   deleted_at   ·   reversed_at

1. **`modified_at` must never be used alone.** The soft-delete path writes `deleted_at` and does not
   touch `modified_at`, so a legitimate deletion would be missed.
2. **Source-existence validation (§2) remains mandatory** on the resulting candidate list.
3. **Orphan / source-less candidates are excluded and escalated**, exactly as in §2.
4. **No blind full-scope reprojection**, at any point.
5. **Keep a reversal pair together.** An amount correction marks the original payment `is_reversed`
   and inserts a fresh row carrying `reversal_of`. **Both belong in the recovery set** — the union
   above picks up both, because the original gets `reversed_at` and the fresh row `created_at` at the
   same moment.
6. **`payment_corrections` is reliable secondary evidence** for corrections and reversals
   (`payment_id`, `corrected_at`, `before`/`after`/`diff`, linked reversal/new ids).
   **`audit_logs` are secondary only and must not be the primary signal** — every audit write is
   wrapped in a swallow-all `except`, and the correction paths write no audit row at all.

**This rule does not cover the other source types.** It was established by auditing all six
ledger-affecting `vendor_payment` write paths; several other source types have no `modified_at` field
at all or never populate it. Each additional source type must be audited and given its own rule here
before it is enabled.

**Still not proven, and not to be claimed:** a **production activation-time backup** has not been
taken — the §5.10 artifact was a dump of disposable rehearsal state — an **actual Node-writer stop or
reversion** has never been executed, the **quiet window has never been exercised**, and nothing here
was executed against production.

---

## 5. Orphan-scope evidence (U4-C scan, 2026-09-23)

Measured read-only against the restored disposable backup database
`trukvia_r1restore_1790137793`, which is disposable rehearsal state, not production.

| | |
|---|---:|
| `source_type`s assessed | 11 |
| Distinct `source_id`s carrying ledger legs | 14,146 |
| Of those, with an existing authoritative source document | 2,861 |
| **Orphan / source-less `source_id`s** | **11,285 (79.8%)** |
| **Ledger legs belonging to orphan `source_id`s** | **22,638** |

Orphans were present in 9 of the 11 assessed source types.

**Observed example — `vendor_payment`.** The scan independently reproduced the figure first seen in
the §5.7 rehearsal: **34 orphan `source_id`s, 68 ledger legs, ₹25,500 one-sided value.**

**The nominal orphan amounts are NOT evidence of confirmed business loss.** The dataset contains
substantial synthetic / test-shaped data, and the cause of the orphans was not determined. The
figures establish the **scale of the hazard this rule guards against** — nothing more.

---

## 6. If the source mapping is unavailable or ambiguous — STOP

If a `source_type` has no mapping, its mapping is ambiguous, or the `source_id` shape does not match
what the mapping expects:

- **STOP.**
- **Do not guess** a collection, a parent record or an id prefix.
- **Escalate** instead, and record what was ambiguous.

`invoice_payment` and `trip_customer_receipt` (§2.1) are the two known cases that fall here today.

---

## 7. This is a documentation hard rule, not enforcement

**No write-path guard currently enforces any rule in this runbook.** `reproject_source` will still
delete existing legs and write no replacement when the source document is missing; nothing in the
code prevents a blind full-scope reprojection.

This runbook is therefore a **procedural control that depends on the operator following it**. It is
recorded as a documentation hard rule so the requirement exists and is auditable — not because the
system will stop a mistake.
