# TRUKVIA · Migration Invariants (Class-A / Class-B)

**Contract tag:** `contract@v1.iter150j`
**Applies to:** the current Python/FastAPI backend AND every future Node/TypeScript port.
**Severity legend:**
- **Class-A** — financial correctness, security, tenant isolation, idempotency, approval bypass. Violation triggers automatic ingress rollback.
- **Class-B** — response shape drift on non-financial read routes. Warning + human review.
- **Class-C** — cosmetic / timing / logging differences. Informational only.

---

## A · FinTxn projection

**Current behaviour.** Every source doc produces exactly one deterministic pair of legs. Dispatch is by `source_type` inside `services_fin_txn.py::reproject_source`. Legs are inserted by `services_fin_txn_hooks.py::hook_after_source_write`, which first deletes stale legs keyed by `ref_source_key`.

**Exact compatibility requirement.**
- Same `(account_code, direction, amount)` triple emitted for the same source doc.
- Same number of legs (always double-entry pair unless split-tender scenario, which produces an equal-total N-leg set).
- Same `ref_source_key` naming (see §C).
- Same order of insertion is NOT required; parity harness sorts before diffing.

**Class severity.** **A.**

**Parity test.** Golden-fixture harness: 220 source docs → assert JSON-diff of resulting `fin_txn` rows = empty (ignoring `_id`, `created_at`).

**Rollback.** Any single leg mismatch → automatic route flip for that writer.

---

## B · `FIN_SYSTEM_ACCOUNTS` codes

**Current behaviour.** Seeded per-tenant on first write via `services_fin_txn.py::ensure_system_accounts`. Codes are the permanent identifier used by reports and reconciliation.

**Frozen code catalogue.**
```
CASH · BANK_DEFAULT · AR_TRIP_RECOVERY · AP_SUPPLIER · AP_VENDOR · AP_MECHANIC
FUEL_STOCK · TOLL_EXPENSE · DRIVER_ADVANCE · DRIVER_OUTFLOW (Iter150I)
INCOME_TRIP · INVOICE_ISSUED · INVOICE_RECEIPT · CN_ADJUSTMENT · DN_ADJUSTMENT
WALLET_FASTAG · WALLET_DIESEL · WALLET_TRANSFER_HOLDING · (+ per Iter150B wallet family)
```
(Definitive list is `FIN_SYSTEM_ACCOUNTS` in `backend/models.py` — that variable is the source of truth.)

**Compatibility.** Code strings **NEVER** change. Names (display labels) MAY be re-labelled in UI.

**Class severity.** **A.**

**Parity test.** Enum-equivalence test comparing Python `FIN_SYSTEM_ACCOUNTS` codes vs the TS mirror.

**Rollback.** Any code drift → block deploy.

---

## C · `ref_source_key` format

**Current behaviour.** Every FinTxn row carries `ref_source_key = "{source_type}:{source_id}"`. UNIQUE index on `(user_id, company_id, ref_source_key, leg_direction, account_code)` in `fin_txn` enforces natural idempotency.

**Supported source types (13).**
```
invoice · trip_customer_receipt · supplier_payment · vendor_payment · mechanic_payment
credit_debit_note · vendor_bill · mechanic_work_order · expense
wallet_recharge · wallet_transfer · wallet_adjustment · driver_payment (Iter150I)
```
Source of truth: `SUPPORTED_SOURCE_TYPES` in `backend/services_fin_txn.py`.

**Compatibility.** Both the type token and the `":"` separator are frozen. No camelCase (`driverPayment` is forbidden). No new source_type without a locked band.

**Class severity.** **A.**

**Parity test.** Parametric test iterating every source_type and asserting the same key composition on both stacks.

---

## D · Bucket-B idempotency

**Current behaviour.**
- Client (`frontend/src/api.js:72-77`) auto-attaches an `Idempotency-Key` header on every POST.
- Server middleware (`backend/idempotency.py`) dedupes on `(user_id, company_id, key)`; cached body returned on replay for the TTL window.
- Iter150J approval reroute derives a new key `apr:{original}` for the rerouted `POST /api/approvals`.

**Compatibility.**
- Header name is exactly `Idempotency-Key`.
- Case-insensitive on read; canonical case preserved on write to storage.
- Same TTL semantics.
- Replay returns the ORIGINAL response body (not a shortcut "already-processed" code).

