# Iter89 · Impact Assessment — Customer Freight, Shortage, Invoice Redesign
Status: 🟡 Review only · No code changes yet · Awaiting user approval

## Executive Summary
Approve this spec — it's the right direction. Estimate: **~1000-1500 credits, 6-8 iterations, ~10 days build**. Do it in 5 phases (below) so each phase is user-verifiable before the next. Not a rewrite — extends the existing single-source-of-truth Trip model.

## Phase Status
- **Phase 1 · Master Data + Policy Snapshot** — ✅ **COMPLETE** (Iter89, Feb 2026). All 7 pytest locks pass. Live curl end-to-end verified. Awaiting user UI approval before Phase 2.
- **Phase 2 · Central Freight Calc Service** — ⏳ Blocked on Phase 1 user approval.
- **Phase 3 · Central Shortage Calc (Customer + Supplier independent)** — ⏳ Blocked.
- **Phase 4 · Per-field Override Audit Trail** — ⏳ Blocked.
- **Phase 5 · Modern Invoice PDF Redesign** — ⏳ Blocked.

## What Already Exists (Good Foundation)
1. **Trip is already the single source of truth**. Freight, halting, shortage, expenses all persist on Trip. Invoice reads live from trip_ids at render time.
2. **Override fields already exist**: `shortage_amount_override`, `excess_amount_override`, `halting_amount_override`, `supplier_shortage_deduction_override`. Pattern is proven.
3. **Supplier shortage auto-mirror** (Iter74) already flows `trip.shortage_amount → supplier_shortage_deduction` in `services.py`, respecting override flag.
4. **Per-trip customer ref** (Iter66/82/83/84/85) works end-to-end.
5. **Ship-To sites** on customer master (Iter66) work.
6. **Multi-company isolation** already enforced via `LIVE_ONLY_FILTER` + `company_id` on every query.
7. **Historical Isolation Layer** (Iter86) already in place — imports don't leak.
8. **Invoice PDF** already has Cust Ref column (Iter82) + Ship-To block (Iter79).

## What's Missing (Real Gaps)
| Gap | Where | Effort |
|---|---|---|
| Customer.default_freight_method | Customer model + Customer form | S |
| Trip.freight_method Literal expansion (loading_qty, unloading_qty, higher_of, fixed) | Trip model + freight calc service | M |
| Product.default_shortage_allowance_pct | Product model + Product form | S |
| Customer.shortage_config (limit / limit_type / method / effective_from) | Customer model + subform | M |
| Trip snapshot of applied policy (for historical protection) | New fields on Trip: `applied_freight_method`, `applied_shortage_limit`, `applied_shortage_method`, `applied_product_shortage_pct` | M |
| Per-field override audit trail (original_value / final_value / reason / by / at) | New `trip.overrides[]` sub-doc | M |
| Freight calc central service | `services.py::calculate_freight(trip)` — one place, no duplicates | M |
| Shortage calc central service | `services.py::calculate_shortage(trip)` — customer + supplier independent | M |
| Invoice PDF redesign (portrait-first, auto-landscape when >9 cols needed) | `pdf/invoice.py` rewrite | L |
| Invoice all-details view (per-trip breakdown of freight basis, shortage math, halting) | `pdf/invoice.py` + InvoiceView.jsx | L |
| Post-invoice edit safety (invoice always re-derives from trips at render) | Already partly done; add invalidation + audit | S |

## Risks to Watch
1. **Never break existing trips** — new fields must default so old trips still calc correctly. Test with a 2020-era trip.
2. **Supplier shortage rule** (spec §7) is materially different from current auto-mirror: current mirrors customer shortage; new rule uses **fixed KG threshold + full deduction above**. Requires new `supplier.shortage_limit_kg` + supplier-specific calc path. **Do not** repurpose customer shortage code.
3. **Historical protection** (spec §19) means Trip must snapshot the applied policy at time of trip. Changing Customer.freight_method later must NOT re-compute a 3-month-old trip. This is architecturally the most important guarantee — get it right in Phase 1.
4. **Invoice = trips live-read** stays the design (spec §17 wants this). Do NOT persist freight on invoice line items.
5. **PDF landscape auto-switch** — add a col-count threshold and let ReportLab pick.

## Proposed Phasing (each phase pytest-locked + user-approved before next)

**Phase 1 · Master Data + Policy Snapshot** (~200 credits · 2 days)
- Add fields: `Customer.default_freight_method`, `Customer.shortage_config`, `Product.default_shortage_allowance_pct`, `Supplier.shortage_limit_kg`
- Add snapshot fields on Trip
- Trip create: populate snapshot from masters at insert time
- Pytest: master → trip snapshot; edit master, verify old trip unchanged

**Phase 2 · Central Freight Calc Service** (~150 credits · 1 day)
- `services.py::calculate_freight(trip)` supporting: `per_ton_loading`, `per_ton_unloading`, `per_ton_higher_of`, `fixed`, `round_trip`
- Wire into trip create/update
- Pytest: 5 methods × override cases

**Phase 3 · Central Shortage Calc Service (Customer + Supplier separately)** (~200 credits · 1.5 days)
- `services.py::calculate_customer_shortage(trip)` — supports `net_shortage`, `full_after_limit`
- `services.py::calculate_supplier_shortage(trip)` — fixed-KG-threshold + full-deduction
- Kill the current auto-mirror; replace with independent paths
- Pytest: within-limit / above-limit / both methods / customer-supplier independence

**Phase 4 · Override Audit Trail** (~150 credits · 1 day)
- `trip.overrides[]` sub-doc: `{field, original, final, reason, by, at}`
- Trip Form: every calculated field editable; if user changes → prompt reason → push to overrides[]
- Show "System Value · Final Value" side-by-side in Trip View
- Pytest: override flow + audit persistence

**Phase 5 · Modern Invoice PDF Redesign** (~350 credits · 3 days)
- Portrait default; auto-landscape when > 9 relevant cols
- Per-trip breakdown: Freight Basis · Loading · Unloading · Shortage · Halting · Adjustments
- Bill-To / Ship-To split (already possible; polish)
- Amount in words + rounding + GST section (already there; layout polish)
- Pytest: portrait, landscape, multi-trip, GST, ₹ symbol, no clipping

## What I Will NOT Do
- ❌ Duplicate the freight calc in more than one place
- ❌ Persist freight on invoice line items (invoice stays a live view of trips)
- ❌ Auto-recompute historical trips when masters change
- ❌ Use customer shortage code for supplier shortage
- ❌ Break existing trips
- ❌ Start coding until you approve this plan

## Next Step
Please confirm:
a) Phasing looks good, or reorder?
b) Any freight methods beyond the 4 listed (loading / unloading / higher / fixed)?
c) Supplier shortage limit — is it always KG, or sometimes %?
d) Reason-required for every override, or only for financial fields (freight, shortage, halting)?
e) Any customer-specific invoice template branding requirements now, or standard modern layout OK?

Once approved, I'll start Phase 1 with a pytest suite locking the master → trip snapshot behavior, then hand back for your verification before Phase 2.
