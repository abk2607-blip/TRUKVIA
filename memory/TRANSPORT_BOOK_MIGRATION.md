# TRANSPORT BOOK → QORVENA · Migration Feasibility Report

**Status:** 🟡 Awaiting user input · No data touched yet
**Prepared:** Feb 2026
**Guardrail:** Do NOT touch live QORVENA DB until this report is approved AND a full backup is verified.

---

## 0. Executive Summary

Migrating historical Transport Book data into QORVENA is **technically feasible** but the effort depends entirely on **what export format Transport Book supports**. Before I can give you a firm plan or timeline, I need a sample export from your Transport Book account. This document gives you:

1. The exact information I need from you about Transport Book (§1)
2. The complete QORVENA target schema per entity (§2)
3. A proposed **read-only historical archive** approach vs full migration (§3) — my strong recommendation
4. Draft field-mapping template (§4) — will be finalized once I see Transport Book export
5. Duplicate detection & de-dup rules (§5)
6. Sample-migration workflow (§6)
7. Reversibility & backup plan (§7)
8. Open questions for you (§8)

---

## 1. What I Need From You About Transport Book

Please answer these before we go further. Even partial answers help.

### 1.1 Access & Export
- **A. What is the Transport Book export mechanism?** (tick whichever apply)
  - [ ] CSV export per module (Trips/Customers/etc.)
  - [ ] XLS/XLSX export
  - [ ] JSON export / API endpoint
  - [ ] Full database backup (SQL / .bak / .sql.gz)
  - [ ] PDF reports only
  - [ ] Screen scraping only (no export at all)
  - [ ] Something else — please describe

- **B. Do you still have login access to Transport Book?**
  - [ ] Yes, active subscription
  - [ ] Yes, read-only / expired
  - [ ] No — only have old exports/screenshots

- **C. Can you share a small sample export (5–10 records per module)?**
  - Preferred formats in order: CSV/XLSX > JSON > PDF > screenshots

### 1.2 Data Volume (approximate)
- Trips: __________ records (total across all years)
- Customers: __________
- Suppliers: __________
- Vehicles (own + supplier): __________
- Drivers: __________
- Invoices: __________
- Supplier Payments: __________
- Date range: from __________ to __________

### 1.3 Feature Coverage in Transport Book
Which of these does Transport Book actually track? (helps us know what mappings will be N/A)
- [ ] Halting charges
- [ ] Shortage / excess quantity
- [ ] Multi-trip GST invoices
- [ ] Customer Ref / Customer Invoice Number per trip
- [ ] Ship-To multiple sites per customer
- [ ] Supplier Freight (rate breakdown, not just total)
- [ ] Supplier Advance / Diesel-to-supplier
- [ ] Loading date vs Unloading date (2 dates per trip)
- [ ] Round-trip km × rate/km/ton mode
- [ ] Driver salary / batta ledger
- [ ] Vehicle documents (RC/FC/Insurance expiries)
- [ ] Receipt/document attachments per trip

### 1.4 Business Continuity
- Any Transport Book trips whose invoices/payments are **still active** (not yet fully settled)?
  If YES, we need to decide whether they carry over as live QORVENA data OR stay in the historical archive.

---

## 2. QORVENA Target Schema (Complete Field List)

This is the source of truth for what QORVENA can accept. Only fields listed here can be migrated.

### 2.1 Customer (`customers`)
| Field | Type | Notes |
|---|---|---|
| `id` | str (auto: `cust_...`) | Auto-generated. Original TB ID stored in `imported_ref`. |
| `name` | str, required | Match key for dedup |
| `address` | str | |
| `phone` | str | Match key for dedup |
| `email` | str | |
| `gstin` | str | Match key for dedup (if present) |
| `pan` | str | |
| `state` | str | |
| `pincode` | str | |
| `customer_code` | str | Short code (e.g. "ABC001") |
| `opening_balance` | float | Legacy dues carried forward |
| `advance_balance` | float | Legacy surplus |
| `notes` | str | Recommended: prepend "[Imported from Transport Book · ID: xxxxx]" |
| `ship_sites` | list | Empty by default; can be seeded from repeated to_locations |

