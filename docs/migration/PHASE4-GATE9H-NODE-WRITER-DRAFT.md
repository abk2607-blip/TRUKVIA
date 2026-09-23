# Phase 4 · Gate 9h — Node business-writer authorisation (DRAFT)

**Status: DRAFT — NOT A GATE RESULT.** Nothing in this document has been rehearsed, verified or
authorised. It contains **no completed evidence**. Preparing it does **not** authorise activating the
Node writer, changing any database permission, or switching any traffic.

Gate 9g (`6685637`) remains in force and remains **BLOCKED**. This draft is the plan that would have
to be executed, and independently verified, before Gate 9h could be opened at all.

**Prepared:** 2026-09-23 · **Author:** migration workstream · **Supersedes:** nothing

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

**STATUS: UNKNOWN — OPERATOR ACTION REQUIRED.** Carried forward unresolved from Gate 9g §14.

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

**This section replaces Gate 9g §13.4. It does not yet exist as a rehearsed procedure.**

### 5.1 Evidence that must exist BEFORE writer activation

| # | Requirement | Status |
|---|---|---|
| R1 | A verified, restorable backup of `fin_txn` and `fin_hook_failures`, taken immediately before activation, with its restore actually tested on a throwaway database | **NOT DONE** |
| R2 | A recorded row count and a content fingerprint of both collections at the activation instant | **NOT DONE** |
| R3 | The exact activation timestamp, recorded to the second, so writes can be bounded by time | **NOT DONE** |
| R4 | Confirmation that every affected `fin_txn` row carries `projected_at` / `created_at`, so Node-era rows are identifiable | **NOT VERIFIED** |
| R5 | A named operator who can execute the restore and has the access to do so | **NOT ASSIGNED** |

R1 is the one that cannot be skipped. **Without a tested restore, this gate cannot open.**

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

**UNRESOLVED:** 1–4 are manual today. Whether an automated check is required before activation is a
decision for the gate owner.

### 5.3 How affected data would be restored

The ledger is a **derived projection**, which makes rollback easier than for source data — but only
if the source records are intact.

1. **Stop the bleeding** — §11 reversion, so Python is the writer again.
2. **Identify the affected rows** — `fin_txn` rows whose `source_type` is an enabled type and whose
   `projected_at` is at or after the activation timestamp (R3).
3. **Preferred path — reproject, do not restore.** Because the ledger derives from Mongo source
   records that Python still owns, the clean fix is to reproject those sources through Python, which
   deletes and rewrites its own rows by `source_id`. **This is the recommended path.**
4. **Fallback path — restore from backup.** Only if reprojection cannot produce a correct ledger.
   Restore `fin_txn` and `fin_hook_failures` from R1 to the activation-instant state, then reproject
   anything written after it through Python.
5. **Never** restore business/source collections from this backup — they were never at risk, and
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

**UNRESOLVED — needs a decision.** Two options, neither yet chosen:

- **Option A — day closing.** Use the existing day-closure mechanism to freeze the affected period.
  Reuses a control the business already understands; scope is a date, not a collection.
- **Option B — announced quiet window.** Perform the rollback when no operator is entering data.
  Simpler, but relies on coordination rather than enforcement.

Whichever is chosen must be written into this gate **before** activation, not improvised during an
incident.

### 5.6 How rollback success is verified

1. Byte-exact parity between the restored ledger and a fresh Python reprojection of the same sources.
2. `fin_hook_failures` holds no `pending` or `retrying` rows for the affected scope.
3. Row counts match R2, adjusted for legitimate activity since.
4. Debits equal credits per scope.
5. A spot check of at least one real invoice/statement in the UI by a business user.

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

