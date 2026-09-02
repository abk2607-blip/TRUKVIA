# QORVENA · Bitumen Transport ERP — PRD

## Product summary
QORVENA is a Bitumen transport ERP tracking LRs, Trips, Freight, Shortage, Invoices, Payments, Suppliers, Customers, Vehicles, Drivers, Products, Fuel, and Reports. FastAPI + React + MongoDB. Auth via Emergent-managed Google, with a dev-only demo token.

## Iter133 · Expense / Vehicle Cost Management — Turn 2C COMPLETE — NOT READY FOR UAT (2026-09-02)

**Status:** Vendor Ledger + Mechanic Ledger read-only + Vendor/Mechanic Payment Correction (attribute + amount-reversal) shipped with immutable audit trail. Turn 2D (cost-date vs payment-date parametrised reporting + final integration) awaits explicit GO.

### Documentation correction from prior turn
§3.1 of the Turn-2C design addendum listed **four** new fields on VendorPayment/MechanicPayment (`corrected_at, corrected_by, correction_count, latest_correction_id`) but the section header said "three new fields" — corrected to **four new fields** as approved. No functional change.

### FROZEN design implemented
- Admin/Owner only for corrections (`_ensure_admin` gate → 403 otherwise).
- Mandatory `correction_reason ≥ 10 chars` (400 otherwise).
- Immutable append-only `payment_corrections` collection (no update / no delete endpoint).
- **Attribute correction** → same payment row updated in place + one PaymentCorrection row (`kind=attribute`).
- **Amount correction** → original marked `is_reversed=true` + fresh row inserted + one linking PaymentCorrection row (`kind=amount_reversal_new`). Preserves real cashbook history.
- Idempotency mandatory: `Idempotency-Key` on both `/correct` and `/correct-amount`; replay returns cached response with `x-idempotent-replay=1`.
- Tenant isolation via `user_id + company_id` scope.
- Optimistic concurrency via `expected_correction_count` → 409 on mismatch.
- Reconciled-payment guard: if `reconciled_at != ""` and no `force_reconciled_override=true` → 409.
- Ledger auto-reflects: `GET /vendors/{id}/ledger` reads current-state payment `vendor_id` — corrected payments move ledgers automatically. Same for Mechanic.

### Files added (5)
- `backend/services_payment_corrections.py` — shared correction logic (attribute + amount-reversal) for both party types.
- `backend/routers/vendor_ledger.py` — `GET /vendors/{vid}/ledger` + `POST /vendor-payments/{pid}/correct` + `POST /vendor-payments/{pid}/correct-amount` + `GET /vendor-payments/{pid}/corrections`.
- `backend/routers/mechanic_ledger.py` — mirror for mechanic.
- `backend/tests/test_iter133_expense_turn2c.py` — 15 tests (PC-2 through PC-13 + ledger derivation + reversed-original guard).
- `frontend/src/pages/PartyLedger.jsx` — combined Vendor/Mechanic ledger UI with admin-only correction modal.

### Files edited (additive only, 3)
- `backend/models.py` — added **four** new fields on `VendorPayment` + `MechanicPayment` (`corrected_at, corrected_by, correction_count, latest_correction_id`) plus reversal/reconciliation fields (`is_reversed, reversed_by, reversed_at, reversal_reason, reversal_of, reconciled_at, reconciled_ref`); added `PaymentCorrection` model.
- `backend/server.py` — wired `vendor_ledger_r` + `mechanic_ledger_r`; added `payment_corrections` compound index + `is_reversed/reversal_of` indexes.
- `backend/idempotency.py` — whitelisted 4 new POST paths (`/vendor-payments/*/correct`, `/vendor-payments/*/correct-amount`, `/mechanic-payments/*/correct`, `/mechanic-payments/*/correct-amount`).
- `frontend/src/App.js` — added `/vendor-ledger/:id` and `/mechanic-ledger/:id` routes.

### Test evidence
- `test_iter133_expense_turn2c.py`: **15 / 15 PASS** in 1.05 s.
- Combined Iter133 (Turn 1 + 2A + 2B): **62 / 62 PASS** (7.27 s) — no regression.
- Trip / Supplier / Idempotency (`iter49, iter91, iter45, iter111, iter126b`): all green.

### Live end-to-end proof
Created Vendor A + Bill 5000 + Payment 2000 posted to A.
`V1 ledger BEFORE correction → total_debit=5000, total_credit=2000, outstanding=3000`.
Applied `/correct` reassigning payment to Vendor B (with new Bill B on B). Response: `payment.vendor_id=V2, correction_count=1, correction.kind=attribute`.
`V1 ledger AFTER correction → total_debit=5000, total_credit=0, outstanding=5000` ✓ (payment removed).
`V2 ledger AFTER correction → total_debit=2000, total_credit=2000, outstanding=0` ✓ (payment moved).
`/corrections history → 1 row, kind=attribute, reason preserved`.
**ZERO duplicated rows. ZERO manual reconciliation.**

### Locked-area untouched
✅ C3.1 / C3.2 / C3.4 / C3.5 / C4 untouched.
✅ C5 (deferred) untouched.
✅ DG-STABILITY-1 · `pytest.ini` · `scripts/run_regression.sh` untouched.
✅ Supplier Ledger (`_build_ledger`), `services._compute_trip`, driver-recovery sync, invoice recompute — all UNCHANGED.
✅ Fuel collection standalone (as approved).

### Known limitations
- No bank-reconciliation UI — reconciled marker is currently written directly by seeding tests; future Reconciliation module can populate it.
- No maker-checker on corrections — admin authority is sufficient per approved design.
- No corrections export (Tally / GSTR) — corrections feed forward only.
- Correction UI is minimal (attribute: ref/remarks only in the modal; amount: single field). More attribute fields (date, mode, bill reassignment via dropdown) can be surfaced in a later polish turn.

### Next sub-turn (awaiting GO)
**Turn 2D — Cost-date vs Payment-date parametrised reporting + final integration/regression + UAT artefacts.**

### Final status
**EXPENSE TURN 2C COMPLETE — NOT READY FOR UAT — NOT READY FOR LOCK.**

## Iter133 · Expense / Vehicle Cost Management — Turn 2B COMPLETE — NOT READY FOR UAT (2026-09-02)

**Status:** Vehicle Cost + Vehicle Repair History reports are live (backend read-only + minimal UI). No stored totals. Turn 2C (Vendor + Mechanic Ledger UI) awaiting explicit GO.

### Turn 2B source-of-truth map (FROZEN)
| Report / View | Reads from (single source) | Never reads |
|---|---|---|
| Vehicle Cost (total, categories, monthly, drill list) | canonical `Expense` (+ legacy `Trip.expenses/other_expenditures` XOR fallback for trips where `has_canonical_expenses=false`) | VendorBill · MechanicWO · Payment · RepairEvent |
| Vehicle Repair History (per-event derived total, parts, labour) | canonical `Expense` where `repair_event_id != ""` for the parts/labour split; **RepairEvent** row for envelope fields only | RepairEvent.total_cost (does not exist) · VendorBill amount as cost · MechanicWO amount as cost |
| Vendor / Mechanic payable + outstanding *displayed inside repair history rows* | `VendorBill` − `VendorPayment` / `MechanicWO` − `MechanicPayment` | Expense (never used for payables) |
| Cost date | `Expense.date` | never mixed with Payment.date |
| Payment date | `Payment.date` (Turn 2D scope) | never used for Vehicle Cost |

### Files added
- `backend/routers/vehicle_reports.py` — NEW · two GET endpoints, streaming iteration, no `to_list(2000)` caps.
- `frontend/src/pages/VehicleCostReport.jsx` — NEW · minimal UI with KPIs, category breakdown, monthly, repair history drill-down.
- `backend/tests/test_iter133_expense_turn2b.py` — NEW · 22 tests (T2B.1 – T2B.22).

### Files edited (additive only)
- `backend/server.py` — wired new router into mount loop.
- `frontend/src/App.js` — added `/vehicles/:vid/cost` route.
- `frontend/src/pages/Vehicles.jsx` — added a "Cost" action link on each vehicle row.

### APIs (read-only, `/api` prefix, tenant-scoped)
- `GET /api/vehicles/{vid}/cost-summary?from=&to=&category=&trip_linked=yes|no`
- `GET /api/vehicles/{vid}/repair-history?from=&to=&status=&vendor_id=&mechanic_id=&trip_linked=yes|no`

### Duplicate-prevention proof
- Repair envelope has no monetary total field → RepairEvent contribution is always derived from linked Expenses (verified T2B.10, T2B.11).
- Vehicle Cost aggregates `Expense` only; VendorBill/MechanicWO amounts are surfaced as separate "payable" fields inside history rows, never summed into cost (T2B.11, T2B.15).
- Legacy XOR: `has_canonical_expenses=false` trips fall back to `Trip.expenses.*` + `other_expenditures[]`; modern trips read Expense only. No additive double-count (T2B.6, T2B.7).
- Payments never touched by cost report (T2B.14).

### Repair ₹18k + ₹7k proof
Live test fixture: Vendor bill ₹18,000 + Mechanic WO ₹7,000 + twin Expenses ₹18,000 + ₹7,000
→ `total_repair_cost = 25000.00`  ✓  (not ₹36,000 / ₹43,000 / ₹50,000)
→ `vendor_payable = 18000.00`, `mechanic_payable = 7000.00` ✓
After a ₹10,000 vendor payment: `vendor_paid=10000, vendor_outstanding=8000`, vehicle cost UNCHANGED ✓ (T2B.14).

### Filters supported
- Vehicle Cost: `from`, `to`, `category`, `trip_linked=yes|no`.
- Repair History: `from`, `to`, `status`, `vendor_id`, `mechanic_id`, `trip_linked=yes|no`.

### Pagination / high-volume
- Both endpoints use async cursor iteration; no `to_list(N)` caps. Bill/WO/Payment children preloaded via a single `$in` query — no N+1.
- Totals returned always represent the ENTIRE filtered set (T2B.20, T2B.21 — 30 repair events aggregate perfectly, 50 OE rows aggregate perfectly).

### Test evidence
- `test_iter133_expense_turn2b.py`: **22 / 22 PASS** in 4.27 s.
- Turn 1 + Turn 2A: **40 / 40 PASS** (3.61 s).
- Trip / Supplier / Idempotency regressions (`iter49, iter56, iter91, iter45, iter111, iter126b`): **50 / 50 PASS** (14.27 s).

### Live API smoke
- `GET /api/vehicles/{vid}/cost-summary` → `total=0 count=0 cats=0` (fresh vehicle) ✓
- `GET /api/vehicles/{vid}/repair-history` → `count=0 total_repair=0.0` (fresh vehicle) ✓
- Fixture trip with `toll=1000, repair=500` on vehicle → cost summary returns `total_cost=1500`, `by_category=[Toll:1000, Repair:500]`, `repair_total=500` (Repair legacy sits in Vehicle Cost but not in RepairEvent history) ✓

### Live UI smoke
- Route `/vehicles/:vid/cost` renders KPIs + Category-wise + Monthly + Repair History with drill-down `<details>` per event.
- "Cost" link added to each row on `/vehicles`.

### Known limitations
- No Vendor / Mechanic Ledger UI or Paid/Outstanding report — Turn 2C.
- No cost-date vs payment-date parametrised reports — Turn 2D.
- No supplier-settlement projection into Supplier Ledger — Turn 2C or later.
- Legacy supplier-owned Trip semantics still project via `Trip.expenses.*` fallback with `supplier_settlement_mode='n/a'` (as materialised in Turn 2A). Explicit supplier-owned rule handling on Vehicle Cost UI is Turn 2C scope.
- Report caps: none. Uses streaming cursor; production-safe.

### Locked-area untouched
✅ C3.1 / C3.2 / C3.4 / C3.5 / C4 untouched.
✅ C5 (deferred) untouched.
✅ DG-STABILITY-1 · `pytest.ini` · `scripts/run_regression.sh` untouched.
✅ `services._compute_trip`, driver ledger sync, invoice recompute, Supplier Ledger (`_build_ledger`) — all UNCHANGED.
✅ Fuel collection standalone (as approved).

### Next sub-turn (awaiting GO)
**Turn 2C — Vendor Ledger + Mechanic Ledger (read-only backend + UI).**

### Final status
**EXPENSE TURN 2B COMPLETE — NOT READY FOR UAT — NOT READY FOR LOCK.**

## Iter133 · Expense / Vehicle Cost Management — Turn 2A COMPLETE — NOT READY FOR UAT (2026-09-02)

**Status:** Trip → canonical Expense materialisation is live. Turn 2A only. Turn 2B (Vehicle Cost + Repair History reports) awaiting explicit GO.

### Turn 2A architecture (frozen; MASTER PRINCIPLE preserved)
- Deterministic source-line identity — never amount/date/vendor heuristic:
  - Legacy scalars → `trip:{trip_id}:legacy:{diesel|toll|batta|repair|other|firewood}`
  - other_expenditures[] → `trip:{trip_id}:oe:{row.id}`
- Partial UNIQUE index `expenses_source_key_uniq` (user_id, company_id, source_key) enforces one canonical Expense per source line. Blank `source_key` = manual entry (unaffected).
- Sync helper `services_expense_bridge.sync_trip_expenses_to_canonical()` runs after every Trip create/update — idempotent upsert-by-source_key + soft-delete for removed lines. `Trip.has_canonical_expenses` flag is atomically set based on the active count.
- Trip delete cascades soft-delete on all `source_trip_id=tid` canonical rows via `delete_trip_canonical_expenses()`.
- `Expense.source_type ∈ {manual, trip_legacy, trip_other_expenditure}` distinguishes provenance for downstream reports.
- Manual Expenses (`source_key=""`) are never touched by trip sync — proven by test.

### Files added
- `backend/services_expense_bridge.py` — NEW · sync + cleanup helpers. Pure functions; no side-effect on legacy fields.
- `backend/tests/test_iter133_expense_turn2a.py` — NEW · 17 tests (T2.1 – T2.20 plus 2 bonus).

### Files edited (additive only)
- `backend/models.py` — added `Expense.source_type`, `Expense.source_key`, `Expense.source_trip_id`; added `Trip.has_canonical_expenses`. Defaults preserve backward compatibility.
- `backend/routers/trips.py` — imported bridge helpers; call `sync_trip_expenses_to_canonical` after `db.trips.insert_one` and `db.trips.update_one`; call `delete_trip_canonical_expenses` after `db.trips.delete_one`. Legacy fields, `_compute_trip`, driver ledger sync, invoice recompute — all unchanged.
- `backend/server.py` — added partial UNIQUE index on `(user_id, company_id, source_key)` + `source_trip_id` index for cleanup speed.

### Turn 2A test evidence
- `test_iter133_expense_turn2a.py` — **17 / 17 PASS** in 2.90 s.
  - T2.1 trip toll → exactly one canonical Expense ✓
  - T2.2 save twice → no duplicate ✓
  - T2.3 edit toll → same canonical row updated in place ✓
  - T2.4 remove toll → canonical soft-deleted ✓
  - T2.5 no-expense trip → has_canonical_expenses=false, backward compat ✓
  - T2.6 flag deterministic transitions ✓
  - T2.7 two identical OE rows → two distinct canonicals (via row.id) ✓
  - T2.8 idempotency retry → no duplicate ✓
  - T2.9 VendorBill + twin Expense no double-count ✓
  - T2.10 MechanicWO + twin Expense no double-count ✓
  - T2.11 VendorPayment never changes Expense total ✓
  - T2.12 MechanicPayment never changes Expense total ✓
  - T2.18 Cross-company isolation ✓
  - T2.19 Trip delete soft-deletes all canonical rows ✓
  - T2.20 150 OE rows single trip, no truncation, all distinct source_keys ✓
  - +bonus: all 6 legacy scalars materialise correctly ✓; manual Expense untouched by trip sync ✓
- **T2.13 – T2.17 deferred to Turn 2B/2D by design** (Vehicle Cost read, Repair History, Vendor/Mechanic Ledgers, cost-vs-payment-date reports — not part of Turn 2A scope).

