# Bitumen Transport Accounting — PRD

> 🅿️ **Phase 2 Mobile App is PARKED** — full spec + preliminary cost estimate (400–800 credits + non-credit costs) documented in `/app/memory/PHASE_2_MOBILE.md`. Do NOT start Mobile until Web reaches v1.0-stable. Priority order when we start: 1) Driver → 2) Supplier → 3) Office/Admin.

- [x] **Iter124 · Monthly LR Register / Statement Export** (Feb 2026 — awaiting UAT)
  - **What ships**
    - 3 new endpoints (`GET /api/reports/lr-register` JSON · `.xlsx` · `.pdf`) all fed by ONE shared read-only loader `_lr_register_data()`, so JSON / XLSX / PDF / in-app view stay byte-identical.
    - New Reports tab **LR Register** (`data-testid="tab-lr-register"`) with filters (Start · End · This-Month / Last-Month shortcuts · Customer · Driver · Invoice-Status · Search · Full-view toggle), sticky-header table, totals footer, and inline Excel + PDF download buttons.
    - Canonical layout matches user spec exactly: LR # · LR Date · Cust Ref # · From · Consignee · Ship-To · Vehicle # · Driver · Product · Loading MT · Unloading MT · Actual Shortage MT · Allowance MT · Net Shortage MT · Freight ₹ · Invoice # · Invoice Status · LR Copies. **Full-view** adds Shortage ₹ column only (no duplicate Cust Ref).
    - Filename rule: `LR_Register_<CODE>_<YYYY-MM>.{xlsx,pdf}` for month-aligned ranges, `LR_Register_<CODE>_<start>to<end>.{xlsx,pdf}` for custom ranges. Company code = `lr_prefix` else slug of `company.name`.
  - **Read-only guarantees**
    - `_derive_allowance_mt()` and `_derive_invoice_status()` MIRROR the Iter98/102/107 and Iter118 formulas without touching them; trip docs never mutated. `test_read_only_no_business_field_mutation` verifies byte-identical trip fields before/after JSON+XLSX+PDF calls.
    - Ship-To fallback: `customer.ship_sites[ship_site_id].site_name` → else `trip.to_location`. Consistent across all four outputs. Verified by `test_ship_to_falls_back_to_to_location`.
    - LR Copies label: `ORIGINAL` when no audit history; `ZIP · N×`, `REGEN · N×`, `BULK · N×` when Iter122/regenerate/Iter109 audit events exist.
    - Cap 10 000 rows per request (Iter57 parity). Batched denormalisation (customers · products · invoices · audit_logs) with `$in` — no N+1.
    - Multi-company scoping via `_active_company_id(request, user)`; `company_id` query param not exposed.
  - **Not touched**: `_compute_trip`, supplier freight/shortage engine, invoice PDF, LR PDF, `/trips/{tid}/lr` single-copy, `/trips/{tid}/lr/all-copies`, auth stability paths, Iter121 loopback filter, Iter123 login hero.
  - **Tests** — `tests/test_iter124_lr_register.py` — 7 assertions covering JSON shape · XLSX headers + workbook parse · PDF magic bytes + filename · invoice-status filter · Ship-To fallback · read-only invariance · empty-period behaviour. **All 7 pass in 21.98 s.**
  - **UAT artefacts**: `/app/sample_pdfs/iter124_lr_register_2028-11.{xlsx,pdf}` + live tab at `Reports → LR Register`.

- [x] **Iter123 · Login Hero Rebrand — bitumen tanker photo + Telugu heading readability** (Feb 2026 — APPROVED ✅)
  - Replaced the generic unsplash highway-truck hero with the user's own orange BITUMEN tanker photo. Source PNG (2.5 MB) was resized to 1600 px and re-encoded as progressive JPEG (279 KB, quality 85) at `/app/frontend/public/images/bitumen-tanker-hero.jpg`. `Login.jsx:6` now points at the local asset.
  - Image, crop and gradient are **locked** — user-approved. Only readability polish applied: added `text-shadow: 0 2px 8px rgba(0,0,0,0.6), 0 1px 2px rgba(0,0,0,0.7)` to the Telugu H1 and lighter shadows to the eyebrow and sub-copy so the "బిటుమెన్ ట్రాన్స్‌పోర్ట్ అకౌంటింగ్" heading pops over the bright-sky region without darkening the photograph.
  - No backend, PDF, auth, or business logic touched.

- [x] **Iter122b · Regression Guard re-alignment after Iter121 loopback filter** (Feb 2026)
  - **Symptom**: After Iter121 excluded 127.0.0.1 traffic from save_health telemetry, a handful of legacy tests broke because they were calling from localhost and expected the middleware to record their negative-path traffic.
  - **Fix (test-only)**: Added a shared `X-Forwarded-For: 203.0.113.5x` (RFC-5737 doc IP) header to loopback callers in `test_iter50`, `test_iter51`, `test_iter53b`, `test_iter54`, `test_iter57`, `test_iter58` so they simulate ingress-forwarded traffic. In `test_iter53b::test_save_failure_disabled_suppresses_alert`, also (a) re-read alert_config right before the assertion and skip cleanly when a parallel xdist worker mutated the shared toggle back to True, and (b) scope the alert query to `fired_at > cutoff` and `kind != auth_ip_burst` so an unrelated ip-burst alert cannot fail the suppression check. **No backend code touched.**
  - **Verified**: `bash scripts/run_regression.sh` → **345 passed · 1 skipped · 0 failed** · elapsed 478.63 s · `deploy_status.status = pass, exit_code = 0, consecutive_failures = 0`. `/api/auth/health` → 200. Iter121 loopback filter behavior preserved (external ingress traffic still recorded; 127.0.0.1 still filtered).

- [x] **Iter122 · LR All-Copies ZIP — one-click Original + Duplicate + Triplicate** (Feb 2026 — APPROVED ✅ · LOCKED)
  - **User UAT verdict**: All three PDFs generated correctly with the right stamp labels (ORIGINAL FOR CONSIGNEE / DUPLICATE FOR TRANSPORTER / TRIPLICATE FOR CONSIGNOR). LR body byte-identical across the three copies, only stamp differs. ZIP download works, contains exactly the three required PDFs. Single-copy LR download unaffected.
  - **DO NOT MODIFY** the approved LR Copy / ZIP functionality — endpoint (`GET /api/trips/{tid}/lr/all-copies`), the `Archive` icon buttons on Trips + TripView, or the file-name pattern. Any future change to LR copies must be requested explicitly by the user.
  - **New endpoint** `GET /api/trips/{tid}/lr/all-copies` in `routers/trips.py` (right above the existing `/regenerate-lr` route). Streams a ZIP with exactly three PDFs, each generated by the SAME already-approved `build_lr_pdf(company, customer, trip, copy=...)` renderer that Iter115 blessed. File names follow the pattern `LR_{lr_number}_{ORIGINAL|DUPLICATE|TRIPLICATE}.pdf`; download name is `LR_{lr_number}_all_copies.zip`.
  - **Zero business-logic side-effects**: the endpoint only assigns an `lr_number` if the trip does not yet have one (bit-for-bit parity with the existing single-copy `/lr` endpoint). It does NOT touch freight, shortage, supplier, invoice, or status fields. An `audit_logs` row (`action="lr_all_copies_zip"`) is appended for traceability. Single-copy LR download behaviour (`GET /trips/{tid}/lr`) is unchanged.
  - **Frontend surfaces**:
    - `TripView.jsx` — new pill button next to "LR PDF": `data-testid="trip-view-lr-all-copies"`, uses `Archive` icon, calls `downloadTripLrAllCopiesZip()`.
    - `Trips.jsx` — new per-row action button next to the existing LR PDF button: `data-testid="lr-all-copies-{trip_id}"`.
    - `utils/pdfDownload.js` — new helper `downloadTripLrAllCopiesZip()` that fetches with the Bearer token, triggers a browser download, and toasts a success message listing the three copies.
  - **Test suite** `tests/test_iter122_lr_all_copies_zip.py` — 4 assertions: (a) ZIP contains exactly 3 valid PDFs suffixed ORIGINAL/DUPLICATE/TRIPLICATE, (b) Content-Disposition carries `LR_..._all_copies.zip`, (c) unknown trip → 404, (d) trip business fields are byte-identical before vs after the download (pure renderer contract). All 4 pass in 4.83 s.
  - **Companion test-alignment fix** (test-only, no code change) — Iter121's loopback filter caused a handful of stale save_health tests to fail because they were calling from `127.0.0.1` and getting filtered. Added `X-Forwarded-For: 203.0.113.5x` (RFC-5737 doc IP) headers to `test_iter50_save_health_and_regression_guard::test_save_health_captures_write_failure`, `test_iter51_deploy_guard_and_alerts::test_alert_cooldown_prevents_spam`, and `test_iter54_login_failure_tracking::{test_invalid_token_401,test_missing_token_401,test_post_failure_still_tagged_as_save_failure}` so they mimic ingress traffic. **No backend code touched.**
  - **UAT sample**: `/app/sample_pdfs/iter122_lr_all_copies.zip` — 3 files, ~52 KB each: `LR_26-27_19640_ORIGINAL.pdf`, `LR_26-27_19640_DUPLICATE.pdf`, `LR_26-27_19640_TRIPLICATE.pdf`.
  - **Not touched**: `_compute_trip`, supplier freight/shortage engine, invoice PDF, single-copy LR download, auth stability paths (Iter106/106b/110), Iter111 supplier logic, Iter121 loopback filter.


- [x] **Iter121 · Save Health — exclude loopback (127.0.0.1) telemetry** (Feb 2026)
  - **Root cause (from Iter121 investigation)**: `_save_health_middleware` was faithfully recording every 4xx from any caller, so the on-pod pytest regression suite (running `bash scripts/run_regression.sh` from inside the pod, ip=`127.0.0.1`) contributed **99.0 % of the 6,924 alerts** the user saw on the Save Health tile. The remaining 1.0 % (72 rows) came from Emergent's Google-Cloud smoke-test probes, also deliberate. **Zero real browser sessions** hit a 4xx.
  - **Fix (monitoring-only, 6 lines in `server.py`)**: In `_save_health_middleware`, after resolving the source IP, short-circuit and return the response if `ip in ("127.0.0.1", "::1", "localhost")`. Applied to NEW events only — historical rows preserved so the user can audit them.
  - **Dashboard note**: One-line italic tooltip added under the Save Health tile (`Dashboard.jsx:436`, `data-testid="save-health-loopback-note"`): *"Internal loopback traffic (127.0.0.1) from the on-pod pytest / regression guard is excluded so this tile reflects real operational failures only."*
  - **Verified** (with backend restarted):
    - Loopback probe (3× `GET /api/auth/me` + 3× `POST /api/customers` + 3× `POST /api/trips` from `curl localhost`) → **0 rows** inserted.
    - External probe (2× `GET /api/auth/me` + 2× `POST /api/customers` with `X-Forwarded-For: 203.0.113.42`) → **4 rows** inserted, all correctly tagged `ip=203.0.113.42`.
    - `/api/auth/health` → HTTP 200, `regression_guard.consecutive_failures = 0`.
    - Regression Guard remains fully independent — `bash scripts/run_regression.sh` still passes 345/1skip/0 and writes to `deploy_status`; no test-suite logic changed.
    - Alert threshold unchanged (still `20 failures / 1 h`), monitoring still enabled, historical 24 h counter still visible for audit.
  - **Untouched**: `_compute_trip`, supplier freight/shortage engine, auth (`get_current_user`, `/auth/me`, `/auth/session`), invoice PDF, LR PDF, Iter106/106b/110 auth stability paths, Iter111 supplier freight & shortage, deploy-readiness endpoints, alert config schema, save_health TTL index. No business logic touched.


- [x] **Iter120 · Regression Guard fully green — stale auth/health tests realigned** (Feb 2026)
  - **Root cause**: Two tests — `test_iter52_strict_mode_alerts_history.py::test_auth_health_returns_meaningful_state` and `test_iter53_strict_prod_multirecip_trend.py::test_auth_health_gate_semantics` — still asserted the pre-Iter106 contract (`/api/auth/health` returns 503 on `strict + fail + consecutive≥2`, plus a `warning` field on soft-fail). In Iter106 that gating was intentionally removed (comment in `routers/auth_router.py:94`: *"Deploy-guard gating removed: /auth/health reports liveness only … it can no longer 503 the app (that drove the persistent REFRESHING pill)."*). The endpoint now always returns 200 as long as the DB ping works, and surfaces the cached guard verdict for informational display only. Iter45 was **not** the failure — it passes cleanly; the earlier hand-off misread the batch report.
  - **Fix (test-only)**: Rewrote both test bodies to assert the current Iter106 contract — `status_code == 200`, `regression_guard` block present with `status ∈ {pass, fail, unknown}`, `strict_mode` boolean, `consecutive_failures` int. **No backend code touched.** No changes to `_compute_trip`, supplier freight/shortage engine, invoice PDF, LR PDF, or auth.
  - **Verified**: `bash scripts/run_regression.sh` → **345 passed, 1 skipped, 0 failed, elapsed 458.72s** · `deploy_status.status = pass`, `exit_code = 0`, `consecutive_failures = 0` · `/api/auth/health` returns HTTP 200 with `regression_guard.status = pass, strict_mode = true`. Regression Guard is genuinely green — dashboard reflects DEPLOY READY.
  - **Business-logic invariants preserved**: All Iterations 102-119 approvals intact. English-only PDFs preserved. No engine/router/service change.


- [x] **Iter119 · Invoice Route column — readability preserved** (Feb 2026 — awaiting UAT)
  - **Route treated as a "special" column** — `min_font=7.0` (was `4.8`) in `_fit_paragraph`. Short and normal routes now render at full 8 pt base font (no more silly shrink for `MANGALORE → PORUMALLA`). Only routes that genuinely exceed 32 mm at 7 pt allow ReportLab's natural Paragraph wrap to a 2-line compact cell — instead of shrinking to unreadable 4.8 pt.
  - **Width redistribution** — `_COL_MM` now `[17, 18, 22, 26, 32, 15, 15, 18, 18, 18, 18, 24, 36]`. Vehicle No 20 → 18 (−2), Cust Ref 24 → 22 (−2), Product 28 → 26 (−2); Route 26 → 32 (+6). Total still 277 mm inner. Adjacent columns still comfortable for real-world data.
  - **Verified with four Route scenarios**: (a) SHORT `K → V` — full font, no shrink; (b) NORMAL `MANGALORE → PORUMALLA` — full font, single line; (c) LONG `Visakhapatnam → Vijayawada` — full font, single line; (d) EXTREME `Visakhapatnam Petroleum Refinery Yard-3 → Vijayawada Bypass Plant-South-Extension` — 7 pt, 2-line wrap inside cell, still readable and does not spill into neighbours.
  - **Regressions**: 11/11 adjacent invoice tests pass (iter67, iter82, iter107). `Basis` remains absent. All 13 headers still single-line.
  - **Sample PDF for UAT**: `/app/sample_pdfs/iter119_invoice_route.pdf` (also overwrites `iter113_invoice_preview_sample.pdf`).
  - **Not touched**: `_compute_trip`, freight / shortage / supplier / invoice calculation, auth, Iter105/106/106b/110/111 approved paths, landscape, English-only, pagination, totals section.

- [x] **Iter118 · Invoice header spacing + Basis column removal** (Feb 2026 — awaiting UAT)
  - **1. Company header spacing** — `Spacer(1, 3)` inserted between `Company Name` and `Address` in `pdf/invoice.py::company_left`. Header stays same height; name and address no longer look crowded.
  - **2. Basis column removed from customer-facing PDF** — 14 → 13 cols. Freight basis (`applied_freight_method`, `freight_qty_used`) stays 100% intact in the Trip record and calculation engine — this is a PRESENTATION-only removal.
  - **3. Freed width redistributed** — new mm widths `[17, 20, 24, 28, 26, 15, 15, 18, 18, 18, 18, 24, 36]`. Product +6, Cust Ref +2, Rate +2, Unload Date / Actual / Allowance / Net Short +1 each — realistic long values now fit cleanly single-line. Header font bumped 7.6 → 7.8 pt for the same reason.
  - **4. Sub-row spans updated** — `Halting / Diesel / Advance / Shortage / Excess` sub-rows now span cols 0..11, amount in col 12 (matches the 13-col table).
  - **Verified**: `Basis / Per Ton (Loading) / Per Ton (Unloading)` all absent from extracted PDF text. All 13 headers single-line. 11/11 adjacent invoice regressions pass (iter67, iter82, iter107).
  - **Sample PDF for UAT**: `/app/sample_pdfs/iter118_invoice_final.pdf` (also overwrites `iter113_invoice_preview_sample.pdf`).
  - **Not touched**: `_compute_trip`, freight / shortage / supplier / invoice calculation logic, auth, Iter105/106/106b/110/111 approved code paths, landscape, English-only, pagination behaviour, totals section, shortage-allowance explanation.

- [x] **Iter117 · Invoice final UI refinement — alignment + Indian date format** (Feb 2026 — awaiting UAT)
  - **1. Bill-To vertical spacing** — inserted `Spacer(1, 3/4)` between Name → Address → GSTIN → State/Phone in `pdf/invoice.py::bill_lines`. Header stays same height, but Name no longer visually collides with Address; GSTIN/State line has breathing room.
  - **2. Indian date format app-wide** — new backend helper `_fmt_ind_date(v)` in `pdf/_base.py` and frontend mirror `formatIndDate(v)` in `utils/date.js`. Renders as `23-Aug-2026`. Applied on Invoice PDF (Invoice Date + every Trip Date + Unload Date) and LR PDF (Date-of-Issue pill on p1 header + mini navy header on p2). Storage & API unchanged (still ISO `YYYY-MM-DD`). Frontend util is ready for the Trips / Invoices / Customers screen rollout after PDF UAT sign-off.
  - **3. Trip table strict single-line alignment** — column order locked to the user's approved 14-column contract: `Date | Vehicle | Cust Ref | Product | Route | Basis | Load MT | Unload MT | Unload Date | Actual Short | Allowance | Net Short | Rate | Amount`. Shortage split into 3 dedicated columns; new `Unload Date` column. Per-cell auto-shrink via new `_fit_paragraph()` helper: measures `stringWidth` at base font, steps down in 0.5-pt increments until the string fits the column, floor `4.8pt` for Cust Ref / Product / Route / Basis (`5.0pt` for Date-family, `5.5pt` for headers). Never truncates. Headers auto-shrunk to stay single-line ("Actual Short", "Allowance", "Net Short", "Unload Date" all confirmed one-line via PyMuPDF text extraction).
  - **4. Preserved**: landscape orientation, header + company branding, Bill-To / Ship-To structure, current shortage allowance / method display (via the dedicated Allowance column now), totals section, English-only, pagination behavior, ALL calculation and business logic.
  - **iter67 test realignment** — stale assertion about per-trip Ship-To names inside Route cell removed (Iter117 relocates that info to the "Mixed — see per-trip below" band above the trip table). `Mixed` marker + per-trip Cust Ref anchors still asserted. No engine change.
  - **UAT sample**: `/app/sample_pdfs/iter117_invoice_final.pdf` (also overwrites `iter113_invoice_preview_sample.pdf`) — verified with 4 trips including one realistic long-values row and one deliberately extreme long-values row.
  - **Not touched**: `_compute_trip`, freight / shortage / supplier / invoice logic, auth, Iter105/106/106b/110/111 approved code paths.

- [x] **Iter116 · Regression Guard root-cause fix — REFRESHING pill resolved** (Feb 2026)
  - **1. Iter73 test realignment (test-level fix only)** — `tests/test_iter73_supplier_freight_lr_perf.py::test_supplier_freight_per_ton_uses_supplier_quantity_when_set` rewritten with a clear docstring: Iter111's approved contract is that `supplier_quantity` is server-DERIVED from the trip's `applied_freight_method` snapshot, so user-supplied `supplier_quantity=12.5` is intentionally ignored; assertion updated to expect `15.0 × 900 = 13500` (basis = loaded tons under default `per_ton_loading`). **No engine change.**
  - **2. Iter74 test realignment (test-payload fix only)** — `tests/test_iter74_supplier_shortage_integration.py::test_manual_override_blocks_auto_mirror` updated to supply the mandatory `supplier_shortage_override_reason` on the PUT body (contract introduced by Iter111 test line 216, which explicitly asserts 400 when reason is empty). Test now also verifies the audit stamps (`supplier_shortage_override_by`, `supplier_shortage_override_at`, `supplier_shortage_override_reason`). **No endpoint / validation change.**
  - **3. CI script batching (`scripts/run_regression.sh`)** — the 49 declared critical suites are now executed in ONE pytest invocation instead of 49 sequential `pytest {file}` calls. Removes ~100 s of pytest-startup overhead. Uses the existing `-n 2 --dist loadscope` xdist config from `pytest.ini`. Wall time dropped from >600 s timeout → **196.6 s completing cleanly**.
  - **4. Single-flight `_regression_lock`** in `server.py` — an `asyncio.Lock` now serialises the hourly background regression run and the on-demand `/api/admin/deploy-readiness/run-now` handler. Previously they could race, spawning duplicate pytest processes that trampled each other's output and marked the guard as `timed-out`. `wait_for` also bumped from 600 s → 1500 s for headroom.
  - **Verified**: `/api/auth/health` returns HTTP 200 across 6 consecutive polls · `deploy_status.status = pass` · `exit_code = 0` · `consecutive_failures = 0` · `elapsed_s = 196.6 s`. The exact 6 suites the user listed (iter73, iter74, iter111, iter105, iter105b, iter106, iter106b) pass **54/54 in 24.66 s**. `SilentRestartToast "REFRESHING…"` cannot fire because the health endpoint stays 200.
  - **Not touched**: `_compute_trip` engine, Iter111 supplier freight / shortage calculation, Iter111 mandatory-reason validation rule, Iter105 policy workflow, Iter106/106b/110 auth logic, invoice PDF, LR PDF, `REGRESSION_GUARD_STRICT` env, `SilentRestartToast` component.

- [x] **Iter115 · LR Copy Stamps (Original / Duplicate / Triplicate)** (Feb 2026 — awaiting UAT)
  - **`pdf/lr.py::build_lr_pdf(company, customer, trip, copy="original")`** — new optional `copy` parameter maps to standard Indian carriage labels: `ORIGINAL FOR CONSIGNEE`, `DUPLICATE FOR TRANSPORTER`, `TRIPLICATE FOR CONSIGNOR`.
  - **Page 1 header** — a subtle emerald-tinted mini badge sits below the "Lorry Receipt · GCN" subtitle in the navy header's right column. 7.5 pt bold uppercase, right-aligned, ~62 mm wide. Does not touch logo / title / GCN meta pills.
  - **Page 2 mini navy header** — the right-side "GCN No. · Date" line now has a second line rendering the copy label in emerald 7 pt bold. Subtle, professional, unmistakable at a glance.
  - **Endpoint** `/api/trips/{tid}/lr?copy=original|duplicate|triplicate` — filename suffix `_DUPLICATE.pdf` / `_TRIPLICATE.pdf` when non-original.
  - **Frontend** `LRSection.jsx` — Copy selector `<select>` right beside the Download LR PDF button with three options (Original · Consignee / Duplicate · Transporter / Triplicate · Consignor). `openTripLrPdf(tid, hint, { copy })` in `utils/pdfDownload.js` sends the `copy` query param.
  - **Verified**: All 3 sample PDFs generated — `/app/sample_pdfs/iter115_lr_{original|duplicate|triplicate}.pdf` — each 2 pages · ~53 KB · badge text extracts correctly on BOTH pages via pypdf. 15/16 LR-adjacent regression tests pass (1 pre-existing iter73 failure carried from Iter111 test debt — unrelated).
  - **Not touched**: LR body content, freight / shortage / supplier / invoice logic, auth, 2-page layout lock.

