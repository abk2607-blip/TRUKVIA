# QORVENA · Bitumen Transport ERP — PRD

## Product summary
QORVENA is a Bitumen transport ERP tracking LRs, Trips, Freight, Shortage, Invoices, Payments, Suppliers, Customers, Vehicles, Drivers, Products, Fuel, and Reports. FastAPI + React + MongoDB. Auth via Emergent-managed Google, with a dev-only demo token.

## Preferred language
User frequently switches between English and Telugu. Detect the language of the user's prompt and respond in the same. Application UI itself is bilingual by design.

## Locked business rules (do NOT change without explicit approval)
- **Duplicate Masters** (Iter127a):
  - **Customer** — HARD block on GSTIN + PAN (only when no GSTIN); SOFT-blocking on **Name** (bypassable via `X-Confirm-Name-Match: allow` header, surfaced as *Continue Creating*); Phone match is ADVISORY only (soft_matches). Owner/Admin can override GSTIN/PAN via `X-Duplicate-Override` header with reason.
  - **Supplier** — HARD block on GSTIN, PAN (only when no GSTIN), and **Name**; Mobile is ADVISORY only. NO *Continue Creating* button in modal.
  - **Vehicle** — Match on vehicle_number is IDEMPOTENT — backend returns existing row with `duplicate:true`, never inserts a duplicate. Modal offers Cancel / Open Existing.
- **Ship-To Independence** — Ship-To State is independent of Customer State; GSTIN derives State/State Code; no silent copy of Customer State.
- **Trip Loading vs Unloading** — separate stages. Freight available at dispatch; shortage only after unload data.
- **Missing Unload Data** — "Not Available Yet", not zero. Pre-unload invoices must not fabricate shortages.
- **Invoice Number** — Server-assigned as `{Prefix}/{FY}/{Sequence}` per company. NO per-invoice user override. Prefix + Next Number in **Settings** only, Owner/Admin.
- **Invoice Ship-To** — Preview and PDF are identical. GSTIN normalised on display. Unload Date renders correctly.
- **Invoice PDF Page X of Y** — every page. Signature block on last page only.
- **Supplier Deactivate/Reactivate** — soft-delete. Owner/Admin only. Historical data preserved.
- **Draft Recovery** — only meaningful, non-empty forms are offered for restore.

## Completed work (rolling log)
- **Iter126, Iter127a, Iter127b, Iter127c** — LOCKED
- **P0 "REFRESHING..." stability** — CLOSED
- **User Manual v1.0 (bilingual)** — SUPERSEDED (Telugu rendering rejected)
- **User Manual v1.0 English-only (initial)** — SUPERSEDED
- **User Manual v1.0 English-only refined (Draft)** — DELIVERED Feb 2026, awaiting UAT approval
  - Source: `/app/docs/user_manual.md`
  - Builder: `/app/docs/build_manual.py` (ReportLab, DejaVu fonts, cover + TOC + coloured callouts + Page X of Y footer)
  - Screenshots: `/app/docs/screenshots/` (31 files — 26 real app screenshots + 5 pixel-perfect modal mockups)
  - Screenshot builders: `capture_screenshots.py` (Playwright, real app), `capture_modal_mockups.py` (Tailwind HTML mockups for duplicate/deactivate modals)
  - Output: `/app/frontend/public/qorvena_user_manual.pdf` (38 pages, ~4.8 MB)
  - Verification: 0 Telugu runs in source AND in extracted PDF text; live duplicate rules cross-checked against `routers/{customers,suppliers,vehicles}.py` and `DuplicateMasterModal.jsx`; invoice-number auto-format cross-checked against `services.py::_next_invoice_number_for_company`.
  - Corrections from v1 draft: duplicate rules per entity, invoice-number claim removed, cover metadata reframed as "Draft awaiting UAT / Compiled Feb 2026", appendices tightened to reduce blank space.

## Backlog (upcoming)
- **P1** Deploy Readiness Badge
- **P1** Preview Uptime Chip
- **P2** Trip 8279 missing-Ship-To data-hygiene nudge
- **P2** LR Register Email Digest (Resend integration)
- **P2** Credit/Debit Notes
- **P3** Trip Templates feature completion
- **P3** QORVENA global rebranding rename
- **Deferred** Iter105 Demo-Customer UAT
- **Deferred** "Disk newer than in-memory" backend guardrail
- **Idea** In-app Help side-drawer

## Explicitly deferred by user
- IGST vs CGST/SGST recalculation based on independent Ship-To State.
- Freezing historical invoice Ship-To strings as snapshots.

## Critical operational notes
- Backend does **NOT** auto-reload. Any change under `/app/backend` requires `sudo supervisorctl restart backend`.
- `/app/memory/test_credentials.md` holds the demo token and OAuth email used for UAT.
- Manual regen: `python3 /app/docs/build_manual.py`
- Real screenshots regen: `/opt/plugins-venv/bin/python /app/docs/capture_screenshots.py`
- Modal mockups regen: `/opt/plugins-venv/bin/python /app/docs/capture_modal_mockups.py`