**A1 is a real gap, deliberately accepted for now.** Rollback does not depend on it: reversion plus a
full Python reprojection repairs an entire scope without needing to tell individual rows apart
(§5.3). What it costs is *forensics* — "which rows did Node write?" cannot be answered.

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
| Backup + tested restore | **PLATFORM** | NOT DONE |
| Set / unset reverse-bridge env | **PLATFORM** | NOT DONE |
| Restart Node / Python | **PLATFORM** | NOT DONE |
| Parity verification per source type | **CODE / workstream** | method exists, not run against production data |
| Boundary proof S3/S4 against the real role | **CODE / workstream** | **NOT WRITTEN** — needs the role to exist first |
| Safety proof S4b (refused creation writes no ledger row) | **CODE / workstream** | **DONE** — `scripts/fin-account-seed-safety.ts`, 16/16, commit `10b0e82`. Must be re-run against the real role at activation. |
| Resolve the `fin_accounts` question | **CODE / workstream** | **DONE 2026-09-23** — Node requires `insert`; see §3 |
| Decide the write-pause mechanism (§5.5) | **GATE OWNER** | NOT DECIDED |
| Decide whether a writer marker is required (A1) | **GATE OWNER** | NOT DECIDED |

**No code change is required to activate the writer.** The bridge is already implemented and
certified; activation is entirely environment and permission. That is a deliberate property — and it
is also why the controls in this document, rather than the code, are what make it safe.

---

## 13. Evidence required to declare Gate 9h GREEN

Gate 9h may be declared GREEN only when **all** of the following exist as recorded evidence:

| # | Evidence |
|---|---|
| E1 | U2 answered (yes/no only), recorded |
| E2 | `fin_accounts` question resolved and recorded |
| E3 | `nodeLedgerWriter` role created, with the boundary proof (S3 succeeds, S4 refused with code 13) |
| E4 | Backup taken **and its restore demonstrated** on a throwaway database |
| E5 | Activation timestamp and fingerprints (R2, R3) recorded |
| E6 | Pre-write smoke checks S1–S7 green |
| E7 | First-write criteria C1–C6 green for the first source type, **including the business-user check** |
| E8 | The same for every subsequently enabled source type |
| E9 | Reversion (§11 step 1) demonstrated at least once, deliberately, and shown to stop Node writes |
| E10 | Day-book / ledger reconciliation before and after, matching |
| E11 | Write-pause mechanism (§5.5) chosen and documented |
| E12 | Named operator assigned for rollback (R5) |

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

**Every table in this document that reports a status reports it as NOT DONE, NOT VERIFIED, UNKNOWN
or UNRESOLVED, because that is the true state.** Nothing here has been rehearsed.

Opening Gate 9h requires an explicit, recorded decision by the gate owner to allow Node business
writes at all — a policy decision that this document exists to inform, not to make.

---

## 15. Readiness state

**DRAFT — NOT SUBMITTED, NOT REHEARSED, NOT AUTHORISED.**

**Blocker status after the 2026-09-23 investigation:**

| ID | Status |
|---|---|
| **U2** | **OPEN** — production `DB_NAME` unverified (Gate 9g §14). Operator answers yes/no only; the value is never printed. |
| **U3** | **RESOLVED (code) / OPEN (permission).** The silent-failure hazard is fixed and proven 16/16. Node still **requires** `insert` on `fin_accounts` (§3); granting it remains an operator action, not yet done. |
| **U4** | **OPEN and MANDATORY.** No tested data-rollback procedure exists (§5, R1). Reprojection repairs most cases but **cannot** repair orphaned `source_id` rows or rows written under a different `ref_source_key`; backup must also cover **`fin_accounts`**. |
| **U5** | **OPEN and MANDATORY.** Write-pause mechanism undecided (§5.5). Verified 2026-09-23: reverting the env is sufficient **without any code change**, but `os.environ` is per-process, so a `.env` edit needs a **process restart** — it is not instant like `.node-routing-kill`, and an in-flight write can still complete. |
| **U6** | **DEFERRED — not an activation blocker.** No writer attribution exists and timestamps cannot substitute (§9). Recorded as future hardening. |

**Required before this can become a real gate:** §13 E1–E12 in full.