**Class severity.** **A.**

**Parity test.** Same-key replay produces byte-identical body + no duplicate FinTxn legs.

---

## E · Correction / reversal semantics

**Current behaviour.**
- Never delete a source doc post-hook.
- Always append a correction row (`payment_corrections`, `driver_payment_corrections`) + re-invoke `hook_after_source_write`, which deletes stale legs by `ref_source_key` and re-projects.
- Iter150I introduced the atomic single-hook `correct-amount` pattern for driver payments.
- Correction endpoints (`/*/correct`, `/correct-amount`, `payment_reversal`) are NOT approval-gated in Phase-1.

**Compatibility.** No use of multi-doc Mongo transactions. Same delete-then-reproject sequence. Same collection names for corrections.

**Class severity.** **A.**

**Parity test.** Correction golden fixtures assert identical FinTxn deltas post-correction.

---

## F · Bank snapshot behaviour

**Current behaviour.**
- Snapshots captured ONLY at POSTED by the writer (`_snapshot_party_bank`, `_snapshot_company_bank` inside each of the 4 payment routers).
- Snapshot fields: `masked_number`, `bank_name`, `ifsc`. NEVER full `account_number`.
- Full account number lives on the master (`party_bank_accounts.account_number`, `company_bank_accounts.account_number`), reveal gated by `view_bank_account_full` permission.
- Approval envelope (Iter150J) carries `bank_account_id` / `company_bank_account_id` references only — NEVER account_number, NEVER snapshot copies.

**Compatibility.** Same field names, same masking, same reveal permission, same timing (never at DRAFT/PENDING).

**Class severity.** **A** (security).

**Parity test.** Static grep: no `account_number` in `approvals`/`approval_revisions`/`approval_audits` payloads. Golden fixtures assert masked-only snapshot fields at POSTED.

---

## G · Maker-Checker lifecycle (Iter150J)

**Current behaviour.**

State machine:
```
DRAFT → PENDING_APPROVAL → APPROVED → POSTED
             ↓                ↓
          REJECTED         EXECUTION_FAILED
             ↓
         (edit + resubmit → PENDING_APPROVAL, revision_index+1)
             ↓
        WITHDRAWN
```

Transitions via `find_one_and_update` CAS with status precondition. Revisions append-only. Audit action tokens: `submit / edit / approve / reject / withdraw / auto_approve / execute / execute_fail`.

**Compatibility.**
- Same 7 states, same string tokens.
- Same 8 audit action tokens.
- CAS behaviour: second concurrent approve returns 409 "Approval already advanced".
- Reject requires non-empty reason (400 otherwise).

**Class severity.** **A.**

**Parity test.** Full 30-scenario lifecycle harness (Iter150J-equivalent).

---

## H · Maker/Checker separation

**Current behaviour.** Server-side check: if `apr.maker_user_id === current_user_id` → HTTP 403 with `detail == "Maker cannot approve own submission"`.

**Compatibility.** Exact HTTP status **403** and exact `detail` string preserved.

**Class severity.** **A.**

**Parity test.** Contract test on `/approvals/{aid}/approve` submitted with the maker's own bearer.

---

## I · Solo-owner auto-approval

**Current behaviour.**
- Detection query: `count(users where parent_user_id = uid AND user_id ≠ uid AND role ∈ [owner, accountant] AND is_active ≠ false) == 0`.
- If solo → same common approval path → `auto_approved: true`, `checker_user_id: "__solo_owner__"`, single writer execution, single FinTxn projection, audit records include `auto_approve` action.

**Compatibility.**
- Sentinel string `"__solo_owner__"` is frozen.
- Detection query semantics preserved (exclude self).

**Class severity.** **A.**

**Parity test.** Solo-owner tenant fixture: submit driver payment → POSTED with sentinel value.

---

## J · RBAC permission catalogue

**Current behaviour.** `ROLE_PERMISSIONS` in `backend/models.py` — three roles:
- `owner`: full set + `approve_transactions` (Iter150J) + `manage_bank_accounts` + `view_bank_account_full`
- `accountant`: `edit_trip`, `edit_invoice`, `edit_master`, `create_note`, `issue_note`, `manage_bank_accounts`, `view_bank_account_full`, `submit_approval` (Iter150J)
- `viewer`: read-only