### Regression evidence
- Turn 1 suite (`test_iter133_expense_turn1.py`): **23 / 23 PASS**.
- Trip / customer-ref / supplier suites (`iter49, iter56, iter83, iter91, iter92, iter45`): **33 / 33 PASS** (18.77 s).
- Supplier freight + idempotency + policy change + multi-trip supplier UAT (`iter111, iter126b, iter102, iter105`): **30 / 30 PASS** (12.08 s).

### Live smoke evidence
Live POST `/api/trips` with `expenses={toll:1000, repair:500}` returned `has_canonical_expenses=True`; live GET `/api/expenses?trip_id=…` returned exactly 2 rows: `Toll ₹1000 src=trip:{tid}:legacy:toll`, `Repair ₹500 src=trip:{tid}:legacy:repair`.

### Duplicate-counting proof (write-time + read-time)
- One user action → one canonical Expense per source_key (upsert semantics; partial UNIQUE index).
- Payments (Vendor / Mechanic) never touch the Expense collection — asserted by tests T2.11 + T2.12.
- Manual Expenses never touched by trip sync — asserted by dedicated bonus test.
- Turn 2B / future reports must honour the XOR bridge: `if trip.has_canonical_expenses → read canonical; else → read legacy scalars`. No additive path.

### Locked-area untouched confirmations
✅ C3.1 / C3.2 / C3.4 / C3.5 / C4 untouched.
✅ C5 (deferred) untouched.
✅ DG-STABILITY-1 · `pytest.ini` · `scripts/run_regression.sh` untouched.
✅ `services._compute_trip` unchanged. Driver-recovery sync unchanged. Invoice recompute unchanged.
✅ Fuel collection standalone (as approved).
✅ Batta → Driver Ledger NOT auto-posted (deferred per user decision).

### Known limitations
- **No** Trip UI change in Turn 2A — legacy Trip form works as-is; server materialises silently in the background.
- **No** Vehicle Cost report, Repair History, Vendor / Mechanic Ledger UI, Paid/Outstanding — Turn 2B.
- **No** supplier-settlement projection into supplier ledger — Turn 2C or later.
- **No** legacy-Trip materialisation of `Trip.expenses` for `vehicle_type='supplier'` treatment (currently materialises as own-side cost; behaviour matches current `services._compute_trip` semantic for own-side scalars but semantic clarification will be visited when Vehicle Cost report is added).
- **No** mass migration of historical trips — only trips saved AFTER Turn 2A go live receive canonical rows.

### Next sub-turn
**Turn 2B — Vehicle Cost + Vehicle Repair History (read-only endpoints + minimal UI).** Awaiting explicit GO before starting.

### Final status
**EXPENSE TURN 2A COMPLETE — NOT READY FOR UAT — NOT READY FOR LOCK.** Full slice (through Turn 2D) required before UAT.

## Iter133 · Expense / Vehicle Cost Management — Turn 1 COMPLETE — NOT READY FOR UAT (2026-09-02)

**Status:** Foundation slice implemented per FROZEN architecture. Not locked. Not UAT-ready. Turn 2 (Trip write-path integration + reporting) pending.

### Architecture (frozen; also see conversation-history freeze reply)
- **Three distinct parties**: `Supplier` (hired vehicle owner — existing, untouched), `Vendor` (spare-parts / workshop — NEW), `Mechanic` (labour — NEW). Separate masters, separate ledger semantics. No `supplier_kind` polymorphism.
- **Four roles**:
  - `RepairEvent` — operational envelope. **NEVER stores a monetary total.** `extra='forbid'` on the Pydantic model — any `total_cost` field triggers 422.
  - `VendorBill / MechanicWorkOrder` — payable + document evidence.
  - `Expense` — **canonical authoritative cost transaction.** One real-world cost = one Expense row.
  - `VendorPayment / MechanicPayment` — cash movement only. **NEVER creates or modifies an Expense.**
- **Report source map (future turns will read strictly this way)**:
  - Vehicle Cost / Trip Cost / Expense Register → `Expense` only.
  - Vendor Ledger → `VendorBill + VendorPayment` only.
  - Mechanic Ledger → `MechanicWorkOrder + MechanicPayment` only.
  - Supplier Statement → existing supplier ledger + Expense projections where `supplier_settlement_mode='supplier_settlement_adjustment'`.
  - No report ever sums both a payable source and its twin Expense source.
- **Turn-1 hard constraint (frozen)**: `1 VendorBill → at most 1 vehicle_id`. Multi-vehicle split is P1 · DEFERRED.
- **Legacy Trip.expenses / other_expenditures**: untouched, backward compatible. Bridge via `has_canonical_expenses` XOR flag lands in the Trip-integration turn.
- **Fuel collection**: untouched (keeps litres/rate/odometer richness).
- **Batta → Driver Ledger**: DEFERRED to Driver Salary/Advance module (Turn 1 does NOT auto-post).
- **MaintenanceLog**: retired (dead code; no live rows; no CRUD router). Not migrated. RepairEvent + Expense replaces it.

### Files added (all additive · NO existing router / model / test touched)
- `backend/routers/vendors.py` — NEW · Vendor master CRUD + minimal VendorPayment CRUD.
- `backend/routers/mechanics.py` — NEW · Mechanic master CRUD + minimal MechanicPayment CRUD.
- `backend/routers/repair_events.py` — NEW · RepairEvent envelope CRUD.
- `backend/routers/vendor_bills.py` — NEW · VendorBill CRUD.
- `backend/routers/mechanic_work_orders.py` — NEW · MechanicWorkOrder CRUD.
- `backend/routers/expenses.py` — NEW · Expense CRUD with all Turn-1 invariants (twin-FK XOR, party-mismatch guard, supplier_settlement_mode explicit-choice guard, file_id tenant validation).
- `backend/tests/test_iter133_expense_turn1.py` — NEW · 23 tests covering party separation, envelope-no-total, 18k+7k repair no-double-count, write-time invariants, mode handling, trip-toll canonical entry, attachments, payment ≠ Expense, partial payments, cross-party rejection, idempotency, soft-delete + RBAC, tenant isolation, audit trail.

### Files edited (additive only)
- `backend/models.py` — APPEND new models (`Vendor`, `Mechanic`, `RepairEvent`, `VendorBill`, `MechanicWorkOrder`, `Expense`, `VendorPayment`, `MechanicPayment`). No existing model changed.
- `backend/server.py` — Wire the 6 new routers in the mount loop; add index-creation calls in startup for `vendors / mechanics / repair_events / vendor_bills / mechanic_work_orders / expenses / vendor_payments / mechanic_payments`.
- `backend/idempotency.py` — Add 10 new Bucket-B POST patterns to the whitelist (vendors/mechanics create + reactivate + payments; repair-events; vendor-bills; mechanic-work-orders; expenses).

### APIs (all `/api` prefixed, company-scoped via `X-Company-Id`)
- Vendor master: `GET/POST /vendors`, `GET/PUT/DELETE /vendors/{vid}`, `POST /vendors/{vid}/reactivate`
- Vendor payments (minimal): `GET/POST /vendors/{vid}/payments`, `PUT/DELETE /vendors/{vid}/payments/{pid}`
- Mechanic master: `GET/POST /mechanics`, `GET/PUT/DELETE /mechanics/{mid}`, `POST /mechanics/{mid}/reactivate`
- Mechanic payments (minimal): `GET/POST /mechanics/{mid}/payments`, `PUT/DELETE /mechanics/{mid}/payments/{pid}`
- Repair envelope: `GET/POST /repair-events`, `GET/PUT/DELETE /repair-events/{rid}`
- Vendor bills: `GET/POST /vendor-bills`, `GET/PUT/DELETE /vendor-bills/{bid}`
- Mechanic work orders: `GET/POST /mechanic-work-orders`, `GET/PUT/DELETE /mechanic-work-orders/{wid}`
- Expenses: `GET/POST /expenses` (rich filters: trip/vehicle/repair/party/category/date range), `GET/PUT/DELETE /expenses/{eid}`

### Turn-1 invariants (enforced at write time)
| Rule | Enforcement |
|---|---|
| RepairEvent has no monetary total | `model_config = ConfigDict(extra='forbid')` → 422 on any `total_cost` |
| Expense.amount > 0 | 400 |
| Expense.date & category required | 400 |
| Twin-FK XOR (vendor_bill_id XOR mech_wo_id) | 400 if both |
| Vendor-bill linkage: party_type='vendor' + party_id = VB.vendor_id | 400 mismatch |
| Mechanic-WO linkage: party_type='mechanic' + party_id = WO.mechanic_id | 400 mismatch |
| supplier_owned_vehicle XOR settlement mode: True → mode∈{adjustment,company_borne}; False → 'n/a' | 400 |
| VendorBill 1 → ≤ 1 vehicle_id | schema (single scalar) |
| VendorBill duplicate `(vendor_id, bill_number)` | 409 |
| Payment never creates Expense | Payment routers do NOT touch expenses collection (test-verified) |
| Payment cross-party | 400 if VP.vendor_id ≠ bill.vendor_id (or same for mechanic) |
| File attachments must be same-tenant | 400 on invalid file_id |
| Delete requires audit reason ≥ 3 chars | 422 |
| RepairEvent / VendorBill / MechanicWO delete blocked while linked live records exist | 400 |
| Soft-delete only (never hard-delete) | is_deleted=true + deleted_by/at/reason |

### RBAC + tenant isolation
- Read/Create/Update: any authenticated user (mirrors Supplier module).
- Delete + Reactivate: Owner / Admin only (`effective_role` check → 403 otherwise).
- All queries scoped by `user_id + company_id`. `X-Company-Id` header switches active company.

### Audit + idempotency
- Every create/update/delete logged via `_log_audit()` under modules: `vendor / mechanic / repair_event / vendor_bill / mechanic_work_order / expense / vendor_payment / mechanic_payment`.
- All 10 new POST endpoints are Bucket-B: send `Idempotency-Key: <string>` and the middleware replays cached response 24 h.

### Indexes (all idempotent, created on backend startup)
- vendors: `(user_id, company_id, name)` — `vendors_scope_name`
- mechanics: `(user_id, company_id, name)` — `mechanics_scope_name`
- repair_events: `(user_id, company_id, event_date DESC)`, `(vehicle_id)`, `(trip_id)`
- vendor_bills: `(user_id, company_id, bill_date DESC)`, `(vendor_id)`, `(repair_event_id)`, `(vehicle_id)`
- mechanic_work_orders: `(user_id, company_id, work_date DESC)`, `(mechanic_id)`, `(repair_event_id)`, `(vehicle_id)`
- expenses: `(user_id, company_id, date DESC)`, `(trip_id)`, `(vehicle_id)`, `(repair_event_id)`, `(vendor_bill_id)`, `(mechanic_work_order_id)`, `(party_type, party_id)`, `(category)`
- vendor_payments: `(user_id, company_id, date DESC)`, `(vendor_id)`, `(vendor_bill_id)`
- mechanic_payments: `(user_id, company_id, date DESC)`, `(mechanic_id)`, `(mechanic_work_order_id)`

### Test evidence
- **Turn-1 targeted suite `test_iter133_expense_turn1.py`: 23 / 23 PASS** in 3.65 s (serial `-n 0`).
- Regression:
  - Supplier module: `test_iter45_supplier_module_phase1.py + iter45_multicompany_isolation.py + iter91_supplier_entries.py + iter92_supplier_halting.py + iter47_phase3_supplier_deep.py` → **22 / 22 PASS** (25.82 s).
  - Trip / Vehicle: `test_iter49_trip_edit_halting_regression.py + iter56_trip_search_filter.py + iter83_trips_list_cust_ref.py + iter90_product_wise_supplier_shortage.py + iter63_supplier_vehicle_master.py` → **30 / 30 PASS** (15.30 s).
  - Idempotency + supplier freight: `test_iter111_supplier_freight_and_shortage.py + iter127c_supplier_deactivate.py + iter126b_idempotency.py` → **28 / 28 PASS** (8.64 s).
- Pre-existing failures observed while running `test_iter132a/b/c` (8 failed): all are `ModuleNotFoundError: No module named 'services' / 'xlsx'` — tests use `from services import ...` and `from xlsx.gstr1 import ...` which only resolves under the configured xdist bootstrap (`-n 2 --dist loadscope`) and NOT under isolated targeting. **These failures are xdist-sys.path dependent, pre-existing, and unrelated to Iter133**. Files touched by Turn 1 do not include `services.py`, `pdf/gstr1.py`, `xlsx/gstr1.py`, credit-note flow, or DN flow.

### Confirmations (untouched)
- C3.1, C3.2, C3.4, C3.5, C4 modules — untouched.
- C5 — deferred; untouched.
- DG-STABILITY-1 — untouched.
- `pytest.ini`, `backend/scripts/run_regression.sh` — untouched.
- Locked C3/C4 semantics preserved.

### Turn-1 explicit non-goals (deferred; NOT implemented)
Vehicle Repair Reports · Vehicle Cost Reports · Vendor Ledger UI · Mechanic Ledger UI · Paid/Outstanding reports · Trip Cost reporting · Profitability · Fuel → Expense merge · Driver Ledger Batta integration · Multi-vehicle VendorBill split · Inventory · GST ITC · Tally export · Driver Salary · Tyre · Maintenance module · Spares inventory · Legacy Trip write-path materialisation (materialisation into canonical Expenses lives in a later turn) · Supplier-ledger projection extension.

