# QORVENA · Bitumen Transport ERP — PRD

## Product summary
QORVENA is a Bitumen transport ERP tracking LRs, Trips, Freight, Shortage, Invoices, Payments, Suppliers, Customers, Vehicles, Drivers, Products, Fuel, and Reports. FastAPI + React + MongoDB. Auth via Emergent-managed Google, with a dev-only demo token.

## Preferred language
User frequently switches between English and Telugu. Detect the language of the user's prompt and respond in the same. Application UI itself is bilingual by design.

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

## Completed work (rolling log)
- **Iter126, Iter127a, Iter127b, Iter127c** — LOCKED
- **P0 "REFRESHING..." stability** — CLOSED
- **User Manual v1.0 (English)** — LOCKED · UAT approved
- **Iter128 · Deploy Readiness Badge** — SHIPPED to preview · awaiting user UAT
  - Backend: role-gated `/api/admin/deploy-readiness` and `/api/admin/deploy-history` — Owner/Admin/Manager only (`server.py`)
  - Frontend: `DeployReadinessBadge.jsx` — TanStack Query poll every 60 s, paused when tab hidden; states = Ready / Checking… / Not ready / Offline; popover shows Checked/Elapsed/Exit Code + See History link
  - Mounted in `Layout.jsx` beneath CompanySwitcher (desktop) and inside mobile top bar (icon-only variant)
  - Backend is the single source of truth for role gating — badge hides itself on 403; no `/auth/me` changes made
  - Tests: `test_iter128_deploy_readiness_badge.py` (8/8 pass) — covers owner allowed, manager allowed, accountant/viewer/unauthed rejected, history parity, run-now untouched
  - Locked-area regression suite (iter126/iter127*/iter128) — 170/170 pass
  - Frontend smoke: badge renders correctly on both desktop + mobile, popover fields populate
  - Files touched: `backend/server.py`, `frontend/src/components/Layout.jsx`, plus new `test_iter128_deploy_readiness_badge.py` and `DeployReadinessBadge.jsx`
  - Backend restart executed once, explicitly flagged before running

## Backlog (upcoming)
- **P1** Preview Uptime Chip — 🧊 frozen until Iter128 UAT signoff
- **P2** Trip 8279 missing-Ship-To data-hygiene nudge
- **P2** LR Register Email Digest — 🧊 frozen until Iter128 UAT signoff
- **P2** Credit/Debit Notes
- **P3** Trip Templates feature completion
- **P3** QORVENA global rebranding rename
- **Deferred** Iter105 Demo-Customer UAT
- **Deferred** "Disk newer than in-memory" backend guardrail
- **Idea** In-app Help side-drawer
- **Later** User Manual footer distribution link

## Explicitly deferred by user
- IGST vs CGST/SGST recalculation based on independent Ship-To State.
- Freezing historical invoice Ship-To strings as snapshots.
- Adding `effective_role` to `/api/auth/me` — auth is frozen; badge uses backend 403 as the gate instead.

## Pre-existing regression status (baseline, NOT caused by Iter128)
- Latest cached regression run (Iter50 guard): 6 failed / 497 passed / 1 skipped
  - `test_iter43_drilldown_share_refine_chat.py::test_expenditure_drill_down_returns_trip_rows`
  - `test_iter46_halting_single_source.py` (5 tests)
- `backend_test.py::test_01_company_defaults` fixture assumes an empty tenant; already failing on stashed pre-Iter128 code
- `test_iter6/7/8_features.py` cascade errors — same count and identity on stashed code

## Critical operational notes
- Backend does **NOT** auto-reload. Any change under `/app/backend` requires `sudo supervisorctl restart backend`.
- `/app/memory/test_credentials.md` holds the demo token and OAuth email used for UAT.
- Manual regen: `python3 /app/docs/build_manual.py`
- Deploy Readiness Badge:
  - Backend endpoint: `GET /api/admin/deploy-readiness` (Owner/Admin/Manager only, 403 otherwise)
  - Frontend polling: 60 s, paused when tab hidden
  - `data-testid`: `deploy-badge-root`, `deploy-badge-status`, `deploy-badge-popover`, plus internal `deploy-badge-{checked-at,elapsed,exit-code,see-history}`