### 2.2 Supplier (`suppliers`)
| Field | Type | Notes |
|---|---|---|
| `id` | str (auto: `sup_...`) | |
| `name` | str, required | Dedup key |
| `contact_person` | str | |
| `mobile` | str | Dedup key |
| `alt_mobile` | str | |
| `address`, `state`, `city` | str | |
| `gst_in`, `pan`, `msme_number` | str | |
| `bank_name`, `account_number`, `ifsc`, `branch` | str | |
| `payment_terms` | str | Free text |
| `opening_balance` | float | Historical payable/advance carried forward |
| `opening_balance_type` | `payable` \| `advance` | |
| `is_active` | bool | |

### 2.3 Vehicle (`vehicles`)
| Field | Type | Notes |
|---|---|---|
| `id` | str (auto: `veh_...`) | |
| `vehicle_number` | str, required | Dedup key (normalized) |
| `vehicle_type` | `own` \| `supplier` | Required |
| `owner_name`, `owner_phone` | str | For own |
| `supplier_id`, `supplier_name`, etc. | str | For supplier vehicles — MUST link to supplier |
| `make_model` | str | |
| `capacity_tons` | float | |
| `rc_expiry`, `fc_expiry`, `insurance_expiry`, `permit_expiry`, `puc_expiry` | str (ISO date) | |
| `is_active` | bool | |

### 2.4 Driver (`drivers`)
| Field | Type | Notes |
|---|---|---|
| `id` | str (auto: `drv_...`) | |
| `name` | str, required | Dedup key |
| `phone` | str | Dedup key |
| `license_number` | str | |
| `notes` | str | |

### 2.5 Trip (`trips`) — Largest / Most Complex
| Field | Type | Notes |
|---|---|---|
| `id` | str (auto: `trip_...`) | |
| `customer_id` | str, required | Must resolve to a Customer FIRST |
| `date` | str ISO | Required |
| `vehicle_number`, `vehicle_id`, `vehicle_type` | str | |
| `loading_date`, `unloading_date` | str ISO | Halting calc |
| `loaded_qty`, `unloaded_qty`, `shortage_qty`, `excess_qty` | float | |
| `shortage_amount`, `excess_amount` | float | Auto-calculated unless override |
| `total_halting_days`, `grace_days`, `chargeable_halting_days`, `halting_rate_per_day`, `halting_amount` | mixed | |
| `supplier_id`, `supplier_name`, `supplier_freight` | For supplier trips | |
| `supplier_freight_mode` | `per_ton` \| `fixed` | |
| `supplier_rate_per_ton`, `supplier_fixed_amount`, `supplier_advance`, `supplier_diesel` | float | |
| `driver_id`, `driver_name`, `driver_mobile` | str | |
| `load_details` | str | Default "Bitumen VG 40" |
| `hsn_sac` | str | Default "996791" |
| `customer_reference_number` | str | The field you asked for per-trip (Iter66/82/83/84/85) |
| `tons`, `from_location`, `to_location`, `from_pincode`, `to_pincode` | mixed | |
| `freight_mode` | `per_ton` \| `fixed` | Required |
| `rate_per_ton`, `fixed_amount`, `round_trip_kms`, `rate_per_km_per_ton`, `freight_amount` | float | |
| `expenses` | Expenses obj | diesel/toll/batta/repair/other |
| `status` | `pending` \| `invoiced` \| `settled` | Historical trips → likely `settled` |
| `notes` | str | Recommended prepend "[Imported · TB ID xxx]" |

### 2.6 Invoice (`invoices`)
| Field | Type | Notes |
|---|---|---|
| `id` | str (auto: `inv_...`) | |
| `invoice_number` | str | Preserve TB invoice number verbatim |
| `customer_id` | str | |
| `invoice_date`, `due_date` | str ISO | |
| `trip_ids` | list[str] | Must resolve to migrated trips |
| `subtotal`, `cgst`, `sgst`, `igst`, `total` | float | |
| `gst_treatment` | `rcm` \| `forward` \| `exempt` | |
| `payments` | list[Payment] | Historical partial payments |

### 2.7 SupplierPayment (`supplier_payments`)
| Field | Type | Notes |
|---|---|---|
| `id` | str (auto: `sp_...`) | |
| `supplier_id` | str | |
| `date` | str ISO | |
| `amount` | float | |
| `type` | `payment_out` \| `receipt_in` | |
| `mode` | Cash/Bank/UPI/IMPS/NEFT/RTGS/Cheque/Other | |
| `ref_no`, `remarks`, `trip_id`, `lr_number` | str | |
| `against` | `advance` \| `trip` \| `outstanding` \| `other` | |