**Compatibility.** Permission-string tokens are frozen. Role names are frozen.

**Class severity.** **A.**

**Parity test.** Enum-equivalence between Python `ROLE_PERMISSIONS` and TS mirror.

---

## K · Cross-company / tenant isolation

**Current behaviour.** Every mongo query filters `{user_id, company_id}`. `_active_company_id` validates `X-Company-Id` against `{id, user_id}`. No global `find_one({id})` on tenant-scoped collections.

**Compatibility.** Every Node query on a tenant-scoped collection MUST include the same scope filter.

**Class severity.** **A** (security).

**Parity test.** Static lint rule on Node repo forbidding un-scoped queries on the tenant-scoped collection list. Two-tenant fixture asserts foreign tenant sees zero rows.

---

## L · Day Closing

**Current behaviour.** Owner-only writer (`fin_day_closing.py`). UNIQUE index on `(user_id, company_id, close_date)`. Post-close writes to that date are blocked.

**Compatibility.** Same permission gate, same uniqueness, same post-close-block behaviour, same seal semantics.

**Class severity.** **A.**

**Parity test.** Day-closing scenario: seal → attempt writer for that date → assert blocked.

---

## M · Reconciliation read-only

**Current behaviour.** `services_reconciliation.py` + `routers/fin_reconciliation.py` read only from `fin_txn` and `fin_accounts`. Never back-writes to source docs.

**Compatibility.** Zero source-doc writes from any reconciliation endpoint.

**Class severity.** **A.**

**Parity test.** Static grep on Node reconciliation module forbidding writes to source collections.

---

## N · `fin_hook_failures` queue durability

**Current behaviour.** Never TTL-expired. Records persist until resolved or manually cleared. Exponential backoff on retries. Drained by `backend/scripts/replay_fin_hook_failures.py`.

**Compatibility.** No TTL. Same schema shape. Same backoff parameters (or documented equivalents).

**Class severity.** **A.**

**Parity test.** Failure-injection test: writer throws → row appears → replay drains → row cleared.

---

## O · Audit trail semantics

**Current behaviour.** `audit_logs`, `approval_audits`, `policy_change_events` — all append-only. No PATCH/DELETE HTTP endpoints exposed on any audit collection.

**Compatibility.** Append-only guarantee. Action-token vocabulary frozen (see §G for approval audits).

**Class severity.** **A.**

**Parity test.** HTTP surface test: assert absence of PATCH/DELETE routes on audit collections.

---

## P · HTTP status / detail compatibility

**Current behaviour.** See `error-string-parity.md` for the full frozen literals list.

**Compatibility.** Exact HTTP status codes AND exact `detail` string literals preserved for every entry.

**Class severity.** **A.**

**Parity test.** Cross-stack error-matrix runner iterates every literal and asserts identity.

---

## Q · PDF / report parity

**Current behaviour.** `pdf_brand.py` (Iter150E-locked). Deterministic byte-parity for brand headers/footers/fonts. Fonts resolved from `backend/fonts/`. Templates rendered via ReportLab.

**Compatibility.** Rendered PDF header/footer bytes identical (or explicitly re-baselined during migration under a new locked band).

**Class severity.** **A** for tax-authority outputs (GSTR JSON) · **B** for cosmetic brand elements.

**Parity test.** Golden PDF binary diff (already exists as Iter150E test).

**Open decision.** May keep Python's PDF generator behind a `ReportsPort` even after migration to preserve parity — see `pii-security.md` §Deployment note.

---

## R · Locked-band protection

**Current behaviour.** Iter150A / B / C / D / E / F / G / H / H2 / I / J lock covenants — each file at strict `+0/-0` vs its lock ancestor SHA.

**Compatibility.** New migration waves form the next checkpoint chain. Rewriting any locked file requires an explicit new gated lock, not silent modification. During the Python→Node migration, Python-side locked files remain `+0/-0` while Node port produces equivalent behaviour under new TS-side lock covenants.

**Class severity.** **A.**

**Parity test.** Existing `test_iter150j_locked_band_zero_diff.py` + future equivalents per migration wave.

**Rollback.** Any un-authorised locked-file drift → block merge.

---

## Class-A gate summary

The migration is Class-A-clean when **all seventeen invariants A through R** have their parity tests green for the migrated route AND all Class-B tests are non-regressive AND no locked-band drift is observed on either side.
