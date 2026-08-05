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
- [x] Iteration 4 tests: 15/15 new passing (77/78 overall)
- [x] **File & Media Storage** integration via Emergent Object Storage — upload/list/preview/download/soft-delete with categories (vehicle_doc, fuel_bill, lr_proof, trip_attachment); new **Files** page in sidebar. Storage bucket per user (`bitumen-accounting/uploads/{user_id}/`). Max 10MB per file. Tested end-to-end via curl.

## Backlog (P1)
- [ ] Drivers & Vehicles master (currently free-text)
- [ ] CSV / Excel export of trips & invoices
- [ ] Payment reminders / SMS to customers
- [ ] Multi-user (staff) accounts under one company
- [ ] Fuel efficiency (km/L) & vehicle-wise P&L
- [ ] Waiting charges / halting charges auto-add
- [ ] E-way bill integration
- [ ] Attachment of LR / POD to trips
