# Phase 4 · Gate 9h — Node business-writer authorisation (DRAFT)

**Status: DRAFT — NOT A GATE RESULT.** Nothing in this document is authorised. Two parts have since
been **rehearsed, both on disposable local state only** (2026-09-23): the U4 recovery path on a
disposable clone (§5.7), which produced three corrections to the procedure, and the R1 backup restore
into a fresh disposable database (§5.8), which passed. Neither is **activation evidence**, neither
touched production, and neither authorises anything. Every other section remains unrehearsed and
unverified, and the document still contains **no activation evidence**. Preparing or updating it does
**not** authorise activating the Node writer, changing any database permission, or switching any
traffic.

Gate 9g (`6685637`) remains in force and remains **BLOCKED**. This draft is the plan that would have
to be executed, and independently verified, before Gate 9h could be opened at all.

**Prepared:** 2026-09-23 · **Author:** migration workstream · **Supersedes:** nothing
**Updated:** 2026-09-23 — U4 recovery-path rehearsal findings recorded in §5 (documentation only)

---

## 1. Purpose and scope

Gate 9h would govern exactly one transition:

> **from** "Python is the only business writer"
> **to** "Node may perform approved business writes."

**In scope:** the `fin_txn` / `fin_hook_failures` projection writes reached through the reverse
bridge (Python → Node), one source type at a time.

**Out of scope, and unchanged by this gate:**
- The frozen GET/HEAD allowlist and the Python front door (Gate 9f).
- Deferred routes — they stay with Python.
- Maker-Checker.
- Any business write that is not a ledger projection. Trips, invoices, payments and every other
  source record continue to be written by Python. **MongoDB remains the system of record.**

---

## 2. Exact changes from Gate 9g

| Aspect | Gate 9g (in force) | Gate 9h (proposed) |
|---|---|---|
| Node traffic | GET/HEAD only, frozen allowlist | unchanged, **plus** loopback `POST /internal/fin/reproject` |
| Node DB user | `{ role: "read", db: "<DB_NAME>" }` — strategy 1 | read **plus write on two named collections only** (§3) |
| Business writer | "Python is the only business writer" (§10) | Python for all source records; **Node for the ledger projection of enabled source types only** |
| Node writes observed | **0** in 1,127 profiled operations | expected **> 0** and deliberately so |
| Data rollback | "No data rollback is ever needed, because Node performs no writes" (§13.4) | **that guarantee no longer holds** — §5 replaces it |
| Kill switch | `touch /app/backend/.node-routing-kill` | unchanged for reads; writes have their own switch (§11) |

**The single most important consequence:** Gate 9g's rollback position rests entirely on Node
performing no writes. Gate 9h removes that premise, so a real data rollback plan (§5) becomes a
**precondition**, not a formality.

---

## 3. Required Node database write permission and its boundary

**NOT YET PROVISIONED — OPERATOR ACTION REQUIRED.**

The permission must be the narrowest that allows the projection to work. A broad `readWrite` role
is **not** acceptable and would fail this gate.

Proposed custom role (**NOT YET CREATED, NOT YET REHEARSED**):

```
role: nodeLedgerWriter
  read                on db "<DB_NAME>"
  insert/update/remove on "<DB_NAME>.fin_txn"
  insert/update/remove on "<DB_NAME>.fin_hook_failures"
  createIndex          on "<DB_NAME>.fin_hook_failures"   (see note)
  insert               on "<DB_NAME>.fin_accounts"          (REQUIRED — see below)
```

**Boundary — what Node must still be refused:**
- Any write to `trips`, `invoices`, `customers`, `vendors`, `expenses`, `suppliers`, `vehicles`,
  `companies`, `user_sessions`, `audit_logs`, or any other business collection.
- `fin_accounts` — **RESOLVED 2026-09-23. Node DOES require insert here.**
  `ensureSystemAccounts` (`apps/api/src/fin/projection.ts`) is a per-code find-or-insert that runs
  first in **every** projection. The discovery pass found **1,180 scopes: 857 hold 13 accounts, 323
  hold 14** — the difference is always `DRIVER_OUTFLOW`. A 13-account scope becomes 14 the moment
  it next projects, so for 857 scopes Node's first write WILL attempt an insert. The role must
  therefore carry `insert` on `fin_accounts`, scoped to that collection and nothing more.

  **The silent-failure hazard this created is now fixed.** The port had dropped Python's re-read and
  re-raise, so a refused insert was swallowed, `codeToId` still held the positionally derived id,
  and `persistLegs` wrote a ledger leg pointing at an account row that does not exist — with no
  error and no failure-queue entry. `ensureSystemAccounts` now mirrors
  `services_fin_txn.ensure_system_accounts` exactly: re-read after a failed insert, continue if the
  row is there (the benign race), **raise if it is not**. The throw happens before any delete or
  persist, so the projection is atomic and the caller records the failure.
  Evidence: `apps/api/scripts/fin-account-seed-safety.ts` — **16/16**.
- Schema/admin operations.

**Verification required (NOT YET DONE):** repeat the Gate 9g style proof in the negative direction —
show that the new user *can* write the two collections and *cannot* write a business collection
(expect code 13), mirroring how `node_ro` was proven in Gate 9g §8.

---

## 4. U2 — production `DB_NAME` verification

**STATUS: ANSWERED 2026-09-23 — the answer is YES, so U2 is BLOCKED / FAIL-CLOSED.** The operator
inspected the production `DB_NAME` privately and reported, yes/no only, that the lowercase name
**does contain the substring `prod`**. That is the whole of what was reported and the whole of what
is recorded here: **the value itself was not disclosed and does not appear anywhere in this
document.**

This resolves the *question* and does **not** resolve the *blocker*. Per step 4 of the procedure
below, a `yes` means Gate 9h stays blocked until a separately authorised change is made. **Nothing
has been changed:** the production `DB_NAME` was not renamed, no environment variable was set, no
guard was modified, and the production writer was never started.

`backend-node/src/config.ts:84` refuses to boot when:

```ts
nodeEnv === 'production' && dbName.toLowerCase().includes('prod')
```

**Procedure — no secret is printed or shared:**
1. The operator inspects the production `DB_NAME` **privately**, on the platform.
2. The operator reports **only a yes/no**: does the lowercase name contain the substring `prod`?
3. If **no** → U2 satisfied; record the answer, not the value.
4. If **yes** → Node will not boot in production at all. That requires a separately authorised
   change (either the guard or the database name), and Gate 9h stays blocked until it is resolved.

**The actual `DB_NAME` value must never appear in this document, in a commit message, in a chat
transcript, or in any log.**

---

## 5. Data rollback plan

**This section replaces Gate 9g §13.4.** The **recovery path** was rehearsed on a disposable clone on
2026-09-23 (§5.7) and three corrections came out of it, which are written into §5.2 and §5.3 below.
The **restore path (R1) was rehearsed on 2026-09-23 and passed** (§5.8). The procedure below is
therefore the corrected one, with the parts that remain unrehearsed marked as such.