---

## 3. 🌟 Recommended Approach: "Historical Archive" (Read-Only) vs "Full Live Merge"

**This is the single most important decision in the project. Two options:**

### Option A — Historical Archive (Read-Only) · **STRONGLY RECOMMENDED**
- Add a new field `imported_from: str = "transport_book"` and `imported_ref: str` (original TB ID) to every entity.
- Add `is_historical: bool = True` flag.
- Historical trips have `status = "archived_historical"` (new status, does NOT affect current settlements/ledgers/dues).
- Historical invoices/payments visible in **search + view + reports only**; they do NOT roll into current outstanding balance, dashboard KPIs, or supplier settlement.
- Historical Customers/Suppliers get flag `is_historical_only=True` — they show up in dropdowns but with a grey "📎 Historical" pill.
- **Reversible in one command:** `db.*.delete_many({"imported_from": "transport_book"})`.

**Pros:**
- Zero risk to live data
- Trivial rollback
- Historical data still searchable
- No risk of "why is my outstanding balance suddenly wrong?"

**Cons:**
- If a historical customer places a new order, we may end up with 2 customer records (historical + live). Solved by "Promote to live" button per record.

### Option B — Full Live Merge
- Historical trips merge into live tables with `status = "settled"` and appear in every calculation.
- Historical opening balances roll into `customer.opening_balance` / `supplier.opening_balance`.
- Riskier — a mismapping of `freight_amount` can throw off a whole year's P&L.

**My recommendation: Option A** for the initial migration. We can always "Promote to live" specific records later if you want them affecting current calculations.

---

## 4. Draft Field Mapping Template (to be finalized after seeing Transport Book export)

I've prefilled the QORVENA target column. The Transport Book source column will be filled once you share a sample export. Fields marked ❓ likely need business rules from you.

### 4.1 Trips
| Transport Book field | QORVENA field | Transform rule | Status |
|---|---|---|---|
| _(TBD)_ Trip Date | `date` | dd-mm-yyyy → ISO yyyy-mm-dd | ❓ |
| _(TBD)_ Vehicle No | `vehicle_number` | Uppercase + strip spaces | ❓ |
| _(TBD)_ Customer Name | `customer_id` | Resolve to migrated Customer.id | ❓ |
| _(TBD)_ From Location | `from_location` | Direct | ❓ |
| _(TBD)_ To Location | `to_location` | Direct | ❓ |
| _(TBD)_ Tonnage | `tons` | Direct | ❓ |
| _(TBD)_ Rate | `rate_per_ton` | If TB has rate_per_km, use `rate_per_km_per_ton` instead | ❓ |
| _(TBD)_ Freight Amount | `freight_amount` | Direct | ❓ |
| _(TBD)_ Customer Invoice No | `customer_reference_number` | Direct | ❓ |
| _(TBD)_ Diesel/Toll/Batta/Repair | `expenses.*` | Sum other → `expenses.other` | ❓ |
| _(TBD)_ Halting Amount | `halting_amount` | + `halting_amount_override = True` | ❓ |
| _(TBD)_ Shortage | `shortage_amount` | + `shortage_amount_override = True` | ❓ |
| _(N/A likely)_ Ship-To Site | `ship_site_id` | Requires master data mapping | ⚠️ likely blank |
| _(N/A likely)_ Loading vs Unloading date | `loading_date`, `unloading_date` | If TB has only 1 date, default both = `date` | ⚠️ likely blank |
| — | `imported_from` | Static: `"transport_book"` | ✅ |
| — | `imported_ref` | TB internal ID | ✅ |
| — | `is_historical` | Static: `True` | ✅ |
| — | `status` | Static: `"archived_historical"` | ✅ |

### 4.2 Customers — mapping template similarly extends for every entity
_(Full templates for Customers, Suppliers, Vehicles, Drivers, Invoices, Supplier Payments will be prepared once you confirm the Transport Book export columns.)_

---

## 5. Duplicate Detection Rules

Before insert, we run a dedup check against existing QORVENA masters:

