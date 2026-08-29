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
- **Deploy Readiness Badge** (Iter128) — `/api/admin/deploy-readiness` + `/api/admin/deploy-history` are role-gated to Owner/Admin/Manager (403 otherwise). Frontend badge polls every 60s, paused when tab hidden. Backend is the sole role gate — badge hides on 403; no `/auth/me` change.

## Completed work (rolling log)
- **Iter126, Iter127a, Iter127b, Iter127c** — LOCKED
- **P0 "REFRESHING..." stability** — CLOSED
- **User Manual v1.0 (English)** — LOCKED · UAT approved
- **Iter128 · Deploy Readiness Badge** — 🔒 **LOCKED · UAT approved 2026-08-29**
  - Backend: role guard added to `/api/admin/deploy-readiness` and `/api/admin/deploy-history` (Owner/Admin/Manager only, 403 otherwise) in `server.py`
  - Frontend: `DeployReadinessBadge.jsx` — TanStack Query poll every 60s, paused when tab hidden; states = Ready / Checking… / Not ready / Offline; popover shows Checked / Elapsed / Exit Code + See History link
  - Mounted in `Layout.jsx` beneath CompanySwitcher (desktop) and inside mobile top bar (icon-only variant)
  - Tests: `test_iter128_deploy_readiness_badge.py` — 8 pytest cases (owner/manager allowed; accountant/viewer/unauthed rejected; history parity; run-now untouched)
  - Iter51/52/53 auth-header co-update: 3 pre-existing tests updated to send demo Bearer to reflect the new role gate (test-only change, +10/−3 lines)
  - Fresh regression run 2026-08-29 02:25 UTC: **503 passed · 1 skipped · 0 failed · exit_code=0 · elapsed=642.6s** ✓
  - Badge visual UAT: desktop pill + popover + mobile icon variant all confirmed green
  - `data-testid`: `deploy-badge-root`, `deploy-badge-status`, `deploy-badge-popover`, plus internal `deploy-badge-{checked-at,elapsed,exit-code,see-history}`

## Backlog (upcoming)
- **P1** Preview Uptime Chip — 🧊 frozen
- **P2** Trip 8279 missing-Ship-To data-hygiene nudge
- **P2** LR Register Email Digest — 🧊 frozen
- **P2** Credit/Debit Notes
- **P3** Trip Templates feature completion
- **P3** QORVENA global rebranding rename
- **Deferred** Iter105 Demo-Customer UAT
- **Deferred** "Disk newer than in-memory" backend guardrail
- **Deferred** iter43 + iter46 xdist / data-fixture cleanup (6 tests failing only inside 67-file batch; pass in isolation — not a code bug)
- **Idea** In-app Help side-drawer
- **Later** User Manual footer distribution link

## Explicitly deferred by user
- IGST vs CGST/SGST recalculation based on independent Ship-To State.
- Freezing historical invoice Ship-To strings as snapshots.
- Adding `effective_role` to `/api/auth/me` — auth is frozen; badge uses backend 403 as the gate instead.

## Critical operational notes
- Backend does **NOT** auto-reload. Any change under `/app/backend` requires `sudo supervisorctl restart backend`.
- `/app/memory/test_credentials.md` holds the demo token and OAuth email used for UAT.
- Manual regen: `python3 /app/docs/build_manual.py`
- Fresh deploy-readiness run: `POST /api/admin/deploy-readiness/run-now` (~10-11 min); poll `GET /api/admin/deploy-readiness` for status.
- Deploy Readiness Badge component: `/app/frontend/src/components/DeployReadinessBadge.jsx`