### 5.1 Evidence that must exist BEFORE writer activation

| # | Requirement | Status |
|---|---|---|
| R1 | A verified, restorable backup of `fin_txn` and `fin_hook_failures`, taken immediately before activation, with its restore actually tested on a throwaway database | **VERIFIED / PASS** for the restore rehearsal (§5.8). The activation-instant backup itself has not been taken, because no activation has occurred |
| R2 | A recorded row count and a content fingerprint of both collections at the activation instant | **NOT DONE** for activation; the *method* was exercised in §5.7 |
| R3 | The exact activation timestamp, recorded to the second, so writes can be bounded by time | **NOT DONE** for activation; and §5.7 showed a timestamp alone is **not sufficient** to identify affected rows |
| R4 | Confirmation that every affected `fin_txn` row carries `projected_at` / `created_at`, so Node-era rows are identifiable | **VERIFIED** in the §5.7 rehearsal — 370/370 relevant rows carried both fields |
| R5 | A named operator who can execute the restore and has the access to do so | **ASSIGNED 2026-09-23** — the gate owner/operator. The restore itself was demonstrated in §5.8, but on a local machine against a local disposable database; whether this operator holds the production access a real restore would need is untested |

**R1 — now demonstrated.** The restore was rehearsed on 2026-09-23 and **passed**; the evidence is in
§5.8. The authoritative artifact was found on the local machine, its SHA-256 matched the previously
verified hash, and `mongorestore` completed with exit code 0 into a fresh disposable database.

R1 remains the one that cannot be skipped, and what is now proven is the **restore mechanism**, not
the activation backup: no backup has been taken at an activation instant, because no activation has
occurred. The recovery rehearsal in §5.7 still does **not** substitute for it either, because
reprojection is a different mechanism from restore — the two are now both demonstrated, separately.

R2 and R3 are recorded as *method demonstrated, activation capture not taken*. In the rehearsal a row
count and a SHA-256 content fingerprint over the affected scope proved sufficient both to detect the
injected damage and to confirm recovery, and a timestamp was recorded to the second — but no
activation-instant capture exists, because no activation has occurred.

### 5.2 How a bad Node write would be detected

Ordered by how quickly each fires:

1. **Parity comparison (primary).** Reproject a sample of the enabled source type through Python
   into a throwaway database and compare byte-exact against what Node wrote. This is the same
   method used across slice 2c; it is the only check that proves *correctness* rather than absence
   of errors.
2. **Failure queue.** A rising `fin_hook_failures` count, or rows reaching `permanently_failed`.
3. **Row-count drift.** `fin_txn` growing or shrinking against the expected leg count per source.
4. **Ledger balance check.** Debits and credits must remain equal per scope.
5. **Application errors** in the Python bridge log (`node projection bridge returned …`).

**Measured 2026-09-23 (§5.7).** Four corruption shapes were injected into a disposable clone.
**Detectors 1, 3 and 4 were exercised against them**, together with the §5.3 step 2 timestamp scan;
those are the four columns below. **Detector 2 was run and produced nothing** — no `pending` or
`retrying` rows appeared, which is what should happen, because the corruption was written straight
into `fin_txn` rather than through the hook and so never reached the failure queue; it is therefore
not evidence either way about that detector's usefulness against a real faulty writer. **Detector 5
was not tested at all**: no Node writer was running and no bridge traffic existed, so there was no
Python bridge log to inspect, and nothing below says anything about it. The result:

| Injected corruption | 1 parity | 3 row-count | 4 balance | timestamp scan (§5.3 step 2) |
|---|---|---|---|---|
| C1 — narration text altered on one leg | **detected** | missed | missed | detected |
| C2 — amount altered on one leg | **detected** | missed | detected | detected |
| C3 — one leg deleted | **detected** | detected | detected | **missed** |
| C4 — spurious extra leg inserted | **detected** | detected | detected | detected |

**Parity was the only detector that detected all four corruption scenarios.** Row-count and balance
each caught some of them, as the matrix shows; neither caught every one.

Two specific weaknesses were observed rather than assumed:

- **The row-count detector can be fully masked.** C3 and C4 together removed one row and added one
  row, so the global `fin_txn` count was **identical** before and after the corruption (28,164 both
  times). A count that has not moved is therefore **not** evidence that nothing was written.
- **Balance and count are both blind to value-neutral corruption.** C1 changed only narration text:
  the money was right, the row count was right, debits still equalled credits, and only parity saw
  it. This is the same class of defect as the narration `str()`/f-string parity defect found in slice
  2c, which is why it was chosen.

**Consequently:** parity is the **primary** detector, and detectors 1, 3 and 4 are **not optional**
during rollback verification (§5.6) — they are the minimum set, run together, with parity decisive
where they disagree.

**UNRESOLVED:** 1–4 are still manual today. Whether an automated check is required before activation
remains a decision for the gate owner; the rehearsal does not settle it, but it does show that a
manual parity run cannot be dropped in favour of the cheaper counters.

### 5.3 How affected data would be restored

The ledger is a **derived projection**, which makes rollback easier than for source data — but only
if the source records are intact.

1. **Stop the bleeding** — §11 reversion, so Python is the writer again.
2. **Identify the affected rows — by parity, not by timestamp alone.**
   The timestamp scan is the starting point: `fin_txn` rows whose `source_type` is an enabled type
   and whose `projected_at` is at or after the activation timestamp (R3). **It is not sufficient on
   its own.** A bad write that *deletes* a leg leaves no row behind, so there is nothing for the scan
   to match, and the damaged source is silently omitted from the recovery set.

   This was not theoretical: in the §5.7 rehearsal the timestamp scan found **3 of the 4** damaged
   sources, and reprojecting exactly that set left the ledger still wrong (369 legs against a
   baseline of 370, fingerprint mismatch). The missing source was found only by parity.

   **The recovery set is therefore the union of the timestamp scan and a parity comparison** against
   a fresh Python reprojection of the enabled source type. Parity is what makes missing legs
   visible; the timestamp scan only narrows the work.
3. **Preferred path — reproject, do not restore.** Because the ledger derives from Mongo source
   records that Python still owns, the clean fix is to reproject those sources through Python, which
   deletes and rewrites its own rows by `source_id`. **This is the recommended path** — but only
   within the scope restriction in step 4.
