# QORVENA · Bitumen Transport ERP — PRD

## Product summary
QORVENA is a Bitumen transport ERP tracking LRs, Trips, Freight, Shortage, Invoices, Payments, Suppliers, Customers, Vehicles, Drivers, Products, Fuel, and Reports. FastAPI + React + MongoDB. Auth via Emergent-managed Google, with a dev-only demo token.

## Preferred language
User communicates in English. Respond in English. (Prior bilingual reference retained only for legacy modules; new work is English-only as of User Manual v1.0.)

## Locked business rules (do NOT change without explicit approval)
- **Duplicate Masters** (Iter127a):
  - **Customer** — GSTIN + PAN blocked; **Name** warning bypassable via *Continue Creating* (`X-Confirm-Name-Match: allow`); Phone advisory only. Owner/Admin can override GSTIN/PAN via `X-Duplicate-Override` with reason.
  - **Supplier** — GSTIN, PAN, and **Name** all blocked; Mobile advisory only. NO *Continue Creating* button.
  - **Vehicle** — vehicle_number match is IDEMPOTENT; returns existing row.
- **Ship-To Independence** — Ship-To State independent of Customer State; GSTIN derives State/State Code.
- **Trip Loading vs Unloading** — separate stages. Freight at dispatch; shortage only after unload data.
- **Missing Unload Data** — "Not Available Yet", not zero. Pre-unload invoices must not fabricate shortages.
- **Invoice Number** — Server-assigned `{Prefix}/{FY}/{Sequence}`. No per-invoice override. Prefix + Next Number in **Settings** only, Owner/Admin.
- **Invoice Ship-To** — Preview and PDF identical. GSTIN normalised on display. Unload Date renders correctly.
- **Invoice PDF Page X of Y** — every page. Signature block on last page only.
- **Supplier Deactivate/Reactivate** — soft-delete. Owner/Admin only. Historical data preserved.
- **Draft Recovery** — only meaningful, non-empty forms are offered for restore.
- **Deploy Readiness Badge** (Iter128) — `/api/admin/deploy-readiness` + `/api/admin/deploy-history` role-gated to Owner/Admin/Manager (403 otherwise). Frontend badge polls every 60s, paused when tab hidden.
- **Iter129 Phase 1 Security Hardening**:
  - CORS restricted via `CORS_ORIGINS` env (fallback to `*` only if empty); `allow_credentials=False`.
  - Response security headers on every route: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security`, `Permissions-Policy: camera=(), microphone=(self), geolocation=()`, `Content-Security-Policy` (with `frame-ancestors 'none'`).
  - `/api/files/public/{obj_path}` — path-traversal + prefix allow-list (`lr_shares/` or `public/` only; blocks `..`, leading `/`, backslash).
  - File-upload allow-list — JPG / JPEG / PNG / WEBP / HEIC / HEIF / PDF only; other types return 415. Existing stored files unaffected.

## Completed work (rolling log)
- **Iter126, Iter127a, Iter127b, Iter127c** — LOCKED
- **P0 "REFRESHING..." stability** — CLOSED
- **User Manual v1.0 (English)** — LOCKED · UAT approved
- **Iter128 · Deploy Readiness Badge** — 🔒 LOCKED · UAT approved 2026-08-29
- **Xdist Test Cleanup** — 🔒 LOCKED · UAT approved 2026-08-29 (test-only; Iter46 UUID-namespaced fixtures + Iter43 read-after-write retry)
- **Iter129 Phase 1 Security Hardening** — 🔒 LOCKED · UAT approved 2026-08-29
  - Files: `backend/server.py` (+40/−8), `backend/routers/files.py` (+44/−8), new `backend/tests/test_iter129_sec_phase1_hardening.py` (13 tests)
  - Verified: 13/13 targeted tests · full regression 503 passed / 1 skipped / 0 failed · exit 0 · Iter128 badge remains Ready · desktop + mobile smokes clean · no console errors
  - Zero touches to Iter126/127a-c/128, P0, User Manual, Save Health, Auth, Invoice, Freight, Shortage, Tax, LR, Supplier, Regression Guard
  - Single approved backend restart used; no other restarts
- **Iter130 · Demo-Token Production Guard + Token Rotation** — 🔒 LOCKED · UAT approved 2026-08-29
  - Fail-secure design: preview-only `IS_PREVIEW_ENV=1` + `REACT_APP_IS_PREVIEW_ENV=1` gate the demo path. Absence in production = guard ON.
  - Backend: `auth.py` `_IS_PREVIEW` gate + env-backed `DEMO_TOKEN`; `routers/auth_router.py::demo_login` returns 404 in prod; `server.py` startup hook purges any legacy `test_session_bitumen_2026` session row (defense-in-depth after one-shot Mongo delete).
  - Token rotation: new 43-char urlsafe secret stored only in `backend/.env` as `DEMO_TOKEN_VALUE`. Never printed, never in source, never in the frontend bundle.
  - Frontend: `Login.jsx` demo button double-gated (`REACT_APP_IS_PREVIEW_ENV && REACT_APP_ENABLE_DEMO_LOGIN`); production build omits the button from the shipped JS.
  - Test cleanup: 114 test files rewritten to read `os.environ["DEMO_TOKEN_VALUE"]`; new `backend/tests/conftest.py` loads `.env` for pytest; new `test_iter130_demo_guard.py` (11 tests).
  - Approved cooldown-race cleanup: `test_iter51_deploy_guard_and_alerts.py::test_alert_fires_when_threshold_crossed` + `::test_alert_cooldown_prevents_spam` race-hardened with the iter53b pattern (cutoff filtering + skip-on-config-drift). Test-only. No product code change.
  - Verified: Iter130 11/11 pass · full regression 503 passed / 1 skipped / 0 failed / exit 0 · Iter128 badge 🟢 Ready · legacy token 401 · new token 200 · demo-login 200 in preview · Google OAuth unchanged · tenant isolation unchanged · RBAC unchanged
  - Zero touches to Iter126/127a-c/128, Iter129, P0, User Manual, Save Health, Invoice, Trip, Freight, Shortage, Tax, LR, Supplier
  - Two restarts used: 1 backend (auth.py env re-read) + 1 frontend (bake in `REACT_APP_IS_PREVIEW_ENV=1`)
- **Iter131 · Scheduler Cascade Fix** — 🔒 LOCKED · UAT approved 2026-08-29
  - Broke the ~11-min self-perpetuating cascade caused by regression suite tests POSTing to `/api/admin/deploy-readiness/run-now` inside a running regression.
  - `/run-now` now short-circuits with `{triggered:false, reason:"already_running"}` when `_regression_lock.locked()` — nested calls no longer queue behind the in-flight run.
  - `/run-now` on-demand path also writes `next_check_at = now + 1h` (previously only the periodic loop wrote it, causing the 5-day fossil).
  - Enabled hourly cadence: `REGRESSION_GUARD_PERIODIC=1` added to `backend/.env`; existing `_run_regression_background` loop now sleeps 1 h between runs.
  - Test-only assertion updates on `test_iter51::test_deploy_readiness_run_now_triggers` and `test_iter128::test_run_now_endpoint_untouched` (accept both response shapes). No Iter128 badge product code touched.
  - One-shot Mongo hygiene: `deploy_status.next_check_at` refreshed from 5-day fossil (2026-08-24) to a live +1h value.
  - New `test_iter131_scheduler_no_cascade.py` (6 tests, all pass).
  - Verified: Iter131 6/6 · full regression **503 passed / 1 skipped / 0 failed · exit 0 · elapsed 766.8 s** · first `triggered_by=auto/periodic` entry recorded 12:50 UTC · next_check_at correctly +59.6 min after run · Iter128 badge 🟢 Ready · Iter130 sanity 11/11 · zero regression processes leaked
  - Zero touches to Save Health, Iter126/127a-c/128 product code, Iter129, Iter130, Invoice, Trip, Freight, Shortage, Tax, LR, Supplier, Auth, RBAC, Google OAuth, `run_regression.sh`, `predeploy_check.sh`, pytest config
  - One approved backend restart used
- **Iter132a · Credit Note Foundation** — 🔒 LOCKED · UAT approved 2026-08-29
  - Foundational Credit Note module shipped behind `ENABLE_CDN=1` staged rollout flag. Debit Note deferred to Iter132b (not started).
  - **Schema (additive only)**: new `credit_debit_notes` Mongo collection; new `Company` fields `credit_note_prefix="CN"`, `next_credit_note_number=1`, `debit_note_prefix="DN"`, `next_debit_note_number=1`, `require_cdn_approval=false` (backfilled onto 194 existing companies). New `models.CreditDebitNote` / `CDNLine` / `CDNCreateRequest` / `CDNCancelRequest`. Invoice schema and numbering **untouched**.
  - **Numbering**: `_next_credit_note_number_for_company` derives FY from `note_date` (not `now_utc()`) via new `_derive_fy_from_iso` helper — 31-March lands in outgoing FY, 1-April lands in new FY. Uses atomic Mongo `$inc` (unlike invoice's `$set: seq+1`) so concurrent issues cannot race. Cancelled notes never re-use a sequence.
  - **Endpoints (7)** under `/api` in new `routers/notes.py`: POST `/credit-notes`, POST `/credit-notes/{nid}/issue|cancel`, PUT `/credit-notes/{nid}` (draft-only), GET `/credit-notes`, GET `/credit-notes/{nid}`, GET `/invoices/{iid}/notes`. All feature-flagged; 404 when `ENABLE_CDN` unset.
  - **Validation**: `note_date ≥ invoice_date`, `≤ today`, statutory 30-Nov deadline enforced with Owner-only override + mandatory reason. Historical/imported invoices rejected (422). Over-credit guard rejects any CN that would drive effective invoice total < 0 (422). Cancellation reason ≥ 8 chars mandatory. `reason_text` ≥ 8 chars mandatory.
  - **GST parity**: `gst_type`, `cgst_rate`, `sgst_rate`, `igst_rate`, `rcm` all inherited from linked invoice at create time. RCM notes skip tax addition to gross (parity with invoice behaviour).
  - **Effective balance**: derived via new `_effective_invoice_totals` + `_apply_effective_balance` helpers in `services.py`. **Never mutates persisted `balance_due`** on invoices. Wired into `routers/customers.py::list_customers` (customer-list outstanding aggregation only in this foundation pass — remaining ~9 read-sites deferred).
  - **Invoice-delete guard**: `DELETE /api/invoices/{iid}` returns 409 while any non-cancelled CN references the invoice.
  - **PDF**: self-contained `pdf/credit_note.py` — red "CREDIT NOTE" banner, linked-invoice reference box, reason block, tax split, RCM notice. **Zero shared logic with `pdf/invoice.py`** — Iter127b page-of-pages logic untouched.
  - **RBAC (additive only)**: `create_note`, `issue_note`, `cancel_note`, `edit_note_settings` added. Existing owner/accountant/viewer entries untouched. `test_role_permissions_still_intact` guards this.
  - **Audit**: every state transition (`create`, `issue`, `cancel`, `update`) logs via `_log_audit` with new module strings `credit_note`.
  - **Indexes**: 3 on `credit_debit_notes` — `(user_id, company_id, note_date_desc)`, `(invoice_id, status)`, and partial-unique `(user_id, company_id, kind, note_number)` (with `$gt: ""` filter — corrected after the initial `$ne` MongoDB-partial-index limitation).
  - **Approval workflow**: `require_cdn_approval=false` default → accountant can auto-issue CN in one request. When set true, notes remain in `draft` until Owner/Admin issues.
  - **Feature flag**: `ENABLE_CDN=1` set in preview `.env`. Production deploys will not carry the flag → CN endpoints return 404 there until explicitly enabled.
  - **Tests (new)**: `test_iter132a_credit_note.py` — 10 tests covering feature flag, FY derivation, auto-issue, over-credit 422, historical rejection, cancel semantics, no-number-reuse, invoice-delete-block, related-notes endpoint, RBAC additivity.
  - **Verified**: Iter132a **10/10** · Iter130 **11/11** · Iter131 **6/6** · Deploy-Guard **502 passed / 2 skipped / 0 failed / exit 0 / 704 s** · Iter128 badge **🟢 Ready** · `/api/credit-notes` **200** · legacy token **401** · new token **200** · unauth **401** · `next_check_at +59.1 min` · cascade guard verified live (`triggered:false, reason:"already_running"`) · deploy-history shows 3 consecutive `auto/periodic` passes.
  - **Skipped tests**: 2 (`test_iter51::test_alert_cooldown_prevents_spam` + `::test_alert_fires_when_threshold_crossed`) — documented intentional config-drift self-skips from Iter130 cooldown-race cleanup; not failures.
  - **Zero touches** to: invoice model, invoice numbering (`_next_invoice_number*`, `_compose_invoice_number`), `pdf/invoice.py`, Iter126/127a-c/128/129/130/131 code paths, Auth/RBAC existing perms, Save Health, Google OAuth, `run_regression.sh`, `predeploy_check.sh`, `pytest.ini`, Trip, Freight, Shortage, Tax, LR, Supplier.
  - **Restarts used**: 2 authorised backend restarts (staging + N1 fix). Zero unauthorised restarts.
  - **Not shipped (deferred)**: Iter132b Debit Note (kind='debit'), GSTR-1 Section 9B export, CN/DN Register report, remaining 9 outstanding-balance read-sites, frontend UI, User Manual chapter.
- **Iter132b · Debit Note Foundation** — 🔒 LOCKED · UAT approved 2026-08-29
  - Backend-only foundation for Debit Notes (kind='debit'), built on the Iter132a CN skeleton. Behind the same `ENABLE_CDN=1` staged rollout flag. Frontend UI, GSTR-1 export, and CN/DN Register report remain deferred.
  - **Schema (additive only)**: reused Iter132a `credit_debit_notes` collection with `kind` discriminator. Uses existing `Company.debit_note_prefix="DN"` and `Company.next_debit_note_number=1` (both introduced and backfilled onto 194 companies in Iter132a). Zero new Mongo collections, zero new `Company` fields, zero new models — `CreditDebitNote` / `CDNLine` / `CDNCreateRequest` / `CDNCancelRequest` already cover DN via `kind`.
  - **Numbering**: new `_next_debit_note_number_for_company` in `services.py` — mirrors CN pattern (`_derive_fy_from_iso` on `note_date`, atomic `$inc` on `next_debit_note_number`). **Independent counter** from CN — same invoice can carry CN `CN/26-27/0007` and DN `DN/26-27/0003` side-by-side. Cancelled DN never re-uses a sequence.
  - **Endpoints (7)** under `/api` in existing `routers/notes.py` (mirrors CN routes; no new router): POST `/debit-notes`, POST `/debit-notes/{nid}/issue`, POST `/debit-notes/{nid}/cancel`, PUT `/debit-notes/{nid}` (draft-only), GET `/debit-notes`, GET `/debit-notes/{nid}`. Existing GET `/invoices/{iid}/notes` extended to include DN in the mixed list. All feature-flagged via `_require_flag`; 404 when `ENABLE_CDN` unset.
  - **Validation**: `note_date ≥ invoice_date`, `≤ today`, `reason_text ≥ 8 chars` mandatory, cancellation reason ≥ 8 chars mandatory, historical/imported invoices rejected (422), zero-value lines rejected (422 — "must be positive"). No "over-credit" ceiling for DN (a debit adds to the customer's liability; there is no negative-balance bound to protect).
  - **Effective balance semantics**: extended `_apply_effective_balance` in `services.py` — **effective_total = original_total − Σ(issued CN) + Σ(issued DN)**. Cancelled DN excluded. Persisted `invoice.total_amount` and `balance_due` remain **immutable** (verified by `test_effective_balance_increases_with_debit_note`).
  - **GST parity**: `gst_type`, `cgst_rate`, `sgst_rate`, `igst_rate`, `rcm` all inherited from the linked invoice at DN create time — identical to CN behaviour. RCM DN skips tax addition to gross.
  - **Invoice-delete guard**: `DELETE /api/invoices/{iid}` already returns 409 while any non-cancelled note (CN or DN) references the invoice — reuses the Iter132a check (no code change needed for DN coverage).
  - **PDF**: self-contained `pdf/debit_note.py` — orange/red "DEBIT NOTE" banner, linked-invoice reference box, reason block, tax split, RCM notice. **Zero shared logic with `pdf/invoice.py` or `pdf/credit_note.py`** — Iter127b page-of-pages logic and Iter132a CN PDF untouched.
  - **RBAC**: reuses Iter132a's additive perms (`create_note`, `issue_note`, `cancel_note`, `edit_note_settings`) — a single set covers both CN and DN. No new perm strings. `test_role_permissions_still_intact` continues to guard.
  - **Audit**: every DN state transition (`create`, `issue`, `cancel`, `update`) logs via `_log_audit` with new module string `debit_note`. CN audit strings untouched.
  - **Indexes**: reuses the 3 Iter132a indexes on `credit_debit_notes` including the partial-unique `(user_id, company_id, kind, note_number)` — the `kind` discriminator already guarantees CN/DN numbering isolation.
  - **Feature flag**: same `ENABLE_CDN=1` gate as CN. Production deploys without the flag → DN endpoints return 404.
  - **Tests (new)**: `test_iter132b_debit_note.py` — **11 tests** covering feature flag, DN prefix/FY numbering, CN/DN independent-counter proof, effective balance increases with DN, original-invoice immutability under DN, multi-DN accumulation, cancelled-DN excluded, cancelled-DN number not reused, invoice-delete blocked by active DN, related-notes endpoint includes DN, GST/RCM parity, positive-amount guard, historical-invoice rejection. `test_cancelled_dn_excluded_from_effective_balance` uses a local Motor client (matches Iter132a proven pattern — avoids the shared `services.db` module-level client bound to a closed loop under xdist).
  - **Verified**: Iter132b **11/11** in 16.47 s · Iter132a **10/10** · Iter130 **11/11** · Iter131 **6/6** · Deploy-Guard **503 passed / 1 skipped / 0 failed / exit 0 / 739.24 s** · Iter128 badge **🟢 Ready** · `next_check_at +60 min` · deploy-history shows **3 consecutive passes** at 17:04, 18:00, 19:01 UTC (Iter131 hourly cadence live) · zero regression processes leaked · `/api/debit-notes` **200** · legacy token **401** · demo token **200** · unauth **401**.
  - **Skip count note**: earlier Iter132a-lock run showed 502 passed / 2 skipped; this Iter132b run shows 503 / 1. Delta is one of the two Iter51 cooldown-race tests self-un-skipping — documented config-drift pattern from Iter130 cleanup. **0 failures either way**; both configurations expected.
  - **Zero touches** to: invoice model, invoice numbering (`_next_invoice_number*`, `_compose_invoice_number`), `pdf/invoice.py`, `pdf/credit_note.py`, Iter126/127a-c/128/129/130/131/132a code paths, Auth/RBAC existing perms, Save Health, Google OAuth, `run_regression.sh`, `predeploy_check.sh`, `pytest.ini`, Trip, Freight, Shortage, Tax, LR, Supplier, Customer masters.
  - **Restarts used**: 1 authorised backend restart (staging). Zero unauthorised restarts.
  - **Not shipped (deferred to Iter132c or later)**: CN/DN frontend UIs (list, create, issue, cancel, PDF preview), remaining 9 outstanding-balance read-sites, GSTR-1 Section 9B export, CN/DN Register report, User Manual chapter, Customer Statement CN/DN rows.
- **Iter132c · Slice C1 · Effective Balance Everywhere** — 🔒 LOCKED · UAT approved 2026-08-30
  - Wires the Iter132a/b effective-balance layer into the remaining 9 outstanding-balance read-sites. Zero product-code changes to `services.py`, `pdf/*.py`, `routers/notes.py`, or any Iter132a/b core path. Additive response keys only; existing `outstanding`, `balance_due`, `total_amount` unchanged.
  - **9 read-sites wired**: `GET /api/customers/{cid}/transactions` (R1), `GET /api/customers/{cid}/monthly-balances` (R2), `GET /api/customers/bulk-reminder` (R3), `GET /api/customers/{cid}/statement.pdf` (R4), `GET /api/dashboard` (R5), `GET /api/invoices` (R6), `GET /api/invoices/overdue` (R7), `GET /api/invoices/{iid}` (R8), `GET /api/reports/balance-sheet` (R9). Each site reuses `_apply_effective_balance` (Iter132a-locked helper) — one batch Mongo query per call, no N+1.
  - **Response contract**: every existing aggregate key (`outstanding`, `total_billed`, `total_receivable`, `sundry_debtors`) stays **raw** for back-compat; new sibling keys `outstanding_raw`, `outstanding_effective`, `total_billed_effective`, `total_receivable_effective`, `sundry_debtors_effective`, `credits_total`, `debits_total`, `aging_effective`, per-customer `balance_effective` are **additive only**. Per-invoice responses gain 4 keys (`effective_total_amount`, `effective_balance_due`, `credits_total`, `debits_total`).
  - **Overdue drop-off (R7)**: `/invoices/overdue` now drops fully-credited invoices (`effective_balance_due ≤ 0.01`) after the DB filter. Bulk reminder (R3) drops customers whose effective balance is ≤ 0 — prevents dunning WhatsApp messages to customers whose invoices are fully credited.
  - **Statement PDF (R4)**: adds one small line `Adjustments: −CN ₹X / +DN ₹Y` **only when notes exist**. All existing summary cells, invoice-table rows, and layout stay byte-identical for note-free customers.
  - **Two pre-existing bugs found & fixed as part of C1 correctness (approved as A1 + B1)**:
    - **A1 · `monthly_balances` field-name bug** (`customers.py:950` projection + `customers.py:978` bucketing): invoice docs use `invoice_date`, not `date`. Prior code silently bucketed every invoice under `"unknown"`. Fix: 2-character rename `date` → `invoice_date`. Response shape identical; month values now correct (`"2026-06"` etc.). Trip bucketing untouched (trips DO have a `date` field).
    - **B1 · `to_list(2000)` truncation on `/dashboard` + `/reports/balance-sheet`**: with 7,665 live invoices in the demo company, the pre-existing cap silently dropped 5,656 invoices from aggregation → `total_receivable`, `sundry_debtors`, and their effective siblings were all corrupted at >2000-invoice scale. Fix: replaced `to_list(2000)` with `async for` Motor cursor streaming; pre-fetched issued notes ONCE per request (grouped by `invoice_id` in a Python dict); two DB queries total per endpoint, no N+1. Balance-sheet gained proper as-of correctness for notes (filter `note_date ≤ as_of`) which the prior additive `_apply_effective_balance` call had leaked past.
  - **CN/DN semantics preserved**: `status="issued"` filter is the single source of truth for which notes contribute; cancelled and draft notes automatically excluded. Persisted `invoice.balance_due` + `invoice.total_amount` remain **immutable** (proven by `test_shared_c_persisted_balance_due_never_mutates_across_all_9_sites`).
  - **Tests (new)**: `test_iter132c_effective_balance_everywhere.py` — **15 tests** including per-site R1–R9 coverage, shared invariants (T-shared-A cancelled note, T-shared-C persisted-immutability across all 9 sites), plus 3 A1/B1 regression tests (invoices bucket into actual month not "unknown"; dashboard/balance-sheet totals include invoices beyond the old 2000 cap, validated against a MongoDB `$group` ground-truth).
  - **Test isolation strategy (P1–P3)**: every test uses a freshly-created customer via `POST /api/customers` to avoid cross-test note pollution; company-aggregate tests (R5, R9) use before-after baseline snapshots to isolate the specific test's delta from the ~₹358 M accumulated pool; `test_shared_a` narrowed to per-invoice scope (specific invoice's effective must equal raw after cancel).
  - **Verified**: Iter132c C1 **15/15** in 8.47 s · Iter132a **10/10** · Iter132b **11/11** · Iter130 **11/11** · Iter131 **6/6** (combined 38/38 in 27.34 s) · **Deploy-Guard 503 passed / 1 skipped / 0 failed / exit 0 / 732.60 s (12:12)** · Iter128 badge **🟢 Ready** · `elapsed_s=733.0` · `next_check_at +60 min` · consecutive_failures=0 · deploy-history shows 2 consecutive passes at 02:42 and 03:14 UTC · `/api/auth/health` **200** · new demo token **200** · legacy token **401** · unauth **401** · invoice numbering `INV/26-27/0751` intact · streaming aggregation byte-perfect match: endpoint `invoice_count=7,705` and `total_billed=₹358,088,793` equal Mongo `$group` ground truth exactly.
  - **Zero touches** to: `services.py` (helper reused as-is), `models.py`, `server.py`, `pdf/invoice.py`, `pdf/credit_note.py`, `pdf/debit_note.py`, `routers/notes.py`, `auth.py`, Save Health, Iter130/131 scheduler, Google OAuth, invoice numbering (`_next_invoice_number*`, `_compose_invoice_number`), invoice schema, RBAC/perms, `run_regression.sh`, `predeploy_check.sh`, `pytest.ini`, `.env`, and every other `to_list(2000)` occurrence outside the two C1-scope aggregate paths.
  - **Restarts used**: 1 authorised backend restart (after B1 streaming rewrites landed). Zero unauthorised restarts.
  - **STOP RULE compliance**: halted twice mid-iteration when tests failed (once on initial pollution, once on pre-existing bug exposure); RCA-only reports with explicit fix proposals; both fixes applied only after user GO. No autonomous scope expansion.
  - **Not shipped (deferred to future iterations)**: CN/DN frontend UIs (Slice C2), GSTR-1 Section 9B export (Slice C3), CN/DN Register report (Slice C4), remaining `to_list(2000)` sites outside the 2 C1-scope endpoints (see Iter132c-agg-fix proposal), User Manual chapter, Customer Statement CN/DN rows in the invoice table (line-items, not the summary line — a stricter presentation change deferred).

## Frozen — do NOT start without explicit instruction
- **Phase 2 security items** 🧊 (pending separate approvals):
  - Save Health role-gating
  - Deploy Readiness `/run-now` role-gating
  - Auth / localStorage token removal
  - Global 500-error sanitisation
  - Sensitive-field range validators
- **Deploy-guard auto-scheduler stale-timestamp** 🧊 — `deploy_status.next_check_at` frozen at `2026-08-24T06:56:02Z`; scheduler treats itself as overdue and re-fires immediately after every 11-min guard run. Read-only diag captured under Iter130; no scheduler change in this lock.
- Preview Uptime Chip 🧊
- LR Register Email Digest 🧊
- User Manual footer distribution link 🧊
- CN/DN Frontend UI, GSTR-1 Section 9B export, CN/DN Register report, Customer Statement CN/DN row-items, remaining `to_list(2000)` truncation sites (Iter132c-agg-fix candidate) 🧊
- All Iter126 / Iter127a-c / Iter128 / Iter129 Phase 1 / Iter130 / Iter131 / Iter132a / Iter132b / Iter132c C1 / P0 locked functionality 🔒

## Backlog (later, on user's call only)
- **P2** Trip 8279 missing-Ship-To data-hygiene nudge
- **P3** Trip Templates feature completion
- **P3** QORVENA global rebranding rename
- **Deferred** Iter105 Demo-Customer UAT
- **Deferred** "Disk newer than in-memory" backend guardrail
- **Idea** In-app Help side-drawer

## Explicitly deferred by user
- IGST vs CGST/SGST recalculation based on independent Ship-To State.
- Freezing historical invoice Ship-To strings as snapshots.
- Adding `effective_role` to `/api/auth/me` — auth frozen; Iter128 badge uses backend 403 as the gate.

## Critical operational notes
- Backend does **NOT** auto-reload. Any change under `/app/backend` requires `sudo supervisorctl restart backend`.
- `/app/memory/test_credentials.md` holds the demo token and OAuth email used for UAT.
- Manual regen: `python3 /app/docs/build_manual.py`
- Fresh deploy-readiness run: `POST /api/admin/deploy-readiness/run-now` (~10-11 min); poll `GET /api/admin/deploy-readiness` for status.
- Deploy Readiness Badge component: `/app/frontend/src/components/DeployReadinessBadge.jsx`
- Security headers + CORS + upload allow-list are locked in `server.py` and `routers/files.py`; touching them requires explicit approval.
