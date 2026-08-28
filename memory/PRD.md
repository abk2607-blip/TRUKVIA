# QORVENA · Bitumen Transport ERP — PRD

## Product summary
QORVENA is a Bitumen transport ERP tracking LRs, Trips, Freight, Shortage, Invoices, Payments, Suppliers, Customers, Vehicles, Drivers, Products, Fuel, and Reports. FastAPI + React + MongoDB. Auth via Emergent-managed Google, with a dev-only demo token.

## Preferred language
User frequently switches between English and Telugu. Detect the language of the user's prompt and respond in the same. Application UI itself is bilingual by design.

## Locked business rules (do NOT change without explicit approval)
- **Duplicate Masters** (Iter127a):
  - **Customer** — GSTIN + PAN are blocked; **Name** is a warning bypassable via *Continue Creating* (`X-Confirm-Name-Match: allow`); Phone is advisory only. Owner/Admin can override GSTIN/PAN via `X-Duplicate-Override` with a written reason.
  - **Supplier** — GSTIN, PAN, and **Name** are all blocked; Mobile is advisory only. NO *Continue Creating* button.
  - **Vehicle** — Match on vehicle_number is IDEMPOTENT — backend returns existing row with `duplicate:true`, never inserts a duplicate.
- **Ship-To Independence** — Ship-To State is independent of Customer State; GSTIN derives State/State Code; no silent copy.
- **Trip Loading vs Unloading** — separate stages. Freight available at dispatch; shortage only after unload data.
- **Missing Unload Data** — "Not Available Yet", not zero. Pre-unload invoices must not fabricate shortages.
- **Invoice Number** — Server-assigned `{Prefix}/{FY}/{Sequence}` per company. NO per-invoice user override. Prefix + Next Number in **Settings** only, Owner/Admin.
- **Invoice Ship-To** — Preview and PDF identical. GSTIN normalised on display. Unload Date renders correctly.
- **Invoice PDF Page X of Y** — every page. Signature block on last page only.
- **Supplier Deactivate/Reactivate** — soft-delete. Owner/Admin only. Historical data preserved.
- **Draft Recovery** — only meaningful, non-empty forms are offered for restore.

## Completed work (rolling log)
- **Iter126, Iter127a, Iter127b, Iter127c** — LOCKED
- **P0 "REFRESHING..." stability** — CLOSED
- **User Manual v1.0 (bilingual)** — SUPERSEDED (Telugu rendering rejected)
- **User Manual v1.0 (English initial + refined)** — SUPERSEDED
- **User Manual v1.0 (English, presentation-improved) — Draft** — DELIVERED Feb 2026, awaiting UAT
  - Source: `/app/docs/user_manual.md`
  - Builder: `/app/docs/build_manual.py` (ReportLab, DejaVu fonts, cover + TOC + coloured callouts + Page X of Y footer, 26mm callout labels)
  - Screenshots: `/app/docs/screenshots/` — 26 real app screenshots captured at **2× DPI** + 5 pixel-perfect modal mockups
  - Screenshot builders:
    - `capture_screenshots.py` — real app pages (Playwright)
    - `recapture_hires.py` — 2× DPI re-capture
    - `crop_screenshots.py` — trims left sidebar for larger useful area (PIL)
    - `capture_modal_mockups.py` — pixel-perfect duplicate/deactivate modals from Tailwind HTML
    - `retake_trip_view.py` — reserved (trip view SPA won't hydrate headless)
  - Output: `/app/frontend/public/qorvena_user_manual.pdf` (37 pages, 9.2 MB @ 2× DPI)
  - Presentation refinements (this pass):
    - 2× DPI screenshots + left-sidebar crop for readability
    - In-PDF image size 95mm → 105mm max height
    - Callout labels widened to 26mm; label font tuned to prevent mid-word wrap
    - Save Retry section rewritten in plain English (no `Idempotency-Key`)
    - Troubleshooting rewritten (no HTTP codes / header names)
    - Removed unusable "Loading trip…" screenshot
  - Verification: 0 Telugu in source and PDF; 0 dev-jargon leaks (`403`, `409`, `Idempotency-Key`, `case-insensitive`, `hard block`, `soft block`, header names).

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
- Real screenshots regen (2× DPI): `/opt/plugins-venv/bin/python /app/docs/recapture_hires.py && python3 /app/docs/crop_screenshots.py`
- Modal mockups regen: `/opt/plugins-venv/bin/python /app/docs/capture_modal_mockups.py`