4. **Scope restriction — reproject only `source_id`s whose source document still exists.**
   Reprojection is delete-then-insert. If the authoritative source document is absent, the delete
   still happens and **nothing is inserted in its place**, so a blind reprojection *destroys* ledger
   rows rather than repairing them.

   Measured in the §5.7 rehearsal scope: **185 `source_id`s carried `vendor_payment` ledger legs, but
   only 151 source documents existed.** The remaining **34 orphaned `source_id`s account for 68
   ledger legs and ₹25,500** in that scope alone. Reprojecting them blindly would have deleted all 68
   legs with no possibility of recreating them.

   **Authoritative full-scope measurement, 2026-09-23 (U4-C).** The scan was then repeated read-only
   across **all 11 `source_type`s present** in the restored backup database (§5.8), against each
   type's authoritative source collection: **14,146 distinct `source_id`s carried ledger legs, 2,861
   had an existing source document, and 11,285 (79.8%) were orphaned, accounting for 22,638 ledger
   legs.** The `vendor_payment` figure above was independently reproduced. **The nominal orphan
   amounts are not evidence of confirmed business loss** — the dataset contains substantial
   synthetic / test-shaped data and the cause of the orphans was not determined. The rule is stated
   operationally in **`PHASE4-GATE9H-NODE-WRITER-RUNBOOK.md` §2**.

   **Rule:** before reprojecting, confirm the source document exists for each `source_id`. Orphaned
   `source_id`s are **excluded from reprojection** and escalated separately — they can only be
   addressed by restore (step 5) or by a deliberate, recorded decision, never by reprojection.

   *This is distinct from the reversed-payment observation in §5.7, which is a separate, pre-existing
   condition and not an orphan.*
5. **Fallback path — restore from backup.** Only if reprojection cannot produce a correct ledger —
   which now explicitly includes the orphaned-`source_id` case in step 4. Restore `fin_txn` and
   `fin_hook_failures` from R1 to the activation-instant state, then reproject anything written after
   it through Python, again subject to step 4. **This path was rehearsed end to end on 2026-09-23 and
   reached byte-exact recovery (§5.10).** The §5.9 rehearsal had already reached this step for real:
   an orphan-backed residual discrepancy survived a correctly scoped reprojection, so it is not
   hypothetical.

   **The restore is collection-level.** It restores the whole of `fin_txn` and `fin_hook_failures`,
   across every tenant and source type — not only the affected scope. **Legitimate ledger activity
   recorded after the activation instant therefore disappears with the restore**, which is precisely
   why the second half of this step exists. §5.10 observed this directly: the restore returned the
   ledger to the activation fingerprint, temporarily rolling back legitimate work, which was then
   reconstructed by a controlled, source-backed reprojection.

   **How "anything written after it" is identified — `vendor_payment` only.** This rule is written
   for the **first activation scope** and for no other source type. §8.1 fixes that scope to
   `vendor_payment`, one tenant, one controlled document, so this is the only rule that has to be
   right at activation. After the restore has returned `fin_txn` to the activation fingerprint:

   1. Identify post-activation `vendor_payment` activity as the **union of four existing source-side
      signals**, any one of which at or after the activation timestamp:

      - `created_at` · `modified_at` · `deleted_at` · `reversed_at`

      **`modified_at` alone is not sufficient and must never be used as the sole signal** — the soft
      delete path writes `deleted_at` and does not touch `modified_at`.
   2. Apply the **existing source-existence validation** (step 4) to that list.
   3. **Reproject only the source-backed** candidates. Orphaned `source_id`s stay excluded and
      reported, exactly as in step 4.
   4. **Keep a reversal together as a pair.** An amount correction marks the original payment
      `is_reversed` and inserts a fresh row carrying `reversal_of`. **Both must be in the recovery
      set**; the union above picks up both, because the original gets `reversed_at` and the fresh row
      gets `created_at` at the same moment.
   5. Use **`payment_corrections`** as **secondary** evidence for corrections and reversals — it
      carries `payment_id`, `corrected_at`, `before`/`after`/`diff` and the linked reversal/new ids.
      `audit_logs` are **secondary only** and must not be relied on as the primary signal: every
      audit write is wrapped in a swallow-all `except`, and the correction paths write no audit row
      at all.
   6. **Verify** by fingerprint and parity, per §5.6.

   **This is a procedure, not a technical control.** Nothing enforces it.

   **Scope of the evidence.** The four signals were established by a read-only audit of all **six**
   ledger-affecting `vendor_payment` write paths against the restored backup, and every path was
   found to carry at least one of them, with each signal present on 100% of the documents in the
   state that path produces. **That result is specific to `vendor_payment`.** It is **not** valid for
   `mechanic_payment` and **not** valid for the remaining source types — several of them have no
   `modified_at` field at all, or never populate it. **Before any other source type is enabled, its
   own signals must be audited and a rule for it recorded here.**
6. **Never** restore business/source collections from this backup — they were never at risk, and
   restoring them would destroy legitimate operator work done since activation.

### 5.4 Who performs rollback

| Action | Who |
|---|---|
| Decide to roll back | Gate owner / product owner |
| Unset the writer env (reversion) | Operator — **platform action** |
| Reproject through Python | Operator, using the existing replay CLI |
| Restore from backup | Operator with database credentials — **platform action** |
| Verify the result | Migration workstream, using parity comparison |

**No automated or agent-initiated rollback.** Every step is deliberate and operator-run.

### 5.5 Pausing business writes during rollback

**DECIDED 2026-09-23 — Option B, the declared quiet window.** This is the U5 policy.

This section governs the coordination of **business writes** during the affected-window operation.
Enabling or disabling the **Node writer** is a different control and remains §11; the two must not be
conflated.

- **Option B — declared quiet window. SELECTED.** Perform the operation when no operator is entering
  data for the affected scope. It relies on coordination rather than enforcement.
- **Option A — day closing. NOT SELECTED**, because its premise does not hold. The existing
  day-closure mechanism is **not** a data-entry or write lock: `FinDayClosure` records a financial
  checkpoint, and its own definition states that any past business date remains enterable across
  every canonical source type after that day has been closed. No canonical write path consults
  `fin_day_closures` — only the day-closing router itself and reconciliation reporting. Closing a day
  would record a checkpoint without pausing anything, and making it enforce would require a new
  control in every write path, which this gate does not introduce.

**What Option B does and does not provide.** It is coordination, **not technical enforcement**.
Nothing in the system rejects a write during the window; a write made during it is still accepted and
projected normally. What the window buys is a *verifiable* before-and-after state for §5.6.

**The declared quiet-window procedure**, at the level the §5.7 rehearsal established and no further:

1. The named operator (R5) **declares the window**, recording its start and end.
2. The window is **scoped** to the affected tenant and the enabled source type, not the whole system.
   Under §8.1 the first activation is one source type, one tenant and one deliberately reprojected
   document, so the window is correspondingly small.
3. A **row count and content fingerprint are taken before and after** the window over the affected
   scope, as in §5.7.
4. **Parity verification** is run per §5.6, with checks 1–4 together and parity decisive.
5. Any **legitimate activity that did occur** during the window is identified and accounted for in
   that verification — §5.6 check 3 already requires counts to be read "adjusted for legitimate
   activity since". Unaccounted movement means the verification is incomplete, not that the data is
   necessarily wrong.

**Not yet exercised.** No quiet window has ever been declared. The §5.7 rehearsal ran on a disposable
clone with no concurrent operators, so the coordination itself is untested and §13 E11 remains
outstanding on that basis. The policy is recorded here **before** activation, rather than improvised
during an incident, which is what this section always required.