### Turn 2 proposed scope (awaiting user GO)
1. Trip write-path integration — flat `Trip.expenses.*` + `other_expenditures[]` submitted through the legacy Trip form get materialised into canonical Expense rows atomically; `Trip.has_canonical_expenses=true` set atomically. XOR reporting switch.
2. Vehicle Cost / Vehicle Repair History read-only endpoints + minimal UI.
3. Vendor Ledger / Mechanic Ledger read-only endpoints + UI (mirrors Supplier Ledger).
4. Supplier-settlement-adjustment projection into existing supplier ledger (CREDIT rows).
5. Cost-date vs Payment-date parametrised reports.

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
- **Iter133 · L2d v3 · Invoice PDF Reliability / Multi-page Rendering** — 🔒 **LOCKED · UAT approved 2026-08-31**
  - **Problem**: Real invoices with dense content (multi-trip + halting sub-rows + long amount-in-words) returned HTTP 500 on `GET /api/invoices/{iid}/pdf`, breaking both Invoice PDF Preview and Download. Original defect: `AKB/26-27/0025` (9 trips + 2 halting rows, MEGHA ENGINEERING, tenant A KISHORE BABU & SONS).
  - **Fix 1 — Safe-width corrections (layout only)**: `tc_inline_tbl = 147 mm`, `left_bank_tbl = 163 mm`, `bottom_tbl = [163 mm, 107 mm]`, `sig_tbl = [161 mm, 109 mm]`. Sum ≤ 270 mm — inside the 272.77-mm frame content width after reportlab's default 12-pt L/R padding.
  - **Fix 2 — Fresh Flowable objects for two-pass render (root-cause fix)**: Story assembly wrapped in `def _make_story():` closure (`pdf/invoice.py:164-775`). Both `SimpleDocTemplate.build()` passes now receive freshly-instantiated `Table` / `Paragraph` / `KeepTogether` / `Spacer` / nested-table objects — eliminates reportlab flowable-state pollution (`Table._rowHeights`, `KeepTogether._postponed`, Frame accounting) across passes. `_count_doc.build(_make_story())` (line 793) + `doc.build(_make_story(), onFirstPage=_footer_cb, onLaterPages=_footer_cb)` (line 796). `_count_doc` + `_footer_cb` construction hoisted OUT of the closure so they survive both passes.
  - **Fix 3 — Forward-compatible Iter127b static guardrail**: `test_8_source_guardrail_two_pass_wiring` now accepts either the original `list(story)` OR the L2d v3 `_make_story()` two-pass pattern, preserving intent while allowing improvement.
  - **Zero touches** to invoice calculations, freight, GST/RCM, halting, shortage/excess, diesel/HSD, advances, subtotal, round-off, final payable, amount-in-words calculation/content, invoice numbering, invoice schema, persisted `balance_due`, effective-balance logic, CN/DN, Ledger, Customer Statement, Passbook, Auth/RBAC, Save Health, and every previously locked Iter132/133 area.
  - **Verification evidence (authoritative, measured)**:
    - **Targeted 18/18 pass** (15.32s): Iter127b page-of-pages 10/10 + Invoice PDF wide-content regression 6/6. Breakdown: (1) 1-trip / no-halting HTTP · (2) 9-trip + halting HTTP · (3) long amount-in-words HTTP · (4) combined halting+shortage+diesel+advance HTTP · (5) static width invariant ≤ 270 mm · (6) 30-trip multi-page HTTP. At least two dense tests exercise the real router path.
    - **Full Deploy Guard** — `checked_at=2026-08-31T14:17:04.508006+00:00 · status=pass · elapsed_s=743.6 · exit_code=0 · consecutive_failures=1 (residual from prior guardrail-stale run, now cleared) · strict_mode=true · next_check_at=2026-08-31T15:17:04.508014+00:00 · pytest_summary="503 passed, 1 skipped, 0 failed, 8 warnings in 743.21s"`. Iter128 Deploy Readiness Badge 🟢 GREEN.
    - **Real AKB tenant UAT** (read-only Mongo lookup of production records for tenant `A KISHORE BABU & SONS`, user_id `user_63cdc1a46ace`, in-process `build_invoice_pdf` on actual documents):
      - **`AKB/26-27/0024`** (control · 1 trip): 965,029 bytes · **1 page** · Preview + Download HTTP 200 ✅
      - **`AKB/26-27/0025`** (originally failing · 9 trips + 2 halting): 967,469 bytes · **2 pages** · **9/9 trips retained** · **2 halting rows retained** · ₹ glyph · Amount in Words · Signatory · Page X of Y · Preview + Download HTTP 200 ✅
    - Human-eye UAT sign-off received from the AKB user post-fix. Original HTTP 500 / LayoutError defect **resolved**.
  - **Master Principle contract locked**: *CONTENT GROWS → PAGE COUNT GROWS → PDF STILL SUCCEEDS.* Fix is **generic**, not 0025-specific — validated across 1-trip · 9-trip+halting · 30-trip multi-page · long-amount-in-words · combined-sub-rows shapes. 50-trip / 100-trip invoices supported by the same fresh-flowable + safe-width envelope. HTTP 500 on any legitimate invoice is inadmissible going forward.
  - **Files changed**: `backend/pdf/invoice.py` (4 width edits + story-factory closure refactor · no calculation change), `backend/tests/test_invoice_pdf_wide_content_regression.py` (NEW · 6 tests), `backend/tests/test_iter127b_invoice_page_of_pages.py` (guardrail updated to accept both patterns).
  - **Restarts**: 3 authorized backend restarts across the slice (v1 width · v2 width tightening · v3 story-factory). Zero unauthorized.
  - **Existing locks preserved**: Iter126, Iter127a-c, Iter128, Iter129, Iter130, Iter131, Iter132a/b, Iter132c C1/H1/C2/C2b/C2c, Iter133 L1/L1.5/L2/L2b/L2c/L2d/L2e — all remain locked and untouched.
  - **Backlog frozen**: C3 GSTR-1 §9B · C4 CN/DN Register · Statement Email Delivery · Iter132c-agg-fix · Phase 2 Security · `AKB/26-27//26-27/0004` hygiene · Preview Uptime Chip · LR Digest · Trip Templates · Trip Sheet redesign · Tyre · Driver Salary · Expense/Vehicle Cost ERP · Maintenance.


## Iter132c · C5 · GSTR-1 §9C CDNRA / CDNURA Amendments — 🟡 DEFERRED (2026-09-02)

**Status**: Phase 1 discovery complete. **Implementation intentionally postponed** in favour of higher-priority operational ERP modules.

**Architectural prerequisite identified (Phase 1 finding)**: a genuine data-model gap exists — QORVENA today has no persistent prior-filing manifest and no CN/DN amendment lifecycle. Emitting CDNRA/CDNURA without those two foundations would either fabricate statutory claims from a heuristic (`cancelled_after_export[]`) or create a second CN/DN source of truth. Both violate the master principle.

**Prerequisite (approved but on-hold) — required before any C5 code is written**:
1. New persistent collection `gstr1_filings` — one immutable manifest per `(company_id, period_yyyy_mm, section)` recording the exact frozen note set + canonical SHA256 hash + operator-confirmed `Mark as Filed` action. This is the authoritative prior-filing evidence — NOT `audit_logs`, NOT `cancelled_after_export[]`, NOT `approved_at`.
2. Scoped unlock of `backend/models.py` + `backend/routers/notes.py` to add three fields on `CreditDebitNote` (`amends_note_id`, `amendment_seq`, `amendment_reason_text`) plus two new endpoints `POST /credit-notes/{nid}/amend`, `POST /debit-notes/{nid}/amend`. Chain semantics: original `seq=0, amends_note_id=None`; amendments are NEW documents pointing to the LAST-IN-CHAIN note; monotonic seq; no forks; no cycles; original never overwritten.
3. Amendment gate: an amendment (or cancellation-as-amendment) requires the target note to be present in a filed manifest for its `note_date`'s period+section — else HTTP 422 `prior_filing_evidence_missing`.

**Planned phased implementation (when un-deferred)**:
- Turn A.1 · Filing manifest persistence + `POST /reports/gstr1-filings/mark-filed` + T1-T6
- Turn A.2 · Amendment lifecycle + `POST /{cn,dn}/{nid}/amend` + T7-T14
- Turn B · `_gstr1_9c_payload()` canonical builder + `GET /reports/gstr1-9c` + T15-T25
- Turn C · High-volume + UI (Mark-as-Filed, Amend, chain view, §9C review tab) + T26-T31
- Turn D (optional) · §9C Offline Utility JSON adapter (mirror of C3.4)

