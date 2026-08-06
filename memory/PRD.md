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

## Backlog (P1)
- [ ] Drivers & Vehicles master (currently free-text)
- [ ] CSV / Excel export of trips & invoices
- [ ] Payment reminders / SMS to customers
- [ ] Multi-user (staff) accounts under one company
- [ ] Fuel efficiency (km/L) & vehicle-wise P&L
- [ ] Waiting charges / halting charges auto-add
- [ ] E-way bill integration
- [ ] Attachment of LR / POD to trips