### 5.6 How rollback success is verified

1. Byte-exact parity between the restored ledger and a fresh Python reprojection of the same sources.
2. `fin_hook_failures` holds no `pending` or `retrying` rows for the affected scope.
3. Row counts match R2, adjusted for legitimate activity since.
4. Debits equal credits per scope.
5. A spot check of at least one real invoice/statement in the UI by a business user.

Per §5.2, checks 1–4 are run **together**, not as alternatives, and check 1 is decisive. A passing
count or balance with a failing parity means the recovery is not complete.

**Rehearsal result (§5.7), disposable clone, 2026-09-23:**

| # | Result |
|---|---|
| 1 | **PASS — byte-exact.** Post-recovery fingerprint `sha256 709595a3…c53fa` was identical to the pre-drill fingerprint |
| 2 | **PASS** — 0 `pending` / `retrying` rows |
| 3 | **PASS** — 370 legs in scope, 28,164 rows globally, both matching the pre-drill capture |
| 4 | **PASS** — 177,550.0 in / 177,550.0 out |
| 5 | **NOT EXECUTED** — requires a human and a running application; neither was in scope for the rehearsal |

Byte-exact recovery was reached **only after the complete required reprojection set had been
identified** by the corrected procedure in §5.3 step 2 (timestamp scan ∪ parity), restricted to
source-backed `source_id`s per step 4. The first attempt, following the previous
timestamp-only wording, did not recover the ledger.

### 5.7 U4 rehearsal — 2026-09-23, disposable clone only

**Scope of the exercise.** A disposable clone of the local validation database (58 collections,
956,097 documents, 117 indexes, verified equal to its source) was created for this purpose and
dropped afterwards. One tenant scope was used: 185 `vendor_payment` `source_id`s carrying 370 ledger
legs. Four corruption shapes (§5.2) were injected, detectors 1–4 were run against them (detector 5
was not — see §5.2), the §5.3 procedure was executed, and recovery was verified against §5.6.

**What was executed:**

- Pre-drill evidence capture (row counts, SHA-256 content fingerprint, timestamp to the second).
- R4 confirmation — 370/370 rows carried both `projected_at` and `created_at`.
- Controlled corruption, detection, reprojection-based recovery, and §5.6 verification.
- A pre-corruption parity baseline: **300 of 302 legs on source-backed `source_id`s were byte-identical
  between the existing ledger rows and a fresh Python reprojection**, with zero field-level
  differences.

**What was NOT executed, and must not be read as done:**

- **R1 backup restore** — not attempted during *this* rehearsal: the artifact had not yet been located
  on the machine. It was found and the restore was rehearsed separately later the same day; that is
  recorded in §5.8, not here.
- **§5.6 check 5** — no UI spot check by a business user.
- **A live writer reversion.** §11 step 1 was exercised only at the guard level: the `apps/api`
  Finance-writer authorisation check was shown to refuse startup when the authorisation is unset or
  points elsewhere. **No writer process was started, stopped or reverted**, so E9 (§13) is *not*
  satisfied by this rehearsal.
- Nothing in production was contacted, read or written, and the local validation database was
  confirmed unchanged afterwards.

**Separate pre-existing observation — reversed `vendor_payment` stale legs.** One `vendor_payment`
carrying `is_reversed: true` still had an active pair of ledger legs (₹3,000) that Python's own
projection would not produce, because `_party_payment_legs` returns no legs for a reversed payment.
Of 143 reversed `vendor_payment` records in the clone, this was the **only** one affected. This is a
pre-existing data condition, **not** a Node-writer risk and **not** an orphaned `source_id` —
reprojection *corrects* it rather than damaging it. It is recorded here so it is not confused with
the orphan finding in §5.3 step 4, which has the opposite consequence.

**Remaining U4 prerequisites.** U4 cannot move past PARTIAL until all of the following exist:

| # | Prerequisite | Status |
|---|---|---|
| U4-a | R1 backup-restore rehearsal, on a throwaway database, with the artifact's checksum verified | **VERIFIED 2026-09-23** (§5.8) — checksum matched, restore exit code 0 |
| U4-b | The corrected parity-based recovery identification procedure (§5.3 step 2) adopted and rehearsed end-to-end | **PARTIAL — not GREEN.** Rehearsed once end to end on 2026-09-23 (§5.9): timestamp scan ∪ parity found all three injected changes where timestamp-only missed one, source-existence filtering excluded 34 orphan candidates, and the source-backed damage recovered byte-exact. **Step 5 is now VERIFIED** on two counts: the **restore → reproject mechanism** (§5.10, 2026-09-23, byte-exact, 0 residual differences), and the **recovery-identification method for the first activation scope** — a six-path read-only audit established the `vendor_payment` signal set now recorded in §5.3 step 5. **Still not complete**: step 1 verified the post-reversion state rather than executing a reversion (**E9 pending**), §5.6 check 5 was not executed, the activation-time production backup remains a separate outstanding requirement (E4/R1), and **the identification rule is verified for `vendor_payment` only** — every other source type remains unverified unless separately audited. U4-B therefore stays **PARTIAL** |
| U4-c | The source-existence scope restriction for reprojection (§5.3 step 4) adopted as a hard rule in the runbook | **PARTIAL — not GREEN.** The authoritative orphan-scope measurement is **complete** (§5.3 step 4, 11 source types, 11,285 orphaned `source_id`s over 22,638 legs), and the rule is now captured in the runbook artifact **`docs/migration/PHASE4-GATE9H-NODE-WRITER-RUNBOOK.md` §2**. **The rule has since been exercised** on disposable-clone rehearsals — §5.9 and §5.10 each generated parity candidates, applied source-existence filtering, and excluded and reported 34 orphan candidates rather than reprojecting them. It remains a **documentation-level hard rule only: no write-path guard enforces it**, so it depends on the operator following it. It stays **PARTIAL** until the acceptance wording above is satisfied outside a rehearsal |
| U4-d | The §5.5 write-pause / reversion decision (Option A or B) taken and written in | **DECIDED 2026-09-23 — Option B** (§5.5); the window has not been exercised |

### 5.8 R1 backup-restore rehearsal — 2026-09-23, PASS

**Result: the restore works.** This closes U4-a. It does not close U4 (§5.7).

**Artifact.** The exact expected artifact was found on the local machine — two byte-identical copies,
56,723,720 bytes each — and its **SHA-256 matched the previously verified hash**. It is a genuine
`mongodump --archive --gzip` stream (mongodump 100.18.0, server 7.0.43). **The artifact itself was
opened read-only and was not modified.**