**Preserved discovery evidence**:
- Statutory schema (CDNRA/CDNURA fields `ont_num`, `ont_dt`, `nt_num`, `nt_dt`, `ntty`, `pos`, `typ`, `itms.itm_det`) confirmed against `tutorial.gst.gov.in/contextualhelp/Einv/CDNRA.htm`, `tutorial.gst.gov.in/contextualhelp/Einv/CDNURA.htm`, offline-utility PDF, sandbox developer references.
- Full field-by-field mapping, edge-case matrix, routing rules (CDNR → CDNRA, CDNUR B2CL → CDNURA), and RBAC/audit design captured in the Phase 1 discovery report (this session's conversation history).
- 5 MB portal ceiling applies to §9C output (same as C3.4).
- IFF quarterly M1/M2 restriction (only B2B, CDNR, B2BA, CDNRA allowed) noted.

**Zero code touched during Phase 1 discovery**. No new collection, no schema change, no endpoint, no test, no UI. Discovery was strictly read-only.

**Blockers to un-defer**: business-side prioritisation only. No technical blocker.


## Iter132c · C3.4 · GSTR-1 §9B Offline Utility JSON — ✅ READY FOR UAT (2026-09-02 · not yet locked)

### Scope shipped
- Additive endpoint `GET /api/reports/gstr1-9b-offline.json?month=YYYY-MM[&raw=0|1]`. Returns either the QORVENA envelope `{utility_json, advisories, meta}` (default) or the standalone GSTN utility JSON body when `raw=1` (importable file suitable for the GSTN Offline Tool workflow, subject to operator-side portal round-trip verification).
- Pure adapter `_gstr1_9b_offline_json_projection()` in `backend/routers/gst.py` — takes the LOCKED C3.1 canonical payload and re-shapes it into the exact GSTN GSTR-1 Offline Utility V3.2 envelope for Table 9B (CDNR + CDNUR). NO DB access. NO recompute. NO second calculator.
- Fail-loud validator `_validate_gstn_utility_envelope()` — enforces envelope key set, GSTIN regex, `fp` = MMYYYY, `nt_num ≤ 16`, CDNUR `pos` is 2-char digit, `typ` in {B2CL, EXPWP, EXPWOP}, duplicate `(ctin, nt_num)` and duplicate CDNUR `nt_num` detection, and the 5 MB portal-ceiling body-size check.
- New Reports UI button on the existing GSTR-1 §9B tab: **"§9B Offline JSON"** (`data-testid="g9b-download-offline-json-btn"`). Reuses the same month selector and download plumbing; disabled while the C3.1 canonical report is loading or in reconciliation-mismatch state.

### Frozen design decisions
1. **`version`** default = `"3.2"` per `tutorial.gst.gov.in/downloads/invoiceuploadofflineutility.pdf`. Operator override via env `GSTN_UTILITY_VERSION_STRING` — never permanently hard-coded outside the `_GSTN_UTILITY_VERSION_DEFAULT` constant.
2. **`gt` / `cur_gt`** emitted as `0` with explicit `advisories.gt_cur_gt_defaulted_to_zero = true` — QORVENA does not persist prior-year / current-year gross turnover; scope not expanded.
3. **`hash`** emitted as literal `"hash"` (utility-format convention matching every public Excel-to-JSON converter sample). QORVENA does NOT claim to generate the portal's real cryptographic hash — the portal recomputes on import.
4. **Statutory claim scope**: `"GSTN Offline Utility JSON — schema/shape validated (portal round-trip not performed)"`. NO "portal upload-ready" claim.
5. **5 MB portal ceiling** (`tutorial.gst.gov.in/downloads/invoiceuploadofflineutility.pdf`): utility body serialised bytes are measured (`meta.utility_json_bytes`) and > 5 MB triggers a HTTP 422 with a fail-loud `utility_json_exceeds_5mb_portal_ceiling` problem — automated chunk generation NOT implemented in this slice.

### Exclusions surfaced via advisories (no silent drop)
- `commercial_notes_excluded_from_offline_json` — `apply_gst=false` notes (out of §9B statutorily)
- `b2cs_report_net_of_in_table_7` — B2CS adjustments (net-of in Table 7, out of §9B)
- `cancelled_after_export_requires_9c_amendment` — §9C CDNRA/CDNURA amendments deferred to C5
- `rsn_field_omitted_portal_optional_in_v3_2` — reason code preserved in C3.1/XLSX/PDF (audit) but not present in the GSTN utility schema
- Draft notes and cancelled-within-period notes are already dropped by the LOCKED C3.1 payload — same behaviour preserved

### Test evidence (2026-09-02)
- **C3.4 targeted suite `test_iter132c_c3_4_gstr1_offline_json.py`: 24 / 24 PASS** (T1 B2B CN → CDNR shape · T2 B2B DN IGST · T3 mixed CN+DN same ctin sorted · T4 fp=MMYYYY + out-of-period excluded · T5 CDNR routing · T6 CDNUR B2CL 2-char pos · T7 B2CS excluded + advisory · T8 GSTIN+POS mapping · T9 RCM Y/N verbatim · T10 commercial excluded + advisory · T11 draft excluded · T12 cancelled-within-period excluded · T13 duplicate prevention · T14 canonical parity vs C3.1 · T15 sum of `val` == C3.1 totals · T16 envelope required keys + types · T17 fail-loud 422 on missing issuer GSTIN · T18 idempotency · **T19 10 000 notes streaming + byte-size measurement** · T20 schema/version compliance · T21 cancelled-after-export advisory only · T22 byte-size fields present and match local serialisation · T23 raw=1 returns utility_json body only · T24 GSTN_UTILITY_VERSION_STRING env override honoured).
- **C3.1 + C3.2 regression: 37 / 37 PASS** (16.6 s).
- **C4 + C3.5 regression: 54 / 54 PASS** (212 s).
- **C3.1 §9B period-boundary flake reproduces DG-STABILITY-1** (unrelated xdist shared-state race): fails under xdist parallel with C4, passes when run solo. NOT a C3.4 defect. LOCKED files unchanged. Ticket already documented under DG-STABILITY-1 P1 backlog.

### Live artifact (2026-09-02 · demo tenant · active company `co_d2ef16a8cf364265` GSTIN `37ZZZZZ9999Z1Z5` · period 2026-08)
| Artefact | Bytes | SHA256 |
|---|---|---|
| Envelope `{utility_json, advisories, meta}` | 970 | `04adf87ec8caa7017616a4b74a6f53729423dfd0e90b2cd40272b6aa5726e275` |
| Raw utility_json (`?raw=1`) | 110 | `ff294a2e9f6515797a233e73b9d19f343457fbee8974a2d2eb2b566c061419dd` |

Envelope fields verified: `gstin=37ZZZZZ9999Z1Z5`, `fp=082026`, `version=3.2`, `hash="hash"`, `gt=cur_gt=0`, `canonical_reconciled=true`, `utility_json_over_5mb=false` (110 B / 5 242 880 B). Advisories: `gt_cur_gt_defaulted_to_zero=true`, `rsn_field_omitted_portal_optional_in_v3_2=true`, all exclusion counters `0` for this period. Byte-parity confirmed: raw response body == envelope's `utility_json` serialisation.

### Files touched (all additive)
- `backend/routers/gst.py` — ADD `_GSTN_*` constants, `_gstn_utility_version()`, `_gstn_pos_2char()`, `_gstn_fp()`, `_gstr1_9b_offline_json_projection()` adapter, `_validate_gstn_utility_envelope()` validator, `GET /api/reports/gstr1-9b-offline.json` route. `import json` added to module imports.
- `backend/tests/test_iter132c_c3_4_gstr1_offline_json.py` — NEW · 24 tests T1–T24.
- `frontend/src/pages/Reports.jsx` — ADD `doOfflineJsonDownload()` handler + one button in `GSTR19BReport()`. No other visual change.

### Files explicitly UNTOUCHED (LOCKED)
- `_gstr1_9b_payload()` and every existing C3.1 route in `routers/gst.py`
- `_GSTR1_9B_REASON_MAP` in `services.py`
- `backend/xlsx/gstr1_9b.py`, `backend/pdf/gstr1_9b.py` (C3.2)
- `backend/xlsx/gstr1.py`, `backend/pdf/gstr1.py` (C3.5)
- `backend/xlsx/cndn_register.py`, `backend/pdf/cndn_register.py`, `frontend/src/pages/CndnRegister.jsx` (C4)
- `pytest.ini`, `backend/scripts/run_regression.sh`, DG tests

### Known limitations documented
- Portal-utility import round-trip **not** performed in this sandbox. Claim scope = "schema/shape validated". Any deeper claim requires an operator-side utility import UAT.
- 5 MB oversize returns fail-loud 422; automated chunk-splitting is out of scope for this slice.
- `EXPWP`/`EXPWOP` CDNUR variants are validator-permitted but not emitted (QORVENA is transport-domestic — no export data model exists today).

### Status
**READY FOR UAT — NOT YET LOCKED.** Awaiting explicit LOCK approval after operator-side utility-import UAT.


## Iter132c · C4 · Credit Note / Debit Note Register (JSON + XLSX + PDF) — 🔒 LOCKED / FROZEN (2026-09-02 · UAT approved · XLSX spec-compliance corrected pre-lock · fresh artifact provenance verified)

### FINAL LOCK EVIDENCE (2026-09-02)
1. **C4 targeted suite**: **21 / 21 PASS** (T1–T21 including T19 10 000-note streaming, T20 landscape column-width envelope, T21 effective-balance parity with `services._effective_invoice_totals`).
2. **Regression**: **C3.5 + C3.2 = 51 / 51 PASS** — zero cross-contamination.
3. **High-volume**: 10 000 CN/DN notes streaming verified in T19 (35.7 s). No `to_list()` truncation. No N+1: exactly one `find().sort()` streaming cursor over `credit_debit_notes` + one bounded `$in` per referenced customer set + one bounded `$in` per referenced invoice set.
4. **Fresh canonical JSON** (active company `co_c2ac839cf8bf4ff4` · `TEST Iter7 Co` · GSTIN `36AAAAA0000A1Z5` · period 2026-09-01→2026-09-02): `note_count=301` · `len(rows)=301` · `len(by_customer)=81` · `len(by_reason)=9` · `tax_summary.total_amount=₹23,811.00` · `reconciliation.reconciled=True` · `warnings=[]`.
5. **Fresh XLSX** (SHA256 `63c7b9c4eab27dea1b20a77a7c8c8330d06ae43fb0e62bf053c592ed8dbfb5d4`): sheet names EXACTLY `['Summary','Register','By_Customer','By_Reason']` in that order · Register rows 301 == JSON `len(rows)` · By_Customer rows 81 == JSON `len(by_customer)` · By_Reason rows 9 == JSON `len(by_reason)` · numeric currency cells numeric · Register `Total` column format `"₹ "#,##0.00`.
6. **Fresh PDF** (SHA256 `f06e12800e712d79bc841fb86d29ca00354296fd7b124381a4557dfb5bf6e952`): 17 pages · A4 landscape (841.89 × 595.28 pt) · header shows `TEST Iter7 Co · GSTIN: 36AAAAA0000A1Z5 · State: Telangana (36)` · `Reconciled: YES` on page 1 · U+20B9 (₹) glyph present · zero U+FFFD tofu · "NOT a GST portal upload file" disclosure banner present · `Register` section present · `Page 1 of 17` footer present · `issuer_company_gstin_missing` warning ABSENT (GSTIN configured on this company).
7. **UI parity**: `/reports/cndn-register` in the same demo session on active company `TEST Iter7 Co · default` renders **301 notes · Total ₹23,811.00 · Credit 261 · Debit 40 · Net Δ ₹-9,091.00** — byte-parity with the fresh JSON/XLSX/PDF.
8. **PDF warning behavior**: `issuer_company_gstin_missing` logic in `_cndn_register_payload()` UNCHANGED. Remains a legitimate fail-loud data-quality warning that fires only when the *selected* company's profile has an empty `gstin` field. Correctly absent for GSTIN-configured companies and correctly present for GSTIN-less companies (as observed on the earlier 2-page UAT artifact generated against a different company on the same tenant).
9. **XLSX spec-compliance correction (performed pre-lock, 2026-09-02)**: initial delivery accidentally emitted `Summary / Credit_Notes / Debit_Notes / By_Reason`. Corrected to approved spec `Summary / Register / By_Customer / By_Reason` via XLSX-projection-layer + T15/T16 test assertions only. Zero backend / API / data-model / PDF / frontend / C3.x / DG-STABILITY-1 changes required or made. Approved spec now compliant.
10. **C3.5**: LOCKED and untouched (verified: `backend/xlsx/gstr1.py`, `backend/pdf/gstr1.py`, `backend/routers/gst.py`, `backend/tests/test_iter132c_c3_5_gstr1_export.py` — zero diff since C3.5 lock).
11. **DG-STABILITY-1**: untouched · remains separate P1 backlog item · `pytest.ini`, `backend/scripts/run_regression.sh`, `test_iter51_deploy_guard_and_alerts.py`, `test_iter67_extras.py`, `test_iter26_phase1_ai_templates.py` unmodified.
12. **Official DG definition**: unchanged.

### MASTER PRINCIPLE SATISFACTION (LOCKED CHAIN)
`db.credit_debit_notes` (authoritative source · `_compute_note_totals` LOCKED Iter132a/C2b) → `_cndn_register_payload()` canonical register dataset (SINGLE COMPUTATION) → CndnRegister UI · XLSX 4-sheet workbook · PDF working report · effective-balance / ledger parity via `_effective_invoice_totals` + `_apply_effective_balance` · GSTR-1 §9B statutory classification parity via `_GSTR1_9B_REASON_MAP`. **ENTER ONCE → CALCULATE ONCE → REFLECT EVERYWHERE → REPORT READY → NO MANUAL RECONCILIATION.**

### FROZEN SCOPE
After this lock: no C4 code changes · no C4 UI changes · no C4 PDF/XLSX presentation changes · no C4 test changes. Any future C4 modification must be a separately approved change.

---

## Iter132c · C4 · Credit Note / Debit Note Register (JSON + XLSX + PDF) — 🔒 LOCKED (2026-09-02 · pytest 21/21 · live UAT preview verified)
- **Scope shipped in C4**: three additive endpoints — `GET /api/reports/cndn-register`, `.xlsx`, `.pdf` — all PURE PROJECTIONS of a single canonical `_cndn_register_payload()` helper in `backend/routers/reports.py`. New tab + page under **/reports/cndn-register** with 4-button pattern (View Register · Download JSON · Download XLSX · Download PDF) mirroring the LOCKED GSTR1Report visual language. NO new persisted register collection.
- **Architecture (LOCKED · ONE SOURCE OF TRUTH)**:
  - `db.credit_debit_notes` (LOCKED Iter132a/C2b) → `_cndn_register_payload()` → JSON · XLSX · PDF (identical values, three renderers).
  - Reuses canonical helpers only: `_compute_note_totals`, `_effective_invoice_totals`, `_apply_effective_balance`, `_GSTR1_9B_REASON_MAP`. Register row values are read verbatim from persisted notes; NO recompute anywhere in the endpoint or exporters.
- **Filter matrix** (all optional except date defaults to current month): `from`, `to` (ISO YYYY-MM-DD), `kind` (all|credit|debit), `customer_id`, `status` (issued|draft|cancelled|all — default issued), `reason_code` (QORVENA enum). Every filter narrows in Mongo (not in Python).
- **Row semantics**: credit → `signed_amount = -total_amount`; debit → `signed_amount = +total_amount`; KPI `net_amount = debit_total - credit_total`. Each row also carries the deterministic `reason_code_gstr1_9b` §9B statutory remap (`_GSTR1_9B_REASON_MAP`; unknowns → "07 Others" with warning).
- **High-volume correctness**: streaming Motor cursor with in-Mongo `note_date` range filter + bounded `$in` preloads for referenced customer_ids / invoice_ids only. NO `to_list(5000)/(2000)` truncation. Proven at **10 000 notes / 200 customers** by T19 (test elapsed 35.7s).
- **Fail-loud reconciliation**: `reconciliation.reconciled=False` when endpoint row count / total ≠ Mongo `$group` ground truth over the identical filter → surfaces a `warnings[]` entry rather than silent drift.
- **Exports**:
  - XLSX (`backend/xlsx/cndn_register.py`) — 4 sheets: **Summary / Credit_Notes / Debit_Notes / By_Reason**. Currency cells use `"₹ "#,##0.00` prefix format. Register row shape (22 columns) mirrors JSON.
  - PDF (`backend/pdf/cndn_register.py`) — A4 landscape, L2d v3 fresh-flowable two-pass render, `Page X of Y` footer on every page, DejaVu ₹ glyph, disclosure banner "NOT a GST portal upload file". Register table 14 columns · widths sum ≤ 273mm (T20 guardrail).
- **Frontend** (`frontend/src/pages/CndnRegister.jsx` + `Reports.jsx` tab entry): Filter bar (From, To, Kind, Status, Customer dropdown from paginated `/customers`, Reason dropdown) · 5 KPI cards (Total · CN · DN · Net Δ · Cancelled) · Tax Summary band (Taxable / CGST / SGST / IGST / Total Tax / Grand Total) · By-Reason breakdown table · Register table with credit/debit row tint + drill-down links to Notes and Invoice preview · 4 action buttons + View JSON toggle · Reconciled banner. `useCdnEnabledState()` hook variant added to `useCdnEnabled.js` to avoid initial-render redirect race.
- **Verification evidence (authoritative, measured)**:
  - Targeted `test_iter132c_c4_cndn_register.py`: **21/21 pass in 36.55 s**. Covers T1 canonical shape · T2 bad-kind 400 · T3 bad-status/reversed-dates 400 · T4 default month range · T5 kind filter · T6 customer_id filter · T7 reason_code filter + §9B remap · T8 status lifecycle · T9 credit=- / debit=+ sign convention · T10 row-level byte-parity vs persisted note fields · T11 fail-loud reconciliation · T12 KPI derivation match · T13 tax_summary sum parity · T14 by_reason 9B remap · T15 4-sheet XLSX · T16 XLSX row counts == JSON kind split · T17 A4 landscape + Page X of Y · T18 disclosure banner + ₹ glyph · **T19 10 000-note streaming with cleanup (35.7s)** · T20 <=273mm column-width envelope guardrail · T21 effective-balance parity with `services._effective_invoice_totals`.
  - Regression: C3.5 §9A + C3.2 §9B suites: **51/51 pass** — zero cross-contamination.
  - Live preview UAT: `/reports/cndn-register` rendered with 299 notes · Reconciled YES · CN 260 (₹15,926.00) · DN 39 (₹7,045.00) · Net Δ ₹-8,881.00 · By-Reason table showing rate_correction/§9B 04, sales_return/§9B 01, other/§9B 07, etc.
- **Statutory disclosure (documented in PDF banner + XLSX Summary + every-page PDF footer)**:
  - This is a WORKING REPORT (CN/DN Register). NOT a GST portal upload file.
  - Statutory feed is GSTR-1 §9B (`/reports/gstr1-9b*`, LOCKED C3.1/C3.2). §9A invoice-side is `/reports/gstr1*` (LOCKED C3.5). §9C amendments remain future C5.
- **Isolation**: every C4 test seeds a fresh unique customer + invoice per test, deletes in `finally`; T19 uses tagged prefix `cdn_c4t_<8hex>_XXXXX` for clean bulk deletion. No shared demo-tenant or C3.5 seed state.
- **Zero touches** to: `credit_debit_notes` collection or `services._compute_note_totals` / `_effective_invoice_totals` / `_apply_effective_balance` (all LOCKED · Iter132a); `routers/notes.py`; `routers/gst.py`; C3.1/C3.2 §9B code; C3.5 §9A code; every previously LOCKED Iter path.
- **Files shipped**:
  - `backend/routers/reports.py` (+380 lines · `_cndn_register_payload` helper + 3 endpoints)
  - `backend/xlsx/cndn_register.py` (NEW · ~290 lines · 4-sheet workbook)
  - `backend/pdf/cndn_register.py` (NEW · ~330 lines · A4 landscape L2d v3)
  - `backend/tests/test_iter132c_c4_cndn_register.py` (NEW · 21 tests, T1–T21)
  - `frontend/src/pages/CndnRegister.jsx` (NEW · Filter bar · KPI cards · Tax Summary · By-Reason · Register table · 4-button action row)
  - `frontend/src/pages/Reports.jsx` (+3 lines · tab entry + nested route wiring)
  - `frontend/src/hooks/useCdnEnabled.js` (+15 lines · additive `useCdnEnabledState()` export)
- **Rollback boundary**: revert the 3 endpoints in `reports.py`; delete `xlsx/cndn_register.py`, `pdf/cndn_register.py`, `tests/test_iter132c_c4_cndn_register.py`, `frontend/src/pages/CndnRegister.jsx`; revert the 3 wiring edits in `Reports.jsx` and the additive `useCdnEnabledState` in `useCdnEnabled.js`. No DB migration; no schema change; no new runtime dependency.
- **Deferred (still frozen, awaiting explicit GO)**: DG-STABILITY-1 · C3.4 Portal offline-utility JSON · C5 §9C emission · Statement Email Delivery · Iter132c-ai-agg-fix · Phase-2 Security Hardening · LR Register Email Digest · Trip Templates · new modules (Tyre / Driver Salary / Expense / Maintenance) · every other backlog item.


## Iter132c · C3.5 · GSTR-1 §9A Export Parity (Invoice-side · CSV + JSON + XLSX + PDF) — 🔒 LOCKED (2026-09-02 · UAT approved)
- **Scope shipped in C3.5**: brings the existing invoice-side GSTR-1 report (Iter127a) to full export parity with §9B. Three additive endpoints — `GET /api/reports/gstr1.json`, `GET /api/reports/gstr1.xlsx`, `GET /api/reports/gstr1.pdf` — all PURE PROJECTIONS of a single canonical `_gstr1_payload()` helper extracted from the existing `report_gstr1` route (byte-identical for the 9 pre-existing keys). Existing frontend CSV workflow preserved. Reports UI (`GSTR1Report()`) now offers four clearly labelled buttons: **Download CSV · Download JSON · Download XLSX · Download PDF**.
- **High-volume correctness fix (mandatory under C3.5)**: removed the pre-existing `to_list(5000)` on invoices and `to_list(2000)` on customers inside the payload builder. Now streams via `db.invoices.find(...)` cursor with Mongo-side `invoice_date` range filter, and preloads only referenced customer_ids via `$in`. Proven at 10 000 invoices / 2 500 customers (test T19).
- **Fail-loud reconciliation**: additive `reconciliation` field compares endpoint totals to a Mongo `$group` ground truth over the identical filter; `reconciled=False` produces a `warnings[]` entry rather than silent drift. Verified live: 6371-invoice August month → endpoint = ground_truth = ₹32.78 Cr, reconciled=True.
- **Presentation polish (LOCKED as of UAT 2026-09-02)**:
  - PDF Summary: `₹`-prefixed values rendered via DejaVu (`_UNI_FONT` on every summary cell) — zero missing-glyph tofu.
  - Table headers: monetary columns end with `(₹)` suffix (e.g. `Taxable (₹)`); data cells carry plain numbers.
  - Invoice # column widened 28 → 34 mm so `AKB/26-27//26-27/0004` (21 chars) is a single visual token (mirrors LOCKED §9B Note # 28 mm fix pattern).
  - Date column widened 16 → 18 mm so ISO `YYYY-MM-DD` remains single-line at 7pt DejaVu.
  - B2B column widths `[34,18,32,28,22,12,8,22,18,18,18,22,21]` (sum 273 mm — within landscape envelope). B2C sum 268 mm. By_State sum 254 mm.
  - XLSX currency format `"₹ "#,##0.00` (prefix, not suffix) on every currency cell.
  - Two-pass fresh-flowable render (L2d v3 pattern) — `_make_story()` closure guarantees no `LayoutError` on dense months. Page X of Y footer on every page.
- **Statutory boundary (documented in code + PDF + XLSX Summary sheet + every-page PDF footer)**:
  - POS = `customer.state` (IGST §12(9) registered-recipient rule). Ship-To is operational/logistics only and never overrides POS. Bill-To (customer) is the authoritative reporting identity/state source.
  - **NOT emitted here (out of scope for C3.5, must not be inferred)**: B2CL split · HSN Summary (Table 12) · Docs Summary (Table 13) · Amendments (9A / 9B / 9C). §9B is separate (C3.1/C3.2 LOCKED); §9C is future C5.
  - PDF/XLSX are HUMAN-READABLE WORKING REPORTS, not GST portal upload files. Disclosure banner on PDF page 1 and every-page footer.
- **Verification evidence (authoritative, measured)**:
  - C3.5 targeted `test_iter132c_c3_5_gstr1_export.py`: **33 / 33 passed in 197.13 s** (final run after all diagnostic activity). Covers: existing-shape preservation · additive fields · JSON/XLSX/PDF endpoint contracts · content-type/content-disposition · 4-sheet workbook · Summary-totals parity · PDF totals via pdfplumber · empty-period edge case · bad-month 400 · reconciliation ground-truth equality · **Bill-To POS enforcement (T17 seeds Karnataka customer with Maharashtra ship-to; asserts POS follows customer)** · static guardrail that `to_list(5000)/(2000)` cannot re-enter the payload builder · **10 000-invoice / 2 500-customer streaming test (T19) with cleanup** · A4-landscape column-width envelope guardrail · CSV-consumer row-shape preservation · audit-log emission per download · Python-3.11 f-string safety · `(₹)` header suffix on every monetary column · Invoice # ≥ 34 mm · PDF ₹ glyph without tofu · Disclosure banner preservation · Long-invoice-number single-line rendering.
  - §9B regression (C3.1 + C3.2): **37 / 37 passed** — zero cross-contamination.
  - Live endpoint smoke on preview backend (final run): `gstr1=200 gstr1.json=200 gstr1.xlsx=200 gstr1.pdf=200 gstr1-9b=200 gstr1-9b.xlsx=200 gstr1-9b.pdf=200` — all 7 GSTR-1 endpoints healthy.
  - Manual UAT (browser + downloaded artefacts, month 2026-08): 4 labelled buttons rendered · Reconciled banner "● RECONCILED YES ✓ · 6010 invoices · total ₹ 26,17,31,323.00" · KPIs render · By-State POS table · B2B (2104) + B2C (3906) rendered · PDF 198 pages, A4 landscape 841.89 × 595.28 pt, `Page 1 of 198` and `Page 198 of 198` present, banner + footer disclosure verified · XLSX 4 sheets (Summary / B2B / B2C / By_State) with numeric ₹-formatted currency cells · long invoice numbers `INV/26-27/xxxx` and `AKB/26-27//26-27/0004` single-line · existing CSV workflow preserved and unchanged.
- **Zero touches** to: §9B code (C3.1/C3.2 pdf/xlsx/routers/services — all LOCKED), `routers/notes.py`, `routers/invoices.py`, `routers/customers.py`, `services._recompute_invoice`, `ship_to_resolver.py`, `pdf/invoice.py` (L2d v3 LOCKED), `pdf/ledger.py`, invoice numbering, tax calculation, RBAC, feature flags, and every previously LOCKED Iter126–132c and Iter133 path.
- **Rollback boundary**: revertable by (a) deleting `backend/xlsx/gstr1.py`, `backend/pdf/gstr1.py`, `backend/tests/test_iter132c_c3_5_gstr1_export.py`; (b) restoring `backend/routers/gst.py` pre-C3.5 form (inline `report_gstr1` body — remove `_gstr1_payload` helper and the three new `.json/.xlsx/.pdf` endpoints); (c) reverting the `GSTR1Report()` component in `frontend/src/pages/Reports.jsx` to its single-CSV-icon form. No DB migration; no schema change; no new runtime dependency (openpyxl, reportlab, PyMuPDF, httpx all pre-pinned).
- **Files shipped**: `backend/pdf/gstr1.py` (NEW · 393 lines), `backend/xlsx/gstr1.py` (NEW · 270 lines), `backend/routers/gst.py` (+278 / −26 · `_gstr1_payload` extraction + 3 new endpoints), `backend/tests/test_iter132c_c3_5_gstr1_export.py` (NEW · 762 lines, 33 tests), `frontend/src/pages/Reports.jsx` (+79 / −26 · `GSTR1Report()` cluster only).
- **DG exception (recorded per lock policy)**: *"Official curated Deploy Guard did not complete cleanly because of a proven pre-existing Iter51 shared-state/race failure unrelated to C3.5. C3.5 independently passed its full targeted suite (33/33) and live endpoint/UAT verification. Diagnostic evidence: hang root-caused to `test_iter51_deploy_guard_and_alerts.py::test_alert_fires_when_threshold_crossed` (fails deterministically in serial isolation, 5.42 s; reproduces `AssertionError` with `--timeout=60`; predates C3.5). Cascade `[gw0] node down: Not properly terminated` spuriously fails 6 unrelated `test_iter42_unloading_diff_fix` tests (all 7/7 pass in isolation). Additional 5 pre-existing deterministic failures exist in `test_iter67_extras` (3, `KeyError: 'id'` seed helper) and `test_iter26_phase1_ai_templates` (2) — none in C3.5 scope, none in Deploy Guard curated 67-file list. Zero C3.5 files appear in `pytest_cache/lastfailed`; `grep -c c3_5 run_regression.sh = 0`. Diagnostic-only dependency `pytest-timeout==2.4.0` installed to expose the crash cleanly. Tracked as separate P1 backlog item **DG-STABILITY-1**."*
- **Deferred (still frozen, awaiting explicit GO)**: DG-STABILITY-1 (below) · C3.4 Portal offline-utility JSON · C4 CN/DN Register · C5 §9C emission · Statement Email Delivery · Iter132c-ai-agg-fix · Phase-2 Security Hardening · LR Register Email Digest · Trip Templates · new modules (Tyre / Driver Salary / Expense / Maintenance) · every other backlog item.

## DG-STABILITY-1 · Deploy-Guard stability backlog (P1 · NOT started · created 2026-09-02)
Established via C3.5 diagnostic-only investigation. Curated 67-file / 504-test Deploy Guard (`backend/scripts/run_regression.sh`) has been demonstrably flaky since Aug-31; the Aug-31 GREEN was a timing-lucky pass of tests that fail deterministically today. **No fix implemented as part of C3.5.** Three separable sub-tasks:
- **DG-1a · Fix `test_iter51_deploy_guard_and_alerts.py` shared-state race** — `test_alert_fires_when_threshold_crossed` + `test_alert_cooldown_prevents_spam` share the process-global alert-config singleton and `save_health_alerts` collection with sibling xdist workers. Filter `fired_at > cutoff` silently drops alerts when the preview-backend clock leads the test host. Recommended: emit worker-unique alert kinds (e.g. `save_failure_gw{PYTEST_XDIST_WORKER}`) OR pin the file to a single worker via `pytest.mark.xdist_group`.
- **DG-1b · Permanent pytest timeout protection** — add `--timeout=60 --timeout-method=thread` to `pytest.ini addopts` (or `run_regression.sh`) so worker hangs become named test failures instead of cascading `[gw0] node down` crashes that spuriously fail up-to-6 unrelated iter42 tests per crash.
- **DG-1c · Fix 5 pre-existing deterministic failures unrelated to DG scope** — `test_iter67_extras.py::test_preserved_calculations_intra_state`, `::test_preserved_calculations_inter_state_igst`, `::test_multi_company_isolation_ship_sites_and_ref` (all `KeyError: 'id'` on customer POST response — seed helper needs update to the current `/api/customers` response shape). `test_iter26_phase1_ai_templates.py::TestDuplicateTrip::test_create_and_duplicate`, `::TestMultiCompanyScoping::test_company_isolation_in_ai_tool` (assertion drift). None impact C3.5. None impact the DG scope (all outside `run_regression.sh` curated list).
Owner: TBD. Estimated effort: DG-1a ~1 h, DG-1b ~15 min, DG-1c ~2 h. Blocks: only future lock-gate governance decisions; does NOT block any currently pending product work.

## Iter132c · C3.2 · GSTR-1 §9B XLSX + PDF Export — 🔒 LOCKED (2026-09-01 · UAT approved · Full Deploy Guard GREEN · pytest 503 pass / 1 skip / 0 fail)
- **Scope shipped in C3.2**: two additive projection endpoints — `GET /api/reports/gstr1-9b.xlsx?month=YYYY-MM` (accountant-friendly 6-sheet workbook) and `GET /api/reports/gstr1-9b.pdf?month=YYYY-MM` (A4-landscape human-readable statutory working report). Both are PURE PROJECTIONS of the C3.1 canonical JSON.
- **Architecture (LOCKED · ONE SOURCE OF TRUTH)**:
  ```
                    credit_debit_notes  (authoritative, LOCKED)
                            │
                    _compute_note_totals (Iter132a, LOCKED — calculated once at issue)
                            │
              ┌────────────▼─────────────┐
              │  _gstr1_9b_payload(...)  │  ← shared internal helper
              │     (C3.2.1 · LOCKED)    │     (C3.1 canonical payload builder)
              └────────────┬─────────────┘
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
        JSON endpoint  XLSX endpoint  PDF endpoint
        (C3.1)         (C3.2)         (C3.2)
                                 │
                                 └── audit_logs.gstr_export/download {format,period,row_count,gst_true_total,gst_false_total}
  ```
  Each of the three public endpoints delegates to `_gstr1_9b_payload` and emits its own `gstr_export/download` audit row with the served `format`. **Neither XLSX nor PDF ever recomputes tax, totals, POS, routing, reconciliation, or statutory classification.**
- **Zero duplicate statutory calculation**: XLSX and PDF read `payload["cdnr"|"cdnur"|"b2cs_adjustments"|"commercial_notes"|"cancelled_after_export"|"totals"|"reconciliation"|"warnings"]` and render — no recomputation, no re-classification, no second dataset. Zero re-entry for the accountant.
- **XLSX contract (LOCKED)**:
  - Six sheets: `Summary` · `CDNR` · `CDNUR` · `B2CS_Adjustments` · `Commercial_Notes` · `Cancelled_After_Export`.
  - Frozen header row on every data sheet (row 4 header; row 5+ data).
  - CN rows tinted red-50 (`FEF2F2`), DN rows tinted blue-50 (`EFF6FF`) — parity with Ledger PDF (L2 LOCKED).
  - Currency format `#,##0.00 ₹`; date format `dd-mm-yyyy` (matches CDNR JSON V3.2 portal shape).
  - Deterministic row order (already sorted by `note_date` in the C3.1 cursor).
  - Reconciliation status cell tinted green when `reconciled=true`, red otherwise (Summary sheet).
  - Locked column-header lists as module constants: `CDNR_HEADERS · CDNUR_HEADERS · B2CS_HEADERS · COMMERCIAL_HEADERS · CANCELLED_HEADERS` (referenced by T5 static-header assertion).
  - No row cap; no `to_list(N)` truncation.
  - Content-Type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`; Content-Disposition `attachment; filename="GSTR1_9B_<company_code>_<YYYY-MM>.xlsx"`.
- **PDF contract (LOCKED)**:
  - **A4 landscape** (297 × 210 mm) · 12 mm L/R margins · 273 mm content-width envelope.
  - Two-pass build with **L2d v3 fresh-flowable `_make_story()` closure** — proven pattern from Invoice PDF regression suite; fresh Flowables per pass eliminates ReportLab state pollution at high row density.
  - `NumberedCanvas` footer: `GSTR-1 §9B · CN/DN Register · Computer-generated · Page X of Y · Printed YYYY-MM-DD UTC`.
  - Sections in order: Header band (logo + company + GSTIN + state) → Accent divider → Period + row count + Reconciled ✓/✗ badge → 5-row Summary table → CDNR → CDNUR → B2CS Adjustments (banner: `net-of Table 7`) → Commercial Notes (banner: `§34/§15(3)(b) excluded from §9B`) → Cancelled After Export (banner: `§9C amendment due`) → Warnings.
  - Every data table uses `repeatRows=1` (header repeats on page break).
  - Empty sections render `No <section> records for this period.` placeholder — never crash on empty `platypus.Table`.
  - CN rows tint red-50, DN rows tint blue-50 — parity with Ledger PDF.
  - `Paragraph` cells for long text (Recipient, Reason) — wrap gracefully.
- **16-character Note # readability fix (LOCKED)**: PDF column widths tuned so the full 16-character statutory `nt_num` renders as a single visual token (was wrapping under the initial 20 mm Note # column at 7 pt Helvetica → 21.7 mm required content width vs 18 mm available → wrap). Fix widens Note # to **28 mm across all five landscape tables**; space reclaimed from the widest text column (Reason/Info/Advisory) in each table. Column-width sums post-fix (all ≤ 273 mm envelope):
  - `CDNR` = 268 mm · `CDNUR` = 270 mm · `B2CS` = 270 mm · `COMMERCIAL` = 270 mm · `CANCELLED` = 272 mm
  - Enforced by T15 static-width regression (`_all_col_widths_mm()` helper + `_CONTENT_W_MM = 273.0` module constant).
  - Verified visually via `fitz.search_for("T14-<uuid>-00001")` — 1 match post-fix (0 matches pre-fix).
- **Parity guarantees (fail-loud)**:
  - **XLSX ↔ JSON parity** (T6): every CDNR row's `ctin · nt_dt · ntty · val · pos · inum · txval · camt · samt · iamt · rsn · reason_code_qorvena` compared cell-by-cell against the JSON payload. Lookup key = `(customer_name, nt_num)` (tenant-unique) because `nt_num` alone is per-customer-monotonic under the LOCKED Iter132a numbering — NOT globally unique.
  - **PDF ↔ JSON semantic parity** (T14 dense-period 30 CN/DN mix; T17 high-volume 2,100 notes) — every seeded note number retrievable via `fitz.search_for(...)` at every scale.
  - Summary reconciliation cell (T7) matches JSON `reconciliation.reconciled` and `endpoint_gst_true_total`.
  - Payload-shape completeness (T19 under C3.1) — every top-level key present including on empty periods.
- **High-volume streaming behaviour (LOCKED)**:
  - No `to_list(N)` anywhere in the payload builder or the exporters (openpyxl writes row-by-row, reportlab consumes flowables lazily).
  - **XLSX 2,100 notes** (T9) — direct-Mongo seed → HTTP 200 → openpyxl reader confirms all 2,100 rows present in CDNR sheet → cleanup verified 0 orphans.
  - **PDF 2,100 notes** (T17) — direct-Mongo seed → HTTP 200 → valid `%PDF-` header + `%%EOF` → page count ≥ 10 → sampled note numbers (first, middle, last) all found via `fitz.search_for` → cleanup verified 0 orphans.
  - No LayoutError; no HTTP 500 by volume; no clipped rows; no lost final rows.
- **PDF multi-page behaviour (LOCKED)**:
  - CONTENT GROWS → PAGES GROW → PDF STILL SUCCEEDS.
  - `NumberedCanvas` two-pass ensures `Page X of Y` is accurate.
  - `repeatRows=1` on every table means the header re-prints on every new page.
  - Empty period → 1 page with placeholder text (never empty-table crash).
  - Dense 30-note period → 2 pages (verified by T14 `fitz.page_count`).
  - 2,100-note period → ≥ 10 pages (verified by T17).
- **Audit logging (LOCKED)**:
  - Every download emits ONE `audit_logs {module:"gstr_export", action:"download", entity_ref:"GSTR1_9B_<code>_<month>.<ext>", changes:{format,period,row_count,gst_true_total,gst_false_total}}` row.
  - JSON endpoint logs `format:"json"` (entity_ref `gstr1_9b_<month>`); XLSX logs `format:"xlsx"`; PDF logs `format:"pdf"` (both with full filename ref).
  - Verified by T18 for both XLSX and PDF (before/after counts increment).
- **Verification evidence (authoritative, measured)**:
  - C3.2 targeted `test_iter132c_c3_2_gstr1_9b_export.py`: **18/18 passed · 0 failed · 0 skipped · exit 0 · 12.57 s** (post-guard confirmation run, three consecutive greens).
  - C3.1 regression `test_iter132c_c3_gstr1_9b.py`: **19/19 passed** (post-guard confirmation).
  - Full Deploy Guard (auto-triggered at 2026-09-01T08:48 UTC after the manual `POST /run-now` returned `already_running` due to hourly cadence overlap): `checked_at=2026-09-01T09:01:30.633739+00:00 · status=pass · elapsed_s=788.8 · exit_code=0 · consecutive_failures=0 · strict_mode=true · next_check_at=2026-09-01T10:01:30.633745+00:00 · pytest_summary="503 passed, 1 skipped, 8 warnings in 788.38s (0:13:08)"`. Iter128 Deploy Readiness Badge **🟢 GREEN**.
  - Deploy-history context — 6 consecutive green runs on 2026-09-01 (`05:21 manual, 06:02, 07:15, 07:31, 08:44, 09:01`).
  - Live JSON/XLSX/PDF smoke on preview tenant (`2026-09`, 100 notes): JSON `HTTP 200 · reconciled=true · all 5 buckets present`; XLSX `HTTP 200 · 20,472 bytes · openxmlformats MIME`; PDF `HTTP 200 · 64,543 bytes · %PDF- + %%EOF valid`.
- **Files changed (additive-only)**:
  - `backend/routers/gst.py` — extracted `_gstr1_9b_payload(month, request, user) -> dict` (side-effect-free canonical builder); added 3 endpoint wrappers `report_gstr1_9b` / `report_gstr1_9b_xlsx` / `report_gstr1_9b_pdf` (each 25–35 LOC · each emits its own `gstr_export/download` audit row).
  - `backend/xlsx/__init__.py` — new · empty package marker.
  - `backend/xlsx/gstr1_9b.py` — new · `build_gstr1_9b_xlsx(company, payload) -> bytes` + 5 sheet builders + locked header-list constants (`CDNR_HEADERS · CDNUR_HEADERS · B2CS_HEADERS · COMMERCIAL_HEADERS · CANCELLED_HEADERS`) + shared style helpers.
  - `backend/pdf/gstr1_9b.py` — new · `build_gstr1_9b_pdf(company, payload) -> bytes` + `NumberedCanvas` + `_make_story()` closure + 5 section builders + locked column-width constants (`CDNR_COL_WIDTHS_MM · CDNUR_COL_WIDTHS_MM · B2CS_COL_WIDTHS_MM · COMMERCIAL_COL_WIDTHS_MM · CANCELLED_COL_WIDTHS_MM`) + `_all_col_widths_mm()` regression helper.
  - `backend/tests/test_iter132c_c3_2_gstr1_9b_export.py` — new · 18 hermetic tests · re-runnable via uuid-derived `_fake_gstin` helper against LOCKED Iter127a duplicate-master guard.
- **Zero touches** to: `models.py`, `routers/notes.py`, `routers/invoices.py`, `routers/customers.py`, `routers/reports.py`, existing `pdf/*.py` (invoice / ledger / credit_note / debit_note / lr / owner), `services.py` (only additive `_GSTR1_9B_REASON_MAP` from C3.1), `auth.py`, `server.py`, `.env`, invoice numbering, invoice/note schemas, `_compute_note_totals`, `_effective_invoice_totals`, `_apply_effective_balance`, RBAC, feature flags, and every LOCKED Iter132a/b/c and Iter133 L1/L1.5/L2/L2b/L2c/L2d/L2e path. C3.1 lock remains intact.
- **Restarts used**: **1 authorised backend restart** (after PDF column-width tune). Zero unauthorised restarts.
- **STOP RULE compliance**: two failure cycles surfaced during C3.2 development (Python-3.11 f-string SyntaxError from `\uXXXX` escapes; T6 nt_num-collision + T14/T17 PDF column overflow) — each escalated with full RCA + product-vs-test classification; fixes applied strictly after explicit user GO. Zero autonomous product-code changes across the entire slice.
- **Known limitations (documented, not blocking C3.2 lock)**:
  - **Portal offline-utility JSON** (`b2b`/`cdnr`/`cdnur` GSTN offline-utility upload structure) — deliberately out of C3.2 scope, deferred to future **C3.4**. C3.2 ships human-readable PDF + accountant-friendly XLSX only.
  - **§9C amendment emission (CDNRA / CDNURA)** — deferred to future **C5**. C3.2 surfaces cancelled-after-export notes with `_advisory` text in every downstream (JSON / XLSX / PDF) but does not emit §9C rows.
  - **Recipient identity snapshot** — CN/DN carry `invoice_number_snapshot` but not a customer-GSTIN/state snapshot at issue time. XLSX and PDF reflect the *current* customer record for `ctin`/`pos` (parity with LOCKED `/reports/gstr1` invoice-side and LOCKED `/reports/gstr1-9b` JSON). Documented pre-existing latent gap; NOT a C3.2 regression.
  - **PDF template drift** — column-width constants match GSTR-1 Offline Utility **V3.2 (Aug 2026)** shape. Annual GSTN template refresh may require a width-constant refresh in a future micro-slice.
- **Rollback boundary**: revertable by (a) deleting `backend/xlsx/__init__.py`, `backend/xlsx/gstr1_9b.py`, `backend/pdf/gstr1_9b.py`, `backend/tests/test_iter132c_c3_2_gstr1_9b_export.py`; (b) restoring the pre-C3.2 `backend/routers/gst.py` (single `report_gstr1_9b` endpoint with inline body and inline audit — remove the two new XLSX/PDF endpoints and the `_gstr1_9b_payload` extraction wrapper, inlining the payload body back into `report_gstr1_9b`). No DB migration performed; no persisted-schema change; no new dependency added (`openpyxl` and `reportlab` were both already pinned; `fitz`/PyMuPDF was already used by L2e). A rollback restores the codebase byte-for-byte to the C3.1-only baseline at Deploy Guard `checked_at=2026-09-01T05:21:36Z`.
- **Deferred (still frozen, awaiting explicit GO)**: C3.3 Frontend Reports UI · C3.4 Portal offline-utility JSON · C4 CN/DN Register · C5 §9C emission · Statement Email Delivery · Iter132c-ai-agg-fix (`to_list(2000/5000)` truncation) · Phase-2 Security Hardening · LR Register Email Digest · Trip Templates · new modules (Tyre / Driver Salary / Expense / Maintenance) · every other backlog item.

## Iter132c · C3.1 · GSTR-1 §9B Canonical Statutory JSON Feed — 🔒 LOCKED (2026-09-01 · Full Deploy Guard GREEN · pytest 503 pass / 1 skip / 0 fail)
- **Scope shipped in C3.1**: canonical statutory JSON feed for GSTR-1 §9B (CDNR / CDNUR / B2CS-net-of / Financial-commercial / cancelled-after-export). *Zero re-entry, zero recomputation.* The feed reads the same authoritative issued CN/DN records already used by Ledger, Statement and Passbook (`ENTER ONCE → CALCULATE ONCE → REFLECT EVERYWHERE`).
- **Endpoint**: `GET /api/reports/gstr1-9b?month=YYYY-MM` · `ENABLE_CDN=1` feature-gate · RBAC parity with `/reports/gstr1`.
- **Statutory routing (locked per authoritative GSTN validation — GSTN Contextual Help + Offline Utility V3.2, CGST §34 / §15(3) / Rule 53(1A), delinking 14-Sep-2020)**:
  - `apply_gst=True` + valid recipient GSTIN → `cdnr[]` (grouped by `ctin`, `inv_typ="R"`).
  - `apply_gst=True` + no GSTIN + inter-state (`gst_type=igst`) + invoice > ₹2.5 L → `cdnur[]` (`typ="B2CL"`).
  - `apply_gst=True` + neither of the above → `b2cs_adjustments[]` with `_warnings=["report_net_of_in_table_7"]` (statutorily net-of in Table 7, surfaced here for audit visibility, NOT part of §9B).
  - `apply_gst=False` → `commercial_notes[]` (statutorily EXCLUDED from §9B per §34 / §15(3)(b) — financial/commercial notes are NOT reported in GSTR-1).
  - Cancelled with `cancelled_at > period_end` → `cancelled_after_export[]` with `_advisory` for §9C amendment (§9C emission itself deferred to future C5).
  - Draft, and cancelled-in-period, and cancelled-never-issued → silent drop.
- **RCM handling**: `rchrg="Y"`, tax fields **populated** from the persisted note (not zeroed), `val = note.total_amount` (RCM tax excluded per `_compute_note_totals` line 91).
- **Filing period**: driven by `note.note_date` (issue date), not by original invoice date. Boundary: last-day-in / first-day-next-out.
- **Reason-code map (deterministic, locked)**: `sales_return→01, post_invoice_discount→02, short_delivery→03, quality_claim→03, rate_correction/under_charge/missed_halting/freight_escalation→04, other→07`. Unknown → `07` + `reason_remapped_to_others` warning. `rsn` is portal-optional in CDNR JSON V3.2 (used only in the offline-utility XLSX column).
- **Fail-loud reconciliation invariant (locked)**: endpoint totals reconciled against a Mongo `$group` ground truth on every call: `Σ cdnr.val + Σ cdnur.val + Σ b2cs.val == Σ issued(apply_gst=True).total_amount` and `Σ commercial.total_amount == Σ issued(apply_gst=False).total_amount` and `row_count == count(issued in period)`. Any delta → HTTP 500 with offending IDs. Never silently disappears.
- **Streaming**: `async for` cursor over `credit_debit_notes` (no `to_list(N)` truncation) — verified against 2,100-note seeded volume with 0 truncation and 0 orphans post-cleanup.
- **Auditability**: every call emits `audit_logs {module:"gstr_export", action:"download", entity_ref:f"gstr1_9b_{month}", changes:{format,period,row_count,gst_true_total,gst_false_total,cancelled_after_export_count}}`.
- **Zero touches** to: `models.py`, `routers/notes.py`, `routers/invoices.py`, `routers/customers.py`, `routers/reports.py`, `pdf/*.py`, `auth.py`, `server.py`, `.env`, invoice numbering/schema, `_compute_note_totals`, `_effective_invoice_totals`, `_apply_effective_balance`, RBAC/perms, feature flags, and every locked Iter132a/b/c and Iter133 L1/L1.5/L2/L2b/L2c/L2d/L2e path.
- **Verification evidence (authoritative, measured)**:
  - Targeted `test_iter132c_c3_gstr1_9b.py` — Run #1 **19/19 pass · 7.16 s · exit 0** · Run #2 immediate re-run **19/19 pass · 7.26 s · exit 0** (proves idempotency after fixture uniqueness fix) · Run #3 post-guard **19/19 pass · 7.43 s · exit 0**.
  - Full Deploy Guard (manual trigger for C3.1 lock): `checked_at=2026-09-01T05:21:36.501471+00:00 · status=pass · elapsed_s=773.9 · exit_code=0 · consecutive_failures=0 · strict_mode=true · next_check_at=2026-09-01T06:21:36.501478+00:00 · triggered_by=manual · pytest_summary="503 passed, 1 skipped, 8 warnings in 773.48s (0:12:53)"`. Iter128 Deploy Readiness Badge 🟢 GREEN.
  - Live JSON smoke on preview tenant (2026-09): `HTTP 200 · note_count=40 · reconciled=true`; all 5 buckets present; bad-month `2026-13 → HTTP 400`.
- **Files changed (additive-only)**:
  - `backend/routers/gst.py` — +265 LOC (new endpoint `report_gstr1_9b` + `_dd_mm_yyyy` + `_gstr1_reason_for` helpers + 1 import line).
  - `backend/services.py` — +30 LOC (`_GSTR1_9B_REASON_MAP` deterministic dict; placed after all existing helpers at end of file).
  - `backend/tests/test_iter132c_c3_gstr1_9b.py` — NEW · 19 hermetic tests · `_fake_gstin(state_prefix)` helper for re-runnability against the LOCKED Iter127a duplicate-master guard.
- **Restarts used**: 1 authorised backend restart (after endpoint code landed). Zero unauthorised restarts.
- **STOP RULE compliance**: three test-side failure cycles surfaced (Telangana↔AP state mismatch → GSTIN idempotency 409 → day-1-of-month date boundary). Each escalated with RCA + product-vs-test classification; fixes applied strictly after explicit user GO. Zero autonomous product-code changes across the entire slice.
- **Known limitations (documented, not blocking C3.1 lock)**:
  - **§9C amendments** — cancelled-after-export notes surface in an advisory bucket with `_advisory` text; actual §9C (CDNRA/CDNURA) emission itself is deferred to a possible future **C5** slice.
  - **Recipient identity snapshot** — CN/DN carry `invoice_number_snapshot` but not a customer-GSTIN/state snapshot at issue time; the endpoint uses the *current* customer record for `ctin`/`pos` (parity with the LOCKED `/reports/gstr1` invoice-side behaviour). Documented pre-existing latent gap; NOT a C3.1 regression.
  - **Portal template drift** — the deterministic reason-code map and the CDNR/CDNUR schema shape match GSTR-1 Offline Utility **V3.2 (Aug 2026)**. Annual GSTN template refresh may require a 1-line reason-map update or `itms` header list update in a future micro-slice.
  - **CDNR `nt_num`** ceiling on the portal is 16 chars; QORVENA notes are 13 chars → safe up to 99,999/yr; no action needed.
- **Rollback boundary**: revertable by deleting `_GSTR1_9B_REASON_MAP` from `services.py`, removing the C3.1 block in `gst.py` (routes `report_gstr1_9b` + the two module-level helpers `_dd_mm_yyyy`, `_gstr1_reason_for`), and deleting `backend/tests/test_iter132c_c3_gstr1_9b.py`. No DB migration performed; no persisted-schema change; no dependency added (`openpyxl` was already in `requirements.txt` for LR Register XLSX). A rollback restores the codebase byte-for-byte to the pre-C3.1 Deploy Guard baseline at `checked_at=2026-08-31T14:17:04Z`.
- **Deferred (still frozen, awaiting explicit GO)**: C3.2 GSTR-1 §9B XLSX + PDF exports · C3.3 Frontend Reports UI tile · C4 CN/DN Register · C5 §9C emission · Statement Email Delivery · Iter132c-ai-agg-fix · Phase-2 Security Hardening · every other backlog item.


- **Iter133 · L2e · Statement Effective-Balance Parity** — 🔒 LOCKED · UAT approved 2026-08-31
- **Iter133 · L1.5 · Passbook CN/DN Row Detail** — 🔒 **LOCKED · UAT approved 2026-08-30**
  - Extends `GET /api/customers/{cid}/transactions` to surface issued Credit / Debit notes as individual rows in the unified `transactions[]` list. Scope strictly `{user_id, company_id, customer_id, status:"issued"}`; draft + cancelled notes excluded. `date_from` / `date_to` filters apply on `note_date`. New `txn_type` values accepted: `credit_note`, `debit_note`.
  - Row shape: `{type: "credit_note"|"debit_note", date: note_date, id, ref: note_number, amount: total_amount (positive), invoice_id, invoice_number (snapshot), reason_code, reason_text, status: "issued", kind}`. Amount always stored positive; UI adds the ± prefix per kind.
  - **Existing summary aggregates unchanged**: `summary.credits_total` / `summary.debits_total` continue to be sourced from the invoice-effective enrichment (Iter132c C1 R1); this slice is additive-only and does not double-count into the summary.
  - Frontend (`CustomerHistory.jsx`): `TxnRow` now renders CN as red `− ₹X · Credit Note` and DN as blue `+ ₹X · Debit Note` with reference-invoice + reason line beneath, row tint per kind. `TypeIcon` (FileMinus/FilePlus), `StatusChip` (`Issued · CN` / `Issued · DN`) extended. `groupByMonth` accumulator: CN subtracts, DN adds to monthly total. `openTxn` routes CN/DN clicks to the linked invoice detail.
  - **Zero touches** to Iter132a/b, Iter132c C1, Iter133 L1, Iter133 L2/L2b/L2c, invoice numbering, `pdf/*.py`, `services.py`, Auth/RBAC, Save Health, Ledger PDF, Statement PDF.
  - **Verification evidence (authoritative)**:
    - **Targeted re-run** — 31/31 passed, 0 failed, 0 skipped:
      | Test file | Collected | Passed |
      |---|---:|---:|
      | `test_iter133_l1_5_passbook_cdn_rows.py` (L1.5) | 6 | 6 |
      | `test_iter133_l1_ledger_cdn_rows.py` (L1) | 7 | 7 |
      | `test_iter133_l2_ledger_statement_presentation.py` (L2 + L2b + L2c — single file) | 18 | 18 |
      | **Grand total** | **31** | **31** |
    - **Full Deploy Guard (manual trigger)** — `checked_at=2026-08-30T16:01:28.867891+00:00 · status=pass · elapsed_s=749.0 · exit_code=0 · consecutive_failures=0 · strict_mode=true · next_check_at=2026-08-30T17:01:28.867899+00:00 · pytest_summary="503 passed, 1 skipped, 0 failed, 8 warnings in 748.49s"`. The 1 skip is the documented Iter51 cooldown-race self-skip, not a failure. Three consecutive pass runs post-L1.5 land: 15:09, 15:48, 16:01.
    - **No autonomous fixes** applied at any stage.
    - **No locked-area changes**: Iter132a/b · Iter132c C1/H1/C2/C2b/C2c · Iter133 L1 · Iter133 L2/L2b/L2c · CN/DN business logic · numbering · effective-balance logic · Invoice logic · Auth/RBAC · PDFs · services · Save Health — all untouched.
  - **Reporting correction**: An earlier verification note stated the targeted total as *"6 + 25 + 25 = 31"* — this was a reporting-arithmetic error (numbers guessed from memory, not measured; the arithmetic itself was inconsistent). The **authoritative measured matrix is `6 + 7 + 18 = 31`**, verified via `pytest --collect-only` per file and confirmed by the verbose per-test PASSED lines. No test-name overlap between the three files; L2/L2b/L2c are three sub-slice prefixes co-located in a single physical file, which caused the earlier miscount. Every future verification report must be measured, not remembered, and every arithmetic total must reconcile.
  - **Tests (new)**: `test_iter133_l1_5_passbook_cdn_rows.py` — 6 hermetic tests: (T1) issued CN row shape; (T2) issued DN positive-sign convention; (T3) cancelled notes excluded (draft exclusion covered by shared `status:"issued"` filter); (T4) `date_from`/`date_to` filter on `note_date`; (T5) customer isolation — CN on cust-X invisible in cust-Y passbook; (T6) `summary.credits_total`/`debits_total` unchanged + `txn_type=credit_note|debit_note|trip` filter correctness.
  - **Restart**: 1 authorized backend restart. UI smoke on preview: Customer History loads, L2c Adjustments strip shows `−₹450 CN / +₹3,175 DN`, All · Passbook table renders (trips + invoices grouped by month with correct columns).
  - **Files changed**: `backend/routers/customers.py` (+62 additive rows in `/customers/{cid}/transactions`), `frontend/src/pages/CustomerHistory.jsx` (TxnRow/TypeIcon/StatusChip/groupByMonth/openTxn extended), new `backend/tests/test_iter133_l1_5_passbook_cdn_rows.py`.
  - **Existing locks preserved**: Iter133 L1 🔒, Iter133 L2 🔒, Iter133 L2b 🔒, Iter133 L2c 🔒 — all remain locked and untouched.
  - **Master Principle re-affirmed**: *Enter Once → Calculate Once → Reflect Everywhere → Report Ready → No Manual Reconciliation.* A CN/DN entered in QORVENA now automatically flows to the Customer Passbook alongside Invoice/Payment rows; combined with Iter133 L1 (Ledger API) and L2/L2b/L2c (Ledger UI + Ledger PDF + Statement PDF), the CN/DN adjustment is reflected across every downstream surface without any manual reconciliation. **Verification evidence must also be precise, auditable, and internally consistent** — measured, not remembered.
  - **Not shipped (still deferred, awaiting explicit GO)**: Slice C3 GSTR-1 Section 9B export, Slice C4 CN/DN Register report, Iter132c-agg-fix `to_list` in `ai.py`/`services.py`, Statement Email Delivery, Phase 2 Security Hardening, `AKB/26-27//26-27/0004` hygiene, Preview Uptime Chip, LR Register Email Digest, Trip Templates completion.
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
- **Iter132c-agg-fix · H1 · `/reports/ledger` Streaming** — 🔒 LOCKED · UAT approved 2026-08-30
  - Removes the pre-existing `to_list(2000)` truncation on `/reports/ledger` and `/reports/ledger/pdf` (which reuses the JSON endpoint). Same B1 streaming pattern proven in Iter132c C1 for `/dashboard` and `/reports/balance-sheet`. Read-side correctness fix — zero write-path, zero schema, zero contract change.
  - **Root cause of pre-existing bug**: `reports.py:44` used `await db.invoices.find({...}).to_list(2000)` for a per-customer T-account ledger. For any customer with more than 2,000 invoices (real-world risk for large fleets and long tenure), the oldest invoices were silently dropped from `entries[]`, `opening_balance`, `total_debit`, `total_credit`, and `closing_balance`. Latent in demo (top customer had 696) but a statutory audit-trail risk.
  - **Fix approach**: replaced `to_list(2000)` with a single `async for` Motor cursor and a **single-pass** aggregation that computes `entries[]` (in-range invoices + in-range payments) AND `opening_balance` (pre-start invoices minus pre-start payments) in the same loop. Two DB queries per call (customer master lookup + invoice cursor); no N+1; MongoDB cursor auto-batches at 101 docs (Motor default) so peak memory scales only with the in-range entries returned in the response, not the full cursor size.
  - **Semantic preservation**: opening-balance rule preserved exactly — pre-start invoices add their `total_amount` to opening, pre-start payments subtract regardless of parent-invoice date. Entry sort order preserved (date ascending; invoice before payment on same day). Response shape byte-identical (same keys, same order).
  - **CN/DN scope discipline**: ledger continues to NOT surface CN/DN as entries (deliberately deferred — adding CN/DN rows would be a separate presentation-change slice with PDF-layout implications). Cancelled and draft notes automatically excluded.
  - **Downstream PDF (`/reports/ledger/pdf`)**: reuses `report_ledger` and passes its return dict to `build_ledger_pdf` (pdf/ledger.py). Inherits the fix automatically. `pdf/ledger.py` NOT touched.
  - **Tests (new)**: `test_iter132c_agg_fix_ledger.py` — 4 tests.
    - **T1** small-dataset ground-truth: endpoint totals equal Mongo `$group` aggregation over the same customer.
    - **T2** ⭐ **core H1 regression**: direct-seeds 2,100 invoice docs (unique `seed_tag`) into MongoDB for a fresh isolated customer, calls the real `/reports/ledger` endpoint, asserts `len(entries)==2100` and `closing_balance==₹210,000`, then guaranteed cleanup via `finally:` + post-cleanup verification that zero orphan docs remain. Direct Mongo seed shortcut used ONLY for the volume fixture; the ledger API is still exercised end-to-end.
    - **T3** opening-balance semantic preservation: pre-start invoices + pre-start payments handled correctly with `?start=... &end=...` filter.
    - **T4** PDF-consumer regression: `/reports/ledger/pdf` returns 200, `application/pdf`, non-trivial size after the JSON streaming rewrite.
  - **Test isolation**: per-test unique customer via `POST /api/customers`; direct-Mongo docs tagged with unique `seed_tag=H1TEST-<uuid>` for surgical cleanup; test process fetches `user_id` via `/api/auth/me` (P2 helper `_current_uid()`).
  - **Test-only fix P1c** (applied to `test_iter130_demo_guard.py` L135-156): the pre-existing Iter130 test used `monkeypatch.delenv("IS_PREVIEW_ENV", ...)` — the SAME file's earlier test at L114-118 already documents that this pattern is defeated by `load_dotenv()` in the `db.py` import chain re-populating the value from `.env`. P1c aligns L135's test with the documented workaround (`setenv("IS_PREVIEW_ENV", "0")` + `finally:` restore), producing consistent 11/11 pass. Zero product-code touched.
  - **Verified**:
    - H1 targeted: **4/4 in 2.93 s** · exit 0
    - Iter132c C1: **15/15** · Iter132a: **10/10** · Iter132b: **11/11** · Iter130: **11/11** · Iter131: **6/6** (all pass in isolation)
    - **Deploy-Guard: 503 passed / 1 skipped / 0 failed / exit 0 / 1077.55 s (17:57)**
    - Iter128 badge: **🟢 Ready** · `elapsed_s=1078.3` · `next_check_at +60 min` · `consecutive_failures=0` · **4 consecutive passes** at 02:42, 03:14, 04:35, 05:05 UTC (Iter131 hourly cadence intact throughout)
    - `/api/auth/health` **200** · new demo token **200** · legacy demo token **401** · unauth **401**
    - Live ledger sanity on production data: top customer (`cust_1c232a355617455d`, **696 invoices**) → `/reports/ledger` returns all **696 entries**, closing `₹20,587,680`, no truncation.
    - Invoice numbering intact: `INV/26-27/0900` — sequential FY-scoped pattern preserved.
  - **Zero touches** to: `services.py`, `models.py`, `server.py`, `pdf/invoice.py`, `pdf/credit_note.py`, `pdf/debit_note.py`, `pdf/ledger.py`, `routers/notes.py`, `routers/customers.py`, `routers/dashboard.py`, `routers/invoices.py`, `auth.py`, `auth_router.py`, Iter132a/b core, Iter132c C1 code, Save Health, Iter130/131 scheduler product code, Google OAuth, invoice numbering (`_next_invoice_number*`, `_compose_invoice_number`), invoice schema, RBAC/perms, `run_regression.sh`, `predeploy_check.sh`, `pytest.ini`, `.env`, `requirements.txt`, `ai.py`, all frontend files, and every other `to_list(2000)` occurrence outside `/reports/ledger`.
  - **Restarts used**: 1 authorised backend restart (after H1 streaming rewrite landed). Zero unauthorised restarts.
  - **STOP RULE compliance**: halted twice mid-iteration when tests failed (test-helper bugs, then xdist parallel-run artefacts); RCA-only reports; test-only fixes applied strictly after explicit user GO. No autonomous product-code changes.
  - **Not shipped (deferred)**: remaining `to_list(2000)` sites in `ai.py` (M1/M2/M3 LLM tools — Iter132c-ai-agg-fix candidate), `add_payment`/`bulk_auto_allocate` write path (explicit scope exclusion), `/reports/gstr-1` statutory export (separate controlled scope), CN/DN rows in ledger (separate presentation-change slice), Slice C2 (Frontend UI), Slice C3 (GSTR-1 Section 9B), Slice C4 (CN/DN Register report).

## Iter132c C2 · CN/DN Frontend UI + PDF endpoints + Customer-entry flow + GST Treatment + PDF font/RCM/GSTIN refinements — 🔒 LOCKED (2026-08-30 UAT approved)

### Slice C2 — Frontend UI + 2 PDF backend endpoints — 🔒 LOCKED
- **What shipped**
  - New dedicated **Notes list page** (`/app/frontend/src/pages/Notes.jsx`) with kind pill (Red=Credit, Blue=Debit), status filter (all / draft / issued / cancelled), search, RBAC-gated Cancel action, and download links.
  - New **create dialog** (`components/NoteCreateDialog.jsx`) launched from Invoice detail (`RelatedNotesSection.jsx`) — inherits invoice's GST posture, over-credit guard is server-enforced.
  - **Feature probe** via `useCdnEnabled()` hook (React-Query `staleTime: Infinity`, `retry: false`) hitting the existing gated `/credit-notes` list endpoint — fail-secure: sidebar link + list route + all mount points hidden when the backend flag is off.
  - New backend read-only endpoints: `GET /api/credit-notes/{nid}/pdf` and `GET /api/debit-notes/{nid}/pdf` (StreamingResponse of the redesigned builders; tenant-scoped, 404 on cross-tenant lookup, 400 on `status="draft"`).
- **Non-goals honoured**: numbering, `_compute_note_totals`, sign convention, over-credit guard, statutory-deadline validator, RBAC roles, feature flag surface, `_effective_balance`, invoice schema, invoice numbering, `pdf/invoice.py` — all untouched.

### Slice C2b — Customer-scoped CN/DN entry + Professional PDF redesign — 🔒 LOCKED
- **Customer entry flow**: `components/NoteCreateFromCustomerDialog.jsx` (invoice picker on top of `/api/customers/{cid}/transactions`) + 2 gated action buttons (`customer-add-credit-note-btn`, `customer-add-debit-note-btn`) wired into `pages/CustomerHistory.jsx`. Reuses the existing C1-enriched customer transactions endpoint (with `effective_balance_due`, `credits_total`, `debits_total`); zero new backend endpoints.
- **Redesigned PDFs** (`pdf/credit_note.py`, `pdf/debit_note.py`) — A4 portrait, top accent bar (Red `#B91C1C` / Blue `#1D4ED8`), company logo, dedicated "CREDIT TO" / "DEBIT TO" + "REFERENCE INVOICE" grid, coloured reason banner, professional line-item table with white-on-accent header, right-aligned totals with accent-underlined final row, amount-in-words, RCM notice, authorised-signatory block.
- **PDF byte tests** via `pdfminer.six==20260107` (added to `requirements.txt`) covering all header, customer, reference-invoice, reason, line, tax, total, amount-in-words and RCM elements.
- **Non-goals honoured**: `pdf/invoice.py`, `pdf/lr.py`, `pdf/owner.py`, `pdf/_base.py` — all untouched. C1 effective-balance semantics and CN/DN business logic — all untouched.

### GST Treatment (parity slice under C2b) — 🔒 LOCKED
- **Additive `apply_gst: bool = True` field** on `CreditDebitNote` and `CDNCreateRequest` (models.py). Backward-compat: reads default `True` when field missing on legacy docs (no migration required).
- **`_compute_note_totals(payload_lines, invoice, apply_gst=True)`** in `routers/notes.py` — when `apply_gst=False`, zeroes CGST/SGST/IGST/total_tax but retains invoice-inherited `gst_type` and rate metadata for reporting parity; `gross = subtotal` in that path (matches RCM parity).
- **Statutory validators untouched**: 30-Nov FY deadline guard, over-credit guard, note_date validators, tenant isolation, RBAC — all still enforced regardless of `apply_gst`.
- **UI**: `NoteCreateDialog.jsx` adds a **GST Treatment** radio fieldset (defaults to "Proceed with GST — inherit from invoice") with a warning banner when "Proceed without GST" is selected, plus `apply_gst` in the POST payload.
- **PDF**: when `apply_gst=False`, both CN and DN builders render a prominent red-bordered "**GST NOT APPLIED**" pill directly under the reason block, replace the CGST/SGST/IGST/Total-Tax rows with a single "GST · Not Applied" row, and preserve the standard "TOTAL …" footer.
- **Regression**: 5 new tests (`test_iter132c_c2b_pdf_redesign.py`) — zero-tax path, PDF-badge presence, PDF-tax-rows absence, DN parity, and past-deadline block still fires with `apply_gst=False`.

### Slice C2c — ₹ Unicode-font fix · RCM presentation clarifier · Empty-GSTIN presentation guard — 🔒 LOCKED
- **₹ Unicode-font fix**: swapped default Helvetica → registered `DejaVuSans` / `DejaVuSans-Bold` (`pdf/_base.py::_UNI_FONT`) across every ParagraphStyle **and** every raw-string body cell in the four PDF paths: `pdf/credit_note.py`, `pdf/debit_note.py`, `pdf/ledger.py`, and the inline builder inside `routers/customers.py::customer_statement_pdf`. Follow-up patch after initial C2c iteration added `("FONTNAME", (0, body_start), (-1, -1), _UNI_FONT)` to CN/DN line-item tables, ledger data rows, and all 3 tables of `customer_statement_pdf` (summary / trips / invoices) to guarantee U+20B9 renders on **every** currency-bearing cell — not just Paragraph-wrapped ones. Verified: **₹ count = 4** on CN + DN + Ledger PDFs, **₹ count = 10** on STMT PDF for a single-invoice tenant; no Helvetica remains anywhere in the 4 changed builder paths.
- **RCM presentation clarifier** — CN/DN totals now show `"Total Tax (RCM — not collected)"` label (only when `rcm=True` and `apply_gst=True`), a new explicit "GST under Reverse Charge · Not included in Payable" row, and the final total label becomes `"TOTAL CREDIT NOTE (excl. RCM GST)"` / `"TOTAL DEBIT NOTE (excl. RCM GST)"`. The legacy one-line muted footer `"RCM applicable —"` is elevated to a bordered accent-coloured box under the totals: *"REVERSE CHARGE MECHANISM (RCM) — GST on this Credit/Debit Note is to be paid by the recipient under Notification No. 08/2017. The tax amount shown above is not included in the payable total."* **Zero calculation change** — persisted totals, `total_amount`, tax fields, and `_compute_note_totals` untouched.
- **Empty-GSTIN presentation guard** — when a company's stored `gstin` is empty/whitespace, the CN/DN PDF renders `"GSTIN: —"` in place of the previous `"GSTIN:  · State: …"` double-space artifact. No schema change, no hard-coded GSTIN, no data-side write.
- **Non-goals honoured**: `pdf/invoice.py`, `pdf/lr.py`, `pdf/owner.py`, `pdf/_base.py`, `services.py`, `routers/invoices.py`, `auth.py`, `server.py`, invoice numbering, `_effective_balance`, `_compute_note_totals` sign convention, RBAC, feature flags, `AKB/26-27//26-27/0004` anomalous invoice number (belongs to a separate future Invoice-Number Hygiene one-off), and the entire Customer-Ledger CN/DN row-integration (deferred to Iter133 L1/L2) — all untouched.

### Final regression evidence (2026-08-30 lock day)
- **Serial targeted matrix (`-n0`)**: Iter132a **10/10**, Iter132b **11/11**, Iter132c C1 **15/15**, Iter132c-agg-fix H1 **4/4**, C2 PDF endpoints **6/6**, C2b + GST + C2c **19/19**, Iter130 **11/11**, Iter131 **6/6**, Iter51 deploy-guard **10/10**, Iter128 badge **8/8** — **total 100 passed / 0 failed / 0 skipped / exit 0** in ~48.85 s.
- **Full Deploy Guard (`/api/admin/deploy-readiness/run-now`)** — user-triggered fresh run at `2026-08-30T11:06:29Z` (`triggered_by: "manual"`): **503 passed / 1 skipped / 0 failed / exit 0 / elapsed 723.91 s (12:03)**. `consecutive_failures=0`, `next_check_at=2026-08-30T12:06:29Z`, `strict_mode=true`. Deploy Readiness Badge: **🟢 Ready**.
- **Combined-run false positives** (documented, not regressions): 4 tests flap under xdist parallelism or shared-loop pollution (`test_r5/r9_effective_balance`, `test_effective_balance_increases_with_debit_note`, `test_demo_login_endpoint_module_returns_404_without_preview`) — all **pass in isolation** per the handoff-summary guidance. Same behaviour observed on prior locked iterations; not caused by C2b/C2c code changes.
- **Product-behaviour spot verifications**: ₹ renders in all 4 PDFs, `apply_gst=True/False` both round-trip correctly, RCM clarifier + `(excl. RCM GST)` label + no legacy line, `GSTIN: —` on empty issuer GSTIN, over-credit + past-deadline validators enforced regardless of GST treatment, `git diff HEAD` on invoices.py/services.py = 0 lines.

### Files changed in C2 + C2b + GST + C2c (final inventory)
- **New**: `frontend/src/pages/Notes.jsx`, `frontend/src/components/NoteCreateDialog.jsx`, `frontend/src/components/NoteCreateFromCustomerDialog.jsx`, `frontend/src/components/RelatedNotesSection.jsx`, `frontend/src/hooks/useCdnEnabled.js`, `backend/pdf/credit_note.py`, `backend/pdf/debit_note.py`, `backend/tests/test_iter132c_c2_pdf_endpoints.py`, `backend/tests/test_iter132c_c2b_pdf_redesign.py`.
- **Modified**: `backend/models.py` (+8 lines for `apply_gst`), `backend/routers/notes.py` (+21 lines threading `apply_gst`, +2 PDF endpoints), `backend/routers/customers.py` (+17 lines font swap in `customer_statement_pdf`), `backend/pdf/ledger.py` (+8 lines font swap), `frontend/src/pages/CustomerHistory.jsx` (+36 lines buttons + dialog mount), `frontend/src/components/Sidebar.jsx` (+CN/DN link), `backend/requirements.txt` (+`pdfminer.six==20260107` for test-only PDF text extraction).
- **Zero touches**: `pdf/invoice.py`, `pdf/lr.py`, `pdf/owner.py`, `pdf/_base.py`, `services.py`, `routers/invoices.py`, `auth.py`, `auth_router.py`, `server.py`, `.env`, `pytest.ini`, `run_regression.sh`, invoice numbering helpers, `_effective_balance`, `_compute_note_totals` sign convention, RBAC roles, feature-flag env, Iter130/131/132a/132b/132c-C1/H1 code, Save-Health, Google OAuth, `AKB/26-27//26-27/0004` anomalous invoice number.

### Restarts used
- **3 authorised backend restarts** across the full C2 → C2b → C2c → C2c-follow-up arc. Zero unauthorised restarts.

### STOP RULE compliance
- Halted twice mid-iteration when targeted tests failed (once for STMT-PDF body-cell font gap, once for xdist/asyncio-loop pollution). RCA-only reports; fixes applied strictly after explicit user GO. No autonomous product-code changes.

### Not shipped (deferred, awaiting separate approvals)
- **Iter133 L1/L2** — Customer Ledger CN/DN row integration (data-layer merge + PDF presentation).
- **Slice C3** — GSTR-1 Section 9B statutory export.
- **Slice C4** — CN/DN Register report.
- **Iter132c-ai-agg-fix** — remaining `to_list(2000)` truncation in `ai.py` LLM tools (M1/M2/M3).
- **Invoice-Number Hygiene one-off** — the single anomalous `AKB/26-27//26-27/0004` invoice row (data-only, tenant-approved rewrite pathway).
- **Phase 2 Security Hardening** — Save-Health role-gating, `/run-now` role-gating, localStorage-token removal, global 500-error sanitisation.
- **Trip Sheet redesign / rebrand / other backlog** — untouched.

## Iter133 L1 · Customer Ledger CN/DN Row Integration (data-layer only) — 🔒 LOCKED (2026-08-30 UAT + Deploy-Guard approved)

- **What shipped**
  - `/api/reports/ledger` now emits `type: "credit_note"` and `type: "debit_note"` entries alongside existing `invoice` / `payment` rows.
  - **Sign convention** (approved): Credit Note → credit column (reduces receivable). Debit Note → debit column (increases receivable). Running-balance formula unchanged: `balance = running + debit − credit`.
  - **Opening-balance treatment**: notes dated `< start` fold into opening — CN subtracts, DN adds — mirroring the pre-existing invoice/payment opening semantics. Notes dated `> end` are excluded.
  - **Draft / cancelled exclusion**: `status ∈ {"draft", "cancelled"}` never touch opening, entries, totals, or closing (only `status == "issued"` participates).
  - **Same-day sort priority** (auditor-friendly): `invoice → debit_note → credit_note → payment`.
  - **Additive `totals_by_type` metadata** on the JSON response — `{invoice, payment, credit_note, debit_note}` — backwards-compatible; existing consumers ignore it.
  - **Ledger PDF (`/api/reports/ledger/pdf`)** renders the new rows automatically via payload-driven `pdf/ledger.py`; zero PDF code change in L1.
- **Design guarantees preserved**
  - **Tenant + customer isolation**: every CN/DN cursor filter carries `{user_id, company_id, customer_id, status:"issued"}`.
  - **No N+1**: single additional Motor `async for` cursor (`db.credit_debit_notes.find(...)`) reusing the existing `(user_id, company_id, note_date DESC)` compound index — no join, no per-note round trip.
  - **DB queries per call**: 2 → 3 (customer master + invoice cursor + CN/DN cursor). Negligible latency impact.
  - **`invoice_number_snapshot` used verbatim** for the "against …" particulars — no join needed.
- **Non-goals honoured (zero touches)**
  - `pdf/ledger.py`, `pdf/invoice.py`, `pdf/credit_note.py`, `pdf/debit_note.py`, `pdf/lr.py`, `pdf/owner.py`, `pdf/_base.py`.
  - `routers/notes.py`, `routers/customers.py`, `routers/invoices.py`, `routers/dashboard.py`, `routers/ai.py`.
  - `models.py`, `services.py`, `auth.py`, `server.py`.
  - Frontend — no changes; the existing Reports Ledger consumer picks up new rows automatically because the response shape is additive.
  - Invoice numbering, `_effective_balance`, `_compute_note_totals`, RBAC, feature flags, `AKB/26-27//26-27/0004` anomalous invoice row.
- **Regression evidence (2026-08-30 lock day)**
  - **Targeted matrix** (serial `-n0`): L1 **7/7** + Iter132a **10/10** + Iter132b **11/11** + C1 **15/15** + H1 **4/4** + C2 **6/6** + C2b+C2c **19/19** = **72 / 72 passed** in isolation.
  - **Full Deploy Guard** at `2026-08-30T13:13:54Z`: **504 passed / 0 skipped / 0 failed / exit 0** in 729.81s (~12 min 10 s), `consecutive_failures=0`, `strict_mode=true`, `next_check_at=2026-08-30T14:13:54Z`, Iter128 badge **🟢 Ready**.
  - **Behavioural spot-checks** (post-regression, fresh tenant):
    - Ledger JSON — invoice ₹18,000 + issued CN ₹1,500 + issued DN ₹900 → `total_debit=18,900 · total_credit=1,500 · closing=17,400` · `totals_by_type={invoice:18000, payment:0, credit_note:1500, debit_note:900}`.
    - Cancelled CN → **excluded** from entries and totals.
    - Opening-balance rollup (query starting after all notes) → `opening=17,400 · entries=0 · closing=17,400`.
    - Ledger PDF byte-check: `CN/26-27/0312` present, `CN/26-27/0313 (cancelled)` absent, `DN/26-27/0234` present, `₹` glyph count = 4.
- **Files changed (final L1 inventory)**
  - `backend/routers/reports.py` — +76 / −6 lines (second cursor, priority sort, `totals_by_type`).
  - `backend/tests/test_iter133_l1_ledger_cdn_rows.py` — NEW · 265 lines · 7 tests.
- **Restarts used**: 1 authorised backend restart. Zero unauthorised restarts.
- **STOP RULE compliance**: no autonomous fixes; xdist / asyncio-loop pollution flagged as known-issue and confirmed as false positives via `-n0` re-runs.
- **Not shipped (deferred)**
  - **L2** — Customer Ledger / Statement PDF presentation (customer-facing readability, professional layout).
  - **C3** — GSTR-1 §9B statutory export.
  - **C4** — CN/DN Register report.
  - **Iter132c-ai-agg-fix** — `to_list(2000)` truncation in `ai.py` LLM tools.
  - **Invoice-Number Hygiene one-off** — anomalous `AKB/26-27//26-27/0004`.
  - **Phase-2 Security Hardening**, Trip Sheet redesign, other backlog — all untouched.

## Iter133 L2 + L2b + L2c · Customer Ledger & Statement Presentation — 🔒 LOCKED (2026-08-30 UAT + Deploy-Guard approved)

- **L2 · Ledger UI + PDF branded presentation** — Redesigned `pdf/ledger.py` (84 → ~240 lines) with company logo + Bill-To/Period/Closing card + `totals_by_type` pill row (invoiced/DN/CN/payments) + adjustments summary line + per-row tint (CN=red-50, DN=blue-50) + Amount-in-Words + Authorised Signatory + `Page X of Y` footer via a two-pass `NumberedCanvas`. Frontend `Reports.jsx` LedgerReport: per-type coloured pills in the Ref column (INV/PMT/CN/DN), row-level red/blue tint for CN/DN, `totals_by_type` mini-cards, "Adjustments this period" strip. Frontend `CustomerHistory.jsx` passbook: presentational aggregate strip using existing `summary.credits_total` / `summary.debits_total` — no backend change.
- **L2b · Customer Statement PDF branding parity** — Same branded hero band + logo + company GSTIN with empty-guard + Bill-To / Statement-Period / Outstanding info card + Amount-in-Words + Authorised Signatory + Page X of Y — for `customer_statement_pdf`. Balance Bridge + Adjustments table preserved unchanged.
- **L2c · Visual polish (15-item plan)** — Ledger table column widths rebalanced to 178 mm (`19/26/61/24/24/24`), header padding lifted, tabular number breathing room, subtle Opening-Balance grey, divider above TOTAL, Closing Balance row emphasised with amber accent + top-rule + 10-pt bold. Statement Balance Bridge widened to 178 mm (`118/60`), payments/Balance-Due divider hierarchy, DejaVu heading style, Adjustments table widened (`20/30/12/32/60/24`) so `post_invoice_discount` doesn't overflow, thin amber section rules above Balance Bridge and Adjustments, tightened inter-section spacing, signatory spacer trimmed from 10 mm → 6 mm.
- **Master Principle upheld** — *Enter Once → Calculate Once → Reflect Everywhere → Report Ready → No Manual Reconciliation.* A single issued CN/DN now propagates automatically to effective invoice balance (C1) → dashboard/balance-sheet → `/reports/ledger` JSON entries + `totals_by_type` (L1) → Reports → Ledger UI → `/reports/ledger/pdf` → `/customers/{cid}/statement.pdf` (with Balance Bridge + per-note Adjustments) → CustomerHistory passbook aggregate strip. Zero customer-side manual reconciliation.
- **Non-goals honoured (zero touches)** — `pdf/invoice.py`, `pdf/credit_note.py`, `pdf/debit_note.py`, `pdf/lr.py`, `pdf/owner.py`, `pdf/_base.py`, `routers/reports.py` (L1 LOCKED), `routers/notes.py`, `routers/invoices.py`, `routers/dashboard.py`, `routers/ai.py`, `models.py`, `services.py`, `auth.py`, `server.py`. Invoice numbering, `_effective_balance`, `_compute_note_totals`, effective-balance semantics, tax/GST calculations, RBAC, feature flags, `AKB/26-27//26-27/0004` anomalous invoice, statutory validators, L1 payload contract — all unchanged.
- **Regression evidence (2026-08-30 lock day)**
  - **Targeted matrix (serial `-n0`)**: L2/L2b/L2c 18 + L1 7 + C2b/C2c 19 + C2 endpoints 6 + H1 4 + C1 15 + Iter132a 10 + Iter132b 11 = **90 / 90** in isolation (combined-run flap on `test_l1_t3_cn_before_start_folds_into_opening` and `test_effective_balance_increases_with_debit_note` — known cross-file test-data pollution documented since L1 lock, both pass in isolation).
  - **Full Deploy Guard** at `2026-08-30T15:09:17Z`: **503 passed / 1 skipped / 0 failed / exit 0** in 736.27 s (~12 min 16 s), `consecutive_failures=0`, `strict_mode=true`, `next_check_at=2026-08-30T16:09:17Z`, `failed_tests=[]`. Iter128 badge **🟢 Ready**.
  - **PDF spot verifications** (fresh tenant, real CN + DN): Ledger PDF `₹×9-10` · all 6 cols visible · no numeric wrap · Opening/TOTAL/Closing highlighted · CN/DN row tint · Amount-in-Words · Signatory · `Page 1 of 1`. Statement PDF `₹×17-18` · CUSTOMER STATEMENT hero · BILL TO / STATEMENT PERIOD / OUTSTANDING blocks · Balance Bridge (5 rows with dividers) · Adjustments (6 columns, `post_invoice_discount` fits) · cancelled notes absent · Signatory · `Page 1 of 1`.
- **Files changed (final L2 + L2b + L2c inventory)**
  - `backend/pdf/ledger.py` — 84 → ~242 lines (full redesign in L2, table tuning in L2c).
  - `backend/routers/customers.py` — +178 lines total (L2 Bridge+Adjustments, L2b branded header/AmtWords/Signatory, L2c widths/dividers/heading style/spacing, final spacer trim).
  - `backend/tests/test_iter133_l2_ledger_statement_presentation.py` — NEW · 451 lines · 18 tests (9 L2 + 7 L2b + 2 L2c).
  - `frontend/src/pages/Reports.jsx` — +60 / −16 lines (type pills, row tint, `totals_by_type` cards, adjustments strip).
  - `frontend/src/pages/CustomerHistory.jsx` — +22 lines (passbook aggregate adjustment strip).
- **Restarts used**: 3 authorised backend restarts across the L2 → L2b → L2c → L2c-spacer arc. Zero unauthorised restarts.
- **STOP RULE compliance**: no autonomous product-code fixes; known xdist/asyncio-loop pollution flagged and confirmed as false positives via `-n0` isolation runs.
- **Not shipped (deferred, awaiting separate approvals)**
  - **L1.5** — Passbook UI per-note CN/DN row integration on `/customers/{cid}/transactions`.
  - **AI `customer_ledger` tool** — CN/DN parity micro-slice.
  - **C3** — GSTR-1 §9B statutory export.
  - **C4** — CN/DN Register report.
  - **Iter132c-ai-agg-fix** — `to_list(2000)` truncation in `ai.py` LLM tools.
  - **Invoice-Number Hygiene** one-off (anomalous `AKB/26-27//26-27/0004`).
  - **Phase-2 Security Hardening**, Trip Sheet redesign, other backlog — all untouched.

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
- CN/DN Frontend UI, GSTR-1 Section 9B export, CN/DN Register report, Customer Statement CN/DN row-items, remaining `to_list(2000)` truncation sites (`ai.py` LLM tools · Iter132c-ai-agg-fix candidate) 🧊
- All Iter126 / Iter127a-c / Iter128 / Iter129 Phase 1 / Iter130 / Iter131 / Iter132a / Iter132b / Iter132c C1 / Iter132c-agg-fix H1 / P0 locked functionality 🔒

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