| Entity | Primary dedup key | Secondary tie-breakers |
|---|---|---|
| Customer | `gstin` (case-insensitive) if present | else `phone` normalized, else fuzzy `name` (Levenshtein < 3) |
| Supplier | `gst_in` if present | else `mobile` normalized, else fuzzy `name` |
| Vehicle | `vehicle_number` (uppercase + strip whitespace + hyphens) | Exact match only |
| Driver | `phone` normalized | else `license_number`, else fuzzy `name` |
| Invoice | `invoice_number` per `customer_id` | Exact match — reject import if collision |

**On duplicate detected:**
- Option a) Merge into existing QORVENA record + append historical trips to it
- Option b) Create a separate `[HIST]` prefix record and keep them side-by-side
- **Recommended:** Option (a) for Customer/Supplier/Vehicle/Driver (masters), Option (b) for Invoice (avoids number collision)

---

## 6. Sample Migration Workflow (5–10 records first)

1. You share a sample Transport Book export (CSV/XLSX preferred)
2. I generate `/app/backend/migrations/transport_book_import.py` — a **dry-run** script that:
   - Reads the export
   - Runs dedup checks
   - Produces a JSON report: `will_insert`, `will_skip_duplicate`, `will_fail_validation`
   - Writes NOTHING to DB
3. We review the report together
4. You approve → I run with `--sample-size=10` on a scratch tenant
5. You verify the 10 imported records in QORVENA UI
6. You approve → full migration on a **fresh DB backup**

---

## 7. Reversibility & Backup Plan

Before ANY write to production DB:

1. **Full mongodump backup**: `mongodump --uri="$MONGO_URL" --db=qorvena --out=/backups/pre-migration-YYYY-MM-DD/`
2. Backup saved to Emergent Object Storage with 90-day retention
3. Migration script writes an audit log: `/app/backend/migrations/logs/transport_book_YYYY-MM-DD.log`
4. **Rollback command available at any time:**
   ```
   db.trips.delete_many({"imported_from": "transport_book", "imported_batch": "<batch_id>"})
   db.customers.delete_many({...})
   ...
   ```
5. Each migration run is tagged with a `imported_batch = "tb_YYYYMMDD_HHMMSS"` so we can roll back a specific batch without affecting the rest.

---

## 8. Open Questions for You

Please answer these when convenient:

1. **What is the Transport Book export mechanism?** (See §1.1 checklist)
2. **Approximate data volume?** (See §1.2)
3. **Which features does Transport Book actually track?** (See §1.3)
4. **Are you OK with Option A (Historical Archive · Read-Only)?** — my strong recommendation
5. **Any Transport Book trips still open/uninvoiced/unsettled** that need to carry into live QORVENA?
6. **Do you want historical invoice numbers preserved verbatim** even if they clash with QORVENA's `INV/YY-YY/####` sequence?
7. **How far back do you want to go?** All records, last 3 years, last 5 years?
8. **What should happen to Transport Book document attachments** (LR photos, receipts)?
   - Copy into Emergent Object Storage under `historical/`?
   - Skip and keep in Transport Book?
9. **Access approval**: Are you able to give me one sample export file (CSV/XLSX) via file upload to this chat so we can build the mapper?

---

## 9. Next Steps

- **You:** Answer §1 and §8, share a sample Transport Book export
- **Me:** Finalize field mapping (§4), build the dry-run migration script, produce a JSON preview report
- **You:** Review + approve
- **Me:** Sample import (5–10 records) on scratch data
- **You:** Verify + approve
- **Me:** Take DB backup → full migration → verify → hand back

Do NOT approve the actual migration until you have seen the dry-run JSON report and the sample import passes your visual check.

---

## 10. Estimated Effort (once export format is confirmed)

| Stage | Effort |
|---|---|
| Field mapping finalization | 0.5 day |
| Migration script (masters: Customer/Supplier/Vehicle/Driver) | 1 day |
| Migration script (Trips + Invoices + Payments) | 1.5 days |
| Dry-run + report generation | 0.5 day |
| Sample import + verification | 0.5 day |
| Full migration + verification + backup | 0.5 day |
| **Total (assuming clean CSV/XLSX export)** | **~4 days build + your verification time** |

If Transport Book only offers PDF/screen-scrape → add 3–5 extra days for a scraper, and quality of mapped data drops significantly.

---

**End of Feasibility Report · Awaiting your answers to §8 to proceed.**