**Tooling.** `mongorestore` was not installed on the machine: the MongoDB Server 7.0 installation
ships only `mongod`, and the Database Tools are a separate package. The official MongoDB Database
Tools 100.9.4 were therefore used in **portable form, extracted into a scratchpad directory**. Nothing
was installed: **no system, registry, PATH or repository modification was made by that tooling**, and
the directory can simply be deleted. This matters for R1 because the requirement is that an operator
can restore the backup with standard tooling — a bespoke reader would not have demonstrated that.

**Restore.**

| | |
|---|---|
| Target | `trukvia_r1restore_1790137793` — a **fresh disposable database**, created for this rehearsal. **Disposable rehearsal state, not production.** |
| Namespace mapping | `--nsFrom`/`--nsTo`, so no local database was ever created under the production database name |
| `mongorestore` exit code | **0** |
| Reported | **960,150 document(s) restored successfully. 0 document(s) failed to restore.** |
| Restored | **62 collections**, **181 indexes** |

**The `save_health` count difference — TTL expiry, not a restore failure.** The restore reported
960,150 objects; a live count immediately afterwards gave **957,190**. The **2,960** difference was
isolated to **exactly one collection, `save_health`** (log 8,855, live 5,895); the other 61
collections agreed with the log exactly. `save_health` carries a TTL index `save_health_ttl` with
**`expireAfterSeconds` = 1,209,600 (14 days)**, measured directly on the restored collection, and the
backup predates the rehearsal, so MongoDB's TTL monitor removed the aged telemetry rows once they
were written. The documents were restored correctly and then expired by design. **This explanation
applies to `save_health` only and is not generalised to any other collection.**

For the collections R1 exists to protect — `fin_txn`, `fin_hook_failures` and `fin_accounts` —
**no TTL index exists**, so they restore without this effect.

**The backup is authoritative for this rehearsal; the local validation database is NOT a complete
copy of it.** Measured, side by side:

| | Restored from backup | Local validation DB |
|---|---|---|
| Collections | **62** | 58 |
| `fin_txn` | **28,360** | 28,164 |
| `fin_accounts` | **15,887** | 15,663 |
| `trips` | **117,632** | 116,867 |
| `vendor_payments` | 2,040 | 2,040 |

Four collections present in the restore are **absent from the validation database**:
`fin_hook_failures`, `fuel`, `saved_trip_filters`, `team_members`.

**These differences are not restore failures** — the restore reported zero failures. They mean only
that the validation database is a partial copy. **Why it is partial was not measured and is not
inferred here.** The consequence for this gate is narrow but real: **validation-database counts are
not a proxy for the authoritative backup**, and any count taken as backup evidence must come from a
restore of the artifact, not from the validation database.

**Isolation.** Production was **not accessed** — no connection, no read, no write, and the artifact
was not fetched from it. No local database was created under the production database name. The local
validation database was confirmed unchanged afterwards (58 collections, 956,097 documents, `fin_txn`
28,164, `fin_accounts` 15,663, `vendor_payments` 2,040 — all matching its pre-rehearsal baseline). The
U4 corruption/recovery drill was **not** re-run.

**What this does and does not establish.** It establishes that the named artifact is intact and
restorable with standard tooling into a clean database. It does **not** establish that a backup has
been taken at an activation instant (R2/R3 remain as recorded), that the assigned operator holds the
production access a real restore would require (R5), or that the §5.3 step 5 fallback path —
restore followed by reprojection — works end to end. *(That last one was rehearsed separately the
same day and is now VERIFIED; see §5.10.)* **U4 remains PARTIAL.**

### 5.9 U4-B end-to-end rehearsal — 2026-09-23, disposable clone only, PARTIAL

**Result: the corrected identification procedure works. U4-B stays PARTIAL, not GREEN.** The §5.3
sequence was run once, end to end, exactly as written above.

**Scope.** A fresh disposable clone, `trukvia_u4b_1790141306`, taken from the restored backup
database (§5.8), which was left unchanged. Test scope: **`mechanic_payment`, one tenant** — the
smallest scope in the data containing both source-backed and orphaned `source_id`s, and deliberately
not the §5.7 scope.

| | |
|---|---:|
| `source_id`s in scope | 63 — **29 source-backed, 34 orphan** |
| Ledger legs | 126 |
| Pre-rehearsal fingerprint | `sha256 00cc600c…82d1` |
| Activation instant (R3) | 2026-09-23T05:29:30+00:00 |

**Simulated bad writes, three shapes:** **D1** a source-backed leg deleted · **D2** a source-backed
amount changed · **D3** a narration changed on an **orphan** source. D2 and D3 were stamped at the
activation instant; D1, being a deletion, leaves no row to stamp.

**§5.3 steps, as executed:**

| Step | Result |
|---|---|
| 1 — stop the bleeding | `node_bridge_ready` returned **False**, so Python was the writer. **No writer process was running, so no actual stop or reversion was executed** — this verified the post-reversion state only. **E9 remains pending.** |
| 2 — identify (timestamp ∪ parity) | timestamp scan **2** (D2, D3) · parity **36** · **union 36**. Timestamp-only would have **missed D1** entirely |
| 3 / 4 — reproject, source-existence restricted | 36 candidates → **2 source-backed reprojected (D1, D2)**, **34 orphan candidates excluded and reported**. **D3 was among the excluded orphans.** No blind full-scope reprojection was run |
| 5 — fallback restore | **Required by the resulting state, and NOT rehearsed.** After reprojection the fingerprint differed from the baseline; the **residual discrepancy was exactly D3** |
| 6 — never restore business/source collections | `mechanic_payments` **463 → 463, unchanged** |

**§5.6 verification:** checks **1–4 passed** (parity byte-exact across the source-backed ids,
`fin_hook_failures` 0 pending, 126/126 legs, debits equal credits). **Check 5, the UI spot check, was
NOT executed** — it needs a human and a running application.

**What this rehearsal established.**

- The corrected identification principle works **in practice**, not only on paper: **timestamp scan
  ∪ parity, followed by source-existence filtering.**
- **Timestamp-only identification is insufficient** — D1 was missed, exactly as §5.3 step 2 predicts.
- **Parity was the only detector** that found all three injected changes, and it also surfaced the
  pre-existing discrepancies in the scope.
- **Source-existence filtering prevented 34 pre-existing orphan candidates from being blindly
  reprojected.**
- **Steps 2 and 4 must be understood together:** parity *generates* candidates; source-existence
  validation *determines which candidates are safe to reproject*. Neither is sufficient alone.
- **An orphan-backed residual discrepancy is not repaired by source-backed reprojection alone.**
  When such a residual remains, the documented fallback restore path may be required — and
  **restore followed by reprojection remains unrehearsed end to end.**

**Why U4-B was PARTIAL after this rehearsal:** step 1 verified a state rather than executing a
reversion (E9 pending), step 5 was not executed **in this run — it was rehearsed separately the same
day and is now VERIFIED (§5.10)** — and §5.6 check 5 was not executed. U4-B **remains PARTIAL**, now
on the strength of E9 and check 5 alone.

### 5.10 U4-B step 5 — restore → reproject, 2026-09-23, VERIFIED