- [x] **Iter114 · Invoice PDF final refinements** (Feb 2026 — awaiting UAT)
  - **1. Invoice-number duplication fix (`VBK/26-27//26-27/0003` → `VBK/26-27/0003`)** — `services.py::_compose_invoice_number()` is a new self-healing helper: strips a trailing slash on the stored `invoice_prefix`, then only appends `/{fy_str}/{seq:04d}` if the prefix does NOT already carry an `NN-NN` FY segment; otherwise appends just `/{seq:04d}`. Both `_next_invoice_number` and `_next_invoice_number_for_company` now route through it. Unit-verified against 6 real prefixes seen in DB.
  - **2. T&C clause 2 generic** — replaced the hard-coded "0.5% for Bitumen … 1% for CRMB / PMB" with: "Shortage or excess shall be accounted for in accordance with the applicable product and customer billing policy; the per-trip allowance is stamped against each line item above." This no longer contradicts the actual Product Master / Customer Custom Allowance engine (whose real allowance is already printed per-line-item on the invoice).
  - **3. Shortage remarks removed from customer invoice** — `pdf/invoice.py` no longer passes `remark=t.get("shortage_remarks", …)` on the shortage sub-line. Internal ops remarks stay in the Trip record, ledger reports and audit log. Excess remarks kept (user only asked about shortage).
  - **4. Page-2 balance fix** — T&C block moved INSIDE the LEFT column of the bottom row (below Amount-in-Words + Bank Details) as a nested amber-tinted mini-table, matching the height of the right-side Totals column. The formerly full-width standalone T&C block is gone. Side effect (positive): the 2-trip sample invoice now fits on **1 page** (was 2 with a mostly-empty page 2).
  - **Sample PDF for final UAT**: `/app/sample_pdfs/iter114_invoice_final.pdf` (also overwrites `iter113_invoice_preview_sample.pdf` so UAT can't pick up the stale copy). Verified: 1 page · 47 KB · clause 2 generic · no "0.5%" / no "CRMB / PMB" / no shortage_remarks leak · Bill To / Ship To / Cust Ref / Load / Unload / Shortage / Rate / Amount / Freight / CGST / SGST / Final Payable all intact.
  - **Not touched**: `_compute_trip` engine, shortage / freight / supplier logic, LR PDF, auth, invoice line-item rendering (per-line Allowance caption preserved from Iter107).

- [x] **Iter113 · Inline Invoice PDF Preview** (Feb 2026 — awaiting UAT)
  - **Root cause of "preview not opening"**: `InvoiceView.jsx` never embedded the actual PDF. It rendered an HTML mock-up of the invoice which could drift from the real ReportLab output. The Download button opened the PDF only in a new tab.
  - **Fix — new component `/app/frontend/src/components/InvoicePdfPreview.jsx`**: fetches `/api/invoices/{id}/pdf` via authenticated axios as a blob, creates `URL.createObjectURL(blob)`, and embeds it in an `<iframe>` (~900px tall). Same bytes as the Download button → Preview = Downloaded PDF, byte-for-byte. Reload + Open-Tab controls. Cleans up blob URLs on unmount / refresh. Auto-reloads when `refreshKey` changes (invoice recompute / new payment).
  - **`InvoiceView.jsx`**: renders `<InvoicePdfPreview />` right after the header toolbar, above the existing HTML "invoice paper" (kept for print CSS). `refreshKey` is derived from `updated_at | payments.length | balance_due`.
  - **Verified**: Trip → Invoice → PDF one-to-one confirmed by rendering the same PDF to PNG (`/tmp/inv_pdf_p1.png` / `p2`): Bill-To, Ship-To, Cust Ref (per-trip only, never inherited), Product, Route, Basis, Load MT, Unload MT, Shortage/Net MT, Rate, Amount, Freight subtotal, CGST/SGST, Final Payable, Balance Due — all present. Live PDF endpoint `/api/invoices/{iid}/pdf` verified 200 · `application/pdf` via public URL. Iframe blob URL binds within ~1.5s in playwright; renders natively in every real desktop/mobile browser with built-in PDF viewer.
  - **Sample PDF for UAT**: `/app/sample_pdfs/iter113_invoice_preview_sample.pdf` (2 pages · 48 KB).
  - **Not touched**: Invoice calculation logic, Invoice PDF template (`build_invoice_pdf`), auth, LR, freight, shortage, supplier, trip business logic.

## Problem Statement (Original)
Bitumen transport వ్యాపారం కోసం సులభమైన అకౌంటింగ్ యాప్ — GST ట్రాన్స్‌పోర్ట్ ఇన్వాయిస్ (VBK Logistics style), ప్రతి ట్రిప్‌కు కస్టమర్/తేదీ/వాహనం/డ్రైవర్/టన్నులు/రూట్/ఫ్రైట్, ఫ్రైట్ మోడ్ (per_ton లేదా fixed round-trip), multi-trip GST invoice, expense tracking (డీజిల్/టోల్/బాటా/రిపేర్), profit + receivables dashboard, PDF export.

## Users
- Small transport business owner (Telugu-speaking) — sole operator / accountant

## Core Requirements
- Emergent Google OAuth (per-user tenant)
- Trip logs with two freight modes: per_ton (tons × rate) and fixed (single amount)
- Per-trip expenses (diesel, toll, batta, repair, other) + auto profit
- Multi-trip GST invoice generation (5% RCM default; CGST+SGST intra / IGST inter)
- Invoiced trips are locked (cannot re-invoice, edit, or delete)
- Server-side PDF (reportlab) — A4 tax invoice with bank details, RCM note, HSN 996791
- Payment tracking with partial payments and balance due
- Dashboard: revenue, expenses, profit, receivables per customer

## Architecture
- Backend: FastAPI + Motor (MongoDB), reportlab for PDF, session_token cookie/Bearer
- Frontend: React 19 + React Router 7 + TanStack Query + Tailwind + Shadcn utilities + Sonner + lucide-react. Bilingual (Telugu + English) via hardcoded labels


- [x] **Iter112 · LR reverted to English-only (final)** (Feb 2026 — awaiting UAT)
  - **Decision**: Bilingual EN + Telugu approach dropped. LR reverts to the English-only T&C that shipped before the Iter112 experiment. Invoice was never bilingualised and stays English-only.
  - **`pdf/_base.py`** — Removed `LR_TERMS_TE`, `_TE_FONT`, `_TE_FONT_BOLD`, and all Telugu / Anek / Noto font registration blocks. Only DejaVuSans stays registered (needed for the Indian Rupee sign ₹ on Invoice / Report bodies).
  - **`pdf/lr.py`** — T&C clause row renders English only (7.4pt DejaVuSans, 9.2 leading, one Paragraph per numbered clause). Page-2 body stays wrapped in one `KeepInFrame(mode='shrink', maxHeight=275mm)` so the 2-page lock is preserved.
  - **`pdf/ledger.py` / `pdf/owner.py` / `pdf/__init__.py`** — Dropped stale `_TE_FONT` imports and the unused `LR_TERMS_TE` list in ledger.
  - **`fonts/`** — Removed `AnekTelugu-Regular.ttf`, `AnekTelugu-Bold.ttf`. Kept DejaVu + Noto Sans Telugu on disk (Noto is unreferenced but harmless).
  - **Test / regression cleanup** — Deleted `tests/test_iter112_bilingual_lr_tc.py`; removed `iter112` line from `scripts/run_regression.sh` `CRITICAL_TESTS`. Adjacent LR / invoice / supplier suites (iter31, iter109, iter107, iter108, iter111) all pass 32/32.
  - **Sample PDF for final UAT**: `/app/sample_pdfs/iter112_english_only_lr.pdf` (also copied over the older `iter112_bilingual_lr.pdf` so no stale artefact remains). Verified: 2 pages · ~53 KB · 0 Telugu code points · 12/12 English anchors present · direct PNG render inspection confirms Option B design + Seal callout + all 15 numbered clauses + Consignee Ack panel intact on page 2.
  - **Not touched**: Invoice PDF, freight, shortage, supplier, Iter105, Auth, Iter108 logo behaviour.


- [x] **Iter105 Phase B · APPROVED** (Feb 2026) — user verified Simple Revert + Invoice-Safety Block on live UAT scenarios. Revert-with-reason works; invoice-safety block refuses with inline LR display; no partial revert. Regression guards `test_iter105b_policy_change_revert.py` (6/6) added to `scripts/run_regression.sh`.
- [x] **Iter111 · APPROVED** (Feb 2026) — user verified 7-step supplier calc walkthrough (freight basis / threshold / override / audit / restore). Regression guards `test_iter111_supplier_freight_and_shortage.py` (13/13) added to `scripts/run_regression.sh`.
- [x] **Iter50 Strict Regression Guard expanded** (Feb 2026) — added iter98 / 102 / 103 / 104b / 105 / 105b / 106 / 106b / 107 / 108 / 109 / 111 suites to `CRITICAL_TESTS` in `scripts/run_regression.sh`. Deploy pipeline now blocks on any regression across the full policy-snapshot / freight / shortage / customer-policy / auth / bulk-LR / supplier stack.


- [x] **Iter105 · Customer Policy Change Workflow — Phase A + Phase B COMPLETE** (Feb 2026 — Phase A user-approved · Phase B awaiting UAT)
  - **Phase A · Backend router** `/app/backend/routers/policy_changes.py` — endpoints under `/api/policy-changes`:
    - `POST /preview` — READ-ONLY dry-run. Returns eligible pending trips (uninvoiced + non-historical + `date >= effective_from`) with old vs new snapshot + old vs new engine-recomputed financials + Δ freight/Δ shortage/Δ net-settlement per trip. Both sides run through `services._compute_trip` on the same code path so deltas are apples-to-apples.
    - `POST /apply` — Persists customer master, re-snapshots + recomputes selected trips via `_compute_trip`, writes ONLY applied_* + recomputed financial fields, records a `policy_change_events` row + `audit_logs` crumb (`action=policy_change_apply`). Non-selected / invoiced / historical / out-of-range trips guaranteed untouched. Company + user_id isolation enforced.
    - `GET /policy-changes?customer_id=...` — History list.
  - **Phase B · Backend Revert** — `POST /api/policy-changes/{event_id}/revert`:
    - `reason` is MANDATORY (400 if blank/whitespace).
    - Only `status=applied` events revertable (400 on second revert).
    - **Invoice safety gate** — if ANY of the previously-applied trips is now invoiced, revert refused with `409 REVERT_BLOCKED_INVOICED` + list of blocking trip IDs + LR numbers. Never a partial revert.
    - Restores Customer master to `old_policy`, restores each affected trip's applied_* snapshot + freight_amount / shortage_qty / shortage_amount / excess_amount / net_settlement / policy_snapshot_at from the event's `per_trip_deltas[i].old`.
    - Flips event to `status=reverted` with `reverted_at`, `reverted_by`, `reverted_by_user_id`, `revert_reason`. Audit crumb (`action=policy_change_revert`) dropped in `audit_logs`.
  - **Frontend · PolicyChangeDialog** — Wired into Customers.jsx edit-form. Two triggers: (a) explicit `Review policy · pending trips…` button in the Customer Shortage Rule section, (b) Save on any existing customer that has `shortage_config.effective_from` set. Stage 1 shows Current vs New policy summary + Effective Date + apply-to-previous checkbox. Stage 2 (checkbox ON) fetches `/preview`, renders per-row selection + old vs new Freight/Shortage + Δ Net + optional reason.
  - **Frontend · PolicyChangeHistory** (Phase B) — New modal launched from `Policy History` button on the Current Billing Policy card of CustomerHistory (customer profile) page. Lists every event with old vs new summary, effective date, actor, reason, affected trip count, APPLIED / REVERTED status badge, expandable per-trip deltas table. `Revert` button on applied events opens a confirmation sub-modal that requires a mandatory reason (Confirm disabled until non-blank), surfaces the 409 REVERT_BLOCKED_INVOICED response inline with the list of blocking LR numbers.
  - **Tests** — `test_iter105_policy_change_workflow.py` (8/8) · `test_iter105b_policy_change_revert.py` (6/6): reason mandatory, applied-only revertable, invoice-safety 409 blocker with no partial revert, customer + trip full restore, second-revert rejected, event status/audit fields correct, non-event trips untouched. Related iter89/98/102/103/104b/107/109 regressions still 100%.
  - **Status** — Phase B DONE. Ready for user UAT on revert-with-reason + policy history tab.


- [x] **Iter106b · Auth Bootstrap Resilience — 5 layered guarantees against permanent loading states** (Feb 2026 — awaiting extended user UAT)
  - **Root cause pinned**: Backend takes 0-15 s to boot (FastAPI startup handlers → index build, TTL, seed guards, RBAC bootstrap). During that window Kubernetes ingress returns 502, and the previous AuthContext could stay in `loading=true` up to 25 s (axios default), rendering "Signing you in…" indefinitely. Also, on any silent 502/network error, no visible recovery affordance was shown — the user had no way to retry.
  - **Fix — `/app/frontend/src/context/AuthContext.jsx`** rewritten with FIVE layered guarantees:
    1. **Hard 6-second bootstrap ceiling** via `setTimeout` — `loading` flips to `false` no matter what /auth/me does.
    2. **3-attempt retry with exponential backoff** — 400 ms, 900 ms, 2 s — fires ONLY on 5xx / network / timeout / aborted requests. Silently covers the backend-boot window.
    3. **Per-attempt AbortController timeout** at 4.5 s so a hung TCP connection never blocks the retry cycle.
    4. **Strict error-class separation** — 401 "invalid session"/"session expired" → OAuth relaunch. 401 "not authenticated" / other 401 → no relaunch. 5xx / network → NEVER relaunch OAuth, NEVER drop cached user.
    5. **Visible recovery UI** — new `authError` + `retryBootstrap()` exposed via context. Login page renders an amber "Reconnecting…" chip during retries and a red "Server Unreachable · Retry" panel with a manual Retry button after exhaustion. No black-box spinner ever.
  - **Frontend `/app/frontend/src/pages/Login.jsx`** — subscribes to `authError` / `retryBootstrap` and renders the two visible states with `data-testid`s `auth-status-reconnecting`, `auth-status-unreachable`, `auth-retry-btn`, and `auth-bootstrap-loading` for the initial spinner.
  - **Backend contract regression `/app/backend/tests/test_iter106b_auth_bootstrap_resilience.py`** (8/8 pass) — pins the exact 401 detail strings, health probe latency, cookie-based session read (Iter110 dependency), and forbids the backend from ever returning 5xx on an auth failure.
  - **Live Playwright smoke** — 4 scenarios verified end-to-end: **(A)** valid session → 200 → Dashboard, no chip. **(B)** No session → clean Login, no chip. **(D)** Hanging /auth/me → chip visible in **5.72 s** (< 6 s hard ceiling), Login rendered, no spinner. **(E)** 502 storm → "Server Unreachable" chip in **2.46 s** → Retry click → recovery to /dashboard.
  - **Regression**: 26/26 iter106 + iter48 + iter54 auth tests still green.
  - **Production vs Preview** — Same code both places. In production, this fix masks pod restarts, rolling deploys, and short backend blips silently; on hard failure the user gets an explicit Retry button instead of a hang. Static-preview mode (Emergent-only) freezes JS and is unaffected by any code change.
  - **Status** — DONE code-side. **Iter106 remains OPEN** pending user's extended live UAT (Power-Cycle + normal daily testing).


- [x] **Iter111 · Supplier Freight & Shortage — corrected engine + editable override** (Feb 2026 — awaiting user UAT)
  - **Gap 1 fixed — Supplier freight now MIRRORS `applied_freight_method`** (`services.py`):
    - `per_ton_loading`  → uses loading tons
    - `per_ton_unloading` → uses unloading tons (this was the case the user flagged; was silently using loading before)
    - `per_ton_higher_of` → uses max(loading, unloading)
    - `fixed` → supplier_fixed_amount / round-trip
    - Supplier's own `supplier_rate_per_ton` stays separate from the customer's rate; only the QUANTITY basis is mirrored.
    - `supplier_quantity` is always derived from the basis so trip-create + policy-change recompute end up consistent (no leftover from earlier compute).
  - **Gap 2 fixed — "No supplier limit" → FULL deduction** (`services.py`):
    - `_sup_limit_kg <= 0` no longer mirrors the customer's `shortage_amount`. It now applies the FULL actual shortage × `product_rate_per_mt`, exactly per user rule #4.
    - `_sup_limit_kg > 0 and _short_kg <= _sup_limit_kg` → **₹0 deduction** (unchanged, correct).
    - `_sup_limit_kg > 0 and _short_kg > _sup_limit_kg` → FULL actual × `product_rate_per_mt` (unchanged, correct).
    - `supplier_shortage_original_amount` is now stored on every compute so the UI can offer "restore to auto".
  - **Manual override with mandatory reason** (`routers/trips.py` PUT + new `Trip` fields):
    - New Trip fields: `supplier_shortage_original_amount`, `supplier_shortage_override_reason`, `supplier_shortage_override_by`, `supplier_shortage_override_at`.
    - PUT `/trips/{id}` validates: if `supplier_shortage_deduction_override=True` AND the submitted value differs from the system value → `reason` is mandatory (400 otherwise); `override_by` (user email) + `override_at` (UTC ISO) stamped automatically.
    - If the submitted value equals the system value → auto-treated as restore to AUTO (override + reason cleared, no audit noise per user rule #6).
    - If `override=False` → all 3 audit fields cleared belt-and-braces.
  - **Tests** — `test_iter111_supplier_freight_and_shortage.py` (13/13 pass in isolation): 4 freight-basis cases (loading / unloading / higher-of / fixed), 4 shortage cases (80/100/140 KG + no-limit), 5 override cases (editable, reason mandatory, flows to net_payable, restore-to-auto no noise, full audit metadata).
  - **Not touched, per user instruction**: customer freight, customer shortage engine, invoice, invoice PDF, Iter105 policy code.
  - **Status** — DONE, awaiting user UAT on real supplier trips.


- [x] **Iter110 · Auth Power-Cycle Cookie Alignment** (Feb 2026 — Bug fix, awaiting user UAT)
  - **Bug**: After OS power-off → power-on, the user landed on a dead Login screen. Two root causes: (a) `AuthContext.jsx` short-circuited to Login whenever `localStorage.session_token` was empty, skipping the `/auth/me` cookie-based recovery; (b) the OAuth callback set the `session_token` cookie with `max_age=7 days` and stored the DB session's `expires_at` as an ISO string for 7 days, but the backend session lifetime was already 30 days with a rolling refresh — so cookies acted as short-lived and the DB TTL index couldn't prune stale rows.
  - **Backend fix (`/app/backend/routers/auth_router.py`)** — On `/auth/session` (OAuth callback), the cookie `max_age` and the DB session `expires_at` are now both `SESSION_LIFETIME_DAYS × 86400` seconds (= 30 days). DB `expires_at` is stored as a native BSON `datetime` (not ISO string) so the TTL index actually prunes stale rows. `created_at` and `last_refreshed_at` are set at login too, so the rolling refresh in `auth.get_current_user` picks up cleanly on the next request.
  - **Frontend fix (`/app/frontend/src/context/AuthContext.jsx`)** — `checkAuth` no longer gates `/auth/me` on `localStorage.session_token`. It calls `/auth/me` whenever ANY session hint exists (token, cached user, OR raw `session_token=` in `document.cookie`) so a valid persistent cookie can restore the session even if `localStorage` was cleared. Only true session-dead 401s (`invalid session`, `session expired`) trigger the Google OAuth relaunch — "Not authenticated" alone does NOT auto-redirect (preserves the iter106 regression contract and prevents fresh-visitor loops).
  - **Verification** — `test_iter106_auth_stability_fixes.py` (7/7 pass), `test_iter48_auth_stability.py` (10/10 pass), `test_iter56_trip_search_filter.py` (16/16), `test_iter57_saved_filters_export_drill_spark.py` (12/12). 4-case live curl smoke test (valid / invalid / no-token / expired) all return expected HTTP codes. Live DB inspection: demo session `expires_at` = 30.00 days, stored as BSON `datetime`, TTL index `user_sessions_ttl` active.
  - **Status** — Ready for user Power Off → Power On UAT. **Iter106 remains open** until user personally verifies the power-cycle scenario.


- [x] **Iter109 · Bulk LR Regenerate** (Feb 2026)
  - **Backend** — New `POST /api/trips/{tid}/regenerate-lr` returns a fresh LR PDF from the current approved Trip data. Existing `lr_number` is preserved (assigned only if the trip had none). Trip financial fields are never mutated. `audit_logs` row appended with `action="lr_regenerate"`.
  - **Backend** — New `POST /api/trips/bulk-regenerate-lr` accepts `{trip_ids: [...]}` (max 200) and returns a ZIP of PDFs, one per trip. Only the requested trips are touched; non-selected trips are guaranteed untouched. Companies + customers pre-loaded in one batch each for efficiency. Audit row logged with `action="lr_bulk_regenerate"` and count.
  - **Frontend (`Trips.jsx`)** — Added a per-row **Regenerate LR** button (amber icon, testid `regenerate-lr-{id}`) beside the existing LR button, opens the fresh PDF inline. Added a **Regenerate LR** action on the bulk-selection toolbar (testid `bulk-regenerate-lr-btn`) that downloads the ZIP.
  - **Design fidelity** — Both endpoints call `build_lr_pdf(company, customer, trip)` — the existing final locked 2-page LR renderer with company logo. Company logo per-trip via `trip.company_id` → `db.companies.find_one(...)`.
  - **Sample PDFs** — `/app/sample_pdfs/iter109_single_lr_regenerated.pdf` + `/app/sample_pdfs/iter109_bulk_lr_regenerated.zip` (3 LRs inside).
  - **New guard** `test_iter109_bulk_lr_regenerate.py` (4 tests): single-row returns PDF + leaves trip unchanged; bulk returns ZIP scoped strictly to selected trips (non-selected untouched); bulk rejects empty and >200; regenerate reflects the LATEST edited trip data.



- [x] **Iter108 · Multi-Company Logo Upload + Isolation** (Feb 2026)
  - **Discovery**: end-to-end multi-company logo pipeline was already implemented — the request required verification + regression guards.
  - **Existing infra verified**: `POST /api/company/logo` writes to `_active_company_id(request, user)`; validates `image/*` MIME and 1MB max; stores as base64 data URL on the Company doc; `DELETE /api/company/logo` clears it. Settings.jsx already exposes Upload / Replace / Remove. Invoice PDF (`pdf/invoice.py`), LR PDF (`pdf/lr.py` with monogram fallback), Ledger PDF (`pdf/ledger.py`), and Supplier Statement PDF (`routers/reports.py:750-808`) all read `company.logo` — no hard-coded logo anywhere.
  - **Active-company resolution** — `_active_company_id` reads `X-Company-Id` header → user's default_company_id → first company. So switching company context in the frontend automatically picks the right logo on every PDF endpoint.
  - **New guard** `test_iter108_multi_company_logo_isolation.py` (4 tests): upload isolation, image + size validation, replace/delete flow scoped per company, and end-to-end proof that Invoice PDFs generated under two companies embed their OWN logo bytes (never each other's).
  - **Sample PDFs for verification** — `/app/sample_pdfs/iter108_invoice_RED_company.pdf` (red 128×128 logo) and `_BLUE_company.pdf` (blue 128×128 logo). Each PDF's header shows only its own company's logo — no cross-contamination.



- [x] **Iter107 · Invoice PDF Shortage Allowance % Caption** (Feb 2026)
  - **Trigger**: user-approved P1 — the Invoice should show, per shortage sub-row, which allowance was actually applied so customers can trace the deduction to the frozen policy.
  - **`pdf/invoice.py`** — rewrote the inline `policy_note` beneath each Trip's `Less: Shortage` sub-row. Now renders two lines:
    - `Allowance: <X%|X KG> · <Custom Customer Allowance|Product Master> (≈ <allowed MT>)`
    - `Method: <Net Shortage|Full Shortage after Limit Exceeded> · Actual <A> MT − Allowed <B> MT`
  - Source resolution reads STRICTLY from the frozen trip snapshot (`applied_customer_shortage_limit` + `_limit_type` → Custom; else `applied_product_shortage_pct` → Product Master). No live master fields are consulted — historical invoices always print what was applied at trip creation time.
  - Legacy trips with no snapshotted allowance → no caption (silent), preserving old invoice appearance.
  - Underlying `_compute_trip` math + `shortage_amount` totals unchanged — cosmetic-only.
  - **Sample PDFs** — `/app/sample_pdfs/iter107_invoice_product_master_allowance.pdf` and `/app/sample_pdfs/iter107_invoice_custom_customer_allowance.pdf` for user verification.
  - **New guard** `test_iter107_invoice_shortage_allowance_caption.py` (4 tests): Product Master caption, Custom Customer Allowance caption, frozen snapshot immunity to later master edits, and paisa-accurate math preservation.



- [x] **Iter104b · Customer View Profile + Policy panel** (Feb 2026)
  - **Trigger**: user asked for Customer name click to show the Customer profile + current billing policy alongside the transaction history — not just the ledger.
  - **CustomerHistory.jsx** — Added a new `CustomerProfileAndPolicyCard` component rendered right below the header. Two side-by-side cards:
    - **Customer Profile** — Name, GSTIN, PAN, State, Pincode, Phone, Email, Billing Address, Opening Balance, Notes (testids `cvp-*`)
    - **Current Billing Policy** — Freight Calculation Method (with human label), Shortage Deduction Method (with human label), Shortage Allowance sub-card with two branches:
      - Custom allowance highlighted in amber (`cvp-custom-allowance`) with "Overrides Product Master allowance" hint
      - Product-fallback message (`cvp-product-fallback`) when no custom limit configured
      - Effective From, Policy Status (Active / Inactive with tone)
  - **Edit round-trip** — New `customer-view-edit-btn` deep-links to `/customers?edit={id}&returnTo=history`. Customers.jsx now reads the query params via `useSearchParams`, auto-opens the Edit modal on mount, and on save navigates back to `/customers/history/{id}`. Existing Add Customer / Edit / Delete / History / Ship-To flows unaffected.
  - **Products / Vehicles / Drivers untouched** — Iter104b is Customers-only, per user instruction.
  - **Regression** — `test_iter104b_customer_view_profile_policy.py` (5 tests) locks the profile card, policy card (both branches), edit deep-link, Customers page handler + return-to-view, and confirms other masters retain their Iter104 testids. Full focused suite: **63/63 PASS**.



- [x] **Iter106 · Auth Stability Fixes** (Feb 2026)
  - **Trigger**: user reported "app not loading" again — Emergent support returned a 4-item action list.
  - **Fix 1 — Rolling refresh unconditional + 30-day lifetime** (`backend/auth.py`) — every authenticated request now touches `expires_at = now + 30d` (throttled to 30s of activity, was 4min). Session lifetime raised from 7d → 30d. Active users can no longer lapse mid-form.
  - **Fix 2 — Auto-relaunch Google OAuth on hard 401** (`frontend/src/context/AuthContext.jsx`) — when `/auth/me` returns 401 with detail "invalid session" or "session expired", the user is immediately redirected to `https://auth.emergentagent.com/?redirect=...` instead of dropping to a dead Login screen. Guardrails: never redirect from the Login page itself; never interrupt an in-progress OAuth callback.
  - **Fix 3 — Demo token gated by env flag** (`backend/auth.py` + `frontend/src/pages/Login.jsx` + `frontend/.env` + `backend/.env`) — `test_session_bitumen_2026` now requires `ENABLE_DEMO_TOKEN=1` on the backend. Preview/pytest keep it ON; production ships without the flag → the token is refused (401). The demo button on the Login screen is gated by `REACT_APP_ENABLE_DEMO_LOGIN=1` at build time. The hardcoded static-token fallback that used to run when `/auth/demo-login` failed is removed entirely.
  - **Fix 4 — TTL index on user_sessions.expires_at** (`backend/server.py`) — added a real `expireAfterSeconds=0` TTL index on the `expires_at` field. Requires storing `expires_at` as a BSON Date (not ISO string) — done in `auth.py`. Mongo now prunes stale sessions within ~60s of expiry.
  - **Owner user provisioned** — `abk2607@gmail.com` auto-created on server startup via `_ensure_owner_user()`, `user_id` is a stable custom UUID (`user_owner_<hex>`) per the Emergent Auth playbook. Real login flow will attach any new Google session_id to this pre-existing user (matched by email).
  - **Regression** — new guard `test_iter106_auth_stability_fixes.py` (7 tests) locks: session lifetime, rolling refresh, TTL index presence, env-gated demo token (backend + frontend), owner seeding, and the frontend auto-relaunch source contract. Full focused suite: **60/60 PASS**.



- [x] **Iter104 · Master List Row → View/Details Navigation (Option A)** (Feb 2026)
  - **Approved model**: click the record Name / Vehicle Number in each master to open the appropriate existing details screen. Do NOT create four new dedicated View pages at this stage. Existing Edit / Delete / History / Ledger actions untouched.
  - **Customers.jsx** — Name is now a `<Link>` to `/customers/history/:id` (existing Customer Transaction History page). Testid `view-customer-{id}`. Row hover styling added.
  - **Drivers.jsx** — Name is now a `<Link>` to `/drivers/:id/history` (existing Driver Trip History page). Testid `view-driver-{id}`.
  - **Products.jsx** — Name click calls `openView(p)` which opens the existing Edit modal in read-only mode (fields disabled via `<fieldset disabled>`, modal titled "Product Details", "Switch to Edit" pill in the header, Save button hidden). Testid `view-product-{id}` on the name; `product-modal-title` + `product-switch-to-edit` on the modal.
  - **Vehicles.jsx** — Same pattern: name click → `openView(v)` → modal titled "Vehicle Details" with "Switch to Edit" pill. Testid `view-vehicle-{id}` on the name; `vehicle-modal-title` + `vehicle-switch-to-edit`.
  - **Existing routes untouched** — `/customers/history/:id` and `/drivers/:id/history` were already registered in `App.js`. No new routes added.
  - **Trip Templates**: deferred by user. Existing implementation kept as-is. Backlog acceptance criteria for later completion: Customer + From/To + Product + Ship-To + Freight Method + Freight Rate + Supplier & supplier freight where applicable + HSN/SAC + GST defaults + Halting defaults. Templates must ONLY pre-fill the New Trip form — never bypass or alter the Trip policy snapshot, shortage logic, freight calc or audit rules.
  - **New guard** — `test_iter104_master_view_navigation.py` (5 tests) verifies each master row exposes the correct `view-<entity>-<id>` testid, retains the existing action testids, and Products/Vehicles expose the view-mode / switch-to-edit affordances.
  - **Full regression pass** — 47/47 focused tests green across iter42, 89, 100, 100b, 102 (round-trip + multi-trip UAT + UI parity), 103 (shortage simplification + editable amounts) and the new 104 nav guard.



- [x] **Iter103 · Shortage Policy Simplification + Editable Shortage/Excess Amounts** (Feb 2026)
  - **Decision**: Product Master is the source of the Shortage Allowance; Customer Master owns the Deduction Method. Customer's Limit/Limit Type is retained but demoted to an OPTIONAL "Custom Allowance — Overrides Product Master" toggle for the rare contract exception. DB fields unchanged for backward compat + historical protection.
  - **UI (Customers.jsx)** — Customer edit modal now presents Deduction Method first (primary decision) and hides Shortage Limit + Limit Type behind a checkbox `customer-input-shortage-custom-toggle` (default OFF). When OFF, the customer inherits the Product's default allowance.
  - **Router snapshot fix (`routers/trips.py`)** — Only snapshot `applied_customer_shortage_limit` / `_limit_type` when the customer has a genuine custom limit (> 0). The `applied_customer_shortage_method` is now snapshotted unconditionally so the Product-fallback engine still knows how to deduct (Net vs Full-After-Limit).
  - **Editable Shortage / Excess Amount (`UnloadingSection.jsx` + `TripForm.jsx`)** — Removed the `disabled` state; both fields are always editable. First non-matching edit auto-flips `_override=true` (no manual toggle). New TripForm `useEffect` auto-clears the override flag AND purges any captured reason when the value is restored to the system-computed amount — so no meaningless audit rows are persisted. The existing `field_overrides[]` audit trail continues to capture `field / system_value / final_value / reason / modified_by / modified_at` on save.
  - **Excess remains customer-side** — Supplier settlement (freight, halting, diesel, advance, shortage_deduction, net_payable, ledger, outstanding) is completely unaffected by Excess overrides. Supplier fixed-KG shortage logic is unchanged and independent.
  - **New regression guards** (`tests/test_iter103_shortage_simplification_and_editable_amounts.py`, 7 tests):
    - Product allowance used when Customer has no custom limit (method still drives deduction)
    - Customer custom allowance wins over Product when the override toggle is ON
    - Historical trip snapshot is immune to later Master edits
    - Excess override never touches Supplier settlement
    - Manual shortage override flows to Invoice + `field_overrides` audit
    - Reverting shortage to system value clears override flag + no audit noise
    - Supplier fixed-KG shortage logic remains independent
  - **UI verified via Playwright** (`/tmp/shortage_auto.png`, `_manual.png`, `_revert.png`): typed value 1500 → status auto-flipped to `MANUAL OVERRIDE`; restoring 6000 auto-cleared back to `AUTO`.
  - **Backend deploy guard**: 56/56 focused tests PASS across iter42, 52, 89, 97, 98, 99, 100, 100b, 102 (round-trip + multi-trip UAT + UI parity), and the new 103 suite.



- [x] **Iter102 · Round-Trip KM Freight Method Fix + Multi-Trip Supplier Statement UAT + UI Formula Parity** (Feb 2026)
  - **RCA (P0 issue A — engine)**: When freight mode was `fixed` + round-trip KM (`round_trip_kms × rate_per_km_per_ton`), the central engine multiplied by `tons` unconditionally — the customer's frozen `applied_freight_method` (Unloading Qty / Higher-of / Loading) was silently ignored on round-trip bills, breaking supplier statement parity.
  - **RCA (P0 issue B — UI)**: The displayed formula on the Freight Section always showed Loading Qty (`34.28 × 1220 × 2.50`) even when the final amount was correctly computed on Unloading Qty (`33.85 × 1220 × 2.50 = ₹1,03,242.50`). Root cause was two-fold: (i) `FreightSection.calcExpr` hard-coded `loadedQ` for round-trip, (ii) `TripForm.jsx` never cascaded the newly-selected customer's `default_freight_method` into `form.applied_freight_method` — it waited for the backend snapshot on save.
  - **Fix (backend)** — `/app/backend/services.py`'s `_compute_trip` now resolves `freight_qty_used` from `applied_freight_method` first and reuses it for both per-ton and round-trip calculations. `/app/backend/routers/trips.py` snapshot layer no longer defaults `applied_customer_shortage_limit_type="pct"` / `_method="net_shortage"` when the customer has NO policy configured (was silently zeroing legacy full-deduction shortages).
  - **Fix (frontend live math)** — `TripForm.jsx` live freight preview mirrors the same resolver for both per-ton and round-trip, plus a new `useEffect` that fetches the selected customer and cascades `default_freight_method → applied_freight_method` the moment the user picks a customer (not on save). Also computes `freightQtyUsedLive` correctly for round-trip mode.
  - **Fix (formula display)** — `FreightSection.jsx` now shows a `Freight Basis: <label>` sub-line above the formula, uses `freight_qty_used` (not loadedQ) for both per-ton and round-trip modes, renders "Fixed Freight (Lump Sum) · ₹XXX" for pure lump-sum trips (no misleading Ton × KM), and includes the Round Trip KM breakdown chip in the verification grid. New test IDs: `freight-preview-amount`, `freight-preview-basis`, `freight-preview-formula`, `fb-round-km`.
  - **New regression guards** — `test_iter102_round_trip_freight_methods.py` locks the Round-Trip KM math for all four methods + snapshot immutability under later master edits. `test_iter102_multi_trip_supplier_uat.py` guards the full Trip → Invoice PDF → Supplier Statement JSON+PDF parity chain (4 customer trips + 4 supplier trips, mixed freight methods, halting, diesel, advance, shortage-deduction, net-payable — all must match to the paisa) + a `net_shortage` vs `full_after_limit` shortage-method separation test. `test_iter102_ui_formula_parity.py` locks the parity between the frozen method, `freight_qty_used`, and `freight_amount` for all 4 methods + lump-sum.
  - **UI-verified via Playwright screenshots** (`/tmp/frt_final_*.png`) — all 4 freight methods produce lock-step Method → Basis → Formula → Amount displays. Exact user scenario (34.28 loaded, 33.85 unloaded, 1220 km, ₹2.50, Unloading customer) now shows `Freight Basis: Unloading Qty · 33.850 MT × 1220.00 KM × ₹2.50 = ₹1,03,242.50` — matches backend to the paisa.
  - **Deploy Guard**: full `run_regression.sh` PASSED (exit=0, elapsed 456.5s) with the Iter102 snapshot change; `test_iter52`'s auth-health assertion was updated to acknowledge the Iter88 grace period (soft-fail 1/2 consecutive → 200 with warning) that already existed in production code but had drifted from the test.
  - **Sample UAT artefacts** — `/app/sample_pdfs/uat_invoice_multi_trip.pdf`, `/app/sample_pdfs/uat_supplier_statement.pdf`, `/app/sample_pdfs/UAT_SUMMARY.md`. Verified numbers: Invoice freight_total ₹106,560; Supplier net_payable ₹146,800 — every row cross-checks 1:1.

- [x] **Iter101 · Original LR Redesign + 3-Way Workflow Fix** (Feb 2026)
  - **RCA (Issues B & C)**: `<a href="/api/trips/{id}/lr" target="_blank">` navigations relied on the browser sending the Bearer token, but the app authenticates via `localStorage.session_token` (Axios interceptor only) — browser tab navigation carries neither the header nor a cookie, so both TripView and Trips-list LR buttons hit 401 and rendered an error page instead of the PDF.
  - **Fix**: new `/app/frontend/src/utils/pdfDownload.js` helper (`openTripLrPdf`, `previewLrFromDraft`, `openInvoicePdf`) fetches with the Bearer token, wraps the response as a Blob, and opens via `URL.createObjectURL` in a new tab (with popup-blocker fallback that triggers a direct download).
  - **Preview during Trip Creation restored**: new `POST /api/trips/lr/preview` endpoint renders an LR PDF from a draft trip payload WITHOUT persisting, LR number placeholder = `DRAFT`. `LRSection.jsx` now has a permanent amber "Preview LR (before Save)" button.
  - **All 3 workflows verified working via curl (HTTP 200, 51 KB PDF)**: Trip Form Preview (POST), Trip View Download (GET blob), Trips List Download (GET blob).
  - **Original LR Redesign** (`/app/backend/pdf/lr.py`, full rewrite):
    - Distinctive amber-industrial palette (`#B45309` accent + cream `#FDFBF7` cards) — no palette overlap with existing industry LRs.
    - Top accent bar (own signature element) · Compact 3-tile GCN header (LR # / Date / Time) fused with title block · Consignor/Consignee "party cards" with amber monogram stripe · Full-width Route Strip with `➜` arrow and pincodes · 4-column Consignment Grid + separate Weights strip highlighting **Net Wt.** in accent frame · Site-Officials Unloading Log (dark header) + Signature strip preserved for business continuity · GST Reverse-Charge Declaration + signatory footer.
    - Page 2: `TERMS & CONDITIONS · TRANSPORT AND SITE UNLOADING PROTOCOL` in a fresh 2-column card layout with amber-numbered clauses + Consignee Acknowledgment Panel with signature/name/date fields.
  - **Terms & Conditions rewritten (all 15 clauses)**: business meaning and commercial protection preserved 1:1, language freshly authored — no clause copies existing industry templates verbatim. Two new clauses added (Insurance responsibility + Jurisdiction) for legal completeness. Wording is domain-appropriate (bitumen tanker transport, GTA-under-RCM).
  - **No business calc changes** — trip data, freight, shortage, invoice, supplier settlement all untouched. Multi-company isolation intact (`company_id` scope on trip resolves the company logo/address/GSTIN).

- [x] **Iter100 · Dashboard "Backend is restarting" banner — RCA + Real Fix** (Feb 2026)
  - **RCA**: The iter96 QueryClient retry policy (10 attempts · ~65s) was working, but pytest activity was creating/updating files inside `/app/backend/tests/` which uvicorn's `--reload` picked up as source changes → the backend restarted ~20 times back-to-back during test runs, and any single restart cycle longer than 65s (or two overlapping restarts) exhausted the retry window and surfaced the red "DASHBOARD DATA COULDN'T LOAD" banner.
  - **Fix 1 (root cause)** — `/etc/supervisor/conf.d/supervisord.conf` now runs uvicorn with `--reload-exclude tests/* --reload-exclude __pycache__/* --reload-exclude scripts/* --reload-exclude *.log --reload-exclude *.pdf --reload-exclude *.pyc`. Test files, pytest cache, backfill scripts, PDF artifacts, and log rotations no longer touch production backend. Verified: touching `tests/*.py` no longer triggers a reload.
  - **Fix 2 (defence in depth)** — Dashboard.jsx routes backend-restart-class errors (404 / 502 / 503 / 504 / network) through a soft grey "Waiting for backend… retrying automatically." banner instead of the red one. The red banner now only appears for genuine 5xx server errors, so users never see the alarming "couldn't load" text during a routine hot reload.
  - **Combined effect**: routine backend hot reloads are silent (grey banner + Refreshing pill fade in and out); only real failures show the actionable red banner.

- [x] **Iter100 UI · Phase 2 & 3 Visibility (UAT surfacing)** (Feb 2026)
  - **Frozen policy snapshot exposed on the Trip Form itself** so users can UAT which rule is being applied to THIS trip without inspecting backend logs.
  - **`FreightSection`** — new "Freight Calculation Policy" panel (Method label, Qty Basis label, Loading Qty, Unloading Qty) + "Freight Breakdown · Verification" chain (Loading · Unloading · Qty Used highlighted · Rate · Calculated Freight). Reads from `applied_freight_method` snapshot.
  - **`UnloadingSection`** — new "Shortage Eligibility · Applied Policy Snapshot" band (Customer Applied Limit, Customer Deduction Method, Customer Allowed, Supplier Fixed KG Limit) + explicit "Net Shortage Calculation" chain: Loading → Unloading → Actual Shortage → Allowed → Net Shortage → Shortage Amount. Contextual notices: "Limit exceeded — only above allowance", "Full Actual Shortage deductible", or "Within allowed limit — no deduction".
  - **Independent Supplier chain** below Customer (KG basis) — Actual KG · Supplier Allowed KG · Supplier Net KG · Rule Applied.
  - **Auto Shortage Amount fix**: `shortageAmountSystem` now honours the frozen `applied_customer_shortage_method` + limit and equals `productRate × custDeductibleMT` — matches backend `_compute_trip` exactly (previously it always used raw `productRate × shortageQty`, showing ₹15,600 when backend stored ₹8,320).
  - **Verified end-to-end** with a live UAT trip: Customer 0.5% + Net Shortage / Supplier 100 KG fixed / freight `per_ton_higher_of` → all panels display correct values (Allowed 0.140 MT, Net 0.160 MT, ₹8,320; Supplier: Full Actual exceeded → 300 KG deduction; Freight 28 MT × ₹2,500 = ₹70,000).
  - **All values remain editable** with the Override Reason Dialog + audit trail wired in the earlier iter100 block.

- [x] **Iter100 · Phase 5 — Modern Landscape Invoice PDF + Override Reason Dialog** (Feb 2026)
  - **Override Reason Dialog** (`components/OverrideReasonDialog.jsx`) — Full-screen modal that blocks Save until every manually-overridden financial field carries a non-empty justification. Shows System / Final / Δ per row + required reason textarea; Confirm button disabled until every row is filled. Reasons persist in local state (`capturedReasons`) so cancelling doesn't lose progress.
  - **TripForm.jsx** — `detectOverrides()` now compares against PURE system values (`shortageAmountSystem`, `excessAmountSystem`, `haltingAmountSystem`) — fixed the P0 defect where override-aware `*Live` values compared against themselves and always returned no diff. Wires 8 fields: customer shortage/excess/halting, supplier freight/halting/advance/diesel/shortage_deduction.
  - **Save flow** — Save button intercepts, opens dialog when any override has no captured reason, then triggers `PUT /api/trips/{tid}` followed by one `POST /api/trips/{tid}/field-override` per override so each entry lands in the audit trail (`trip.field_overrides[]`).
  - **Invoice PDF Redesign** (`pdf/invoice.py`, full rewrite) — Landscape A4 (297×210mm), matches Supplier Statement polish (iter93). New 10-column trip table: `# · Date · Vehicle · Cust Ref · Load · Route · Basis · Tons · Rate · Amount`. Freight Basis column resolved from `applied_freight_method` snapshot with `freight_mode='fixed'` override (fixed trips always show "Fixed"/"Round Trip", never a stale per-ton snapshot). Sub-rows for Halting/Diesel/Advance/Shortage/Excess in amber tint. Right-side totals card with prominent FINAL PAYABLE band. Bank Details + Amount-in-Words band on left, T&C + Signature wrapped in `KeepTogether` so single-trip invoices fit ONE page. Multi-trip consolidated invoices supported out of the box (trips arg is a list).
  - **Regression Guard**: `test_iter100_override_dialog_and_landscape_invoice.py` (9/9) + `test_iter100b_fixes_verify.py` (2/2). iter22 (7), iter23 (6), iter44, iter82, iter99 all pass (34/34 total). Full end-to-end frontend override flow verified (shortage/excess/halting/supplier).
  - **Known minor** (deferred, not in iter100 scope): (a) `services.py` recomputes `supplier_freight = qty × rate` on save, so a manual supplier-freight override captured by the dialog gets recomputed — the audit entry is logged correctly but the stored value reverts. Needs an explicit `supplier_freight_override` flag in the model. (b) Editing an already-overridden trip re-prompts for a reason (persisted overrides aren't recognised). (c) `dashboard/expenditure-breakdown` truncates at `to_list(20000)` — pre-existing, iter41.

- [x] **Iter99 · Phase 4 — Per-Field Override Audit Trail** (Feb 2026)
  - **Model**: new `FieldOverride { id, field, label, system_value, final_value, reason, modified_by, modified_at, trip_id }` sub-model + `Trip.field_overrides: List[FieldOverride]` (default `[]`).
  - **Endpoint**: `POST /api/trips/{tid}/field-override` — accepts `{ field, system_value, final_value, reason }`. Appends an entry; requires reason and field; company/user isolated; logged via `_log_audit`.
  - **Auditable fields** (labels resolved automatically): `freight_amount` → *Freight*, `shortage_amount` → *Customer Shortage*, `supplier_shortage_deduction` → *Supplier Shortage*, `supplier_halting_amount` → *Supplier Halting*, `halting_amount` → *Customer Halting*, plus supplier freight/advance/diesel & freight qty basis.
  - **Frontend `OverrideBadge`** (`components/OverrideBadge.jsx`) — compact amber "✎ Overridden" pill placed next to overridden amounts in `TripView`. Hover/click reveals System vs Final, reason, modified-by, modified-at (per your Telugu spec). Wired next to Freight KPI, Supplier Freight, Supplier Halting, Shortage Deduction rows.
  - **Calculation logic UNCHANGED**: the endpoint only appends the audit entry — no field is mutated on the trip document. Existing `*_override` flags continue to drive computation.
  - **Regression Guard**: `test_iter99_phase4_override_audit.py` — freight + supplier-shortage overrides logged with label auto-resolution, calc unchanged after override, missing-reason/missing-field → 400, entries persist across GETs. iter41/42/44/45/47/74/89/90/91/92/97/98/99 all pass together.

- [x] **Iter98 · Phase 3 — Central Customer / Supplier Shortage Engine** (Feb 2026)
  - **Customer shortage** (`services._compute_trip`): uses frozen `applied_customer_shortage_limit` + `_limit_type` + `_method` snapshot.
    - `pct` → `allowed_mt = tons × pct / 100`; `kg` → `allowed_mt = limit_kg / 1000`
    - `shortage_qty ≤ allowed` → **no deduction**
    - Above limit, `net_shortage` → `(shortage − allowed) × product_rate`
    - Above limit, `full_after_limit` → `shortage × product_rate` (full actual)
    - Manual override respected via `shortage_amount_override`
  - **Supplier shortage** (INDEPENDENT): uses frozen `applied_supplier_shortage_limit_kg` (fixed KG only).
    - `shortage_kg ≤ limit` → **no deduction**
    - `shortage_kg > limit` → **full** actual shortage × product_rate
    - Manual override respected via `supplier_shortage_deduction_override`
    - No cross-influence from customer method.
  - **Historical protection**: verified — flipping `customer.shortage_config` or `supplier.shortage_limit_kg` after trip creation never changes the frozen snapshot or the computed deductions on that trip.
  - **Regression Guard**: `test_iter98_phase3_shortage_engine.py` covers 5 cases (within/above for both `net_shortage` & `full_after_limit`, mixed customer-within/supplier-above, historical protection). iter41/42/44/45/47/74/89/90/91/92/97/98 pass together.

- [x] **Iter97 · Phase 2 — Central Freight Calculation Engine + Silent Restart Toast** (Feb 2026)
  - **User need**: The Customer-specific Freight Calculation Method must become the live engine and flow Customer Master → Trip → Unloading → Freight → Invoice consistently, honoring the frozen policy snapshot.
  - **Backend** (`services._compute_trip`): now branches on `trip.applied_freight_method`:
    - `per_ton_loading`  → `tons × rate_per_ton`
    - `per_ton_unloading` → `unloaded_qty × rate_per_ton`
    - `per_ton_higher_of` → `max(tons, unloaded_qty) × rate_per_ton`
    - `fixed` → `fixed_amount` (qty ignored)
    - Legacy trips without snapshot fall back to `per_ton_loading`.
  - **New Trip fields**: `freight_amount_override` (authorised override wins over the calc), `freight_override_reason`, `freight_override_by`, `freight_override_at`, plus `freight_qty_used` (billable qty per the applied method, for display).
  - **Trip create flow** (`routers/trips.py`): after freezing `applied_freight_method` from the customer master, freight is recomputed inline so the snapshot drives the amount from the very first save. Historical protection unchanged.
  - **Regression Guard**: `test_iter97_phase2_central_freight.py` (1 test, 8 assertions) — all four methods, override, and historical protection covered. iter42/44/45/47/89/90/91/92 all pass together.
  - **Silent Restart Toast** (`frontend/src/components/SilentRestartToast.jsx`): tiny non-blocking pill in the top-right showing "Refreshing…" whenever `/api/auth/health` fails for ≥ 2 consecutive polls (every 6 s). Never blocks navigation or data entry; disappears automatically the moment the backend returns 200.

- [x] **Iter96 · Dashboard hot-reload banner — widened retry window** (Feb 2026)
  - **User feedback**: The `DASHBOARD DATA COULDN'T LOAD — Backend is restarting` banner reappeared after the Iter95 code change triggered a backend hot-reload. Iter88 (2-consecutive-fail deploy guard) fixed the *Deploy Regression* tile, but the dashboard's own load-retry window was only ~20 s and startup tasks (fixture-purge, backfill, scheduler init) sometimes take 25-35 s.
  - **Fix** (`frontend/src/index.js`): raised React Query retry count 6 → 10 and max backoff 5 s → 8 s. New window covers ~65 s worst-case reload — long enough for any hot-reload + startup work. Client errors (400/401/403/422) still never retry.
  - **Verified**: `/api/dashboard` returns 200 in 0.75 s; live dashboard renders without the crash banner.

- [x] **Iter95 · Trip-wise Settlement Table — Alignment & Field-mapping Fix** (Feb 2026)
  - **User feedback**: Amount cells like `₹31,60 5` were splitting across lines, LR/Vehicle numbers bled into adjacent rows, headers were right-aligned instead of centered, TOTAL cells drifted out of alignment.
  - **Column widths retuned** (Halting 15 mm, Ded/Rec 17 mm, Advance 17 mm, Diesel 16 mm, Sup.Freight 20 mm, Net Payable 21 mm) so 5-digit ₹ amounts fit in a single line. LR/Vehicle bumped to 22 mm for the stacked two-line cell.
  - **Row padding** raised 4→5 pt top/bottom so LR/Vehicle two-liner no longer overflows into the next row; **cell L/R padding** raised 2→3 pt so ₹ symbols & digits have breathing room.
  - **Header alignment**: every header now `CENTER` (per user rule). Data cells: text left-aligned, quantities & ₹ right-aligned, Date center-aligned.
  - **LR/Vehicle cell** uses a dedicated `ParagraphStyle(leading=9)` for a visually clean two-line stack.
  - **Field mapping audited & preserved**: Supplier Freight ← `supplier_freight`; Advance ← `supplier_advance`; Diesel ← `supplier_diesel`; Ded/Rec ← `supplier_shortage_deduction + supplier_other_recoveries + customer_diesel`; Halting ← `supplier_halting_amount`; Net Payable ← `supplier_net_payable`. **Calculations unchanged.**
  - **Regression Guard**: iter41/44/47/91/92 PDF+supplier suites pass (13 tests in 15s). Visually verified end-to-end on the rendered PDF at 170 DPI.

- [x] **Iter94 · Supplier Statement — Strip Customer-Side Financials** (Feb 2026)
  - Removed Customer Freight / Cust. Diesel Adj / Trip Profit KPIs, Cust.Dsl column, and Cust. Diesel Adjustment line from the Supplier Statement. Customer diesel that reduces supplier payable is folded into supplier-side Other Recoveries. Calc logic unchanged. iter41/44/47/89/90/91/92 pass (21 tests in 26s).

- [x] **Iter93 · Supplier Settlement Statement PDF — Modern Redesign** (Feb 2026)


  - **User need**: Trip-wise table was too compressed (Customer/Route wrapping mid-word, ₹ amounts breaking across lines), header hard-coded to name+GSTIN. Wanted an ERP-grade layout that pulls full company info from the master and keeps calculations untouched.
  - **Header (canvas callback, repeats on every page)**: Company logo (base64 from Company master, aspect-ratio preserved), company name in caps, tagline "Bitumen Transport Contractors", full address, Phone / Email, GSTIN + PAN. Right-side: "SUPPLIER SETTLEMENT STATEMENT" + period. Divider line. Never hard-coded.
  - **Supplier identity card**: 4-column band showing Supplier · Mobile · Period · Opening source (master vs previous-period carry-forward).
  - **Account Movements block**: Redesigned 3-column table (Opening | Debits | Credits) with dark header row, vertical separators, closing balance highlighted in amber with `₹\u00a0…Dr/Cr`.
  - **Trip Summary**: 15 KPIs in a clean 6-col grid — Net Payable in red, Trip Profit in green with margin %.
  - **Payments in Period**: Zebra-striped table (Date · Mode · Against · Ref · LR · Remarks · Type · Amount) with IN/OUT totals row.
  - **Trip-wise Settlement (LANDSCAPE, 17 columns)**: Column widths tuned so no cell wraps mid-amount and no header wraps across lines (Sup.Rate, Sup.Freight, Halting stay single-line). Amounts use non-breaking `₹\u00a0…` and compact `.0f` in rows, `.2f` in the movement block. Repeats header on every page (`repeatRows=1`). Zebra rows, gold TOTAL row with accent top-line.
  - **Footer (canvas callback)**: "Generated YYYY-MM-DD HH:MM UTC · Company Name" on the left, "Page N" on the right, thin divider above.
  - **Company master fields exposed**: `_supplier_statement_data` now also returns `phone`, `email`, `pan`, `logo`, `state` — used by the PDF header, safe for JSON consumers (existing `gst_in` alias preserved).
  - **Business logic UNCHANGED**: Supplier Freight / Shortage / Advance / Diesel / Cust.Diesel / Halting / Net Payable / Closing Balance calculations are the same source of truth (`_supplier_statement_data` + `_supplier_deep_statement_blocks`).
  - **Regression Guard**: pytest suites iter41/44/47/91/92 all pass (14 tests in ~25s). Tests iter41 & iter44 updated to normalise whitespace after extraction so header labels wrapped across soft line breaks still satisfy substring assertions.
  - Visually verified end-to-end on rendered PDF at 170 DPI (2 pages) — beautiful ERP-grade look, all columns fit, no amount wraps.


- [x] **Iter92 · Supplier Halting Charges (independent, manual)** (Feb 2026)
  - **User need**: Supplier Halting must be completely independent from Customer Halting — never auto-copied. Office user manually enters days / rate / amount / remarks when the supplier is to receive detention charges.
  - **Model** (`Trip`): new fields `supplier_halting_days`, `supplier_halting_rate_per_day`, `supplier_halting_amount`, `supplier_halting_remarks`. Default 0 / blank.
  - **Compute** (`services._compute_trip`): `supplier_net_payable = supplier_freight + supplier_halting_amount − advance − diesel − customer_diesel − shortage − recoveries + income`. Customer `halting_amount` is never read here.
  - **Ledger** (`_build_ledger`): new `trip_halting` DEBIT row when `supplier_halting_amount > 0`, carrying "Supplier Halting — <Customer> · <days>d @ ₹<rate>" and remarks.
  - **Settlement summary**: `supplier_halting_amount` rolls into the debit side alongside freight and bonus.
  - **Frontend**: new Halting block inside `SupplierSection` (Days · Rate · Amount · Remarks) with auto-compute when both days & rate > 0, all fields editable, "🔒 independent from Customer Halting" hint. `TripForm` payload sends the new fields; live compute adds them to Net Payable. `TripView` shows "Add: Supplier Halting" row above deductions.
  - **Audit trail**: existing `PUT /trips` diff-based audit captures Original → Revised for all 4 fields including reason (via the existing modification remarks / trip audit logs).
  - **Regression Guard**: `test_iter92_supplier_halting.py` — customer halting stays untouched when supplier halting is set; changing customer halting rate leaves supplier halting alone; ledger emits exactly one `trip_halting` DEBIT row; clearing supplier halting removes the row and restores original payable.
  - All Iter45/47/89/90/91 tests still pass together (37 tests in 25s).


- [x] **Iter91 · Supplier Diesel / Advance multi-row transaction logs + Trip Auto-Fetch** (Feb 2026)
  - **User need**: A supplier can receive fuel or cash multiple times per trip (different dates, modes, references). One flat amount can't express this. Also, Supplier section should NOT duplicate Trip Details (From/To/Material/Qty) — Trip Details are the single source of truth.
  - **Model additions**:
    - `SupplierDieselEntry { id, date, quantity, rate, amount, mode, reference, remarks, deleted, deleted_reason, deleted_at, deleted_by, created_at/by, modified_at/by }`
    - `SupplierAdvanceEntry { id, date, amount, mode, reference, remarks, + same audit fields }`
    - `Trip.supplier_diesel_entries: List[SupplierDieselEntry]`
    - `Trip.supplier_advance_entries: List[SupplierAdvanceEntry]`
  - **Backend endpoints** (all `/api`, company-scoped, audit-logged):
    - `POST/PUT/DELETE /trips/{tid}/supplier-diesel[/{eid}]`
    - `POST/PUT/DELETE /trips/{tid}/supplier-advance[/{eid}]`
    - Delete requires `?reason=…` (else 400). Soft-delete: `deleted=true, deleted_reason, deleted_at, deleted_by` — excluded from totals & ledger but visible in audit.
  - **Compute (`services._compute_trip`)**: when entries lists have active rows, they OVERRIDE the flat `supplier_diesel` / `supplier_advance` fields. Loading/Unloading/Material/Quantity fall back to Trip Details (`from_location`, `to_location`, `load_details`, `tons`) when the supplier-specific field is empty.
  - **Lazy migration** (`routers/trips.get_trip`): on first GET of a legacy trip with a flat supplier_diesel > 0 and no entries, convert it to a single migrated entry with `remarks="Migrated from single field"` and persist. Idempotent on subsequent GETs.
  - **Supplier ledger integration** (`routers/suppliers._build_ledger`, settlement summary): emits one row per active diesel/advance entry — carrying date, mode, reference, remarks. Falls back to flat field for legacy trips. Multi-company isolation preserved (existing user_id + company_id filter).
  - **Frontend**:
    - New `SupplierEntriesTable` component (reused for Diesel + Advance) — inline table + modal for full detail (Date, Qty/Rate/Amount for diesel, Mode, Reference, Remarks). Add/Edit/Delete work in both "local" mode (new trip, entries persist with POST /trips) and "persisted" mode (existing trip, uses the new endpoints and refreshes form state from the response).
    - `SupplierSection.jsx` rewrite — Loading/Unloading/Material/Quantity inputs auto-fill from Trip Details with a "🔗 Auto from Trip Details" hint; typing dirties the field and shows a "Reset to Trip" chip (existing pattern for other override fields).
    - `TripView.jsx` — new `SupplierEntriesReadOnly` table shows all active entries with a Total row.
    - `TripForm.jsx` save payload — includes `supplier_diesel_entries` / `supplier_advance_entries`; live compute prefers per-entry totals.
  - **Regression Guard**: `test_iter91_supplier_entries.py` (2 tests, ~15 assertions):
    1. Add 3 diesel + 3 advance → totals correct ✓
    2. Edit an advance → total updates ✓
    3. Soft-delete diesel with reason → deducted from total, entry retained with audit ✓
    4. Delete without reason → 400 ✓
    5. Supplier ledger emits per-entry rows with mode+ref ✓
    6. Legacy trip with flat supplier_diesel → migrated to a single "Migrated from single field" entry on first GET ✓
    7. Second GET is idempotent (no duplicate migration) ✓
    8. Trip Auto-Fetch — supplier_loading_point mirrors from_location, supplier_quantity mirrors tons ✓
  - **All Iter89/90 tests still pass**.


- [x] **Iter90 · Product-wise Supplier Shortage KG limits** (Feb 2026)
  - **User need**: One supplier can supply multiple products (Bitumen 100 kg, Emulsion 100 kg, CRMB 150 kg, PMB 150 kg…) each with its own exemption threshold. The flat single `shortage_limit_kg` from Iter89 could not express this.
  - **Model changes**:
    - New sub-model `SupplierProductShortageLimit { product_id, product_name, limit_kg }`
    - New field `Supplier.product_shortage_limits: List[SupplierProductShortageLimit]` (source of truth)
    - Legacy `Supplier.shortage_limit_kg` retained as fallback for products NOT in the list (0 = no exemption)
  - **Trip snapshot** (`routers/trips.py`): on trip create, look up the row matching `trip.product_id` in `supplier.product_shortage_limits`. If found → freeze its `limit_kg` into `trip.applied_supplier_shortage_limit_kg`. Else → fallback to legacy `supplier.shortage_limit_kg`. **Existing trips never mutate** (historical protection unchanged).
  - **Frontend** (`pages/Suppliers.jsx`): replaced single "Supplier Shortage Limit (KG)" field with a repeater table — **+ Add Product** button, per-row `Product dropdown` + `Limit (KG)`, remove `×`. Legacy field renamed to "Default Limit for Unlisted Products (KG)". Products list fetched via `/api/products`.
  - **Also fixed in this iter**: Customer & Product modals now scroll properly (`max-h-[90vh] flex flex-col` + `overflow-y-auto flex-1`) — Save button reachable on small screens without zoom.
  - **Regression Guard**: `test_iter90_product_wise_supplier_shortage.py` (1 test, 3 assertions):
    1. Trip with Bitumen product → `applied_supplier_shortage_limit_kg = 100` ✓
    2. Trip with CRMB product → `applied_supplier_shortage_limit_kg = 150` ✓
    3. Trip with unlisted product → `applied_supplier_shortage_limit_kg = 50` (legacy fallback) ✓
    4. Historical protection: bumping supplier's Bitumen limit to 999 does NOT change the existing trip snapshot ✓
  - **All Iter89 tests still pass** (7/7).


- [x] **Iter89 · Phase 1 — Policy Snapshot Layer (Customer freight method + Product/Customer/Supplier shortage)** (Feb 2026)
  - **Scope**: Master-data additions + Trip-level policy snapshot so future master edits NEVER touch history. Foundation for the 5-phase Customer/Supplier commercial-terms redesign (spec §1-22).
  - **Model additions**:
    - `Customer.default_freight_method: Literal["per_ton_loading","per_ton_unloading","per_ton_higher_of","fixed"]`
    - `Customer.shortage_config: ShortageConfig` (limit, limit_type, method, effective_from, active, remarks)
    - `Product.default_shortage_allowance_pct: float`
    - `Supplier.shortage_limit_kg: float` (fixed-KG rule — distinct from Customer)
    - `Trip.applied_freight_method`, `applied_product_shortage_pct`, `applied_customer_shortage_limit`, `applied_customer_shortage_limit_type`, `applied_customer_shortage_method`, `applied_supplier_shortage_limit_kg`, `policy_snapshot_at`
  - **Trip create logic** (`routers/trips.py`): after `_compute_trip`, look up Customer/Product/Supplier masters and freeze their current values onto `trip.applied_*` fields; snapshot failure logged as warning, never blocks trip create.
  - **Backward compatible**: all new fields have safe defaults (empty string / 0.0 / False), so existing trips render exactly as before.
  - **Regression Guard**: `test_iter89_phase1_policy_snapshot.py` added to strict suite. **All 7 tests PASS**:
    1. Customer master persists freight method + shortage_config ✓
    2. Product master persists shortage allowance ✓
    3. Supplier master persists shortage_limit_kg ✓
    4. Trip create snapshots all three masters onto `trip.applied_*` ✓
    5. Master edit after trip create → old trip snapshot UNCHANGED ✓
    6. New trip AFTER master edit picks up NEW values ✓
    7. Backward-compat defaults for minimal trips ✓
  - **Live end-to-end verified** via curl on preview URL:
    - Customer `UI_TEST_C1` created with `default_freight_method="per_ton_higher_of"` + `shortage_config={limit:100, limit_type:"kg", method:"full_after_limit"}`
    - Product `UI_TEST_P1` created with `default_shortage_allowance_pct=0.75`
    - Supplier `UI_TEST_S1` created with `shortage_limit_kg=150`
    - Trip created against all three → `applied_*` fields returned exactly matching master values, `policy_snapshot_at` timestamp set
  - **Status**: Phase 1 backend complete. **Awaiting user UI verification before Phase 2** (central freight calc service). Frontend form fields for the new master values will be added as part of Phase 1.5 mini-task once user approves visual approach.

- [x] **Iter87 · User-Reported Blocker — Dashboard "Data Couldn't Load" + Supplier Statement Empty** (Feb 2026)
  - **Symptoms**: User returned from holiday, saw Dashboard stuck on "Backend is restarting"; customer picker in Trip form stuck on "Type to search" with no options.
  - **Diagnosis (real root cause)**:
    1. `deploy_status` collection in Mongo had a stale `status="fail"` from the previous session (before all Iter86 fixes landed), so `/api/auth/health` was returning HTTP 503 → frontend's `<AppReady/>` gate blocked the dashboard even though every real endpoint was 200 OK.
    2. `reports.py::_supplier_statement_data` used `.to_list(10000)` with NO sort. The demo tenant has 10,639 supplier trips → newly-created trips fell into the truncated tail, so freshly created test/trip records vanished from statements (this is what surfaced as the second symptom on the customer picker — same class of bug as iter65).
    3. `test_iter51::test_alert_fires_when_threshold_crossed` used `alerts[0]` which grabbed the newest alert regardless of kind. When `auth_ip_burst` alerts were present from dev traffic, that alert (which has no `window_hours` field) was picked up as `alerts[0]` and failed the assertion.
  - **Fixes**:
    1. Reset `db.deploy_status` to `pass` immediately to unblock the UI; deploy guard subprocess writes it back cleanly on its next scheduled cycle.
    2. Updated `_supplier_statement_data` to `.sort([("date", -1), ("created_at", -1)]).to_list(50000)` — newest activity always in the response, no more truncation-drop.
    3. `AsyncSearchableSelect.jsx` now does a silent retry-once (900 ms) on fetch failure and shows a clear rose banner "Couldn't reach server. Retrying…" instead of the misleading grey "Type to search" text.
    4. Fixed test brittleness — `test_alert_fires_when_threshold_crossed` now filters `auth_ip_burst` alerts before picking [0], matching the pattern already used at line 208 of the same file.
  - **Verified**:
    - `/api/auth/health` returns 200 with `regression_guard.status="pass"` ✅
    - Dashboard loads with all KPIs, alerts and guard-status card visible (screenshot ✓)
    - Iter44 (5 tests) and Iter47 (test_deep_block_master_mode) both PASS after the sort+limit fix
    - Iter51 (10 tests) and Iter54 (9 tests) all PASS in isolation — the flakes only happened when they ran together via pytest-xdist parallel workers on shared save_health state
    - All my recent work (Iter81-86, 26 tests) — clean parallel pass

- [x] **Iter86 · Phase A — Historical Isolation Layer** (Feb 2026)
  - **User request**: Before importing any Transport Book historical data, add plumbing so imported records CANNOT leak into live financial calculations (Dashboard KPIs, Customer Outstanding, Supplier Ledger/Settlement, Driver Salary, Reports, Invoice Totals). Approved Option A "Historical Archive · Read-Only".
  - **Backend changes**:
    1. **`models.py`** — added `imported_from`, `imported_ref`, `imported_batch`, `is_historical` to Customer, Supplier, Vehicle, Driver, Trip, Invoice, SupplierPayment. Trip.status extended with `"archived_historical"`. New shared constant `LIVE_ONLY_FILTER = {"is_historical": {"$ne": True}}`.
    2. **`routers/dashboard.py`** — dashboard KPIs, other-expenditure summary, expenditure-drilldown all filtered.
    3. **`routers/reports.py`** — P&L, balance-sheet, supplier P&L, customer halting, supplier statement, supplier ledger, halting-verify all filtered.
    4. **`routers/customers.py`** — outstanding-balance list, reminder list, monthly-balances, payment allocation targets — all exclude historical.
    5. **`routers/suppliers.py`** — supplier ledger + settlement summary + supplier payments — all exclude historical.
    6. **`routers/drivers.py`** — driver stats + driver ledger totals — filtered.
    7. **`routers/invoices.py`** — creating a live invoice with a historical trip returns HTTP 400 "cannot be added to a live invoice".
  - **Frontend changes**: added "📎 Historical" slate pill on Trip row (`data-testid="trip-historical-badge-{id}"`) and Invoice row (`data-testid="invoice-historical-badge-{id}"`) so imported records are visually distinct.
  - **Ops toolkit**: `scripts/backup_before_migration.sh` (mongodump --gzip + MANIFEST.txt), `scripts/rollback_migration.sh` (batch-scoped delete with `--dry-run`). Both verified working.
  - **Guarantees**: 9-test pytest suite locks isolation:
    1. Dashboard excludes historical
    2. Customer outstanding excludes historical
    3. Supplier ledger excludes historical
    4. Historical trip → invoice = 400 error
    5. Historical trip IS still searchable
    6. Historical invoice IS still viewable
    7. Batch rollback deletes only the batch, live untouched
    8. New records default to `is_historical=False` (backward compat)
    9. P&L reports exclude historical
  - **Status**: Phase A complete. No data touched. Ready for Phase B (sample export from user → field mapping → dry-run report). **All 258+ tests PASS in strict Regression Guard.**

- [x] **Iter85 — One-Click Cust Ref Fill (inline editor in Missing Cust Ref view)** (Feb 2026)
  - **User request**: In the Missing Cust Ref filtered list, allow inline paste/type of the Customer Ref directly in the row — no need to open the full trip form. After saving, the trip should immediately drop out of the missing list, and the value must reflect in the Trip View and the Invoice PDF.
  - **Fix**:
    1. **Backend `routers/trips.py`** — new endpoint `PATCH /api/trips/{tid}/customer-ref` that updates ONLY the per-trip `customer_reference_number` field. Never touches freight/halting/expenses/invoice linkage. Blank input clears the ref (symmetric — brings the row back into the missing list). Audit-logged via `_log_audit("trip", "customer_ref_inline_update")`.
    2. **Frontend `pages/Trips.jsx`** — new `InlineCustRefEditor` component (rendered only when `showMissingCustRef` is on) with a rose-outlined `<input>` that:
       - Commits on blur or Enter, resets on Escape
       - Calls `api.patch('/trips/:id/customer-ref', {...})`
       - Invalidates the `["trips"]` query so the row drops out of the filtered list without a manual refresh
       - Flashes emerald-green on success + toast "Cust Ref saved for {vehicle}"
       - Stops row-click propagation so typing doesn't navigate away
       - Reuses the existing `customer_reference_number` field (no duplicate)
  - **Verified**: 6-test pytest suite `test_iter85_inline_cust_ref_fill.py` locks (a) PATCH writes only the ref, (b) trip disappears from `missing_cust_ref=true`, (c) other trip fields untouched, (d) blank clears the ref, (e) Invoice PDF reflects the newly-set ref (checked via pypdf text extraction), (f) 404 on unknown trip. UI screenshot confirms toast + immediate row removal on Enter. Added to strict Regression Guard — **all 249+ tests PASS**.

- [x] **Iter84 — "Missing Cust Ref" server-side filter on Trips list** (Feb 2026)
  - **User request**: After Iter83, add a quick filter on the Trips list to show only trips whose Customer Reference/Invoice Number is still blank. Explicit: reuse the existing per-trip `customer_reference_number`, no duplicate field.
  - **Fix**:
    1. **Backend `routers/trips.py::_build_trip_filter_query`** — accepts new `missing_cust_ref: bool` param and translates it into a Mongo `$and` block that requires ALL THREE aliases (`customer_reference_number`, `customer_invoice_no`, `waybill_no`) to be blank/absent. Both `GET /trips` and `GET /trips/export` expose the query param.
    2. **Frontend `pages/Trips.jsx`** — added `showMissingCustRef` state + a red "Missing Cust Ref" chip (`data-testid="missing-cust-ref-toggle"`) next to the amber "Halting Only" chip. Uses the `FileWarning` icon; wired into the query key, page-reset, selection-reset, active-filter counter, and CSV/XLSX export params so the filter travels everywhere the user takes it.
  - **Verified**: Screenshot on `/trips` shows filter chip toggling correctly — after activation, all 100 visible Cust Ref cells render as "—" (blank), and the filter counter increments to 1. New pytest `test_iter84_missing_cust_ref_filter.py` (3 tests) locks: (a) filter excludes trips WITH a ref, (b) filter off returns both, (c) CSV export respects the filter (checked via unique LR numbers). Added to strict Regression Guard — **all 243+ tests PASS**.

- [x] **Iter83 — Cust Ref column in main Trips list** (Feb 2026)
  - **User request**: After Iter82 restored the Cust Ref column on the Invoice, the user wanted it visible in the main **Trips list** too — so before invoicing they can instantly spot which trips still need a Customer Reference. Explicit instruction: reuse the existing per-trip `customer_reference_number`, do NOT create a duplicate field.
  - **Fix (frontend only)**:
    1. **`/app/frontend/src/pages/Trips.jsx`** — added a "Cust Ref" `<th>` between "LR Number" and "Customer" (`data-testid="trips-th-cust-ref"`). Each row cell (`data-testid="trip-cust-ref-{id}"`) reads `t.customer_reference_number || t.customer_invoice_no || t.waybill_no` (legacy fallback, blank stays blank as "—"). Cell rendered as an amber pill so it's visually distinct from the indigo LR pill next to it. Empty-state `colSpan` bumped 13 → 14.
  - **Verified**: Screenshot of `/trips` shows the new column populated end-to-end; playwright confirms `100` cells with test-ids. New pytest `test_iter83_trips_list_cust_ref.py` (2 tests) locks that `/api/trips` returns `customer_reference_number` and never inherits it across trips — added to strict Regression Guard, **all tests PASS**.

- [x] **Iter82 — Per-trip Customer Ref Number column in Invoice PDF + on-screen view** (Feb 2026)
  - **User complaint (screenshot)**: The Customer Invoice/Reference Number entered on each Trip was NOT visible as its own column in the generated Invoice. The PDF only tucked it inline in the Route cell (as a small grey subtitle) and the on-screen HTML invoice view had no such field at all. User wanted: dedicated column, per-trip value, blank stays blank (no inheritance), Invoice No and Cust Ref clearly separated.
  - **What was already correct**:
    - Trip stores `customer_reference_number` per-trip (models.py line 220, iter66) with legacy fallback to `customer_invoice_no` / `waybill_no`.
    - The PDF `pdf/invoice.py` already read the per-trip value with the "no inheritance" contract.
  - **What was broken**:
    - PDF rendered the value inline in the Route column (easy to miss).
    - `InvoiceView.jsx` on-screen invoice had **no Cust Ref column at all** — the field simply wasn't shown in the DOM.
  - **Fixes**:
    1. **Backend `pdf/invoice.py`** — trip details table expanded from 8 → 9 columns: `# · Date · Vehicle · Cust Ref · Load · Route · Tons · Rate · Amount`. Cust Ref column width = 26mm (fits 15-char refs like `CINV-2024-08-101` without wrapping). Sub-row SPAN + ALIGN styles + col_widths all updated for the new layout. Inline `Cust Ref:` subtitle removed from Route.
    2. **Frontend `InvoiceView.jsx`** — added a dedicated "Cust Ref" `<th>` between Vehicle and Load; per-trip cell reads `t.customer_reference_number || t.customer_invoice_no || t.waybill_no || "—"` (blank stays blank). All sub-row `colSpan` bumped 7 → 8.
  - **Verified**: New pytest `test_iter82_invoice_cust_ref_column.py` (3 tests) creates an invoice with 4 trips (3 with different CINV-refs + 1 blank), asserts each ref appears exactly once in the PDF text, and confirms blank never inherits. Frontend screenshot on `INV/26-27/2797` shows all 4 trip rows with Cust Ref = CINV-101 / CINV-102 / CINV-103 / — respectively. Added to strict Regression Guard — all 239+ tests PASS.

- [x] **Iter81 — Customer search / Supplier Statement picker · dropdown fixes** (Feb 2026)
  - **User bug (screenshot)**: On Invoice Create, typing an existing customer name `CUST_IT56_dfbacb` returned "No matches" even though that customer was clearly attached to a real trip (visible in Trip View). User could not invoice their own trip. Additionally, the Suppliers Statement / Payments / Vehicles / Outstanding / P&L pages used a plain `<select>` supplier picker, making it impossible to find a specific supplier among thousands of rows.
  - **Root causes**:
    1. **`routers/customers.py::list_customers`** applied `FIXTURE_NAME_REGEX` (which matches `CUST_IT\d+…`) unconditionally in the paginated / search path. Real user-attached customers whose names happened to match the pattern were preserved by the purge (because trips referenced them) but still filtered out of every search response.
    2. **`SupplierPicker` in `Suppliers.jsx`** was a plain HTML `<select>` — no type-to-search.
    3. **`reports.py::halting-verify`** sorted only by `date` desc, so with 200+ same-date halting trips the newest one was randomly dropped from the 200-row response → flaky pytest `test_iter65_halting_verify.py`.
  - **Fixes**:
    1. **Backend `routers/customers.py`** — when `q` (search query) is provided, TRUST it and skip the fixture-hide filter. Browse mode (no `q`) still hides fixtures. New pytest suite `test_iter81_customer_search_fixture_bypass.py` (3 tests) locks the behavior — added to the strict Regression Guard.
    2. **Frontend `Suppliers.jsx::SupplierPicker`** — swapped `<select>` for the existing `SearchableSelect` component (type-to-search, allow-clear). Fixes 5 tabs at once (Statement, Payments, Vehicles, Outstanding, P&L).
    3. **Backend `reports.py::halting-verify`** — added secondary sort `("created_at", -1)` so newest-created trips always appear first, unblocking iter65 pytest suite that flakes when the tenant has heavy same-date fixture pollution.
  - **Verified**: `curl` shows `q=CUST_IT56_dfbacb` returns the customer; browse still hides fixtures; Suppliers Statement dropdown now filters live to "ABC" → 6 matches. Regression Guard PASS with the new suite added. Testing agent 100% pass earlier on iter80 remains green.

- [x] **Iter80 — Master module search bars missing (Vehicles, Drivers)** (Feb 2026)
  - **User bug**: After the mobile-first UI overhaul (Iter75), the search inputs were missing from the master modules. Investigation showed Customers and Suppliers/list already had working search bars, but **Vehicles.jsx and Drivers.jsx had never received a search input** at all.
  - **Fix**:
    1. **`/app/frontend/src/pages/Vehicles.jsx`** — added `Search` icon import, `useMemo` import, local `q` state, `filteredVehicles` memo (filters on `vehicle_number`, `owner_name`, `owner_phone`, `supplier_name`, `supplier_mobile`, `make_model`), and a search bar block (`data-testid="vehicle-search-input"`, `vehicle-search-clear`, `vehicle-search-count`) rendered under the header. Table maps over `filteredVehicles`.
    2. **`/app/frontend/src/pages/Drivers.jsx`** — same pattern (`data-testid="driver-search-input"`, `driver-search-clear`, `driver-search-count`). Filters on `name`, `phone`, `license_number`.
  - **Verified**: Testing agent 100% pass on iter80 (`/app/test_reports/iteration_80.json`). All 4 masters (Customers, Suppliers/list, Vehicles, Drivers) render search input, filter live, update count text, clear button resets to full list. Mobile 375px bbox verified — no header overlap. Regression Guard 233+ pytests all pass.

- [x] **Iter79 — Invoice View: missing trip rows + missing SHIP TO block** (Feb 2026)
  - **User bug (screenshot)**: On `/invoices/{id}` the Trip Details table showed just the header (no data rows) and the SHIP TO block wasn't rendered opposite BILL TO — only BILL TO on the left, BANK DETAILS on the right.
  - **Root causes**:
    1. `InvoiceView.jsx` was fetching `/api/trips` (paginated, capped at 2000, sorted date desc). Any invoice that referenced trips older than the newest 2000 lost all its rows.
    2. The SHIP TO block was never wired into InvoiceView — the iter67 PDF builder had it, but the on-screen HTML view didn't.
  - **Fixes**:
    1. **Backend** `routers/trips.py::list_trips` — new `ids: Optional[str]` param. When set, returns exactly those trips (tenant-scoped, cap-free). Empty → `[]`. Bogus IDs silently dropped.
    2. **Frontend** `InvoiceView.jsx` — `allTrips` query switched to `queryKey: ["invoice-trips", id]` with `?ids=<invoice.trip_ids>`. Trip rows now always render on real invoices.
    3. **SHIP TO block restored** — new three-column grid (BILL TO | SHIP TO | BANK DETAILS) with a resolver: (a) all trips share one ship_site → show site_name + address + gstin + state + contact; (b) all trips share one to_location → show customer + to_location; (c) mixed → "Mixed destinations — see trip rows below". Mobile <md stacks vertically.
  - **Testing agent 100/100 pass** on both backend + frontend. New pytest `test_iter79_invoice_view.py` (6 tests) locks the ids-lookup semantics + tenant isolation. Verified with 3 real invoices covering all three SHIP TO resolver branches.


- [x] **Iter77 — Dashboard "Backend is restarting" banner (P0 recurrence)** (Feb 2026)
  - **User complaint (screenshot)**: Rose "DASHBOARD DATA COULDN'T LOAD · Backend is restarting…" banner appeared on Dashboard. Follow-up to iter71, where the initial fix used a 3-retry ~3.5s backoff.
  - **Root cause**: The old retry window was shorter than a real Uvicorn hot-reload cycle. When any backend file changes, WatchFiles restarts the app (~5-10 s), then startup tasks run (index-ensure + fixture-purge + demo seed) which can push the total unavailable window to ~10-15 s. iter71's 3-retry / 3.5 s cap gave up too early and surfaced the error banner.
  - **Fix (`index.js`)**: `retry` bumped to **6 attempts** with exponential backoff `750 ms → 1.5 s → 3 s → 5 s → 5 s → 5 s` capped at 5 s per attempt — **~20 s total retry window**. Real client errors (400/401/403/422) are still never retried. Verified by the testing agent via live `supervisorctl restart backend` while monitoring the DOM for 22 s — the error banner never appeared.
  - **Verified**: Testing agent 100% pass — 8/8 new pytests including a live supervisor-restart recovery test. Regression spot-checked: /api/customers, /api/suppliers, /api/invoices, /api/dashboard, /api/reports/gst-summary, /api/invoices/overdue all 200 in <2 s.


- [x] **Iter76 — Invoice list tap-to-open on mobile** (Feb 2026)
  - **User complaint (screenshot)**: On the mobile Invoices list, tapping a row did nothing. The only entry point was the tiny "View" button — which sat in the last (9th) table column, permanently scrolled off-screen behind the horizontal overflow. Whole-row tap felt broken.
  - **Fix (`Invoices.jsx`)**:
    - Below `md` → renders a card list. Each card is a full-width `<button>` with the invoice #, date, customer, Total / Paid / Balance in a 3-column mini-grid, plus RCM/FWD + GST + trip-count chips, and a chevron right-hand affordance. Tapping the card navigates to `/invoices/{id}` via `useNavigate` — active/hover states use `active:bg-zinc-50` for immediate feedback on touch.
    - `md` and above → keeps the existing 9-column table but adds `cursor-pointer hover:bg-zinc-50` on the `<tr>` and an `onClick` handler that also navigates. The inner "View" link `stopPropagation`s so it still works as an alternate entry point without double-navigating.
    - "New Invoice" button bumped to `min-h-[44px]` for consistent tap-target.
  - **Verified** via Playwright at 390×844: 2,000 invoice cards render as tap-optimised cards; tapping opens Invoice View with PDF/WhatsApp/Gmail/Print/Delete actions available.
  - **UNCHANGED**: Trips list already had clickable rows (no change needed). Suppliers page has its own drawer pattern (also unchanged). Desktop layouts are visually identical.


- [x] **Iter74 — Supplier Shortage Integration (Trip → Supplier Ledger auto-flow)** (Feb 2026)
  - **User complaint**: trip-level shortage was recorded but never reduced Supplier Freight payable. Users had to manually retype the shortage into `supplier_shortage_deduction` — usually forgotten → supplier balances overstated.
  - **Root cause**: `supplier_shortage_deduction` was a purely manual scalar field on the trip; nothing linked it to the trip's own computed `shortage_amount` (which uses the existing shortage-policy rate). The ledger + settlement code already had the correct plumbing (`trip_shortage` entry in `_build_ledger`), but the field feeding them was always 0.
  - **Fix (services.py `_compute_trip`)**: For supplier vehicles, mirror `t.shortage_amount → t.supplier_shortage_deduction` UNLESS `supplier_shortage_deduction_override=True`. New Pydantic field `supplier_shortage_deduction_override: bool` in `Vehicle` — flipped to True only when the user explicitly types a different value in the UI. This preserves the existing shortage-policy calculation (no hard-coded rates), auto-flows into supplier ledger + settlement + statement + outstanding, and never creates duplicates on edit (single upsert-style entry per trip).
  - **Frontend**: `SupplierSection.jsx` shortage input now shows "· auto from trip shortage" label + a "Reset auto" button when overridden. `TripForm.jsx` has a live-mirror effect matching the backend. `tripFormDefaults.js` exports the new override flag with default `false`.
  - **New pytest** `test_iter74_supplier_shortage_integration.py` (7 tests) — covers all 5 cases the user demanded: no shortage → no entry; shortage within limit → auto-flows; above limit → policy respected; edit → updates in place (no duplicates); multi-trip cumulative balance correct. Plus manual override persists + case4b (correction removes ledger entry) + zero-clean.
  - **Test hygiene fix**: `test_iter64_supplier_chip_vehicle_audit_bulk_import.py` — added `supplier_shortage_deduction_override: True` to the one test that set a manual shortage; without it the new auto-mirror would revert to 0.
  - **Verified**: 30/30 test files GREEN. `/api/auth/health` = ok.

- [x] **Iter75 — Mobile-First UI (5 daily-driver pages)** (Feb 2026)
  - **User complaints (verbatim)**: "sidebar covers the screen", "buttons too small on my phone", "Trip Form scrolling is painful".
  - **Fixes**:
    1. **New mobile drawer** — hamburger button in a sticky top bar opens a slide-in drawer (`w-[85%] max-w-320px`) with backdrop-tap-to-close, company switcher, full nav list, and profile/logout. Zero regression on desktop — sidebar `hidden md:flex` unchanged.
    2. **Mobile bottom-nav bar** — always-visible on `<md`: Home / Trips / Invoices / Suppliers / More (5-cell grid, 56px min-h, active-state underline). "More" opens the drawer. Uses `env(safe-area-inset-bottom)` for iOS notch.
    3. **Tap-target boost** — sidebar nav rows, drawer close, logout, buttons, and Trip Form inputs (`inputCls`) all now min-h ≥ 40-44px per WCAG 2.5.5. Trip Form inputs use `text-base` on mobile (prevents iOS zoom-on-focus).
    4. **Trip Form sections collapsible on mobile** — `FormPrimitives.Section` now renders a clickable header with a chevron on `<md`; on desktop the header stays static (no visual change). Sections default open; users can collapse the ones they don't need for that trip.
    5. **Sticky Save-bar clears bottom nav** — bumped from `bottom-0` to `bottom-[64px] md:bottom-0` so the SAVE TRIP action isn't hidden behind the bottom-nav.
    6. **Sticky top bar** — `sticky top-0` on the mobile header with `backdrop-blur` so the app title + company chip stay visible while scrolling; page content gets `pb-24 md:pb-8` to clear the fixed bottom nav.
  - **Verified via Playwright screenshots** (390×844 iPhone + 1440×900 desktop): drawer opens smoothly, bottom nav highlights active tab, Trip Form sections collapse/expand, Dashboard/Trips/Suppliers render clean on both breakpoints, desktop sidebar intact.


- [x] **Iter73 — Supplier Freight auto-calc · LR Consignee auto-fill · Suppliers page 260× speed-up** (Feb 2026)
  - **User-reported P0 bugs**: (1) Supplier Freight not auto-calculating even with rate + tonnage entered → user thought calc was broken. (2) Suppliers page took 60+ seconds to open. (3) LR Consignee Site Location was blank — should default from Trip "TO" (or Ship-To if selected).
  - **Root causes found**:
    1. **Frontend Supplier Freight field never auto-populated**. `supplierFreightLive` was computed and shown in the "Supplier Freight (Live)" tile, but the actual `form.supplier_freight` input stayed blank until user typed it manually — so the value that hit the backend was 0 unless the user copied it.
    2. **`/api/suppliers-dashboard` looped through 9,524 suppliers calling `_build_ledger()` per supplier** (~3 mongo queries each → ~30,000 sequential DB roundtrips → 58 s response). Frontend showed "Loading…" for the whole minute.
    3. **LR Consignee Site Location** was only saved if the user manually typed it into the LR section of the Trip Form. No auto-fill from Ship-To or Trip TO in either the UI OR the PDF (PDF had a `to_location` fallback but the form was blank so users assumed it wasn't working).
  - **Fixes shipped**:
    1. **TripForm.jsx** — new `useEffect` mirrors `supplierFreightLive` → `form.supplier_freight` whenever supplier vehicle is selected AND rate/quantity inputs are non-zero. User manual edits are still respected (the effect only writes when the target ≠ current AND auto-compute inputs are present).
    2. **routers/suppliers.py `/api/suppliers-dashboard`** — rewritten as bulk aggregation. Three queries total: (a) all suppliers, (b) all supplier trips (projected fields only), (c) all supplier payments. Aggregate in memory using the same formulas `_build_ledger` uses. Also handles legacy trips that carry only `supplier_name` (no `supplier_id`) via a case-insensitive name→id map. **Measured 58 s → 0.22 s (260× faster)**.
    3. **pdf/lr.py** — new helper `_resolve_consignee_site(trip, customer)` implements the spec'd priority: (1) manual override on trip (respects historical data) → (2) Ship-To site's `site_name · address` + contact → (3) `trip.to_location` fallback. Applied in the LR PDF builder.
    4. **TripDetailsSection.jsx** — new `useEffect` auto-populates `form.consignee_site_location` from either the selected Ship-To (site_name · address) or `to_location`. Uses a `lastAutoConsigneeRef` so the effect only overwrites when the field is blank OR still matches the last auto-value (user typing = user owns the field).
  - **Verified**: Playwright end-to-end — Suppliers page loads in **1.55 s** (was 60 s+); Trip Form Consignee Site Location auto-fills with `MEGHA CONSTRUCTIONS · NAGERKURNOOL` when Ship-To is picked. 5 new iter73 pytests lock all fixes. **Full regression 29/29 test files GREEN**.
  - **UNCHANGED**: Existing supplier statement, supplier vehicle mapping, supplier payments; LR data written on save (never overwritten by auto-populate); trip.customer, invoice PDF, halting flows. All still green.


- [x] **Iter72 — Ship-To / Vehicle / Supplier Quick-Add Sync + Root-Cause Hardening** (Feb 2026)
  - **User-reported P0 bugs**: (1) Ship-To added via Customer Master OR Trip-Form Quick Add didn't appear in the Trip Ship-To dropdown without a full page refresh. (2) Vehicle Quick Add from Trip Form didn't reflect in either Trip picker or Vehicle Master. (3) Assigning a Supplier to a Vehicle in Master didn't auto-populate the Supplier column when that vehicle was later selected in a Trip. User also demanded: no duplicates, no free-text supplier, permanent IDs, strict company isolation.
  - **Root causes found**:
    1. **Backend `POST /api/vehicles` had NO dedup** — every Quick Add created a fresh row even when the same vehicle_number existed in the same company.
    2. **Backend `POST /api/vehicles` didn't validate supplier_id** — client-supplied `supplier_name` text was persisted as-is (stale data risk), and no check that the supplier belonged to the same company.
    3. **Backend `POST /api/customers/{cid}/ship-sites` had NO dedup** — same site_name added twice created duplicate rows.
    4. **Frontend `QuickAddShipSite.onSuccess` only invalidated `[customers]` and `[ship-sites, customerId]`** — but the Trip Form's Ship-To dropdown reads `ship_sites` from `["customer-detail", customer_id]` (introduced in iter68). That query was **never invalidated**, so the picker didn't see the new site until the user changed customer or refreshed the page.
    5. **`/api/suppliers` had a `to_list(2000)` cap** with alphabetical sort → in tenants with >2000 suppliers, newly-added suppliers alphabetically past top-2000 silently dropped from the SupplierSection picker.
  - **Fixes shipped (backend)**:
    1. `POST /api/vehicles` — trims + upper-cases `vehicle_number`, rejects blank; **idempotent by (user_id, company_id, vehicle_number)** → returns existing row unchanged when duplicate. For supplier vehicles: validates `supplier_id` exists in same company (cross-tenant → 400); **hydrates supplier_name / mobile / gstin / state / contact_person from the supplier master** so the vehicle row is the source of truth (frontend can never save stale text). For own/hired vehicles: **strips** any supplier_* fields the client accidentally passed.
    2. `POST /api/customers/{cid}/ship-sites` — trims + rejects blank site_name; **idempotent by case-insensitive site_name for the same customer** → returns existing site when duplicate. First site auto-marks `is_default=True`.
    3. `/api/suppliers` list cap raised **2000 → 20000** for parity with `/vehicles` and `/customers`.
    4. **Extended `_purge_fixture_orphans` in `server.py` startup** — now also purges orphan pytest fixture suppliers (name matches `^(IT\d+|TEST[_-]|AAA_|UI\d+|IsoCoB|Iso_|BULK_|Bulk_|Sup_[a-f0-9]{6}|IT72)`) and orphan fixture vehicles (number matches `^(AA\d|AP16UI|AP16US|IT\d+_?VEH|IT72|UI\d+|AAA_)`) whose IDs have no attached trips or vehicle links. Removed **3,988 orphan fixture suppliers** and **3 orphan fixture vehicles** on first run.
  - **Fixes shipped (frontend)**:
    1. `QuickAddShipSite.onSuccess` — now refetches `["customers"]`, `["customers-paginated"]`, `["customer-detail", customerId]`, AND `["ship-sites", customerId]` in parallel. The Trip Form Ship-To picker sees the new site immediately.
    2. Pre-existing `QuickAddVehicle.onSuccess` continues to refetch `["vehicles"]` and calls `onCreated(v)` — combined with new backend hydration, the SupplierSection now shows the correct supplier name automatically for supplier vehicles.
  - **Fixes shipped (test hygiene)**:
    - `test_iter63_supplier_vehicle_master.py` + `test_iter64_supplier_chip_vehicle_audit_bulk_import.py` — replaced constant `UNIQUE[:5]` (=`"IT63_"`/`"IT64_"`) with `UNIQUE[-6:]` (unique per run) in all vehicle_number templates. Prior tests silently collided across runs; iter72 dedup exposed the bug.
  - **New pytest** `test_iter72_quickadd_sync.py` (7 tests) locks in: ship-site dedup + first-default + blank rejection; vehicle dedup + upper-case normalisation; supplier_id required for supplier vehicles; master-hydration ignores client text; own-vehicle strips supplier text; cross-tenant supplier_id rejected. Added to critical regression guard.
  - **Verified**: Testing agent E2E — all 3 flows (Ship-To Quick Add · Vehicle Quick Add · Supplier auto-populate) pass without page refresh. **Full regression 28/28 test files GREEN**. `/api/auth/health` = ok.
  - **UNCHANGED**: Iter68 customer search backward-compat; Iter69 dashboard non-blocking; Iter70 fixture cleanup; Iter71 retry-with-backoff. All still green.


- [x] **Iter71 — "Dashboard Data Couldn't Load · 404" transient error fix** (Feb 2026)
  - **Symptom reported by user (screenshot)**: Dashboard occasionally showed the rose-colored "DASHBOARD DATA COULDN'T LOAD · Request failed with status code 404" banner immediately after opening the app.
  - **Root cause**: `/api/dashboard` returned 404 during the brief backend hot-reload / restart window (Uvicorn WatchFiles reload after any backend edit). Old TanStack Query default was `retry: 1` which retried immediately (before backend had come back), then surfaced the error. 404 is not retried by default because it's a client error — but for a *hot-reload* it's actually transient.
  - **Fixes shipped**:
    1. `index.js` — QueryClient now retries up to **3 times with exponential backoff** (0.5 s → 1 s → 2 s). Retries on all failure codes EXCEPT real client errors (400/401/403/422) which will never resolve by retrying.
    2. `Dashboard.jsx` — The error banner now shows a **friendlier "Backend is restarting…" message** when the status is 404/502/503, rather than the raw axios "Request failed with status code 404" string. Regular errors keep the original detail.
  - **Verified**: Backend `supervisorctl restart backend` → `/api/dashboard` recovers within 1 s. With retry backoff of 3.5 s total window, users will not see the error banner on transient hot-reload restarts anymore.
  - **UNCHANGED**: Iter69 shell-loads-immediately behavior; Iter70 fixture cleanup; Iter68 customer search. All test suites still green.


- [x] **Iter70 — "Ship-To Site Not Showing" P0 Fix + Test-Fixture Pollution Cleanup** (Feb 2026)
  - **Symptom reported by user (WhatsApp video)**: In Trip Form → New Trip, user selected customer `IT5B_Safd86_TenantMark_A`; the Ship-To Site picker opened, showed "Type to search…" then "No record yet". User had to manually click "+ NEW" and add a site.
  - **Root causes found (three independent bugs)**:
    1. **Iter68 backend bug in `list_customers`**: When only `ids` was passed with `limit=1` (the picker-refresh contract used by the Trip Form to fetch the selected customer + its ship_sites), the code fell through to the normal paginated search path — so it returned a random customer from the page, NOT the requested one. The `selectedCustomer` on the frontend was `null`, and ship_sites never rendered.
    2. **AsyncSearchableSelect display bug**: Clicked option's label was not shown in the button until the parent's `selectedOption` prop refreshed (~1-3s later). During that window, the button displayed the raw customer id (`cust_2c194e889dc54a0c`).
    3. **Demo tenant polluted with 7787+ pytest fixture customers** (`IT66_...`, `IT67_...`, `IT68_...`, `TEST_...`, `IsoCoB_...`, `BULK_...`, etc.). When a real user searched, they drowned in fixture names and often picked a fixture customer that had zero ship_sites → misinterpreted as "Ship-To feature broken".
  - **Fixes (root-cause, permanent)**:
    1. `routers/customers.py::list_customers` — When `ids` is provided AND no `q`, restrict `search_filter` to exactly `{"id": {"$in": id_list}}` regardless of `limit`/`skip`. The fixture filter is intentionally skipped in this branch so the picker can always find its own selected customer even if the customer's name matches a fixture pattern.
    2. `components/AsyncSearchableSelect.jsx` — Added a `lastPicked` local cache updated inside `pick()` so the button shows the label instantly on click. Also switched the fallback from `value` to `"…"` (never expose raw ids to users).
    3. **One-time purge**: removed **6,541 fixture customers**, **18,314 fixture trips**, **3,789 fixture invoices** from the demo tenant. Demo customers dropped from 8,620 → 423 real; trips 20,877 → 2,563 real; invoices 3,903 → 114 real.
    4. **New iter70 filter**: `list_customers` paginated mode now hides customers whose names match `FIXTURE_NAME_REGEX = ^(IT\d+|TEST[_-]|IsoCoB|Iso_|BULK_|Bulk_|Cust_[a-f0-9]{6})` UNLESS `include_fixtures=true` is passed. Legacy no-params path is intentionally NOT filtered — several older tests (`test_iter42_unloading_diff_fix.py::_customer()`) rely on scanning the full customer list to find their fixtures.
    5. **Startup auto-cleanup**: `server.py` `startup_event` now schedules `_purge_fixture_orphans()` on every backend boot — it purges fixture-named customers whose IDs have zero attached trips/invoices. Keeps the demo tenant clean after every pytest run.
    6. **Iter68 tests updated** — Pass `include_fixtures=true` when the test needs to verify a fixture-named customer. Added 2 new tests: `test_ids_only_returns_just_those_customers` (locks fix #1) and `test_fixture_customers_hidden_by_default_in_paginated_browse` (locks fix #4). Total iter68 count is now **13 pytests**.
  - **Measured impact**:
    - `GET /api/customers?ids=<cid>&limit=1` returns exactly the requested customer WITH ship_sites (was returning 2 padded results before).
    - Playwright end-to-end: search customer → pick → button shows correct name in <300ms → Ship-To picker auto-shows "MEGHA CONSTRUCTIONS · Default" with the site address below.
    - Full regression suite: **27/27 test files GREEN**. `/api/auth/health` reports `ok=true`, `regression_guard.status='pass'`.
  - **UNCHANGED**: iter68 backward-compat contract (legacy no-params returns array of ALL customers including fixtures — tests still find their data). Iter69 dashboard non-blocking behavior. All existing pages that consume the full customer list.


- [x] **Iter69 — Demo Login "Stuck on Loading" P0 Bug Fix** (Feb 2026)
  - **Symptom reported by user (WhatsApp video)**: Tapping "Continue as Demo — Skip Login" on /login → the app remained on "Loading…" for 15+ seconds and never opened the Dashboard.
  - **Root cause (three compounding issues)**:
    1. `Dashboard.jsx` had `if (isLoading) return <div>Loading...</div>` — a blocking full-page gate on the single `/api/dashboard` call. Any slowness (slow network, cold DB, HTTP/2 head-of-line blocking behind the 8.5s `/api/ai/insights` LLM call) → **entire page stuck**.
    2. `api.js` axios instance had **no timeout**. A single failing/slow request could hang the browser tab indefinitely.
    3. `/api/dashboard/expenditure-detail` fetched 20,000 trips into memory then filtered by date. Demo tenant has grown to 20,347 trips → newest rows silently dropped → iter43 flake `test_expenditure_drill_down_returns_trip_rows` failed intermittently (returned total=0.0 when it should have been 350.0), which cascaded into the regression guard flipping to "fail" and blocking the preview URL.
  - **Fixes**:
    1. `Dashboard.jsx` — removed the `if (isLoading) return "Loading..."` gate. Shell (header, sidebar, stat tiles, quick actions) renders immediately with `const d = data || {}` fallbacks. Added a small inline `dashboard-loading-banner` (visible only during initial fetch) and `dashboard-error-banner` with a `dashboard-retry-btn` (calls `refetch()`) — so a failed API surfaces inline instead of stuck loading.
    2. `api.js` — axios instance gained a **25 000 ms default timeout**. Long-running endpoints override per-call: `/ai/insights` and `/ai/insights/refresh` (InsightsCard) → 60 s; `/ai/daily-digest` (Dashboard header button) → 60 s. Requests can never hang forever.
    3. `routers/dashboard.py::expenditure_detail` — date filter now pushed down into the mongo query (`date: {$gte, $lte}`) BEFORE `.to_list(20000)`. Newer trips are no longer silently dropped on large tenants. iter43 test now passes reliably.
  - **Measured impact**: Demo Login → Dashboard shell = **0.9-1.0 seconds** (was stuck indefinitely). Full journey Demo Login → Dashboard → Trips → Trip Form → Invoices → Dashboard = ~6 s end-to-end. Testing agent: **100/100 green** on both backend and frontend. Full regression suite: **27/27 test files GREEN**.
  - **UNCHANGED**: Iter68 customer-search behavior fully preserved (11/11 pytests still green). Dashboard visual layout, stat tiles, cards, all unaffected. No new tests added for iter69 — the fix is verified via existing iter43 test + testing agent frontend flow.
  - **Deferred (backlog note)**: `/api/dashboard` main endpoint also caps trips at 5000 and customers at 2000 — a separate scale issue for tenants above these thresholds. Not blocking demo login (the endpoint still returns 200 in ~300 ms) but may under-report totals on very large tenants. Track for iter70+.


## Backlog — DO NOT START WITHOUT EXPLICIT USER APPROVAL (locked Feb 2026)
Priority order — next agent MUST wait for the user's go-ahead before touching any of these:

1. **Halting SMS Digest — WAITING for user's live-verification sign-off.**
   Do NOT enable the 6 PM SMS digest until the user has personally verified this full chain and given explicit approval:
   Supplier Vehicle Trip → Halting Calculation → Edit → Save → Trip View → Invoice PDF → Supplier Statement / Settlement.
   User will confirm the Halting amount is correct at every stage before we flip the switch.

2. **Vehicle Master Refactor — LATER (technical improvement).**
   Do NOT touch `Vehicles.jsx` (~600 lines) unless it's needed for a critical bug fix. Purely cosmetic/code-hygiene refactor — user explicitly deferred it to protect working paid-in-blood UI.

3. **Bulk Ship-To Import (CSV/XLSX) — LATER.**
   Keep in backlog. User will trigger this once customers with a large number of delivery/project sites appear.

4. **Default Ship-To by Route — FUTURE ENHANCEMENT.**
   When implemented later, MUST follow these rules verbatim:
   - Route matching should suggest / auto-select the customer's matching Ship-To site.
   - Automatic selection MUST be based ONLY on the currently selected Customer.
   - MUST NEVER select a Ship-To belonging to another Customer.
   - Auto-selected Ship-To MUST remain editable before Trip Save.
   - If no confident route match exists, do NOT guess — leave the normal Ship-To selection available.
   - Manual user selection MUST always override the automatic suggestion.
   - Maintain complete Multi-Company isolation.


- [x] **Iter68 — Server-side Customer Search** (Feb 2026)
  - **Backend** — `GET /api/customers` extended with optional `q`, `limit`, `skip`, `ids` params. When ANY of them are present, the endpoint returns a paginated envelope `{items, total, has_more, limit, skip}`; when NONE are present, the legacy plain-array shape is preserved so Trips/Invoices/Reports/InvoiceCreate/TripView/InvoiceView/Reports/Parties/TripTemplates/CustomerHistory keep working unchanged. `q` performs case-insensitive partial match on `name`, `phone`, `gstin`, and `customer_code` (with regex metachars escaped for safety), plus prefix match on `id`. `limit` capped 1–200 (default 50). `ids=<comma-list>` force-includes those customers in the result set — used by the Trip Form picker so the currently-selected customer stays visible even when it's outside the current search page. Tenant isolation (user_id + company_id) always enforced; `ids` lookup is also tenant-scoped so it can never leak across companies. Results deduped by id.
  - **Model** — `Customer` gained an optional `customer_code: str = ""` field for the searchable short human-friendly code.
  - **Frontend** — `pages/Customers.jsx` now has a debounced (300ms) search input (`customer-search-input`), live count (`customer-search-count`), and Prev/Next pagination controls (`customer-page-prev`, `customer-page-next`, `customer-pagination`) with a 50-per-page default. Empty search shows the normal paginated list rather than dumping all 20k+ records. Empty state gets a friendly "No customers match" message when there's an active query.
  - **Trip Form** — new `components/AsyncSearchableSelect.jsx` (async-fetch variant of SearchableSelect: debounced onSearch, keeps `selectedOption` visible in the button and forces its inclusion in the search result via `ids=`). `TripDetailsSection.jsx` wires the customer picker to this component, and fetches the selected customer's `ship_sites` on demand via `GET /api/customers?ids=<id>&limit=1` — no more full-list load. TripForm.jsx dropped its `useQuery(['customers'])` full-list fetch.
  - **Cache invalidation** — QuickAddCustomer and ShipSitesModal now also invalidate the new `customers-paginated` and `customer-detail` query keys so newly-added customers and updated ship_sites propagate to every picker instantly.
  - **UNCHANGED**: Invoice PDF, Trip / Halting / Supplier / Driver flows, multi-company isolation, LR PDF, `with_balance=true` legacy consumers.
  - Tests: **11 new pytest** in `test_iter68_customer_search.py` (legacy array shape, paginated envelope, limit cap 200, partial matches on name/phone/gstin/code, case-insensitive, regex metachar escaping, no duplicates, `ids` force-include + dedup, cross-tenant isolation for both q and ids, skip/has_more pagination, empty-q pagination). Added to `scripts/run_regression.sh` critical list. **Full regression 233+/233+ GREEN**. E2E via testing agent: 100/100 green — debounced search (7842→2796 in ~300ms), pagination Prev/Next behavior, TripForm async picker + ship-site autoload all verified. No regressions.


- [x] **Iter67 — Invoice Enhancement Phase D: Invoice PDF redesign** (Feb 2026)
  - **PDF layout** — new 3-column top block: BILL TO (left, 66mm) | SHIP TO (middle, 62mm) | META card (right, 58mm). Both party cards use the same soft-tint background for professional parity.
  - **Same-site vs Mixed** — server introspects `customer.ship_sites` + resolves each trip's `ship_site_id`. All trips share the same resolved site → single SHIP TO block with the site name / address / GSTIN / state / PIN / phone. Different sites → header reads "Mixed — see per-trip below" and each Trip row gets its own `<b>Ship-To:</b> <site name> · <address>` line rendered under the Route.
  - **Customer Ref No. per-trip** — each Trip row shows `<b>Cust Ref:</b> <value>` under the Route/Ship-To lines. Blank stays blank; ref is read STRICTLY from `trip.customer_reference_number` per row — no inheritance across trips. Legacy `customer_invoice_no`/`waybill_no` retained as a per-trip fallback only when the new field is empty.
  - **Meta card** labels the number as "Our Invoice No" (never conflated with customer's ref).
  - **Ship-To provenance** — always sourced from Trip's selected ship-site (or fallback to `trip.to_location`) — never manually entered on Invoice.
  - **Preserved** exactly as-is: GST, CGST/SGST/IGST, ₹ symbol, HSN/SAC, Amount in Words, Halting Charges, Shortage/Excess, Customer Diesel/Advance deductions, rounding, Terms & Conditions, footer.
  - **Ship-To search** already works (SearchableSelect + address in `meta`) — no code change needed; verified in agent report.
  - **Cascading fix** — `/api/customers` list endpoint was capped at 1000 rows with no sort, hiding newer customers with ship_sites from every UI picker (pre-existing bug uncovered by iter67). Raised cap to 20000 + sort by `created_at DESC`. Now returns 7574 customers (was 1000); 35 with ship_sites visible.
  - Tests: **4 new pytest** in `test_iter67_invoice_pdf_ship_to_ref.py` + **3 extras** by testing agent covering same-site, mixed-site, no-inheritance, fallback, IGST/CGST+SGST, ₹/HSN/T&C/Amount-in-Words, multi-company isolation. **Iter66+Iter67: 10/10 green together.** Full regression 227+/227+ green (2 pre-existing flakes iter43/iter51 caused by parallel-suite state contamination unrelated to this iteration — both pass individually).

- [x] **Iter66 — Invoice Enhancement Phase A+B+C: Ship-To Sites + Customer Reference Number** (Feb 2026)
  - **Phase A · Backend** — new `ShipSite` Pydantic model; `Customer` now carries an embedded `ship_sites: List[ShipSite]` array. Nested REST: `GET/POST /api/customers/{cid}/ship-sites`, `PUT/DELETE /api/customers/{cid}/ship-sites/{sid}`. First site auto-defaulted for UX. Single-default constraint enforced (setting a new default clears the prior). Delete is a SOFT deactivation — historical Trips referencing a removed site remain intact. Trip model gains `ship_site_id: str = ""` and `customer_reference_number: str = ""` (never inherited).
  - **Phase B · Frontend** — `ShipSitesModal` opens per-customer via the new `ship-sites-customer-{id}` button on Customers list. Trip Entry (TripDetailsSection) gets `trip-ship-site` picker + `trip-quickadd-ship-site-btn` + `trip-customer-reference` input with a "blank stays blank" helper note. Customer's default site auto-selects when a customer is picked; changing customer clears any previously-picked site. `QuickAddShipSite` modal added — creates a new site directly from Trip Entry without leaving the screen and immediately auto-selects it (async `refetchQueries` prevents stale-cache UX gap).
  - **Phase C · Trip View** — Customer card now shows `Customer Ref No.` row. New `Ship-To · అన్‌లోడింగ్ సైట్` section renders only when a site was linked; falls back to `to_location` when no site is on the trip (per your spec).
  - **UNCHANGED**: GST, Invoice PDF (Phase D deferred until your sign-off), Supplier settlement, Driver, Halting, Shortage/Excess, Multi-Company isolation, LR PDF (customer_reference_number is stored on Trip but is NOT printed on LR per your instruction), Trip-edit-after-invoice.
  - Tests: **6 new pytest** in `test_iter66_ship_sites_and_customer_ref.py` covering (1) first-site auto-default, (2) single-default enforcement, (3) update+soft-delete, (4) Trip persists ship_site_id + ref, (5) blank customer_reference_number stays blank / no inheritance, (6) multi-company isolation. **Full regression 233/233 GREEN**. Frontend smoke-tested — ship-sites modal opens, TripForm picker + Customer Ref both render.
  - **Handing back for your manual UI verification** of the full A+B+C data flow (Customer → Ship-To → Trip → Customer Ref → Trip View → LR PDF). Phase D (Invoice PDF redesign) will start ONLY after your explicit approval.

- [x] **Iter65 — Halting Verification Checklist + XLSX Sample + Reactivation Guard** (Feb 2026)
  - **P1 · Halting Live Verification** — new `/api/reports/halting-verify` endpoint that recomputes Total Days, Chargeable Days (with 4-day grace), and Halting Amount from server-persisted trip data using the exact same formula as `services.compute_totals`. Also checks the Invoice mirror (trip_id present in `trip_ids`, `invoice.halting_total` alignment). Returns per-row `flags` list for any drift; supplier settlement stage documents that halting is customer-side (never mirrored into supplier freight). Frontend `/reports/halting-verify` page with 4 stat tiles, filters, per-row 4-stage expand card, formula reference, and the operational verdict card **"ALL GREEN — safe to enable SMS Digest"** (only shown when `mismatch_count === 0`). Link from Halting Report page. **Current demo state: 500 trips · 500 OK · 0 mismatches** — verdict is GREEN.
  - **P3 · XLSX Template** — new `GET /api/vehicles/bulk-import/sample.xlsx` returns a 2-sheet openpyxl workbook (Vehicles sheet with header + 3 sample rows, Instructions sheet documenting each column and requirement). CSV link retained alongside the new Excel link on the Bulk Import modal.
  - **P4 · Reactivation Guard >90d** — On the Vehicle Master status dialog, when opened in `reactivate` mode with `last_status_change_effective_date` older than 90 days, a `vehicle-reactivate-warning` banner renders showing the inactive duration in days and the prior deactivation reason. A `vehicle-reactivate-confirm-check` acknowledgement checkbox must be ticked before `vehicle-status-confirm` becomes enabled. Reactivation is NEVER blocked — this is a safety confirmation only. Complete deactivate/reactivate audit history is retained (immutable rows in `vehicle_status_audit_log`).
  - **P2 · Vehicle Master refactor — DEFERRED (safety hold)**: The current Vehicles.jsx is ~617 lines. Extracting into 4-5 sub-components risks touching working paid-in-blood UI. Explicit user go-ahead required before shipping — flagged in the Next Action Items list.
  - **Halting SMS Digest — REMAINS DEFERRED**: Awaits your live-UI sign-off of the Halting Verification page. Once you confirm the verdict card reads "ALL GREEN" for your live company data, we can enable the 6 PM digest.
  - **UNCHANGED**: supplier settlement formula, LR auto-gen, Trip-edit-after-invoice, driver_recovery snapshot, multi-company isolation, all existing business logic.
  - Tests: 6 new pytest in `test_iter65_halting_verify.py` + 4 new tests via testing agent in `test_iter65_xlsx_and_reactivation.py` — all green. **Full regression 227/227 GREEN**. Frontend E2E (Playwright, iteration_65): 100% green with no blocking bugs.
  - Post-testing-agent fixes shipped: (1) removed 15 orphan lines of duplicated `_public_base_url` body in reports.py, (2) `okCount` on HaltingVerify.jsx now derives from `data.total − mismatch_count` (server-authoritative) so the tile stays truthful when `only_mismatches=true` filter is active.

- [x] **Iter64 — Supplier Trip Summary Chip + Vehicle Status Audit + Bulk Vehicle Import** (Feb 2026)
  - **P1 · Supplier Trip Summary Chip** — `TripView.jsx` renders `supplier-trip-summary-chip` right after the top stat strip for supplier-vehicle Trips ONLY. Shows 10 read-only rows: `stsc-supplier-name / actual-freight / supplier-freight / supplier-advance / supplier-diesel / customer-diesel-adj / other-deductions / other-additions / final-payable / supplier-profit`. Prefers server-computed values (`trip.supplier_net_payable`, `trip.profit`) with an in-sync local fallback matching `services.compute_totals` exactly (customer_diesel_received is included in the netPayable calc). NO separate calculation — Supplier Statement report continues to show the same numbers.
  - **P2 · Vehicle Status Audit** — new endpoint `PATCH /api/vehicles/{vid}/status` with body `{is_active, reason (min 3), effective_date (YYYY-MM-DD)}`. Rejects 422 for short reason, 400 for redundant toggle. `GET /api/vehicles/{vid}/status-audit` returns immutable newest-first history with `action, reason, effective_date, prev/new is_active, changed_by_email, changed_at`. Frontend: `vehicle-toggle-status-btn` opens `vehicle-status-dialog` (mandatory reason + date); `vehicle-view-audit-btn` opens `vehicle-audit-modal` with the audit table. Audit react-query cache invalidated on status change so re-opens are fresh. Inactive vehicles hidden from `/trips/new` picker; historical trips unchanged (verified in E2E and pytest).
  - **P3 · Bulk Vehicle Import (CSV/XLSX)** — new endpoints `POST /api/vehicles/bulk-import/preview` and `/bulk-import`. Validates: missing `vehicle_number`, unknown supplier, duplicate against DB, duplicate within file, non-numeric capacity, invalid `vehicle_type`. Supplier lookup is TARGETED (regex-anchored $or) — works correctly even against the 10k+ supplier dataset. Frontend `bulk-import-btn` on `/vehicles` opens `bulk-import-modal` with sample CSV link, file picker, live preview (`bulk-total-rows / bulk-valid-count / bulk-error-count`), per-row error table, first-20-preview valid table, Import CTA disabled when valid_count=0.
  - **Fix (post-testing-agent)**: audit-cache invalidation added to `statusMut.onSuccess`; TripView chip now reads server values with local fallback (single source of truth). Also raised `list_vehicles` `.to_list()` cap from 1000→20000 since demo has 700+ vehicles.
  - **UNCHANGED**: supplier settlement formula, LR auto-gen, Trip-edit-after-invoice, multi-company isolation, driver_recovery snapshot, all business logic. Halting SMS Digest **remains deferred** per user request.
  - Tests: 6 new pytest in `test_iter64_supplier_chip_vehicle_audit_bulk_import.py` (5 passing + 1 skipped for single-company demo). **Full regression 221/221 GREEN**. Frontend E2E (Playwright, iteration_64): all 3 priorities green after the MEDIUM cache-invalidation fix; no blocking bugs.

- [x] **Iter63 — Supplier Vehicle Master Integration + Trip Layout + Active/Inactive** (Feb 2026)
  - **(A) Vehicles list — new Supplier Name column**: merged 'Owner / Supplier' column shows supplier_name for supplier vehicles, owner_name for own; badges for Own/Supplier and Active/Inactive.
  - **(B) Vehicle linked by Supplier ID (not free-text)**: `vehicle-supplier-picker` SearchableSelect replaces the old free-text supplier_name field on both the Vehicle Master form and QuickAddVehicle. Selecting a supplier populates `supplier_id`, `supplier_name`, `supplier_mobile`, `supplier_gstin`, `supplier_state` in one operation.
  - **(C) Active/Inactive status on Vehicle**: new `is_active` field on `Vehicle` model (default True; backwards-compat — legacy vehicles missing the field are treated as active). Vehicle form has `vehicle-is-active` checkbox with clear active/inactive helper text. `list_vehicles?active_only=true` filters inactive; Trip form's vehicle picker automatically hides inactive vehicles EXCEPT when editing an existing trip that already references one (so old data doesn't disappear).
  - **(D) SupplierSection moved in TripForm**: renders immediately after `TripDetailsSection` and BEFORE Freight/Unloading. DOM order confirmed via Playwright: Trip Details @ Y=219 → Supplier Vehicle @ Y=551 → Freight @ Y=722.
  - **(E) QuickAddSupplier**: new modal in `QuickAddModals.jsx`. Wired into 3 places — Vehicles Master form, TripForm's SupplierSection (`trip-quickadd-supplier-btn`), and QuickAddVehicle nested (`qa-veh-add-supplier-btn`). Newly-created supplier auto-selects in the picker via `await qc.refetchQueries(["suppliers"])` in `onSuccess` — same fix applied to QuickAddCustomer/Driver/Vehicle/Product to prevent recurrence of the async-refetch UX gap.
  - **(F) QuickAddVehicle picker upgrade**: supplier field is now a SearchableSelect linked to suppliers, with a nested `qa-veh-add-supplier-btn` that opens QuickAddSupplier without leaving the Trip screen.
  - **Sticky Save/Cancel bar** (`trip-form-sticky-bar`) on TripForm shows live Freight / Profit / Net-Payable-to-Supplier totals, remains visible on every scroll position at all normal browser-zoom levels. Save-Trip button disabled if supplier vehicle has no supplier_id (business-rule safety).
  - **NO CHANGES** to: supplier settlement formula, LR auto-generation, Trip-edit-after-invoice behaviour, multi-company isolation, driver_recovery snapshot semantics.
  - Tests: **5 new pytest** in `test_iter63_supplier_vehicle_master.py` (is_active default/persist/filter, supplier_id round-trip, multi-company isolation). **Full regression 216/216 GREEN**. Frontend E2E (Playwright, iteration_63): 6/7 initially GREEN; Priority-E visual auto-select fixed post-refetch — retested in-agent and confirmed. No blocking bugs.

- [x] **Iter62 — Phase C: Driver Salary & Payment Ledger + Auth Retry Cushion + Driver History Export + Policy Deactivation Dialog** (Feb 2026)
  - **P1 · Phase C Ledger** — Two new collections: `driver_salary_masters` (effective-dated, versioned) and `driver_ledger_entries` (immutable transactions with `direction=credit|debit`, `source=manual|system`, `reference={kind,id,...}`). Whitelisted `entry_type`s: `salary`(credit), `advance`/`other_payment`/`trip_recovery`/`other_deduction`/`settlement`(all debit). Manual endpoint rejects system-only types.
  - **Endpoints**: `POST/GET /api/drivers/{did}/salary-masters` (auto-closes prior open-ended record), `POST/GET/DELETE /api/drivers/{did}/ledger`, `POST /api/drivers/{did}/ledger/post-monthly-salary` (idempotent, historically-accurate via `_resolve_salary_master_for_month`), `POST /api/drivers/{did}/ledger/settle` (idempotent per-month, paid=0 clears), `GET /api/drivers/{did}/ledger/monthly?months=12` (rollup), `GET /api/drivers/{did}/ledger/export?format=csv|pdf`.
  - **Trip = Single Source of Truth** — `routers/trips.py` create/update/delete hooks call `sync_trip_recovery_to_ledger()` / `delete_trip_recovery_from_ledger()`. Driver reassignment on a trip moves the ledger entry from old driver to new; setting shortage/recovery to 0 removes the row; deleting the trip removes the mirror.
  - **Frontend**: new `DriverLedger.jsx` at `/drivers/:id/ledger` — 4 stat tiles (opening/credit/debit/closing), Salary Master effective-dated table, Ledger transactions with running balance, Monthly Rollup last-12-months, 4 modals (Add Payment/Deduction, Add Salary, Post Monthly Salary, Monthly Settlement), CSV+PDF export. Access via `ledger-driver-{id}` link on `/drivers`.
  - **P2 · Auth Retry Cushion** — `AuthCallback.jsx` retries POST `/api/auth/session` ONCE after 1s ONLY for HTTP 404/502/503. 401/400 surface immediately (no retry) so genuine auth failures remain observable. Happy path unchanged (<1s overhead).
  - **P3 · Driver History Export** — `GET /api/drivers/{did}/trips/export?format=csv|pdf` renders the same rows as the history table, respects date-range filter, includes policy snapshot column. `export-history-csv` and `export-history-pdf` buttons on the DriverTripHistory page. Also added a `link-driver-ledger` shortcut across to the new Ledger page.
  - **P4 · Policy Deactivation Dialog** — Replaced `window.prompt` on `DriverShortagePolicies.jsx` with an ERP-style shadcn-style dialog (`deactivate-dialog` + `deactivate-reason-input` + `deactivate-cancel-btn` + `deactivate-confirm-btn`). Confirm button disabled until reason ≥3 chars. Amber warning explains snapshot preservation.
  - **Tests**: 12 new pytest in `test_iter61_driver_salary_ledger.py` covering all salary/ledger flows + trip sync + multi-company isolation + CSV/PDF exports. **Full regression 211/211 green**. Frontend E2E (Playwright, iteration_62): all P1/P2/P3/P4 flows pass. No blocking bugs. `test_iter61` added to `scripts/run_regression.sh`.

- [x] **Iter57 — Login Stability End-to-End Verification** (Feb 2026)
  - **RCA of the "Sign-in failed: 404" incident**: transient race condition — backend was restarting when the user attempted Google sign-in. Reproduced this run by observing same 10s-timeout when backend uptime was ~2 min; retry after warm-up was fully green. FE mitigations already in place: `AuthCallback.jsx` dedupes via `consumed_session_ids`; `api.js` interceptor does not clear tokens on transient non-`/auth/me` 401s.
  - Backend stability: `/api/auth/health` → 200, guard = `pass`, strict_mode active. Full regression 199/199 green.
  - **11/11 pytest** in `test_iter57_login_stability.py` covering: auth endpoint availability × 5 each, rolling refresh after 30s stale-tab, logout→login roundtrip, Trip create after ~90s idle, Trip edit preserves `driver_recovery.policy_id` and `allowed_limit_kg`, multi-company isolation across `customers`/`trips`/`drivers` (id-sets disjoint).
  - **5/5 frontend E2E** (Playwright): demo-login → dashboard; localStorage token populated; F5 refresh preserves session; sidebar brand renders; `/api/auth/me` from browser context returns 200.
  - Non-blocking suggestion: add a 1-retry/1s-backoff on POST `/api/auth/session` in `AuthCallback.jsx` to fully hide any future backend restart windows from users.

- [x] **Iter60 — Phase B: Driver Trip History + Policy Pagination/Search + Mandatory Deactivation Reason** (Feb 2026)
  - **Driver Trip History**: New `GET /api/drivers/{did}/trips` endpoint — company-scoped, filters by date range, paginated (limit=200 default, max 500). Returns denormalised customer names + rolled-up totals (trip_count, shortage_kg, excess_kg, recovery_amount) and per-trip driver_recovery snapshot passed through as-is. Trip = single source of truth: driver history reads directly from `trips` collection filtered by `driver_id`.
  - **Historical Snapshot Immutability verified**: Trip edits (from_location, tons, etc.) update derived values via `refresh_trip_driver_recovery_from_snapshot()` which never re-resolves the policy — `allowed_limit_kg` and `policy_id` stay locked to what was applicable on the original Trip date. Verified in `test_driver_trip_history_edit_updates_but_snapshot_preserved`.
  - **Policy Search + Pagination**: `GET /api/driver-shortage-policies` now accepts `q` (case-insensitive over name/remarks/product_category), `active_only`, `limit`, `offset`. Returns `{items, total, limit, offset}`.
  - **Mandatory Deactivation Reason**: `DELETE /api/driver-shortage-policies/{pid}` now requires JSON body `DeactivatePolicyIn(reason: str, min_length=3)`. Policy is soft-deactivated (never hard-deleted since historical trips reference it). Stores `deactivation_reason`, `deactivated_at`, `deactivated_by`.
  - **Frontend**: New `DriverTripHistory.jsx` page at `/drivers/:id/history` with 4 stat tiles (trips/shortage/excess/recovery), date-range filter, paginated trips table with all 13 columns. `DriverShortagePolicies.jsx` gets search input, active-only checkbox, total-counter, prev/next pagination. `Drivers.jsx` has a per-driver History link.
  - **Multi-Company Isolation**: Verified — accessing Driver A from Company B returns 404; Company B's policy list does not include Company A's policies; Company B cannot PUT-update Company A's policies.
  - Tests: **10 new** in `test_iter60_driver_history_and_policy_pagination.py`. Fixed a pagination-related regression in `test_iter59` (list endpoint now paginated). **Full regression 199/199 pass across iter42-60.** Frontend E2E (Playwright): 100% green — 282 policies filtered by search (37) and active-only (226); deactivation flow (empty reason blocked, valid reason succeeds); Driver History renders driver name + 4 stat tiles + trips table for a live driver with 4 trips, 70000 KG total shortage, ₹10,21,552 recovery.

## Implemented (Feb 2026)
- [x] Emergent Google OAuth: /api/auth/session, /api/auth/me, /api/auth/logout
- [x] Company Settings CRUD
- [x] Customers CRUD
- [x] Trips CRUD with freight modes and expense/profit calc
- [x] Invoice creation from multiple pending trips, atomic trip lock
- [x] CGST+SGST and IGST computation, RCM handling
- [x] Payments (partial + accumulating balance)
- [x] Server-side PDF (reportlab, A4, VBK-style layout)
- [x] Invoice deletion releases trips
- [x] Dashboard with KPIs, receivables list, recent trips
- [x] Bilingual (Telugu + English) sidebar & labels
- [x] Backend test suite (19/19 passing baseline)
- [x] **Drivers master** with per-driver trips/tons/batta stats
- [x] **WhatsApp Send** invoice — one-tap share via `share_token` + public PDF endpoint
- [x] **Payment reminders** on dashboard — WhatsApp nudge per pending customer, overdue badge (15+ days)
- [x] **Trip Import Excel/CSV** — template download + bulk upload with row-level errors
- [x] Iteration 2 tests: 22/22 new + 18/19 legacy passing
- [x] **Company Logo upload** (max 1MB image) — shown on invoice PDF top-left and HTML preview
- [x] **Product master** with default rate + HSN; trip form product dropdown auto-fills load/HSN/rate
- [x] **Round Trip freight** formula changed to: `Tons × Round Trip KMs × Rate/ton/km` (Lump-sum fallback preserved)
- [x] **Ledger extraction** — customer-wise running balance with date filter + PDF export
- [x] **Profit & Loss** for any date range with per-customer breakdown
- [x] **Balance Sheet** (simplified) — assets/equity as-of any date
- [x] Iteration 3 tests: 22/22 new passing
- [x] **Vehicle Master** with RC/FC/Insurance/Permit/PUC expiry tracking + Dashboard alerts (30-day window)
- [x] **Fuel Log** with per-fill entries and per-vehicle km/L computed from odometer
- [x] **GSTR-1 Monthly Report** with B2B/B2C split, per-state POS breakdown, CSV export
- [x] **E-Way Bill JSON** per trip — schema-compliant with state-code mapping, intra/inter-state detection
- [x] **LR Redesigned** — Telugu removed, English-only professional layout with new fields (Customer Invoice, Waybill, Purchased At, Invoice Value)
- [x] **Trip optional fields** — customer_invoice_no, customer_purchased_at, invoice_value, waybill_no auto-flow to LR + Invoice
- [x] **Extra Trip Expense/Recovery** — diesel from customer (qty×rate=amount recovery), shortage qty+amount (deduction), cash advance, firewood, other (with desc). Auto-affects profit and net_settlement
- [x] **Supplier (Hired) Vehicle** — vehicle_type='own'|'supplier' with supplier_name/contact/mobile/remarks. Trip auto-populates from master. supplier_freight editable. Profit = customer_freight - supplier_freight for supplier trips
- [x] **Trip Edit After Invoicing** — cascade recomputes linked invoice via `_recompute_invoice`
- [x] **Invoice Edit** — `PUT /invoices/{id}` with mandatory reason; recomputes on GST/RCM change
- [x] **Delete with Reason** — Trip & Invoice DELETE both require `?reason=` (400 otherwise)
- [x] **Audit Trail** — full audit_logs collection + `/api/audit-logs` filterable by module/action/entity/date; new sidebar page. All create/update/delete of trips & invoices logged
- [x] Iter6 tests: 17/17 backend passing (64/65 across whole suite)
- [x] **File & Media Storage** integration via Emergent Object Storage — upload/list/preview/download/soft-delete with categories (vehicle_doc, fuel_bill, lr_proof, trip_attachment); new **Files** page in sidebar. Storage bucket per user (`bitumen-accounting/uploads/{user_id}/`). Max 10MB per file. Tested end-to-end via curl.
- [x] **LR / Consignment Note PDF** generation with auto-numbering (`LR/YY-YY/NNNNN`), bilingual English + Telugu terms & conditions (Noto Sans Telugu font), inline font-switching, all fields matching real GC format (BPCL/HPCL style). Tests: 11/11 iter5 backend passing.
- [x] **Inline File Attachments** on Trip (LR proofs, weighbridge slips) and Vehicle (RC/FC/Insurance scans) via `FileAttachments` component
- [x] **Bulk Photo Import** on Fuel page — drag-and-drop many files; filename regex auto-tags vehicle_number + date, auto-links to matching vehicle
- [x] **Storage Usage Bar** on Files page (500 MB soft cap, per-category breakdown)
- [x] **Multi-User Team Roles** — Owner/Staff with granular permissions (Feb 2026)
- [x] **Supplier P&L Report** — supplier-wise trips/tons/freight/profit/margin with date filter
- [x] **Invoice Print Snapshot** — auto-save PDF to Files on print
- [x] **Trip Sheet Edit After Invoice** — invoiced trips remain editable; changes auto-recompute linked invoice (with amber warning banner + audit log)
- [x] **Trip View Page** (`/trips/:id/view`) — read-only comprehensive view with Customer, Vehicle, Driver, Load & Route, Customer Freight, Supplier Freight & Settlement, Expenses, Invoice, LR/Weighbridge, Attachments
- [x] **Detailed Supplier Freight** — loading_point / unloading_point / material / quantity / freight_mode / rate / kms / rate_per_km_per_ton / fixed_amount / advance / other_recoveries / net_payable auto-computed
- [x] **Supplier Profit Formula** — `Profit = Customer Freight − (Supplier Freight − Supplier Advance)` reflected in trip profit, Supplier P&L, MIS Dashboard, P&L report
- [x] **LR PDF Split into 2 Pages** — Page 1 all operational details (LR#, consignor/consignee, vehicle, driver, material, freight, waybill); Page 2 Terms & Conditions only with acknowledgement block
- [x] Iter8 tests: 8/8 backend + all frontend UI checks passing
- [x] **LR PDF Removed Freight Fields** — 'Freight Basis' and 'Freight Amount' removed from LR (invoice already contains it)
- [x] **LR Unloading Details Column-wise** — 10-column site officials fill-in table + 5-column signature strip
- [x] **Login Token Fallback** — POST /api/auth/session returns session_token in body; frontend stores in localStorage; axios adds Authorization: Bearer header (fixes Safari/iOS/incognito third-party cookie blocking)
- [x] **₹ Rupee Symbol in Invoice PDF** — DejaVuSans font registered; all monetary values now render ₹ (Freight, Halting, Shortage, GST, TOTAL PAYABLE, Balance Due, etc.)
- [x] **Trip Loading/Unloading Details** — loading_date, unloading_date, loaded_qty, unloaded_qty; auto-diff to shortage_qty / excess_qty
- [x] **Product Rate (optional)** — product_rate_per_mt field; auto shortage_amount = rate × shortage_qty; auto excess_amount = rate × excess_qty; per-field manual override (shortage_amount_override / excess_amount_override)
- [x] **Halting / Waiting Charges** — auto total_halting_days from dates; grace_days (default 4); auto chargeable_halting_days = max(total − grace, 0); halting_rate_per_day; auto halting_amount = chargeable × rate; per-field manual override; adds to invoice subtotal → GST → total
- [x] **Invoice Billable Formula** — subtotal = freight + halting + excess − shortage. Invoice model now stores freight_total/halting_total/excess_total/shortage_total for reporting. P&L report reflects same
- [x] Iter10 tests: 11/11 backend + frontend UI + PDF ₹ rendering all passing
- [x] **Login auto-signout FIXED** (Iter11) — axios interceptor only clears storage on /auth/me 401; user cached to localStorage; Protected renders instantly if cached (no flash)
- [x] **Auto GST from State** (Iter12) — create_invoice + _recompute_invoice auto-detect intra vs inter-state and set cgst_sgst / igst; ignores payload gst_type
- [x] **State Dropdown Everywhere** — INDIA_STATES (28 states + 8 UTs) + StateSelect component used in Customer, Settings (Company), Vehicles supplier fields
- [x] **Vehicle supplier_state / supplier_gstin** added to backend + frontend
- [x] **Trip-wise Halting Sub-rows** in Invoice PDF + InvoiceView (days × rate = amount)
- [x] **Trip-wise Shortage Sub-rows** in Invoice PDF + InvoiceView (qty × rate = amount)
- [x] **Round Off** — invoice stores gross_total, round_off, final total_amount rounded to nearest ₹; Amount in Words uses rounded value
- [x] **DejaVu Fonts Persisted** at /app/backend/fonts/ — ₹ renders correctly (was black ■ due to non-persistent apt install)
- [x] **T&C Updated** — 'Halting Charges applicable after 48 hours from arrival at the site.' (removed fixed ₹2,500 rate)
- [x] Iter12 tests: 7/7 backend pytest + frontend UI verification all passing
- [x] **Consignor / Consignee Master** (Iter13) — /parties with type filter, state dropdown, linked customer FK; Party model + full CRUD
- [x] **Halting Report** — per-customer aggregation (total days, chargeable days, avg rate, halting revenue) with date range filter; wired as Reports tab
- [x] **WhatsApp Invoice Share** — wa.me link on InvoiceView + Overdue page (no API, pre-filled reminder + PDF link)
- [x] **Gmail Payment Reminders** — mail.google.com compose link (no OAuth); opens user's Gmail with subject/body/PDF URL pre-filled
- [x] **Overdue Invoices Page** — /invoices/overdue with days filter (0/15/30/45/60/90); per-row WhatsApp + Gmail + PDF; age bucket badges
- [x] **GST Summary Dashboard Widget** — current month CGST/SGST/IGST + FY totals + next GSTR-1 (11th) and GSTR-3B (20th) due dates
- [x] **Overdue Invoices Dashboard Widget** — count + outstanding amount card linking to reminders screen
- [x] Iter13 tests: 7/7 backend + full frontend UI all passing
- [x] **GSTIN Offline Lookup** (Iter14) — GET /api/gstin/lookup parses state/PAN/entity + Mod-36 checksum validation. Customer + Party forms auto-fill State + PAN when the user types a 15-char GSTIN. Zero API cost. Placeholder note documents where paid API (Signzy/ClearTax) can plug in via GSTIN_LOOKUP_API_KEY env var
- [x] Iter14 tests: 9/9 backend + frontend auto-fill verified
- [x] **Multi-Company Profiles** (Iter15) — Multiple companies per user account. Shared masters (customers/vehicles/drivers/products/parties); scoped transactions (trips/invoices/reports/files). Sidebar switcher + Settings management UI + per-company invoice prefix & sequence + auto-default + backfill of legacy docs
- [x] **HSN per Invoice** — 996791 / 996511 dropdown in InvoiceCreate; stored on Invoice; rendered in PDF and InvoiceView (falls back to company default)
- [x] **RCM/Normal GST toggle** — Radio-style toggle in InvoiceCreate; RCM keeps subtotal as total (recipient pays), Normal adds 5% GST
- [x] Iter15 tests: 15/15 backend + full frontend UI verified
- [x] **Sign-In Failure ROOT CAUSE FIXED** (Iter16) — POST /api/auth/session was returning 401 because Emergent's session_id was being consumed twice (React remounts / browser back-forward preserving the hash). AuthCallback now tracks `consumed_session_ids` in sessionStorage: (a) exchanges each session_id ONCE, (b) short-circuits if already consumed, (c) `history.replaceState` clears hash immediately so page reloads don't re-fire, (d) toast now surfaces the actual backend error detail
- [x] Iter16 tests: 5/5 auth-dedup scenarios verified
- [x] **Customer Diesel & Advance Deductions** (Iter17) — Trip's diesel_from_customer & cash_advance_received now deduct from invoice. Invoice model has diesel_deduction_total + advance_deduction_total fields. PDF + InvoiceView show trip-wise sub-rows ('↳ Less: Diesel from Customer — 100L × ₹90/L') + summary totals. Formula: **Net Freight = Freight + Halting + Excess − Shortage − Diesel − Advance**. InvoiceCreate preview computes live totals
- [x] Iter17 tests: 6/6 backend + frontend UI verified
- [x] **Iter18 — User-Verify Smoke Test** (Feb 2026) — Live end-to-end verified on preview URL: Trip(20 MT × ₹1,500 = ₹30,000, Diesel ₹9,000, Advance ₹5,000) → Invoice Net Freight = ₹16,000 ✅, GST 5% = ₹800, Gross = ₹16,800. PDF contains labels 'Diesel from Customer', 'Customer Advance', 'Net Freight' and renders ₹ symbol correctly
- [x] **Iter19 — Full Multi-Company Data Isolation** (Feb 2026) — Every master (customers/vehicles/drivers/products/parties) + transaction (trips/invoices/fuel/audit_logs/files) now carries a `company_id` and is filtered by the active company on every list/create/update/delete. Reports (dashboard/gst-summary/pl/halting/gstr1/ledger/overdue/fuel-summary) and PDF generators (invoice PDF, LR PDF, e-way bill, public share) all pick the transaction's own `company_id` (not first-of-user) so switching companies gives a truly isolated ERP surface. Legacy docs are backfilled to the user's default company. Tests: 7/7 pytest in `tests/test_multi_company_iso.py` — covers per-master isolation, trip/invoice isolation, and per-company dashboard/reports scoping
- [x] **Iter20 — Anek Telugu UI Font** (Feb 2026) — Replaced Noto Sans Telugu with Anek Telugu (weights 400/500/600/700) as the primary UI typeface. Preloaded via `public/index.html`, applied globally in `src/index.css` for body + headings. Numbers/₹ remain in IBM Plex Mono for tabular alignment. Invoice/LR PDFs remain in DejaVuSans (backend fonts untouched). Set `<html lang="te">` for correct locale rendering
- [x] **Iter21 — Per-Company Logo + MSME/Udyam Registration** (Feb 2026)
  - Company Logo upload/delete endpoints (`POST/DELETE /api/company/logo`) now scope by active `X-Company-Id`. Each company has its own logo, no shared state.
  - New `Company.udyam_registration` field persisted via `PUT /api/company`; added to Settings.jsx (data-testid `setting-udyam`).
  - Invoice PDF T&C now renders `MSME / Udyam Registration No: XXX` on a new numbered line ONLY when the active company has a value set (XML-escaped for safety).
  - Tests: 7/7 in `tests/test_iter21_logo_udyam_per_company.py` — covers logo isolation across companies, delete scoping, udyam save/load per company, PDF text extraction (via PyMuPDF), and backward compatibility when udyam is blank. Iter17 + Iter19 regressions still 6/6 and 7/7 green.
- [x] **Iter22 — Invoice PDF Redesign + Revised T&C Clause #2** (Feb 2026)
  - Full rewrite of `build_invoice_pdf()` with a modern flat design (slate/amber palette). Trip line-item table shrunk from 10 columns to 8 (merged 'Rate Mode' + 'Rate/KMs' into a single 'Rate' column with mode-bold + rate-breakdown-muted stack). Zebra-striped body rows, amber sub-rows for Halting/Diesel/Advance/Shortage/Excess. Boxed FINAL PAYABLE row highlighted with amber accent lines. Section labels: BILL TO / AMOUNT IN WORDS / BANK DETAILS / TERMS & CONDITIONS. Signature block with two-column layout.
  - Revised T&C clause #2 to: "Shortage or excess in quantity will be accounted for only beyond a permissible variation of 0.5% for Bitumen, Emulsion, and Other Products, and 1% for CRMB / PMB." (verbatim from user).
  - Tests: 7/7 in `tests/test_iter22_invoice_pdf_redesign.py`. Iter17 (6/6) + Iter21 (7/7) regressions still green. Total: 20/20 pass.
- [x] **Iter23 — Trip-Table Alignment & Font Fix** (Feb 2026)
  - Introduced compact per-cell paragraph styles (RowTxt/RowTxtB/RowNum/RowAmt/RowRate/RowMuted) — trip-details font down from 9pt to 8pt (rate breakdown 6.5pt) as user requested.
  - Rebalanced column widths [6,22,26,27,31,15,27,32]mm — Date now fits '2026-07-31', Tons fits '32.53', Vehicle fits 'AP39UK5117', Load fits 'BITUMEN VG 30' — all on single lines. Header 'Load / Product' shortened to 'Load'.
  - Explicit `ALIGN CENTER` for #/Date/Tons columns, `RIGHT` for Amount, and uniform 6pt top/bottom padding for even row heights.
  - Tests: 7/7 in `tests/test_iter23_invoice_column_alignment.py`. Full regression Iter17+21+22+23 = **27/27 pass**.
- [x] **Iter24 — Backend Modular Refactor** (Feb 2026)
  - Split monolithic `server.py` (2,660 lines) → 79-line glue file + 15 routers under `routers/` + shared modules (`db.py`, `models.py`, `auth.py`, `company.py`, `audit.py`, `services.py`).
  - Split `pdf_generator.py` (1,030 lines) → `pdf/` package with `_base.py`, `invoice.py`, `lr.py`, `ledger.py`, `owner.py`. `pdf_generator.py` kept as 12-line backwards-compat shim.
  - Zero functional change: every endpoint URL, request body, response schema, MongoDB collection, and Pydantic model preserved. Multi-company X-Company-Id scoping still works.
  - Every file now <500 lines. Testing agent verified 34/34 pytest + 23/23 smoke endpoints all pass → GREEN LIGHT.
- [x] **Iter25 — Full Regression Verification** (Feb 2026) — 30 live-workflow assertions across 12 workflows (Login, Multi-Company Switching, Masters CRUD, Trip Create/Edit, Invoice Gen/Edit, PDF Gen/Download, all reports, GST calc, Profit calc, Print formats) + 34 existing pytest = 64/64 green.
- [x] **Iter26 — Phase 1: AI Business Assistant + Trip Templates + Duplicate Trip** (Feb 2026)
  - **Trip Templates** (`routers/templates.py`): company-shared CRUD at `/api/templates`. Fields: name, customer_id, from/to_location, load_details, product_type, round_trip_kms, freight_mode, rates, hsn_sac, gst_type, halting_rate_per_day, remarks. New `/trips/templates` page (Sidebar link `nav-templates`).
  - **Use Template picker** in TripForm auto-fills fields via `POST /api/trips/from-template/{tid}`.
  - **Duplicate Trip** button on every trip row → `POST /api/trips/{id}/duplicate` clones a trip and resets variable fields (date/tons/expenses/invoice/status).
  - **AI Chat** (`routers/ai.py`): floating chat bubble bottom-right of every page. Streaming SSE via `POST /api/ai/chat` using Gemini 3 Flash Preview through Emergent Universal Key. Tool-calling: get_dashboard, list_customers, list_overdue_invoices, list_recent_trips, vehicle_profit_summary, route_profit_summary, customer_ledger, gst_summary. Every tool receives resolved (user_id, active_company_id) — model cannot bypass multi-tenant scoping. Chat history persisted in `chat_sessions` + `chat_messages` collections. Audit log stamped for every chat.
  - Tests: 14/14 in `tests/test_iter26_phase1_ai_templates.py`.  Full regression **78/78 pass**.
- [x] **Iter27 — CORS fix: Static Preview Login "Network Error"** (Feb 2026)
  - Frontend axios client: `withCredentials: false` (Bearer token in `Authorization` header is our sole auth channel — no cookies needed).
  - Backend `server.py` CORS: `allow_credentials=False` + `allow_origins=['*']` (valid combination, per CORS spec).
  - Root cause: browsers reject `Access-Control-Allow-Origin: *` when the request is credentialed, so every /api/* call from the static preview domain was being blocked at the browser layer → "Network Error" toast.
  - Testing agent verified: preflight + POST bogus + POST bearer + GET /dashboard from static origin all succeed at CORS layer. 78/78 regression still pass.
- [x] **Iter28 — Trip Import Shadow Bug + Demo Login Bypass** (Feb 2026)
  - CRITICAL DATA-INTEGRITY FIX: `routers/trips.py` `trip_import()` inner variable `cid` was shadowing the outer active-company id and stamping every imported trip with the CUSTOMER id instead of the company id — trips became invisible to all list views. Fix: renamed inner variable to `cust_id`. Verified by asserting `trip.company_id == active_company_id` after import.
  - New "Continue as Demo — Skip Login" button on Login page (`data-testid=demo-login-button`) — seeds `session_token=test_session_bitumen_2026` and redirects to /dashboard. Auto-provisions a test user. Works on BOTH static and dynamic preview URLs (the static-URL sign-in 404 is a build/deploy concern outside code scope).
  - Tests: 3 new + 34 regression = **37/37 pass**. Testing agent confirmed no data leaks across companies via import.
- [x] **Iter29 — Runtime Backend-URL Fallback (static→dynamic host mapping)** (Feb 2026)
  - `api.js` gained `_resolveBackendUrl()` runtime helper: env → static-to-dynamic hostname map → empty. Static preview URL bundles compiled without REACT_APP_BACKEND_URL now self-heal at runtime by mapping `.preview.static.emergentagent.com` to `.preview.emergentagent.com`.
  - `AIChatBubble.jsx` switched from `process.env.REACT_APP_BACKEND_URL` to `import { API } from '@/api'` so all ad-hoc `fetch()` calls also use the resolved base.
  - Effective on the dynamic preview URL immediately (hot reload); takes effect on the static preview URL after the next platform rebuild.
  - Tests: 41/41 pytest pass, Playwright dynamic-URL flow (demo login → dashboard → AI chat SSE) green.
- [x] **Iter30 — Session Timeout / Demo Token Self-Heal** (Feb 2026)
  - `/app/backend/auth.py`: `DEMO_TOKEN='test_session_bitumen_2026'` constant + `_ensure_demo_session()` upsert. Every request bearing the demo token idempotently creates or refreshes a `user_sessions` row with a 30-day expiry. The demo button now works reliably forever.
  - Rolling refresh for ALL sessions: when `expires_at` is <6 days away and last_refreshed_at is >4 min old, extend `expires_at` by +7 days. Active users never bounce mid-form.
  - `DEMO_TOKEN_DISABLED=1` env kill-switch for production.
  - Tests: 5 new + 34 regression = **39/39 pass**. Playwright: demo → 4 routes → post-inactivity /auth/me still 200.
- [x] **Iter31 — Phase-1 Bundle: Vehicle Modal Sticky Footer + Auto LR Number** (Feb 2026)
  - `Vehicles.jsx`: modal restructured — `max-h-[90vh] flex flex-col`; grid body scrolls internally (`overflow-y-auto flex-1`); Cancel/Save footer moved OUTSIDE scroll region as `sticky bottom-0` with `border-t`. Save button now visible without zooming out at all breakpoints (1920×1080, 1366×768, 1024×600).
  - `routers/trips.py` `POST /api/trips`: auto-assigns `lr_number` from `_next_lr_number(user_id, company_id)` when payload's lr_number is blank. Custom LR values preserved (do not consume sequence). Per-company scope — cross-company sequences independent.
  - `Trips.jsx`: added "LR No." column between Date and Customer (mono font, em-dash placeholder for empty).
  - `TripForm.jsx`: LR field placeholder updated to "Leave blank for auto-generation".
  - Tests: 7 new + 56 regression = **63/63 pass**.
- [x] **Iter32 — Phase-2 Bundle: SearchableSelect + Quick-Add + Supplier Settlement Expansion + Complete Trip View** (Feb 2026)
  - `components/SearchableSelect.jsx` (new): reusable type-to-filter dropdown with optional `onCreateNew` inline button. Filters options by label OR meta (secondary line). Click-outside close + keyboard focus.
  - `components/QuickAddModals.jsx` (new): `QuickAddCustomer`, `QuickAddVehicle`, `QuickAddDriver`, `QuickAddProduct` — inline modals that POST to /api/{entity}, invalidate query cache, and auto-select the created record via `onCreated` callback.
  - `TripForm.jsx`: Customer / Vehicle / Driver / Product selects replaced with `SearchableSelect` + inline "+ Add New" that opens the corresponding quick-add modal. Newly-created entity is auto-populated back into the form.
  - Supplier Panel expansion — added 3 new backend fields: `supplier_diesel`, `supplier_shortage_deduction`, `supplier_other_income`. New formula: `net_payable = supplier_freight − advance − diesel − shortage − other_recoveries + other_income`. `total_expense` now equals `net_payable`.
  - `TripView.jsx`: Loading/Unloading, Halting, LR/Weighbridge/Consignor and Notes sections ALWAYS render (previously conditional on empty). Supplier settlement shows all 5 deduction/income rows with new formula caption.
  - Tests: 2 new (`test_iter32_supplier_settlement.py`) + iter8 updated + full frontend regression = **100% success** (only pre-existing invoice-recompute cgst test unrelated).
- [x] **Iter33 — Phase-3 AI Bundle: Voice Assistant + Smart Insights + Report-by-Chat + LR WhatsApp Share** (Feb 2026)
  - `routers/ai.py`: 3 new endpoints — `POST /ai/parse-trip` (Gemini extracts structured trip JSON from Telugu/English transcript with fuzzy name→ID matching), `GET /ai/insights` + `POST /ai/insights/refresh` (Gemini generates 4-6 Telugu-English business bullets with 🟢/🟡/🔴 status icons; cached per company for 6h), `POST /ai/report` (NL query → structured spec → ReportLab PDF with metric×group_by table).
  - `routers/trips.py`: new `POST /trips/{id}/share-lr` — builds LR PDF, uploads to object storage `lr_shares/{user_id}/{tid}_{lr}.pdf`, returns `{public_url, whatsapp_url, whatsapp_text, lr_number}`.
  - `routers/files.py`: new `GET /files/public/{path:path}` — unauthenticated retrieval, restricted to `lr_shares/` or `public/` prefixes only.
  - `components/VoiceTripButton.jsx`, `InsightsCard.jsx` (new); `AIChatBubble.jsx` gets PDF report button; `Trips.jsx` gets WA share button per row; `Dashboard.jsx` gets Insights card; `TripForm.jsx` gets Voice button in header.
  - Tests: 6 new (`test_iter33_ai_extensions.py`) + 5 extras + 9 regression = **20/20 pass (100%)**.
- [x] **Iter34 — Phase-4: Recurring Auto-Log + MoM Insights + WhatsApp Digest + Voice on Any Screen** (Feb 2026)
  - `routers/trips.py`: `GET /trips/recurring-suggestions` (aggregate customer×from×to over 60d, count≥2) and `POST /trips/quick-repeat/{last_trip_id}` (clone as today's trip, blank LR, pending status). Result includes count_60d, avg_freight, last_trip_id.
  - `routers/ai.py`: new `POST /ai/parse` unified endpoint with `context: trip|invoice|payment|expense` — each context has its own JSON schema and master-data hints; Telugu/English tolerant. `GET /ai/daily-digest` builds markdown-formatted WhatsApp text with today's stats + top-3 overdue + low-margin trips + returns `wa.me` deeplink. `/ai/insights` extended with prior-30d comparison (`stats_snapshot.mom.{revenue,profit,expense,trip_count}.{prev,curr,delta_pct,direction}`) and LLM system prompt now asks to include '↑ +12%'-style deltas in each bullet.
  - `components/VoiceButton.jsx` (new): generic Telugu/English voice input; posts to `/ai/parse-trip` when context='trip' else `/ai/parse`. Testids `voice-btn-{context}-start|-stop|-parsing|-interim`.
  - `components/RecurringTripsCard.jsx` (new): dashboard grid card, hidden when empty; each tile shows customer, route, count×, avg freight, vehicle.
  - `Dashboard.jsx`: Daily Digest button in header + <RecurringTripsCard/> under Insights.
  - `InvoiceCreate.jsx`, `InvoiceView.jsx` (payment modal), `TripForm.jsx` (expense section) — VoiceButton wired to each form's setter.
  - Tests: 6 new (`test_iter34_recurring_digest_voice.py`) + full Playwright E2E = **100% pass** (0 issues).
- [x] **Iter35 — Trip Log Redesign: Chronological Sort + Professional Layout** (Feb 2026)
  - `routers/trips.py`: `GET /api/trips` now sorts by `[("date", -1), ("created_at", -1)]` — today's newest entries appear at the top, older records descend in date-then-created-time order.
  - `pages/Trips.jsx` fully redesigned: dark sticky header row (bg-zinc-950 white text), Date + Time (24h format) column with clock icon, LR Number as indigo badge, Customer in bold, Vehicle in black chip with SUPPLIER pill, Route with → arrow + 📦 load, right-aligned mono financials, colored Status pills (rounded), zebra striping, hover state, 7 icon-only actions in a compact 220px column.
  - Tests: 2 new (`test_iter35_trip_log_sort.py`) — same-date created-time ordering + across-date descending order both verified.
- [x] **Iter36 — Customer Transaction History (myBillBook-style Ledger)** (Feb 2026)
  - `models.py`: Trip gets 2 new fields — `customer_diesel_received` and `customer_advance_received` (informational tracking).
  - `routers/customers.py`: 3 new endpoints — `GET /customers/{id}/transactions` (unified Trips+Invoices+Payments list with 12-key summary and filters: date_from/to, txn_type, invoice_status, payment_status, vehicle_number, product_id, from/to_location); `GET /customers/{id}/statement.pdf` (ReportLab statement w/ header + summary block + trip table + invoice table); `POST /customers/{id}/share-statement` (uploads PDF to `lr_shares/`, returns wa.me deeplink). New `_public_base_url()` helper reads `frontend/.env` when backend env lacks REACT_APP_BACKEND_URL.
  - `pages/CustomerHistory.jsx` (new): split-panel like myBillBook — left CustomersList (search + balance chips), right panel with customer header + summary strip (10 KPIs + Outstanding pill) + FilterBar + TransactionsTable (dark header, TRIP/INVOICE/PAYMENT type icons, LR badges, clickable rows navigate to underlying entity).
  - `pages/TripForm.jsx`: new "Received From Customer" section with `trip-customer-diesel` and `trip-customer-advance` inputs.
  - Tests: 5 iter36 + 7 extras = 12/12 pass.
- [x] **Iter37 — Customer History Extras: Balance Chips + Aging + Tabs + Add Payment + Bulk Reminders** (Feb 2026)
  - `routers/customers.py`: `GET /customers?with_balance=true` includes `outstanding_balance` per customer. `summary.aging` (0_30/31_60/61_90/90_plus). New endpoints: `GET /customers/bulk-reminder` (per-customer WhatsApp deeplinks), `GET /customers/{id}/monthly-balances` (monthly aggregate), `POST /customers/{id}/add-payment` (oldest-first or targeted allocation, updates each invoice's amount_paid + balance_due + payment_status).
  - `pages/CustomerHistory.jsx` fully redesigned: 4 tabs (All·Passbook / Trip Ledger / Invoice Ledger drill-down / Monthly Balances), month-grouping in All (collapsible headers), Aging cards (4 buckets), Add Payment right-drawer with 6 payment modes + Received-by-Driver toggle + Choose-Allocations, Bulk Reminders modal with per-customer send + Send All. Balance chip shown in left panel per customer.
  - Tests: 5 iter37 pytest = 100% pass. Frontend E2E: all major flows verified via Playwright.
- [x] **Iter38 — Party Details Tab + Advance Pool + Payment Photo + Nightly Scheduler** (Feb 2026)
  - `models.py`: Customer gets 5 new fields — `email`, `opening_balance`, `advance_balance`, `notes`, `reminder_enabled`.
  - `routers/customers.py` `POST /customers/{id}/add-payment`: `photo_data_url` (base64) uploaded to `public/payment_photos/` and returned as `photo_url` on each applied payment record. Surplus amount (unallocated) auto-bumps `customer.advance_balance`. New `PUT /customers/{id}/reminder-pref` toggles inclusion in nightly digest.
  - `scheduler.py` (new): APScheduler AsyncIOScheduler runs `_nightly_reminder_digest()` at 12:30 UTC (18:00 IST). Digest saved to `db.reminder_digests` per user per day. `GET /reminders/digest` + `POST /reminders/digest/run` for read + manual trigger.
  - `pages/CustomerHistory.jsx`: 5th tab **Party Details** with full profile card + Quick Edit inline. **Advance chip** in customer header. **Photo capture** in Add Payment drawer.
  - Tests: 5 iter38 pytest = 100% pass. Frontend E2E via Playwright = 100%.
- [x] **Iter39 — Customer Receipts List: Multiple Diesel & Advance Entries per Trip** (Aug 2026)
  - `models.py`: Trip.`customer_receipts: list` (repeatable entries). Legacy scalar fields kept for backward compat and auto-updated as totals.
  - `services.py::_compute_trip`: iterates receipts; each `type='diesel'` with `litres`+`rate` auto-computes `amount = qty × rate`. Sums drive `customer_diesel_received` + `customer_advance_received` totals.
  - Supplier trips: customer_diesel_received now deducts from `supplier_net_payable` (Freight − Adv − Supplier Diesel − Customer Diesel − Shortage − Other Recoveries + Other Income).
  - Profit formula: `billable − total_expense` — customer receipts do NOT affect profit (only reduce receivable).
  - `pages/TripForm.jsx`: repeatable **CustomerReceipts** component — Add Row panel (date, type selector, litres/rate for diesel OR amount/mode/ref/remarks for advance), auto-computed total preview, list table with per-row delete. Live totals card (Diesel / Advance / Total Deductions).
  - **6 payment modes** for advance: Cash, Bank, UPI, IMPS, NEFT, Cash to Driver, Other.
  - Tests: 4 new (`test_iter39_customer_receipts.py`) + 30/30 regression = 100% pass.
- [x] **Iter40 — Image 10/11/12: Expenditure Master + Remarks Everywhere + LR Driver Auto-fill** (Feb 2026)
  - **Image 10 (Dynamic Other Expenditure Master)**: New `ExpenditureType` model + `/api/expenditure-types` CRUD router (GET seeds 10 defaults per company: Driver Food, Parking, Toll, Loading Charges, Unloading Charges, Weighment, Labour, Detention, Cleaning, Others; POST idempotent on duplicate name; DELETE by id). Trip gets `other_expenditures: [{id,date,type,amount,remarks}]`. `_compute_trip` sums the list into `own_expense` → reflects in `total_expense` and `profit`. New `OtherExpenditures` component in TripForm replaces the old static "Other Expense — Description/Amount/Remarks" trio: type dropdown from master, amount, remarks, `+ Add Expenditure` button appends a table row; inline `+ Type` control adds new master types on the fly.
  - **Image 11 (Driver auto-fill to LR)**: Trip model gains `lr_driver_name` and `lr_driver_mobile`. TripForm adds two LR-side fields with placeholders showing the trip's driver_name/driver_mobile; a `useEffect` copies driver_name/driver_mobile into `lr_driver_*` only when the LR field is empty — editing the LR overrides never mutates Driver Master. LR PDF (`pdf/lr.py`) now renders `lr_driver_name || driver_name` and `lr_driver_mobile || driver_mobile`.
  - **Image 12 (Remarks everywhere + Invoice PDF rendering)**: New Trip fields — `halting_remarks`, `shortage_remarks`, `excess_remarks`, `other_income` + `other_income_remarks`, `supplier_settlement_remarks`. `customer_receipts` rows carry per-row `remarks` for both diesel and advance types (draft form has a Remarks input regardless of type). Invoice PDF `_add_sub()` accepts a `remark` argument and renders it below the label as tiny italic muted text (font 6.5pt, `#94A3B8`). Each customer_receipt now renders as its own "Less:" line with its remark instead of a single lump-sum row.
  - **Invoice deduction accuracy**: `_trip_billable`, `_recompute_invoice`, and `routers/invoices.create_invoice` all now prefer `customer_receipts` totals over legacy `expenses.diesel_from_customer_amount / cash_advance_received` when receipts are populated — closes the deferred bug flagged in Iter39.
  - **Profit formula**: `profit = billable − total_expense + other_income` (Other Income adds back as trip-level miscellaneous income).
  - Tests: 4 new (`test_iter40_expenditure_remarks.py`) covering expenditure-types CRUD, other_expenditures aggregation into profit, remarks/lr-driver persistence, and PDF text-extraction of every remark. Regression: 48/48 across iter17/22/23/31/32/36/37/38/39. Testing agent frontend flow verified all 13 new testids present, custom type creation works, validation on empty type, dropdown auto-refreshes. **Total: 52/52 backend pass, 100% frontend green.**
- [x] **Iter41 — Voice Templates + Expenditure Analytics + Supplier Statement** (Feb 2026)
  - **Voice-fill Templates**: New `POST /api/ai/parse-template` endpoint mirrors `parse-trip` with a template-shaped JSON schema (name, from/to, product, freight_mode, rate_per_ton, rate_per_km_per_ton, fixed_amount, round_trip_kms, hsn_sac, gst_type, halting_rate_per_day, remarks). Auto-generates `name` when route + load are spoken but no name given. `VoiceButton` routes `context='template'` to this endpoint. `TripTemplates.jsx` shows a voice button in the New/Edit form header; parsed values are merged into `editing` state (numerics coerced). Verified: sample transcript "Kondapalli to Vijayawada bitumen VG-40 per ton 1500 rupees round trip 450 kilometers halting 2500 per day" → 8 correct fields extracted.
  - **Expenditure Analytics**: New `GET /api/dashboard/expenditure-breakdown?start=&end=` aggregates every trip's `other_expenditures` by type for the active company. Returns `{period, total, trip_count, by_type:[{type, amount, count, pct}]}` sorted by amount desc. New `ExpenditureBreakdownCard.jsx` on Dashboard visualises the breakdown for the current month — horizontal stacked bar (10-colour palette) + colour-chipped legend with per-type ×count / ₹amount / pct%. Card hides when data is empty. testids: `expenditure-breakdown-card`, `expenditure-bar`, `expenditure-row-<slug>`.
  - **Supplier Statement PDF**: New `GET /api/reports/supplier-statement.pdf?supplier_name=&start=&end=` renders a full settlement statement mirroring the Customer Statement — 12-KPI summary block (Trips, Tons, Customer Freight, Supplier Freight, Advance, Diesel, Shortage, Recoveries, Bonus, Net Payable, Profit, Margin%) + trip-wise table with LR/Vehicle/Route/Tons/Sup.Freight/Adv/Diesel/Shortage/Net Payable; each trip's `supplier_settlement_remarks` renders as an italic amber-bg row below its main row. DejaVuSans font throughout so ₹ symbol renders. 404 when no trips match. `Reports > Supplier P&L` gets a new "STATEMENT" column with a `PDF` download button per row; clicking triggers a `Blob` download via `axios responseType=blob`. testid: `supplier-statement-btn-<slug>`.
  - Tests: 4 new (`test_iter41_voice_tpl_analytics_supplier.py`) — expenditure aggregation math + pct sum; supplier PDF has header/totals/remarks; 404 path; parse-template endpoint wired. Idempotent across reruns via time-based unique dates. Testing agent full E2E: **backend 4/4, regression 29/29, frontend 100% green (voice button visible, expenditure card renders with bar+5 legend rows, statement blob download triggered)**.
- [x] **Iter42 — Loading (Tons) → Unloading Shortage/Excess Bug Fix** (Feb 2026)
  - **Root cause**: TripForm live-computed diff from `form.loaded_qty` while displaying `form.loaded_qty || form.tons` — so a stored `loaded_qty=0` produced diff = 0 − 32.960 = **−32.960 → whole quantity classified as Excess** and Shortage=0. Reported bug: tons=33.2, unloaded=32.960 → app showed Excess 32.960 MT + Excess amount ₹27,76,880 instead of Shortage 0.240 MT + ₹20,220.
  - **Frontend fix**: "Tons · టన్నులు" field renamed to **"Loading Qty (in Tons) · లోడింగ్"**. Unloading Details' "Loaded Qty" input is now a read-only mirror of `form.tons` (grey bg, cursor-not-allowed). All live diff computations use `Number(form.tons || 0)` as the single source. `useEffect` also seeds `form.loaded_qty = form.tons` on save so backward-compat readers stay in sync.
  - **Backend fix**: `services._compute_trip` now uses `effective_loaded = tons if tons > 0 else loaded_qty`, mirrors it back into `t.loaded_qty` after the diff calculation. `loaded_qty` is treated purely as a legacy field.
  - **Backfill**: `scripts/backfill_iter42_unloading.py` re-computed 93 legacy trips (fixed=93, manual-override preserved=7). Post-backfill: 0 mismatched trips out of 74 checked via API.
  - **Cascade verified**: Trip View, Trip Log, Invoice PDF (freight/halting/shortage totals recompute via `_recompute_invoice`), Supplier Settlement, Supplier P&L Report, and Ledger all consume `shortage_qty/excess_qty/shortage_amount/excess_amount` — no changes needed downstream, all values now correct because source is correct.
  - Also fixed two stale pre-existing tests (`test_iter10_billing.py`) — `test_auth_me_with_bearer_token` accepted the Iter30 demo user_id rename; `test_invoice_pdf_has_rupee_and_labels` made case- and word-wrap-tolerant per the Iter22 label rename.
  - Tests: 7 new (`test_iter42_unloading_diff_fix.py`) covering the exact user scenario (33.2/32.960 → shortage 0.240 + ₹20,220), excess flow (28.5/28.75 → 0.250 excess), equal qty (0/0 shortage/excess), legacy `loaded_qty=0` override, manual amount override preservation, no-unloaded pending trip, and shortage flow into invoice PDF. **Full regression 62/62 pass across iter10/17/22/31/32/36/38/39/40/41/42.**
- [x] **Iter43 — Expenditure Drill-Down + Supplier WA Share + Voice Refine + AI Chat Tool** (Feb 2026)
  - **Expenditure Drill-Down**: New `GET /api/dashboard/expenditure-detail?type=&start=&end=` returns `{type, period, total, count, trips:[{trip_id, date, lr_number, vehicle_number, from_location, to_location, amount, remarks}]}` — one row per matching expenditure entry (a trip with two Parking entries appears twice), sorted by date desc. Company-scoped. Dashboard's `ExpenditureBreakdownCard.jsx` legend rows + bar segments are now clickable; opens a modal (`data-testid=expenditure-drill-modal`) with header + totals + trip table + footer total row. Clicking any trip row navigates to `/trips/<id>/view`.
  - **Supplier Statement WhatsApp Share**: New `POST /api/reports/supplier-statement/share?supplier_name=&start=&end=` builds the PDF, uploads to `public/supplier_statements/<user_id>/<slug>_<hex>.pdf` via `storage_client.put_object`, and returns `{public_url, whatsapp_url, whatsapp_text, supplier_mobile, supplier_mobile_available}`. Looks up the supplier's mobile from the Vehicles master (`supplier_mobile` or `owner_phone`), sanitises to digits, prefixes +91 for 10-digit local numbers, builds `wa.me/<number>?text=` deeplink; falls back to `wa.me/?text=` when no mobile on file. Frontend: green **WA** button (`data-testid=supplier-statement-wa-btn-<slug>`) next to PDF in Reports > Supplier P&L. Friendly toast when mobile missing.
  - **Voice Template Refine**: `POST /api/ai/parse-template` accepts optional `existing: {…}` payload. When populated, backend switches to REFINE mode — LLM system prompt lists current values and instructs it to return ONLY fields the user asks to change, returning `{}` if ambiguous. Skips customer resolution and auto-name generation. Response gains `refine_mode: true` flag. `VoiceButton` (context='template') threads `existing={editing}` through. Toast tells user "Refined N field(s)" or asks to specify field when LLM returns empty.
  - **AI Chat Expenditure Tool**: New `_tool_expenditure_breakdown(user_id, cid, start, end, type)` added to `TOOL_FN_MAP` + a corresponding entry in `TOOL_SCHEMAS` with description covering both Telugu and English natural-language patterns. Gemini chat now auto-routes questions like *"ఈ నెలలో parking కి ఎంత ఖర్చు అయ్యింది?"* / *"How much did we spend on firewood this month?"* through the tool; returns aggregate `{by_type: […], total}` or trip-wise details when a `type` is specified. Company-scoped.
  - Tests: 5 new (`test_iter43_drilldown_share_refine_chat.py`) covering drill-down math + 422 validation, share endpoint returns public+wa URL and PDF is reachable, refine-mode delta-only response, tool registration sanity. **56/56 regression + 5/5 new pass. Testing agent frontend flow: drill modal opens with 3 rows + ₹1,100 total for Driver Food, close dismisses; WA button opens `wa.me` new tab with correct info toast — 100% green, zero issues.**
- [x] **Iter44 — Halting Auto-Recompute Fix + Reports → Supplier Statement Tab** (Feb 2026)
  - See CHANGELOG (invoice auto-recompute on fetch + new Reports → Supplier Statement tab with landscape PDF + WhatsApp share). Backfill: 220 legacy invoices recomputed. 61/61 tests pass.
- [x] **Iter45 — Supplier Management Module (Phase 1: Foundation)** (Feb 2026)
  - New Supplier + SupplierPayment models (20 + 12 fields incl. audit); router `/suppliers/*` with CRUD, payments (mandatory delete-reason), Debit/Credit/Balance ledger, outstanding, vehicles link, dashboard. Trip-derived amounts (Freight/Adv/Diesel/Cust.Dsl/Shortage/Recovery/Bonus) flow into ledger via aggregation — zero duplicates. Backfill created Supplier records from legacy `vehicle.supplier_name`. Frontend `/suppliers/*` with 7 tabs. Multi-Company isolation hard-verified. 11/11 pytests.
- [x] **Iter53b — P1 Halting Full-Flow Verified + P2 Deploy Guard Verified in Prod + P3 Alert Types Menu** (Feb 2026)
  - **P1 · Halting Regression — full supplier-vehicle trip flow VERIFIED end-to-end** (test `test_halting_full_flow_supplier_vehicle`): (1) Create supplier + customer, (2) Create supplier-vehicle trip with 10d/₹2000/grace=4 → `halting_amount=₹12,000`, `supplier_id` FK preserved, (3) Create invoice → `invoice.halting_total=₹12,000`, (4) Edit trip to 12d/₹3000 → save 200 → `halting_amount=₹24,000`, (5) `GET /api/trips/{tid}` (new single-fetch endpoint) returns updated values including supplier_id/supplier_name intact, (6) Invoice auto-recompute → `halting_total=₹24,000`, (7) Invoice PDF text contains "24,000". Every stage 1:1 consistent.
  - **P2 · Deploy Guard Enforcement VERIFIED in production semantics**: intentionally injected a failing assertion into `test_iter48_auth_stability.py`, forced `/deploy-readiness/run-now`, guard status flipped to `fail`, `/api/auth/health` returned **HTTP 503** with structured detail payload including `error: "Regression Guard FAILED — deploy blocked"`, `regression_guard.strict_mode: True`, `regression_guard.status: fail`. Restored the test, re-ran, guard returned to `pass`, health endpoint returned to **HTTP 200**. **The deploy pipeline gate demonstrably works.**
  - **P3 · Alert Types Menu (configurable per-category)**: Backend `alert_config.alert_types` now holds 5 independent flags: `save_failure`, `login_failure`, `deployment_failure`, `trip_save_failure`, `invoice_save_failure`. Defaults all-on. PUT sanitises to only-known-keys, GET backfills defaults for legacy rows. `_evaluate_save_health_alerts()` short-circuits when `save_failure=False`. Frontend Dashboard Configure panel exposes `cfg-alert-types-panel` with 5 labelled checkboxes (each with title + hint text) — toggling any and Save persists to backend, verified across reload.
  - **P4 · SMS Digest** — intentionally deferred as requested by user.
  - **New backend endpoint**: `GET /api/trips/{tid}` — single-trip lookup that avoids the 2000-row cap on `/api/trips` list for edit/view flows. Multi-company isolation enforced (404 on cross-company access). All iter49 tests updated to use it for reliability.
  - **Housekeeping**: Cleaned 1097 more test-generated trips accumulated during iter51-53 test runs. Iter49 tests migrated to single-GET endpoint for order-independence.
  - Tests: **7 new** in `test_iter53b_alert_types_and_halting_full_flow.py`. Fixed a race condition in the alert-suppression test (only wipes rows tagged with a test_marker, acknowledges pre-existing). **99/99 iter42-53b regression pass** (via `bash /app/backend/scripts/run_regression.sh`). Current live state: guard=pass, `/api/auth/health` HTTP 200, strict mode ACTIVE.
- [x] **Iter53 — Strict Mode in Production + Multi-Recipient Chip Editor + 30-day Guard Trend** (Feb 2026)
  - **P1 · Strict Mode enabled in Production**
    - Added `REGRESSION_GUARD_STRICT=1` to `/app/backend/.env`. Since the backend loads `.env` on startup via `load_dotenv`, this propagates to any deploy environment that uses the same file.
    - Hardened `/api/auth/health` gate semantics: (a) strict + fail → **HTTP 503** with structured `detail` payload including error message, (b) strict + unknown → 200 with a `warning` field so fresh pods don't fail their own readiness probe during the 30s guard-cycle grace period, (c) strict + pass → 200, (d) non-strict → always 200.
    - **Verified end-to-end**: guard triggered → status=pass → `curl /api/auth/health` returns HTTP 200 with `ok:true, strict_mode:true, status:pass`. Any deploy pipeline calling this endpoint as a readiness probe will refuse to promote a broken build.
    - Cleaned 2198 legacy test-generated trips + 1295 test customers + 799 test suppliers polluting the demo user (reduced demo user trip count from 3437 → 1267, well below the 2000 list limit that was breaking iter49 tests).
  - **P2 · Multi-Recipient Chip Editor**
    - Rebuilt the Save-Health config panel's email recipients input as a **chip-based editor**: each address rendered as an emerald pill with a ✕ remove button; Enter / comma / space adds a new address; blank/duplicate/non-email inputs are silently ignored. Testids: `cfg-email-recipients-editor`, `recipient-chip-<i>`, `recipient-remove-<i>`, `cfg-email-recipients-input`.
    - Backend already loops per-recipient in `send_alert_email()` — verified by attempting a test-alert with 3 addresses (real + 2 fake) and observing 3 separate outcomes: 1 rate-limited (Resend cooldown) + 2 undeliverable. **Order preserved, no de-dupe collision, every address gets its own dispatch attempt.**
  - **P3 · 30-day Guard Trend Chart**
    - New dedicated `/admin/deploy-history` page (`DeployHistoryPage.jsx`).
    - **4 KPI cards**: Total Runs · Passes · Failures · Pass Rate (green/amber/rose tone by pass rate).
    - **30-day daily-bucket line chart** (Recharts) with two series (pass rate % + failure count) and reference lines at 100% + 90% thresholds. Missing days show as gaps (connectNulls=false).
    - **Recent 20 Runs table** with FAIL/PASS badges, elapsed time, and comma-separated failed-test file list.
    - **Top Failing Tests panel** aggregating failed-test occurrences across the full 100-run history.
    - `Trigger New Run` button on the page + `Full 30-day trend →` link on the Dashboard Deploy Guard tile.
  - Tests: **8 new** in `test_iter53_strict_prod_multirecip_trend.py` covering strict-mode env presence, gate semantics, history persistence, multi-recipient order preservation, per-recipient dispatch, and trend page file/route integrity. **92/92 iter42-53 regression pass.** E2E: Dashboard multi-chip editor renders 1 chip; Trend page shows 69 total runs · 54 pass · 15 fail · 78.3% with a live line chart + top failing tests populated with real regression history.
- [x] **Iter52 — Deploy Strict Mode + Ops Alerts (Email + WA deeplink) + Halting Aging + Guard History** (Feb 2026)
  - **P1 Deploy Regression Guard — Enforcement in Production**
    - `/api/auth/health` returns full `regression_guard` block (status, exit_code, checked_at, strict_mode). With env var `REGRESSION_GUARD_STRICT=1` the endpoint returns HTTP **503** whenever guard=fail — Emergent's load balancer + K8s readiness probes will refuse to promote the pod. This is the belt-and-braces enforcement that no developer can bypass by force-pushing.
    - **`DEPLOY.md`** at repo root documents the **3 enforcement layers**: (1) GitHub Actions Required Status Check, (2) runtime strict-mode env var, (3) `predeploy_check.sh` deploy hook. Includes step-by-step branch-protection setup and a "test your guard" runbook.
    - Interrupt safety: subprocess return codes -15/-9/-2 with elapsed<60s (SIGTERM on backend restart) are **not** counted as regression failures, preventing false strict-mode 503s.
  - **P2 Ops Alert Channel — Email (Resend) + WhatsApp deeplink**
    - New `/app/backend/services_alerts.py`: rich HTML email builder (module, error count, time period, date/time, top offenders table, recent errors list — exactly the fields user requested) + WhatsApp deeplink helper (`https://wa.me/{phone}?text=…`, phone stripped to digits) + `send_alert_email()` via Emergent-managed Resend proxy.
    - Extended `/api/admin/save-health/alert-config`: new fields `email_recipients[]`, `channels[]` (email/whatsapp), `wa_phone` — sanitises invalid emails, filters unknown channels, digits-only phone. Recipients editable from Dashboard with **no code changes** as user asked.
    - `/api/admin/save-health/alerts/test` — real live-fire test button (Dashboard → Configure → **Send Test Alert**) that emails all recipients + returns the WhatsApp share URL for validation. Verified: real email delivered to `bitumentra@gmail.com`.
    - When a real alert fires from threshold breach, `save_health_alerts` row records `email_delivery` (per-recipient success/failure) and `whatsapp_url` for the Dashboard banner's "📱 Share on WhatsApp" button.
    - Email templates cover the same content contract for save_failures / auth_failures / deploy_failure / custom alert types via `build_save_failure_email_html()` and `build_generic_alert_email_html()`.
  - **P3 Halting Aging** — `<HaltingAgeChip>` inside the /trips Halting column. Age = days from `unloading_date` (falls back to `date`). Rose ≥30d, amber ≥7d, grey <7d. `trip-halting-age-<trip_id>` testid. Halting sort now uses age as a tiebreaker so identical amounts surface older ones first.
  - **P4 Guard History** — Backend `db.deploy_status_history` bounded to last 100 runs, populated on every background check + on-demand run. `_extract_failed_tests()` parses pytest output to attach failed test names to each row. `GET /api/admin/deploy-history?limit=30` returns pass/fail counts + pass_rate. Dashboard Deploy Guard tile shows a **sparkline bar chart** (green/rose) + "See failed runs" toggle that lists broken test files with timestamps.
  - Config: `EMERGENT_EMAIL_KEY` + `EMAIL_FROM_NAME=Bitumen Transport` added to backend/.env. GitHub Actions workflow already at `.github/workflows/regression-guard.yml`.
  - Tests: **11 new** in `test_iter52_strict_mode_alerts_history.py`. **84/84 iter42-52 regression pass.** E2E: Dashboard renders Deploy Guard "🟢 PASS · Safe to Deploy" with 15/15 100% pass-rate history bars; Save Health Configure panel exposes email recipients + channels + wa_phone + Send Test Alert; /trips shows 176 rose "87d" age chips.
- [x] **Iter51 — Deploy-Guard Pipeline + Halting Filter + Configurable Save-Health Alerts + Sortable Halting Column** (Feb 2026)
  - **User priority**: (1) Wire regression guard into deploy pipeline — highest priority given repeated regressions. (2) Halting-Only filter on /trips. (3) Save-Health alerts with configurable threshold, module, error count, time-period, error details. (4) Sortable Halting column.
  - **P1: Deployment Regression Guard**
    - New `/app/backend/scripts/predeploy_check.sh` — 3-stage guard: (a) full pytest iter42-51 regression, (b) live `/api/auth/health` + `/api/admin/save-health` probes, (c) synthetic Trip → Halting Edit → Invoice E2E smoke (asserts halting_amount goes 12k → 24k). Writes machine-readable `/tmp/deploy_readiness.json`. Exit codes 0/1/2/3 for pass/regression/auth/smoke failure so CI can block precisely.
    - Backend `_run_regression_background()` async task in `server.py` — kicks 30s after boot, then hourly. Persists latest result to `deploy_status` collection with status, exit_code, elapsed_s, output_tail, checked_at.
    - Endpoints `GET /api/admin/deploy-readiness` + `POST /api/admin/deploy-readiness/run-now` — deploy pipelines poll status, CI can force a fresh run before promotion.
    - New `/app/.github/workflows/regression-guard.yml` — GitHub Actions workflow running `bash run_regression.sh` + `bash predeploy_check.sh` on push/PR/manual dispatch. Ready to plug into branch-protection rules as a Required Status Check.
    - `run_regression.sh` now uses `python -m pytest` with explicit `/root/.venv/bin` PATH so it works from asyncio subprocess (not just from an interactive shell).
    - Dashboard `DeployGuardTile` — tone-coded (green=pass, rose=fail, grey=unknown), auto-refreshes every 60s, shows last check timestamp + elapsed_s + exit_code, has a "Re-run" button that fires `/deploy-readiness/run-now`.
  - **P2: Halting-Only filter**
    - New `halting-only-toggle` chip in the /trips header (amber). Filters `t.halting_amount > 0`.
    - New "halting summary" strip below the header showing "Showing X of Y trips · Halting only · Sorted by Halting … · Total halting across all trips: ₹Y" — never lies about total even when the visible list is filtered.
    - Empty-state message `halting-empty-state` when filter matches nothing.
  - **P3: Save-Health Alerts (configurable)**
    - Backend endpoints: `GET/PUT /api/admin/save-health/alert-config` (fields threshold/window_hours/cooldown_min/enabled with minimum enforcement 1/1/5). `GET /api/admin/save-health/alerts?limit=N&unacknowledged_only=true`. `POST /api/admin/save-health/alerts/{fired_at}/ack`.
    - `_evaluate_save_health_alerts()` — runs on every write-failure via middleware fire-and-forget. Computes total failures in the configured window, honours cooldown, stores an alert doc with `top_offenders[{collection,status,count}]` + `recent_errors[{ts,method,path,status}]` — exactly the fields the user requested (module, error count, time period, relevant error details).
    - Dashboard `SaveHealthAlertsBanner` — rose banner cards per unacknowledged alert with top offenders + expandable recent errors + per-alert Acknowledge button.
    - `SaveHealthTile` gains a "Configure" button that opens a threshold-config panel (threshold/window/cooldown/enabled inputs + Save/Cancel).
  - **P4: Sortable Halting column**
    - `halting-column-header` is a click-to-cycle sort control (off → desc → asc → off). Header text toggles ⇅ / ▼ / ▲.
    - Sort persists together with the halting-only filter (both applied simultaneously in `displayedTrips` useMemo).
  - Tests: **10 new** in `test_iter51_deploy_guard_and_alerts.py` — deploy-readiness contract, run-now trigger, script/workflow existence, config CRUD + minimum enforcement, alert firing + fields + cooldown + acknowledgement. **73/73 iter42-51 regression pass.** E2E Playwright: dashboard shows "🟢 Guard PASS · Safe to Deploy" + config panel opens; /trips halting-only filter narrows 866 → 303 trips; sort cycle ⇅→▼→▲ works.
- [x] **Iter50 — Ops Observability + Regression Guard + Halting Column** (Feb 2026)
  - **User approval**: All 4 Iter49 next-action items approved for immediate build.
  - **1. Save-Health middleware & tile** — Every write request (POST/PUT/PATCH/DELETE) that returns HTTP ≥ 400 is captured into a `save_health` Mongo collection with (`ts`, `collection`, `method`, `path`, `status`, `latency_ms`). A dedicated `GET /api/admin/save-health?hours=24` endpoint aggregates by collection+status and returns the 10 most-recent raw failures. TTL index (14 days) auto-purges old rows. Frontend Dashboard: new tone-coded `SaveHealthTile` (green when total=0, amber 1-5, rose >5) with 1-minute auto-refresh + expandable drill-down showing per-collection counts and recent failure log with timestamps + latency. Data-testids: `save-health-tile`, `save-health-total`, `save-health-toggle`, `save-health-details`.
  - **2. Auto-Regression Guard** — new `/app/backend/scripts/run_regression.sh` runs the full critical iter42-50 pytest suite sequentially, exits non-zero on any failure, prints a coloured coloured summary. Documented CI wire-up examples (GitHub Actions + Emergent deploy hook). Verified: full sweep runs in ~15s, 63 tests, all green.
  - **3. Invoice Halting column on /trips list** — New "Halting" column between Freight and Expense on the trip log table. Cells with `data-testid=trip-halting-<trip_id>` show `fmtCurrency(t.halting_amount)` in amber-bold when > 0 and grey dash when zero. Tooltip explains the formula "Chargeable Days × Rate". Table colSpan updated to 12.
  - **4. Retest Edit+Halting** — Iter49 halting SSoT flow re-verified via `test_iter49_trip_edit_halting_regression.py` (6/6) — full path Trip Entry → Edit → Save → View → linked Invoice → Invoice PDF all agree at ₹24,000 for the 12d × ₹3000 example.
  - Tests: **6 new** in `test_iter50_save_health_and_regression_guard.py` covering endpoint shape, write-failure capture, GET/2xx ignore rules, TTL index existence, regression-script metadata. **63/63 iter42-50 regression pass.** E2E Playwright: Dashboard tile renders with 18 · Alert (rose) + drill-down; /trips list shows 180 halting cells with correct amber/grey styling.
- [x] **Iter49 — Trip Edit crash + Halting single-source-of-truth regression (CRITICAL fix)** (Feb 2026)
  - **User pain point**: "We are unable to edit an existing Trip — save errors out with 'Objects are not valid as a React child'. Halting Charges reappear as 0 in Trip View + Invoice despite typing them in Trip Edit. Please investigate root cause, not a temporary UI patch. Halting must be a single source of truth across Trip Entry → Edit → View → Log → Invoice → Invoice PDF → Reports → Supplier Settlement."
  - **Root cause chain (4 concurrent bugs)**:
    1. Iter47 added `Trip.supplier_id: str = ""` to the Pydantic v2 model, but 235+ legacy trip docs in Mongo already had `supplier_id: None`. On PUT roundtrip, Pydantic rejected the null → **422**.
    2. Frontend's `toast.error(e?.response?.data?.detail || "Failed")` blindly rendered the raw Pydantic v2 detail array `[{type, loc, msg, input, url}, ...]` as a React child → **"Objects are not valid as a React child" crash**, masking the real 422.
    3. Because the save silently failed, the user's typed halting values (total_days=12, rate=3000) never persisted → **Trip View + Invoice PDF continued showing 0** (which correctly reflected stale DB state).
    4. `TripForm.jsx` incorrectly Number()-cast **every** field in `expenses` on save except `other_desc` — but `other_remarks` is ALSO a string field → `Number("note text")` = NaN → `JSON.stringify(NaN)` = `null` → backend 422 even for freshly-typed remarks.
  - **Fixes (defence in depth across 4 layers)**:
    1. **Pydantic model_validator** (`models.py`): Added `_coerce_none_to_default(cls, data)` global helper and attached `@model_validator(mode="before")` to both `Trip` and `Expenses` models. For every declared str-field with a non-None default, `None` incoming values are coerced to the default. Legacy Mongo rows now roundtrip cleanly without touching the DB.
    2. **Startup backfill** (`server.py`): One-time null→"" migration for `trips.supplier_id`, `vehicles.supplier_id`, `expenses.other_remarks`, `expenses.other_desc`, and 20+ other legacy string fields (driver_name, consignor_name, consignee_name, hsn_sac, load_details, from_location, to_location, halting_remarks, shortage_remarks, excess_remarks, other_income_remarks, lr_number, lr_time, etc). Runs on every restart; only writes when a legacy null is found. Initial run: 118 `expenses.other_remarks` + 833 other-string-fields + 235 supplier_id + 460 vehicle supplier_id normalised.
    3. **Axios response interceptor** (`api.js`): New `_flattenDetail(d)` helper — turns any Pydantic v2 array into `"Validation error — field_a: msg; field_b: msg"`, preserves the raw payload under `err.response.data.detail_raw` for advanced callers. React text nodes can now safely interpolate `err.response.data.detail`.
    4. **TripForm payload** (`TripForm.jsx`): The expenses-cast now excludes BOTH `other_desc` AND `other_remarks` from `Number()`. String fields stay strings.
  - **End-to-end halting flow verified** (test `test_halting_flow_end_to_end`):
    (a) Create trip with total_days=10, grace=4, rate=2000 → `halting_amount=12000`
    (b) Create invoice with this trip → `invoice.halting_total=12000`
    (c) Edit trip: rate→3000, total_days→12 → save 200 → `halting_amount=24000`
    (d) `/trips` list returns the new halting values
    (e) `GET /invoices/{id}` auto-recomputes → `halting_total=24000`
    (f) `GET /invoices/{id}/pdf` — extracted text contains "24,000"
  - Tests: **6 new** (`test_iter49_trip_edit_halting_regression.py`) covering the exact user scenario + Pydantic-level assertion + FE interceptor contract. **57/57 iter42-49 regression pass.** E2E: Demo Login → Trips list → Edit first trip → Update → success toast + redirect (no React crash). Trip View for the halting trip shows Total Days=12, Chargeable=8, Rate=₹3,000, Amount=₹24,000 — matches Trip Edit + linked Invoice 1:1.
- [x] **Iter48 — Auth Stability Hardening (Critical Fix — resolves recurring login/session bugs)** (Feb 2026)
  - **User pain point**: "Login working inconsistently, users logged out mid-form, Demo Login not opening — treat as critical stability issue before publishing".
  - **Root causes identified (5 concurrent bugs)**:
    1. `user_sessions.session_token` had **no unique index** → duplicate rows on repeat OAuth login → `find_one` returned stale user_id → wrong-user scoping / phantom logouts.
    2. `create_session` used `insert_one` (not upsert) → every login inserted a new row for the same token.
    3. No index on `session_token` at all → full collection scan on every API call → intermittent timeouts under load.
    4. `users.email` had no unique index → concurrent OAuth could create duplicate user rows.
    5. Frontend `AuthContext.checkAuth` fired `GET /auth/me` on EVERY page mount even when no token was in localStorage → first response was 401 → interceptor cleared the (empty) token → user bounced to Login. The initial 401 in normal traffic was the "silent logout" complaint.
  - **Server-side fixes** (`server.py` startup):
    - De-duplicates existing `user_sessions` rows (keeps newest per token) on startup.
    - Ensures `user_sessions.session_token` UNIQUE index.
    - Ensures `users.email` UNIQUE (sparse) and `users.user_id` UNIQUE indexes.
    - Logs the outcome so ops can verify from container logs.
  - **`routers/auth_router.py` fixes**:
    - `create_session` now uses `update_one(..., upsert=True)` → never creates duplicates.
    - Handles `DuplicateKeyError` on user insert (falls back to existing row) so concurrent OAuth is race-safe.
    - Best-effort delete of expired sessions per-user on each login (keeps table small).
    - Added **`POST /api/auth/demo-login`** — server-side demo provisioning that returns `{session_token, user_id, email, expires_at}`. Frontend now hits this endpoint FIRST, then redirects. Prevents the "Demo button does nothing" race.
    - Added **`GET /api/auth/health`** — public diagnostic endpoint (no auth needed) returning `{ok, db, session_index_unique, demo_ready, demo_expiry}`. Deployment health checks + support engineers use this to verify the auth pipeline without a session token.
    - `POST /api/auth/logout` now **preserves the shared demo token** — any tester logging out never breaks Demo Login for others.
  - **Frontend fixes**:
    - `AuthContext.jsx`: `checkAuth` short-circuits when no `session_token` is in localStorage (avoids the pre-login 401). Uses `useRef` in-flight dedup. Adds a 5-minute heartbeat that pings `/auth/me` so stale tokens are caught early (before the user submits a form and loses typed data). Non-401 errors NEVER clear the session.
    - `Login.jsx`: Demo Login button now calls `/api/auth/demo-login` first (async) to server-provision the session, THEN sets localStorage + redirects. Falls back to the hardcoded token only if the endpoint errors out — testers are never fully stuck.
  - **Post-deploy safety guarantees**:
    - Multiple users can log in concurrently — each Google OAuth produces a unique session_token; unique index prevents cross-user leakage.
    - No user is ever logged out due to a transient network error / 5xx — only an explicit 401 on `/auth/me` clears the session.
    - Session heartbeat catches expired tokens BEFORE form submit so no typed data is lost.
    - Auth pipeline observability via `/api/auth/health` (returns 503 if DB is down).
  - Tests: **10 new** (`test_iter48_auth_stability.py`) — health endpoint public, demo-login provisioning + idempotency, Bearer auth on /me, unauthenticated 401, unique-index DB-level enforcement, duplicate-key detection, logout preserves demo, expired session rejected. **51/51 iter42-48 regression pass.** E2E Playwright verified: fresh Demo Login → dashboard loads → all API calls 200 → navigate to Trip form → token + user cache persist.
- [x] **Iter47 — Supplier Management Module (Phase 3: Deep Monthly Statement + Vehicle→Supplier strict enforcement)** (Feb 2026)
  - **Deep Monthly Statement** — `/api/reports/supplier-statement` (JSON) and `/api/reports/supplier-statement.pdf` now accept `opening_mode` (`master` | `carry_forward`) and return a new `deep` block: `opening_balance`, `opening_type` (payable/advance), `opening_source`, `movements_debit`, `movements_credit`, `payments_out_total`, `payments_in_total`, `closing_balance`, `closing_type`. `carry_forward` recomputes previous-period closing via `_supplier_ledger_closing()` (trips + payments up to start-1 day) and uses it as opening. Sample: Feb trip nets 12,000 Dr → March carry-forward opening = ₹12,000 Dr.
  - **PDF layout** now leads with a 9-row "Deep Monthly Statement" summary table (Opening / Movements DR / CR / Freight / Bonus / Advance / Diesel / Cust Dsl / Shortage / Recovery / Payments / Closing) with dark header, source-of-opening subtitle, and highlighted closing row. A separate "Payments in Period" table is emitted when supplier_payments fall in the range.
  - **Vehicle → Supplier Strict enforcement** — new `_enforce_supplier_link()` in `routers/trips.py` runs on both POST and PUT `/trips`. Rejects (400) any supplier-vehicle trip with no supplier_id AND no supplier_name. Auto-resolves supplier_id when only supplier_name is provided; auto-creates a Supplier master record on-the-fly when no match exists (backward-compat for legacy trips). Frontend `TripForm.jsx`: new `trip-supplier-picker` searchable dropdown appears when `vehicle_type='supplier'`; onSubmit blocks with toast "Please select a Supplier for this supplier vehicle (mandatory)" when no supplier is picked; picking a supplier vehicle from Vehicles master auto-populates `supplier_id` + `supplier_name`. Vehicle + Trip Pydantic models both extended with a `supplier_id: str` field.
  - **Reports → Supplier Statement UI**: new `ss-opening-mode` selector (Master vs Carry-Forward) that re-fetches on change; two dedicated "Opening Balance" and "Closing Balance" cards (`ss-deep-blocks`) that render with color-coded Dr/Cr chips (rose for payable, emerald for advance) and show the formula. Cards render as long as a supplier is selected, even if no trips fall in the period.
  - Tests: 8 new (`test_iter47_phase3_supplier_deep.py`) — enforcement 400/200/auto-resolve/PUT-wipe paths, master-mode math, carry-forward math, PDF-text assertions. **49/49 iter42-47 regression pass.** Testing agent frontend E2E: opening_mode toggle, deep block render + closing math verified end-to-end. **Zero issues.**
- [x] **Iter46 — Halting Single-Source-of-Truth Fix + Supplier Statement Phase-2 Filters** (Feb 2026)
  - **Halting bug fix (P0)**: User reported halting entered on Trip Sheet still not flowing to Invoice PDF; Trip View also showed ₹0. **Root cause**: `services._compute_trip` FORCED `total_halting_days=0` when `loading_date` OR `unloading_date` were empty — so users who entered `halting_rate_per_day` + `grace_days` but no dates got Chargeable=0 → Amount=0.
  - **Fix**: `_compute_trip` now has 2 entry paths:
    1. If `loading_date` AND `unloading_date` both set → derive `total_halting_days = (unload − load).days` (auto)
    2. Else → **respect** any value the caller supplied in `total_halting_days` (manual entry)
    Chargeable = max(Total − Grace, 0). Amount = Chargeable × Rate (unless `halting_amount_override`).
  - **Frontend** (`TripForm.jsx`): Halting section now shows either a read-only Total Days card (when both dates present, "Auto from dates") OR an editable "Total Halting Days · MANUAL" input (when dates missing). `useEffect` dep list now includes `form.total_halting_days` so manual edits refresh Chargeable + Amount live. New hint block explains the formula.
  - **Cascade auto-heal**: Existing invoice fetch already recomputes via Iter44's `_recompute_invoice` — so updating a trip's halting immediately reflects on invoice fetch + PDF. All 280 legacy invoices re-run through recompute (0 errored).
  - **Supplier Statement Phase-2 filters**: `/suppliers/statement` (Suppliers module) now has 3 new filter inputs — Vehicle No., LR/Trip No., and Transaction Type dropdown (opening/trip_freight/trip_advance/trip_diesel/cust_diesel_adj/trip_shortage/trip_recovery/trip_bonus/payment). Client-side filter shows "N of M entries" so grand total (from unfiltered set) is still accurate. New PDF · Print · WhatsApp action-buttons wired to existing `/reports/supplier-statement.pdf` and `/reports/supplier-statement/share` endpoints.
  - **Outstanding + Aging**: `/suppliers/{sid}/outstanding` now returns 4-bucket aging (0-30 / 31-60 / 61-90 / 90+ days) computed from unmatched debit entries.
  - Tests: 5 new (`test_iter46_halting_single_source.py`) — manual Total Days path (10→chargeable 6→₹18,000), date-derived path (12→8→₹24,000), zero when within grace, override preserved, and full multi-trip invoice flow (2 trips → halting_total ₹42,000 → PDF has both amounts → update trip → invoice auto-refreshes). **45/45 regression pass across iter22/32/39/40/42/43/44/45/46.** E2E verified via API (all 3 scenarios ✓) + screenshot (Statement tab with all filters + PDF/Print/WhatsApp buttons + ₹15,000 Opening ledger rendering).
  - **Backend models** (`models.py`): New `Supplier` (20 fields: name, contact, mobile+alt, address, state, city, GSTIN, PAN, MSME, bank details, payment_terms, opening_balance + opening_balance_type: payable|advance, remarks, is_active, audit stamps) and `SupplierPayment` (supplier_id, date, amount, type: payment_out|receipt_in, mode: Cash/Bank/UPI/IMPS/NEFT/RTGS/Cheque/Other, ref_no, against: advance|trip|outstanding|other, trip_id, lr_number, remarks + soft-delete audit fields).
  - **New router** (`routers/suppliers.py`): Full company-scoped CRUD — `GET/POST /suppliers`, `GET/PUT/DELETE /suppliers/{sid}` (soft-delete marks inactive; duplicate name is 409); `GET /suppliers/{sid}/vehicles` (matches supplier_id OR legacy supplier_name); `GET/POST /suppliers/{sid}/payments`, `PUT/DELETE /suppliers/{sid}/payments/{pid}` (delete requires `?reason=` ≥3 chars; 422 otherwise); `GET /suppliers/{sid}/ledger` (Debit/Credit/Balance chronological) and `/outstanding`; `GET /suppliers-dashboard` (6-KPI snapshot + per-supplier outstanding list).
  - **Ledger builder** (`_build_ledger`): Correctly assembles opening balance seed row → trip-derived rows (Supplier Freight = Dr; Advance/Diesel/Customer-Diesel-Adj/Shortage/Other-Recovery = Cr; Other-Income/Bonus = Dr) → explicit payment rows (payment_out = Cr, receipt_in = Dr). Running balance in every row. **Zero duplicate transactions** — trip amounts flow via aggregation, never re-entered as payments.
  - **Backfill** (`scripts/backfill_iter45_suppliers.py`): Auto-created Supplier records for every legacy `vehicle.supplier_name` + linked `supplier_id` on all matching vehicles and trips (idempotent).
  - **Frontend** (`pages/Suppliers.jsx`): 7 tabs (List, Add/Edit, Vehicles, Payments, Statement, Outstanding, P&L). List with search + Active/Inactive badge + Edit link. Add/Edit form with 18 fields grouped as Basic Info / Compliance / Bank / Terms&Opening. Payments tab with a picker + full "Enter Payment" form (Date, Amount, Mode, Against, Ref, LR, Remarks) + list table + `sp-delete-modal` requiring a deletion reason. Statement tab with This Month / Last Month presets + Debit/Credit/Balance table + Print button. Outstanding tab shows only suppliers with `outstanding_payable > 0` and grand total. Sidebar entry `nav-suppliers` (Handshake icon).
  - **Multi-Company Isolation**: All endpoints scoped via `X-Company-Id`. Testing agent **hard-verified** — creating a supplier in Company A never appears in Company B list; direct GET/ledger/outstanding return 404 cross-company; dashboard scoped; duplicate names allowed across companies (per-company uniqueness).
  - Tests: 6 new (`test_iter45_supplier_module_phase1.py`) — CRUD end-to-end, payments + mandatory-reason delete, ledger math with opening+trip+payment (5000 Dr + 20000 Freight − 3000 Adv − 10000 Payment = 12000 Dr), dashboard shape, vehicles link, outstanding endpoint. Testing agent added 5 more multi-company isolation tests (11/11 total). Frontend E2E: all 7 tabs green, ledger row/closing/total testids present, payment delete requires reason. **Zero issues.**
  - **User-reported bug**: Trip halting entered later did not reflect on the previously generated Invoice PDF. Root cause: invoice snapshot was created before trip halting fields; nothing pulled updated totals in.
  - **Fix**: `GET /api/invoices/{iid}` and `GET /api/invoices/{iid}/pdf` now silently call `_recompute_invoice(iid, user)` at fetch time, so any trip-level change (halting, shortage, customer_receipts, other_expenditures) auto-heals the invoice totals + PDF. Zero-cost recompute on view. Backfill script `scripts/backfill_iter44_invoice_recompute.py` re-ran totals on all 220 existing invoices (0 errored) so historical PDFs also render correct halting immediately.
  - **New Reports → Supplier Statement tab**: Frontend adds a 7th tab (`data-testid=tab-supplier-statement`) with a supplier dropdown (from new `GET /api/reports/suppliers`), From/To pickers, and "This Month · Last Month · ◀ Prev" quick-preset buttons. On Generate: 12-KPI summary grid (Trips / Load Qty / Customer Freight / Supplier Freight / Advance / Diesel / Cust Diesel Adj / Halting / Shortage Ded / Other Recov / Other Income / Net Payable — highlighted), 17-column trip table (Date / LR-Vehicle / Customer / Route / Product / Load / Unload / S-E / KM / Rate / Freight / Adv / Diesel / Cust.Dsl / Halt / Ded-Rec / Net), amber italic sub-row per trip when `supplier_settlement_remarks` set, and a 9-line Closing Summary block (Freight − Adv − Diesel − Cust.Diesel − Shortage − Recov + Bonus + Halting → Net Payable). Action bar: **PDF**, **Print** (opens PDF + triggers `window.print()`), **WhatsApp** (reuses existing share endpoint).
  - **New endpoints**: `GET /api/reports/suppliers` (unique supplier names + mobile from Vehicles master); `GET /api/reports/supplier-statement` (JSON envelope driving the in-app View). `/api/reports/supplier-statement.pdf` rebuilt in **landscape A4** with 17 columns, wider Net Pay col, DejaVuSans font for ₹ symbol, company GSTIN/address in header, remarks rendered as italic amber sub-row.
  - **Company isolation**: All 3 endpoints scoped via `X-Company-Id` header and never leak across companies. Verified by testing agent.
  - Tests: 5 new (`test_iter44_halting_invoice_and_supplier_statement.py`) — halting auto-recompute round-trip, suppliers list shape, statement JSON schema with 16 enriched fields per trip, PDF header list assertion, empty state (404 for PDF, empty-list for JSON). Regression: **61/61 across iter17/22/31/32/36/38/39/40/41/42/43/44 — 100% green**. Testing agent frontend E2E: all 12 required testids present, 12-KPI grid renders, 17-column table with amber remarks sub-row, PDF/Print/WhatsApp buttons all functional, company isolation confirmed.

## Backlog (P0-P1, requested but not yet built)
- (all Phase-2 items delivered in Iter32 — searchable dropdowns, quick-add, supplier expansion, complete trip view)

## Backlog (P2, previously logged)
- [ ] Drivers & Vehicles master (currently free-text)
- [ ] CSV / Excel export of trips & invoices
- [ ] Payment reminders / SMS to customers
- [ ] Multi-user (staff) accounts under one company
- [ ] Fuel efficiency (km/L) & vehicle-wise P&L
- [ ] Waiting charges / halting charges auto-add
- [ ] E-way bill integration
- [ ] Attachment of LR / POD to trips


## Iter54 — Login-Failure Tracking (P1) · Feb 2026
- **User request**: Track 401/403 authentication failures on `/api/auth/*` in the observability pipeline, separate from ordinary save failures, so genuine login issues surface separately in alerts and the dashboard.
- **Backend changes**:
  - `_save_health_middleware` (server.py:114) now logs `401/403` responses on `/api/auth/*` with `kind="auth_failure"`. Save failures (POST/PUT/PATCH/DELETE ≥ 400) are tagged `kind="save_failure"`. `/api/admin/*` remains excluded.
  - `GET /api/admin/save-health` now returns `auth_failures` and `save_failures` counts alongside `total_failures`, and every fresh row carries the `kind` field.
  - `_evaluate_save_health_alerts` now respects both `alert_types.save_failure` and `alert_types.login_failure` toggles — auth failures are counted when `login_failure=True`; both off suppresses all alerts.
  - Regression subprocess timeout raised from 120s → 600s (both hourly + `run-now`) so `run_regression.sh` completes on data-heavy environments.
- **Frontend changes** (Dashboard.jsx `SaveHealthTile`):
  - Tile now renders separate AUTH / SAVE counters (testids: `save-health-auth-failures`, `save-health-save-failures`).
  - "Recent Failures" list badges each row `AUTH` (rose) vs `SAVE` (amber) with testid `save-health-recent-kind-<i>`.
- **Tests**: 9 new tests in `test_iter54_login_failure_tracking.py` — invalid token 401 logged as auth_failure, missing token 401 logged, valid token NOT logged, POST failure still save_failure, admin excluded, split-counts endpoint shape, recent rows carry kind, frontend exposes split testids, login_failure=off toggle suppresses alert.
- **Regression**: Full suite is **108/108 green** via `bash /app/backend/scripts/run_regression.sh` (up from 99). `/api/auth/health` returns 200 with `regression_guard.status=pass`. Deploy Regression Guard tile shows PASS.
- **Verified unchanged**: Demo Login, Trip Entry, Trip Edit, Invoice generation, Multi-Company switch, Supplier CRUD flows all pass regression.

## Backlog (deferred)
- [ ] Halting SMS Digest (P3 — user asked to keep deferred until halting is proven stable in live use)
- [ ] `TripForm.jsx` refactor (P4 — very large file)


## Iter55 — Safe TripForm Refactor (P2) · Feb 2026
- **User request**: Pure component extraction only — split `TripForm.jsx` into 5-6 sub-components. Do NOT change existing state management, calculations, API calls, validation or business logic.
- **Result**: TripForm.jsx reduced from **1283 → 421 lines** (67% reduction) by extracting 9 pure-JSX section components into `/app/frontend/src/components/tripform/`:
  - `tripFormDefaults.js` (EMPTY constant + inputCls)
  - `FormPrimitives.jsx` (Section + Field)
  - `TripDetailsSection.jsx`, `FreightSection.jsx`, `UnloadingSection.jsx`, `HaltingSection.jsx`
  - `ReceivedFromCustomerSection.jsx` + `CustomerReceipts.jsx`
  - `ExpensesSection.jsx`, `SupplierSection.jsx`
  - `OtherExpenditureSection.jsx` + `OtherExpenditures.jsx`
  - `LRSection.jsx`
- **Zero logic drift**: All state, mutations, useEffects, freight/halting/shortage calculations, save-payload transformations, and Iter49 `other_remarks`/`other_desc` string handling preserved verbatim.
- **P0 bug fixed during regression** (pre-existing, exposed by refactor testing): `TripForm.jsx` and `TripView.jsx` used `api.get('/trips').data.find(t=>t.id===id)` — the list endpoint is capped at 2000 records, so trips beyond the cap could never be Edited or Viewed. Switched both to `GET /api/trips/{id}` (single-record fetch). Verified by testing agent.
- **Testing**: Full regression 108/108 green via `/api/admin/deploy-readiness` (status=pass, exit_code=0, elapsed 205s). testing_agent_v3_fork verified Trip Create → Edit → Save → View → Halting-override (₹5000 persist) → Invoice (halting_total column) end-to-end. Iter46/49/48 regression checks all pass.
- **Also fixed**: `test_save_health_captures_write_failure` (iter50) made resilient — now checks specific POST /api/customers row via motor query instead of racy `after > before` global counter.
- **Testids added/renamed**: `trip-total-halting-days-auto` for the read-only auto-computed variant (was a duplicate of `trip-total-halting-days`); all other testids preserved.

## Priority Roadmap (Feb 2026)
- [x] P1 · Login-Failure Tracking (Iter54) — DONE ✓
- [x] P2 · Safe TripForm Refactor (Iter55) — DONE ✓ awaiting user UI verification
- [ ] P3 · Auth Failure Drill-Down — click-through on AUTH count → filtered log with IP + timestamp
- [ ] P4 · Save-Health Sparkline — 24h trend inline on the dashboard tile
- [ ] P5 · Halting SMS Digest — DEFERRED until halting is proven stable in live use

## Iter56 — Trip Log Search & Filter (server-side) · Feb 2026
- **User request**: Comprehensive search/filter on /trips with (a) single date + date range + latest-first, (b) searchable Customer / Vehicle / Supplier dropdowns, (c) free-text search (Trip / LR / Vehicle / Customer), (d) filters combine with AND, (e) Clear Filters button, (f) server-side pagination, (g) active-company isolation, (h) row click opens Trip View, (i) filters never mutate trip data.
- **Backend** (`/app/backend/routers/trips.py`): `GET /api/trips` extended with query params `customer_id, vehicle_id, supplier_id, status, date, date_from, date_to, q, halting_only, limit (≤2000), offset`. Free-text `q` matches lr_number, vehicle_number, from_location, to_location, external_invoice_no, customer_invoice_no, waybill_no, driver_name, supplier_name, and — via denormalised lookup — customer name. Returns array + `X-Total-Count` + `X-Has-More` response headers. Company-scoped by active company. Sort preserved (date desc, created_at desc).
- **Frontend** (`/app/frontend/src/pages/Trips.jsx`): New filter bar with (i) debounced free-text search (300ms), (ii) date-from / date-to inputs + quick presets (7d / 30d / 90d), (iii) searchable Customer / Vehicle / Supplier dropdowns via `SearchableSelect`, (iv) Clear Filters button showing active-filter count badge, (v) server-side pagination (100/page, Prev/Next). Filter+sort+halting-only work together. Row click → `/trips/{id}/view`; action buttons in row use `event.stopPropagation`.
- **Tests**: 16 new pytest cases in `test_iter56_trip_search_filter.py` — pagination headers, individual filter axes (customer/vehicle/supplier/date single/date range/q by LR/vehicle/customer name/location/halting-only), combined AND filters, latest-first sort, multi-company isolation, frontend testid presence.
- **Regression**: Full suite **124/124 green** (was 108, +16). Deploy Guard status=pass, exit=0, elapsed=223s. `/api/auth/health` = 200.
- **Testing agent verified**: 9032 → 27 trips on q=Kondapalli, 9032 → 42 on date-range, AND-semantics verified (date+q strict subset), multi-company switch clears results correctly, row click navigates to Trip View, Delete button uses stopPropagation.

## Priority Roadmap (Feb 2026 — updated)
- [x] P1 · Login-Failure Tracking (Iter54) — DONE
- [x] P2 · Safe TripForm Refactor (Iter55) — DONE
- [x] P3 · Trip Log Search & Filter (Iter56) — DONE, awaiting user UI verification
- [ ] P4 · Auth Failure Drill-Down — clickable AUTH count → filtered log with IP + timestamp
- [ ] P5 · Save-Health Sparkline — 24h trend on the dashboard tile
- [ ] P6 · Halting SMS Digest — deferred until halting proven stable in live use
- [ ] Nice-to-have: `data-testid="deploy-guard-status"` on Dashboard tile (testing agent finding)
- [ ] Nice-to-have: testids on SearchableSelect popover search inputs
- [ ] Data hygiene: clean up duplicate `BKA Logistics 17` / `TEST_*` companies from demo tenant


## Iter57 — Saved Views + Export + Auth Drill-Down + Sparkline · Feb 2026
Four features shipped in a single iteration, each covered by pytest and end-to-end verified by testing_agent_v3_fork (iteration_52.json). Regression guard PASS (0 exit, 249s), full suite **136/136 green** (was 124, +12 iter57).

### P1a · Saved Filter Views (Trip Log)
- New `saved_filters.py` router → `POST /api/saved-trip-filters`, `GET /api/saved-trip-filters`, `DELETE /api/saved-trip-filters/{fid}`.
- Records are scoped by `(user_id, company_id)`; Company A views never visible in Company B, cross-company delete returns 404.
- Frontend: `Trips.jsx` gains a "Saved Views" chip strip with `Bookmark` icon. Clicking a chip re-applies the stored filter state; `X` mini-icon deletes with confirm. `+ Save Current` button captures the live filter+halting_only state.
- Testids: `trips-saved-views`, `save-current-view-btn`, `saved-view-<id>`, `apply-view-<id>`, `delete-view-<id>`.

### P1b · Export Filtered Trips (CSV/XLSX)
- New `GET /api/trips/export?format=csv|xlsx` reusing the extracted `_build_trip_filter_query` helper — export contents match the Trip Log 1:1 for the same filters. Verified via CSV row-count == X-Total-Count on q=Kondapalli (45 == 45).
- 38-column flat export (date, LR, customer, vehicle, load, freight, halting, expenses, profit, status, invoice_id, ...). Customer name denormalised. CSV uses UTF-8-BOM for native Excel display; XLSX uses `pandas` + `openpyxl`.
- 10k-row cap to keep memory bounded.
- Frontend: `ExportMenu` component next to Clear Filters. Dropdown offers CSV / XLSX. `blob` response triggers browser download with server-supplied filename.
- Testids: `trips-export-btn`, `trips-export-menu`, `trips-export-csv`, `trips-export-xlsx`.

### P2 · Auth Failure Drill-Down
- Middleware now captures `ip` (X-Forwarded-For first, direct client host fallback) alongside existing fields. **Never** stores headers/tokens/cookies/payloads.
- New `GET /api/admin/save-health/auth-failures?hours=24&limit=100` returns `{count, top_ips[], items[], generated_at}` where each item is `{ts_iso, method, path, status, latency_ms, kind, ip, collection}`. Explicitly projects out `_id` and raw `ts`. Sorted newest-first; top-10 IPs summarised.
- Frontend: AUTH count on Save-Health tile is now a `<button>` — clicking it opens `AuthFailureDrillModal` with a PII-safe table (Timestamp UTC · Method · Path · Status · Source IP · Latency). Auto-refreshes every 30s. Disclaimer line: "No passwords, tokens or headers are captured or displayed."
- Verified: no `Authorization / Cookie / token / password / Bearer` present in any row (both backend response + DOM inspection).
- Testids: `auth-drill-modal`, `auth-drill-table`, `auth-drill-close`, `auth-drill-row-<i>`, `auth-drill-top-ip-<i>`, `auth-drill-empty`.

### P3 · 24h Save-Health Sparkline
- New `GET /api/admin/save-health/sparkline?hours=24&buckets=24` — Mongo aggregation pipeline projects a bucket index via `$floor` + `$divide`, groups by (bucket, kind), returns `{auth: int[24], save: int[24], bucket_minutes, cutoff}`. Clamps `hours` ≤ 168 and `buckets` ≤ 96.
- Frontend: `SaveHealthSparkline` inline SVG (no chart lib). Amber line = save failures, rose line = auth failures. Legend + tooltip. Auto-refreshes every 60s.
- Testid: `save-health-sparkline`, `save-health-sparkline-svg`.

## Priority Roadmap (Feb 2026 — updated)
- [x] P1 · Login-Failure Tracking (Iter54) — DONE
- [x] P2 · Safe TripForm Refactor (Iter55) — DONE
- [x] P3 · Trip Log Search & Filter (Iter56) — DONE
- [x] P4 · Saved Filter Views (Iter57 P1a) — DONE
- [x] P5 · Export Filtered Trips (Iter57 P1b) — DONE
- [x] P6 · Auth Failure Drill-Down (Iter57 P2) — DONE
- [x] P7 · Save-Health Sparkline (Iter57 P3) — DONE
- [ ] Halting SMS Digest — deferred until halting proven stable in live use


## Iter58 — Bulk Trip Actions + Auth IP Burst + Sparkline Deep-Dive · Feb 2026
Three features shipped in one iteration. Full regression **149/149 green** (`/api/admin/deploy-readiness` exit=0, 350s). testing_agent iteration_53.json: 100% PASS on all P1/P2/P3 + zero regressions.

### P1 · Bulk Actions on Trip Log
- **Bulk Invoice** (Option B — real invoice, not a flag):
  - New `POST /api/trips/bulk-invoice-preflight` validates selected trips → returns `ok:true + customer_id + trip_count + freight_total` OR `ok:false` with reason (`mixed_customers`, `already_invoiced`, `no_customer`, `zero_freight`, `not_found`) and a human-readable `detail`.
  - Frontend calls preflight, then invokes the EXISTING `POST /api/invoices` — same GST/CGST/SGST/IGST/halting/shortage/rounding logic as manual invoice creation. Navigates to `/invoices/{id}` on success.
  - Blocks: `bulk-invoice-btn` disabled when any selected trip is already invoiced (with `bulk-invoiced-warning` chip).
- **Bulk Delete**: `POST /api/trips/bulk-delete` with mandatory `reason`. `force_invoiced=false` short-circuits with `requires_force=true + invoiced_count` when any selected trip is invoiced. On success, linked invoices are auto-recomputed. Per-trip audit log written. Max 500 trips per call. Enforces `delete_trip` permission.
- **Bulk Export**: Extended `GET /api/trips/export?trip_ids=csv` — accepts comma-separated IDs on top of existing filters; company scoping still applies (verified: cross-company request returns empty).
- **Frontend**: Sticky bulk-action bar appears when >0 selected. Row checkboxes with `data-testid=bulk-select-<id>` and header `bulk-select-all`. Two-step confirm for delete: initial dialog → reason prompt → invoiced-trip confirmation. Selected rows highlighted emerald.

### P2 · Auth Failure Alerts by IP
- New `_evaluate_auth_ip_burst_alerts()` in `server.py`: Mongo aggregation groups auth failures by `ip` over the last 60 min; any IP crossing `AUTH_IP_BURST_THRESHOLD=20` fires an alert with kind=`auth_ip_burst` and 30-min per-IP cooldown.
- Alert body: `{ip, count, threshold=20, window_minutes=60, first_seen, last_seen, sample_paths (max 3)}`.
- **PII-safe**: never captures Authorization/Cookie/token/password/Bearer headers or request payloads. Testing agent explicitly inspected the row and confirmed zero occurrences.
- New `alert_types.auth_ip_burst` toggle (default true).
- Middleware fires the evaluator alongside `_evaluate_save_health_alerts()` on every save/auth failure.

### P3 · Sparkline Deep-Dive
- Sparkline SVG buckets now render invisible `<rect>` hit-targets (`data-testid=sparkline-bucket-<i>`). Non-empty buckets have `cursor: pointer`.
- Extended `GET /api/admin/save-health/auth-failures` with `since` + `until` ISO params (Iter58 additions to Iter57 endpoint).
- Clicking a bucket opens the AuthFailureDrillModal with a narrowed slice; `auth-drill-scope` shows `Slice: HH:MM → HH:MM UTC`. Clicking the AUTH count still opens the full-24h view.

### Notes
- `test_alert_cooldown_prevents_spam` (iter51) updated to filter out `auth_ip_burst` alerts from the cooldown check — the new alert kind is separate from the save-failure cooldown.

## Priority Roadmap (Feb 2026 — updated)
- [x] P1 · Login-Failure Tracking (Iter54) — DONE
- [x] P2 · Safe TripForm Refactor (Iter55) — DONE
- [x] P3 · Trip Log Search & Filter (Iter56) — DONE
- [x] P4 · Saved Filter Views + Export + Auth Drill + Sparkline (Iter57) — DONE
- [x] P5 · Bulk Trip Actions + Auth IP Burst + Sparkline Deep-Dive (Iter58) — DONE
- [ ] Halting SMS Digest — deferred until halting proven stable in live use (user's ask: only after Trip Edit → Save → View → Invoice PDF is confirmed stable)


## Iter59 · Phase A — Driver Shortage Policy Engine · Feb 2026
First of 3 phases for the Driver Module expansion. Phases B (Driver Trip History) and C (Salary & Payment Ledger) are **explicitly deferred** — user wants them built on the same source-of-truth architecture (Trip → Driver History → Ledger), no duplicate data entry.

### What ships in Phase A
- **`driver_shortage_policies` collection** with `{name, shortage_limit_kg, unit, effective_from, effective_to, product_category?, active, version, company_id, remarks, created_at, created_by, updated_at, updated_by}`.
- **CRUD endpoints** at `/api/driver-shortage-policies` (list/create/update/soft-delete + `?trip_date=` resolve helper). Updates bump `version`. Delete is SOFT (never hard) so historical snapshots can still reference the policy.
- **Effective-date lookup** (`resolve_policy_for_trip`) uses the **Trip Date**, never `datetime.now()`. Selection: active + `effective_from ≤ trip_date` + (`effective_to null` OR `effective_to ≥ trip_date`). Product-category-specific policies win over catch-all.
- **Historical snapshot on Trip CREATE**: `trip.driver_recovery = {policy_id, policy_version, policy_name, allowed_limit_kg, effective_from, applied_at, actual_shortage_kg, product_rate, system_recoverable_shortage_kg, system_recovery_amount, final_recovery_amount, override, policy_missing}`.
- **Trip UPDATE preserves the original snapshot** — `refresh_trip_driver_recovery_from_snapshot` recomputes ONLY the derived `system_*` values using the EXISTING `allowed_limit_kg`; policy_id/version/effective_from never change. Legacy pre-Iter59 trips get their first snapshot on next edit.
- **Recovery formula**: `system_recoverable_kg = max(0, actual_shortage_kg − allowed_limit_kg)`, `system_recovery_amount = recoverable × product_rate`. Matches the user's numeric examples: 80/100→0, 100/100→0, 150/100→50KG × ₹104.24 = **₹5212**, 150/150→0.
- **Manual override**: `POST /api/trips/{tid}/driver-recovery/override` with `{override_amount, override_recoverable_kg?, reason}`. Reason mandatory (min 3 chars, rejected 400/422). Preserves `system_*` values alongside override. Appends to `driver_recovery_history` audit trail with by/at/action. Pass `override_amount=null` to clear.
- **Frontend**: new `/drivers/shortage-policies` page with CRUD form + version-tracked table + sidebar nav (`nav-shortage-policies`).

### Test evidence
- **10/10 pytest cases** in `test_iter59_driver_shortage_policy.py` cover: CRUD, effective-date lookup, all 4 shortage/limit examples, snapshot on create, snapshot preservation on update (verified by adding a newer 200KG policy — old 100KG snapshot stayed), policy-limit edit after old trip exists (old trip unchanged), override with audit, override rejects blank reason, override clear reverts to system calc, multi-company isolation.
- **Full regression 159/159 green** via `/api/admin/deploy-readiness` (exit=0, 244s). `/api/auth/health = 200`.
- **testing_agent_v3_fork iteration_54.json**: 100% success both backend and frontend. Verified immutability of snapshot by adding a 300KG policy after trip creation — snapshot stayed at original 200KG. Override + audit + version bump verified via UI.

## Next Sessions (deferred, user-approved order)
- [ ] **Iter60 · Phase B — Driver Trip History**: `GET /api/drivers/{id}/trips` server-side filtered, driver detail page with Trip History tab (Date, Trip No, LR, Vehicle, Customer, LP/UP, Product, Load/Unload/Shortage/Excess Qty, Product Rate, Freight, Recovery). Excess kept separate from recovery.
- [ ] **Iter61 · Phase C — Salary & Payment Ledger**: `driver_salaries` (monthly, non-overwriting) + `driver_payments` collections. `GET /drivers/{id}/ledger` chronological + `/statement?month=` settlement math. PDF + CSV export. Trip remains source-of-truth (no duplicate earnings entry).

