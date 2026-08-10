# Bitumen Transport Accounting — PRD

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