**Result: §5.3 step 5 works end to end and reached byte-exact recovery.** This closes the step 5 gap
left open by §5.9. It does **not** make U4-B GREEN or U4 GREEN.

**Environment.** A fresh disposable clone, `trukvia_u4b5_1790142411`, taken from the restored backup
database (§5.8), which was not written to. Scope: **`mechanic_payment`, one tenant** — **63
`source_id`s (29 source-backed, 34 orphan), 126 ledger legs**, baseline fingerprint
`sha256 00cc600c…82d1`. **Activation instant: 2026-09-23T05:48:36+00:00.**

**The R1 artifact for this rehearsal** was created with `mongodump` against the disposable clone at
the activation instant, scoped to **`fin_txn` (28,360 documents) and `fin_hook_failures` (0)** — the
two collections step 5 names, and nothing else. **It is a backup of disposable rehearsal state, not
of production.**

**Conditions after the activation instant.** One **legitimate** business change (a source-backed
`mechanic_payment` amount, reprojected by Python, the sanctioned writer), plus three simulated bad
writes: **D1** a source-backed leg deleted · **D2** a source-backed amount changed · **D3** a
narration changed on an **orphan** source.

**Steps 2–4.** Timestamp candidates **3** (D2, D3 and the legitimate activity) · parity candidates
**36** · **union 37**. Source-existence filtering reprojected **3 source-backed** candidates and
**excluded and reported 34 orphan** candidates. The **residual discrepancy after source-backed
reprojection was exactly the orphan D3**, which triggered step 5.

**Step 5, as executed.**

| | |
|---|---|
| Restore | `mongorestore` of `fin_txn` + `fin_hook_failures` from the rehearsal R1 artifact — **exit code 0, 28,360 documents restored, 0 failed** |
| Post-restore state | Returned to the activation fingerprint **`00cc600c…82d1`**. The orphan damage was undone; **the legitimate post-activation activity was temporarily rolled back with it** |
| Identify post-activation work | `modified_at >= activation instant` on the source collection found **exactly the one legitimate source** |
| Source-existence check | **Passed** — 1 source-backed, 0 orphan |
| Reproject | The legitimate source only. **No blind full-scope reprojection was run** |
| Final fingerprint | **`6de1facd0a79a4c68f500176bb02a05a9a0b6151713cae870cd02905b3941048`** — **exactly the expected value** |
| Residual differences | **0** |
| Business collection | `mechanic_payments` **463 → 463, unchanged** (step 6 held) |

**§5.6 verification:** checks **1–4 PASS** (parity byte-exact across source-backed ids,
`fin_hook_failures` 0 pending, 126/126 legs and 28,360/28,360 rows, debits equal credits
86,700.0 / 86,700.0). **Check 5, the UI spot check, was NOT executed** — it requires a human and a
running application.

**The 34 orphan `source_id`s remained excluded and reported throughout** and were not reprojected at
any point. Their nominal amounts are **not** evidence of confirmed business loss.

#### What this does and does not prove

- It **proves the restore → reproject mechanism** on a disposable clone, end to end, to byte-exact
  recovery.
- It does **not** prove that a **production activation-time backup has been taken**. The artifact
  used here was a dump of disposable rehearsal state. **E4's activation-time-backup half remains
  outstanding.**
- **E9 remains pending** — no Node-writer stop or reversion was executed at any point.
- **E11 remains pending** — the declared quiet window was not exercised.
- **U4 overall remains PARTIAL.**

#### Two operational findings

**A. Restore scope is collection-level, so legitimate work disappears with it.** The tested restore
replaces the whole of `fin_txn` and `fin_hook_failures`, not the affected scope. Legitimate ledger
activity recorded after the activation instant is therefore rolled back, and **the restore must be
followed by a controlled reprojection of the legitimate, source-backed post-activation activity** —
the second half of §5.3 step 5 is not optional. The **U5 Option B quiet window is operationally
important here**, because it limits how much activity can occur during the restore/reprojection
interval. It is **coordination, not technical enforcement**.

**B. A timestamp scan cannot tell legitimate activity from bad writes.** In this rehearsal the scan
returned the legitimate Python activity alongside D2 and D3. **A timestamp scan generates candidates;
it does not by itself establish that a candidate is bad Node activity.** Parity and source-existence
filtering remain necessary. No method for distinguishing legitimate from bad activity beyond this was
rehearsed, and none is claimed.

**The identification rule has since been settled for the first activation scope, and `modified_at`
is not it.** A read-only audit of all six ledger-affecting `vendor_payment` write paths established
that the criterion used in this rehearsal is **insufficient on its own**: the soft-delete path writes
`deleted_at` and never touches `modified_at`, so a legitimate deletion after activation would be
missed entirely. §5.3 step 5 now carries the corrected rule — the union of `created_at`,
`modified_at`, `deleted_at` and `reversed_at` — **scoped to `vendor_payment`, which §8.1 makes the
first activation scope**. It is **not** generalised to `mechanic_payment` or to any other source
type; several of those have no `modified_at` field at all.

---

## 6. Writer activation sequence

**NOT YET EXECUTED. Each step requires its predecessor to be green and recorded.**

| Step | Action | Owner |
|---|---|---|
| 1 | Gate owner records the decision to allow Node business writes | Gate owner |
| 2 | U2 answered (§4) | Operator |
| 3 | `fin_accounts` question settled (§3) | Migration workstream + gate owner |
| 4 | Backup taken and **restore tested** (R1), fingerprints recorded (R2) | Operator |
| 5 | `nodeLedgerWriter` role created; boundary proof run (§3) | Operator |
| 6 | Node restarted with the new credential; `/health/ready` 200 | Operator |
| 7 | Pre-write smoke checks (§7) all green | Migration workstream |
| 8 | Activation timestamp recorded (R3) | Operator |
| 9 | Reverse delegation enabled for **ONE** source type (§8) | Operator |
| 10 | First-write controls observed (§8) | Migration workstream |
| 11 | Repeat 9–10 per source type, one at a time | — |
| 12 | Only after all enabled types are green: consider retiring the forward bridge | Gate owner |

Steps 9–11 are deliberately incremental. **Enabling all thirteen source types at once is explicitly
forbidden by this gate.**

---

## 7. Pre-write smoke / health checks

To be run **after** the credential change and **before** the first delegated write:

| # | Check | Expected |
|---|---|---|
| S1 | `GET /health/ready` on Node | 200, `"routes":"ok"` |
| S2 | `GET /api/auth/health` on Python | 200, `db: up` |
| S3 | Node can write `fin_txn` in a throwaway scope | succeeds |
| S4 | Node **cannot** write a business collection | refused, code 13 |
| S4b | A refused `fin_accounts` creation **fails the projection** and writes **no** `fin_txn` row | throws; 0 ledger rows; 1 `fin_hook_failures` row |
| S5 | Reverse bridge env is still **off** | `node_bridge_ready()` false for every type |
| S6 | Forward bridge still reachable | Python→Node internal hook answers |
| S7 | Failure queue is empty for the target scope | 0 pending / retrying |

S4 is the boundary proof. **If S4 does not refuse, stop — the role is too broad.**

S4b is the safety proof. It is already demonstrated in the code path by
`scripts/fin-account-seed-safety.ts` (16/16, cases C and D); at activation it must be re-run against
the **real role**, because that is the first time the refusal comes from MongoDB rather than from a
test constraint.

---

## 8. First-write controls

### 8.1 Smallest possible scope

- **One source type.** `vendor_payment` is the recommended first, because its reverse-bridge
  behaviour is the most heavily certified and it has no branch that can fail at persist.
- **One tenant**, if `TRUKVIA_FIN_NODE_SOURCE_TYPES` can be scoped that way — **NOT VERIFIED**;
  the env gate is per source type, not per tenant. If it cannot, the first write must instead be a
  single deliberate reprojection of one known document, performed by the operator.
- **One document**, reprojected deliberately rather than by waiting for organic traffic.

### 8.2 Success criteria

| # | Criterion |
|---|---|
| C1 | The ledger rows Node wrote are **byte-exact** against a Python reprojection of the same document into a throwaway database |
| C2 | Exactly the expected number of legs; no duplicates |
| C3 | `fin_txn` ids follow the `ref_source_key` rule |
| C4 | No new `fin_hook_failures` row |
| C5 | Debits equal credits for the affected scope |
| C6 | A business user confirms the corresponding invoice/statement still reads correctly in the UI |

C6 matters as much as C1. **The project's stated priority is that the app works after Node takes
over, not merely that the rows match.**

### 8.3 Stop conditions — abort immediately if any occurs

- Any parity mismatch, however small.
- Any duplicate ledger row.
- Any unexpected `fin_hook_failures` row.
- Any write to a collection outside the two named in §3.
- Any error in the Python bridge log that is not a clean `ok: true`.
- Any business user reporting a wrong figure.

---

## 9. Audit and reconciliation requirements

| # | Requirement | Status |
|---|---|---|
| A1 | Every Node-written `fin_txn` row is attributable to a writer | **NOT AVAILABLE, and NOT an activation blocker.** Verified 2026-09-23: `fin_txn` carries 32 fields and **none** identifies the writer. Timestamps are **not** a substitute — `persistLegs` upserts with `$set`, so `created_at` is rewritten on every reprojection; a Python reprojection after activation looks Node-era and the reverse is equally possible. Deferred as forensic/audit hardening (see below). |
| A2 | The activation, each source type enablement, and any reversion are recorded with timestamp and operator | **NOT DONE** |
| A3 | Parity evidence retained per source type | Method exists (slice 2c harnesses); retention **NOT DEFINED** |
| A4 | Day-book and ledger reports reconcile before and after activation | **NOT DONE** |

**A1 is a real gap, deliberately accepted for now.** Rollback does not depend on it, because the
recovery set is determined by parity and by source existence, not by which process wrote a row — so
reprojection still needs no per-row attribution. **But it cannot be applied blindly to an entire
scope.** Per §5.3 step 4, the `source_id`s being reprojected must first be confirmed to have an
authoritative source document; orphaned, source-less `source_id`s are excluded, because reprojecting
them deletes their legs without recreating them. Within that restriction, reversion plus a Python
reprojection of the source-backed `source_id`s repairs the affected rows without needing to tell
individual rows apart. What it costs is *forensics* — "which rows did Node write?" cannot be
answered.

**Decision 2026-09-23: the writer marker is NOT a Gate 9h activation blocker.** It is recorded as
future hardening. The smallest design, if it is ever wanted, is one optional field
`written_by: 'python' | 'node'` set in `persistLegs` / `_persist_legs`: additive, no index, no
read-path change, and its absence on historical rows would itself mean "pre-Gate-9h". **Not
implemented, and out of scope for this gate.**

---

## 10. Failure handling and abort criteria

**Abort the gate — return to Python-only writing — if any of these is true:**

1. Any §8.3 stop condition fires.
2. The boundary proof (S4) fails.
3. The backup restore (R1) cannot be demonstrated.
4. U2 cannot be answered.
5. The `fin_accounts` question (§3) is unresolved at activation time.
6. A business user reports any figure that does not match expectation.

**Abort is the default response to ambiguity.** A partially understood failure is an abort, not an
investigation with the writer left running.

---

## 11. Reversion path back to Python-only writing

Reversion is deliberately cheap, and that is the main safety property of this design.

| Step | Action | Effect |
|---|---|---|
| 1 | Unset `TRUKVIA_FIN_NODE_SOURCE_TYPES` (or remove the affected type) | `node_bridge_ready()` returns false; Python projects locally again, immediately |
| 2 | Optionally unset `TRUKVIA_FIN_NODE_URL` | Belt and braces |
| 3 | Restart the Python process if the env is file-based | Picks up the change |
| 4 | Reproject the affected sources through Python | Ledger is rewritten by the reference implementation |
| 5 | Optionally revoke the Node write role | Restores the Gate 9g database-level guarantee |

**Step 1 alone stops all Node writes.** It needs no code change and no deployment.

Step 5 is what actually restores Gate 9g's position; until it is done, the read-only guarantee is
weakened even if no writes are occurring.

---

## 12. Operator/platform actions versus code actions

| Action | Type | Status |
|---|---|---|
| Create `nodeLedgerWriter` role | **PLATFORM** | NOT DONE |
| Provision the credential into Node's env | **PLATFORM** | NOT DONE |
| Verify production `DB_NAME` (U2) | **PLATFORM** | NOT DONE |
| Backup + tested restore | **PLATFORM** | **RESTORE TESTED 2026-09-23** (§5.8) — checksum matched, `mongorestore` exit 0 into a fresh disposable database. The **activation-instant backup itself is still NOT TAKEN**, because no activation has occurred |
| Recovery-path rehearsal (reprojection) | **CODE / workstream** | **DONE 2026-09-23** on a disposable clone — byte-exact recovery, and three procedure corrections (§5.7). Does **not** satisfy the restore requirement above |
| Set / unset reverse-bridge env | **PLATFORM** | NOT DONE |
| Restart Node / Python | **PLATFORM** | NOT DONE |
| Parity verification per source type | **CODE / workstream** | method exists, not run against production data |
| Boundary proof S3/S4 against the real role | **CODE / workstream** | **NOT WRITTEN** — needs the role to exist first |
| Safety proof S4b (refused creation writes no ledger row) | **CODE / workstream** | **DONE** — `scripts/fin-account-seed-safety.ts`, 16/16, commit `10b0e82`. Must be re-run against the real role at activation. |
| Resolve the `fin_accounts` question | **CODE / workstream** | **DONE 2026-09-23** — Node requires `insert`; see §3 |
| Decide the write-pause mechanism (§5.5) | **GATE OWNER** | **DECIDED 2026-09-23 — Option B, declared quiet window.** Coordination only, no enforcement; never exercised |
| Decide whether a writer marker is required (A1) | **GATE OWNER** | NOT DECIDED |

**No code change is required to activate the writer.** The bridge is already implemented and
certified; activation is entirely environment and permission. That is a deliberate property — and it
is also why the controls in this document, rather than the code, are what make it safe.

---

## 13. Evidence required to declare Gate 9h GREEN

Gate 9h may be declared GREEN only when **all** of the following exist as recorded evidence:

| # | Evidence |
|---|---|
| E1 | U2 answered (yes/no only), recorded — **SATISFIED 2026-09-23** (§4): answered **yes**, recorded without the value. This satisfies E1 as written; it does **not** unblock U2, which stays BLOCKED / fail-closed |
| E2 | `fin_accounts` question resolved and recorded |
| E3 | `nodeLedgerWriter` role created, with the boundary proof (S3 succeeds, S4 refused with code 13) |
| E4 | Backup taken **and its restore demonstrated** on a throwaway database — **restore demonstrated 2026-09-23** (§5.8): checksum matched, `mongorestore` exit 0, 960,150 documents, 0 failures. **Still outstanding on the first half**: no backup has been taken at an activation instant. The §5.10 rehearsal created an activation-time backup **of a disposable clone**, which does not satisfy this |
| E5 | Activation timestamp and fingerprints (R2, R3) recorded |
| E6 | Pre-write smoke checks S1–S7 green |
| E7 | First-write criteria C1–C6 green for the first source type, **including the business-user check** |
| E8 | The same for every subsequently enabled source type |
| E9 | Reversion (§11 step 1) demonstrated at least once, deliberately, and shown to stop Node writes |
| E10 | Day-book / ledger reconciliation before and after, matching |
| E11 | Write-pause mechanism (§5.5) chosen and documented — **policy recorded 2026-09-23 (Option B)**, but **still outstanding as evidence**: no quiet window has ever been declared or exercised, and the policy provides coordination, not enforcement |
| E12 | Named operator assigned for rollback (R5) — **assigned 2026-09-23** to the gate owner/operator (§5.1 R5) |

**E9 is not optional.** A reversion path that has never been exercised is an assumption, not a
control.

---

## 14. This document authorises nothing

Preparing this draft does **not**:

- authorise activating the Node writer;
- authorise creating or changing any database role or credential;
- authorise enabling reverse delegation for any source type;
- authorise any deployment, restart or production change;
- reopen, amend or supersede Gate 9g (`6685637`), which remains in force and BLOCKED;
- constitute evidence that anything in §13 has been done.

**Every table in this document reports its true state.** A small number of items are recorded as
evidence and nothing more; every other status is NOT DONE, NOT VERIFIED, BLOCKED, UNKNOWN or
UNRESOLVED. Those items are R4, verified during the §5.7 rehearsal; the reprojection recovery path
itself, rehearsed on a disposable clone on 2026-09-23; R1, whose restore was demonstrated the same
day into a fresh disposable database (§5.8); and §5.3 step 5, restore → reproject, rehearsed end to
end that day on a disposable clone (§5.10). **None of them is activation evidence**, and all of them
were performed on disposable local state. No production system was contacted, no writer was started,
and U4 remains PARTIAL.

Opening Gate 9h requires an explicit, recorded decision by the gate owner to allow Node business
writes at all — a policy decision that this document exists to inform, not to make.

---

## 15. Readiness state

**DRAFT — NOT SUBMITTED, NOT AUTHORISED.** Partially rehearsed: the U4 recovery path on a disposable
clone (§5.7), and the R1 backup restore into a fresh disposable database (§5.8). Everything else
remains unrehearsed.

**Blocker status after the 2026-09-23 investigation:**

| ID | Status |
|---|---|
| **U2** | **BLOCKED / FAIL-CLOSED.** **Answered 2026-09-23: YES** — the operator reported, yes/no only, that the production `DB_NAME` contains `prod` (§4). The value is never printed. The question is therefore resolved and the **blocker is not**: a `yes` means the writer stays refused until a separately authorised change is made. Nothing was changed — the database was not renamed, no environment variable was set, no guard was modified, and the production writer was never started. |
| **U3** | **RESOLVED (code) / OPEN (permission).** The silent-failure hazard is fixed and proven 16/16. Node still **requires** `insert` on `fin_accounts` (§3); granting it remains an operator action, not yet done. |
| **U4** | **PARTIAL — still OPEN and MANDATORY, not GREEN.** Rehearsed 2026-09-23 on a disposable clone (§5.7): the **recovery path is proven** — byte-exact fingerprint recovery, §5.6 checks 1–4 passed, R4 **VERIFIED** 370/370, parity detected all four injected corruptions. **R1 is now VERIFIED** (§5.8, 2026-09-23): the artifact's SHA-256 matched and `mongorestore` restored it into a fresh disposable database with exit code 0, 960,150 documents and 0 failures. But the gate stays PARTIAL because (a) R1 proves the **restore mechanism only** — no activation-instant backup has been taken, and the assigned operator's production access is untested. The §5.3 step 5 restore-then-reproject path **is** now rehearsed end to end (§5.10, byte-exact), but on disposable state only; (b) the recovery procedure needed **three corrections** — parity-based identification (a deleted leg is invisible to a timestamp scan), the source-existence scope restriction (**185 `source_id`s vs 151 source documents; 34 orphans = 68 legs = ₹25,500** would be destroyed by a blind reprojection), and the non-optional detector set (row counts can be fully masked by delete + ghost-insert). The first two were exercised together in the §5.9 rehearsal, which nonetheless ended PARTIAL; the third is recorded but not separately re-rehearsed; (c) the §5.5 policy is now decided (Option B, 2026-09-23) but has never been exercised. Outstanding items are itemised as **U4-a … U4-d** in §5.7. The earlier concern about rows written under a different `ref_source_key` was **not** exercised in this rehearsal and remains untested; backup must still cover **`fin_accounts`**. |
| **U5** | **POLICY DECIDED — execution still OPEN and MANDATORY.** Write-pause mechanism chosen 2026-09-23 (§5.5): **Option B, the declared quiet window**, with R5 assigned to the gate owner/operator. Option A was rejected on evidence — day closure is **not** a data-entry lock and no canonical write path enforces it. Option B is **coordination, not enforcement**, and no window has ever been declared or exercised, so **E11 is not satisfied**. Separately, and unchanged from 2026-09-23: reverting the env is sufficient **without any code change**, but `os.environ` is per-process, so a `.env` edit needs a **process restart** — it is not instant like `.node-routing-kill`, and an in-flight write can still complete. That is the §11 Node-writer control, which is distinct from this policy. |
| **U6** | **DEFERRED — not an activation blocker.** No writer attribution exists and timestamps cannot substitute (§9). Recorded as future hardening. |

**Required before this can become a real gate:** §13 E1–E12 in full.
