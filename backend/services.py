"""Business-logic helpers shared across routers.

- _compute_trip: derive freight, halting, shortage, excess, supplier settlement
- _trip_billable: sum of amounts a trip contributes to an invoice
- _recompute_invoice: rebuild GST + totals when an invoice's trips change
- _next_invoice_number / _next_lr_number: per-company running sequences
- _state_code / _gstin_checksum / gstin_state_from_prefix: offline GST helpers
- _in_range: inclusive date-string filter
- _vehicle_expiry_stats: attach days-to-expiry alerts to a vehicle
"""
from typing import Optional
from fastapi import HTTPException
import re
from datetime import datetime, timezone
from db import db
from models import Trip, Invoice, now_utc


def _compute_trip(t: Trip) -> Trip:
    if t.freight_mode == "per_ton":
        t.freight_amount = round(t.tons * t.rate_per_ton, 2)
    else:
        if t.round_trip_kms > 0 and t.rate_per_km_per_ton > 0:
            t.freight_amount = round(t.tons * t.round_trip_kms * t.rate_per_km_per_ton, 2)
        else:
            t.freight_amount = round(t.fixed_amount, 2)
    # ---- Loading / Unloading auto-diff ----
    diff = round((t.loaded_qty or 0) - (t.unloaded_qty or 0), 3)
    if t.loaded_qty > 0 or t.unloaded_qty > 0:
        if diff > 0:
            t.shortage_qty = diff
            t.excess_qty = 0.0
        elif diff < 0:
            t.excess_qty = round(-diff, 3)
            t.shortage_qty = 0.0
        else:
            t.shortage_qty = 0.0
            t.excess_qty = 0.0
    # Product-rate valuation for shortage / excess (editable via override flags)
    rate = t.product_rate_per_mt or 0
    if not t.shortage_amount_override:
        t.shortage_amount = round(rate * t.shortage_qty, 2)
    if not t.excess_amount_override:
        t.excess_amount = round(rate * t.excess_qty, 2)
    # ---- Halting / Waiting Charges auto-calc ----
    if t.loading_date and t.unloading_date:
        try:
            _ld = datetime.fromisoformat(t.loading_date).date()
            _ud = datetime.fromisoformat(t.unloading_date).date()
            t.total_halting_days = max((_ud - _ld).days, 0)
        except Exception:
            t.total_halting_days = 0
    else:
        t.total_halting_days = 0
    _grace = max(int(t.grace_days or 0), 0)
    # Only auto-set chargeable days if not manually diverged from formula
    _auto_chargeable = max(t.total_halting_days - _grace, 0)
    # If user hasn't customised (override marker via halting_amount_override implies manual)
    if not t.halting_amount_override:
        t.chargeable_halting_days = _auto_chargeable
        t.halting_amount = round(t.chargeable_halting_days * (t.halting_rate_per_day or 0), 2)
    e = t.expenses
    # Auto-compute diesel from customer amount
    if e.diesel_from_customer_qty > 0 and e.diesel_from_customer_rate > 0 and e.diesel_from_customer_amount == 0:
        e.diesel_from_customer_amount = round(e.diesel_from_customer_qty * e.diesel_from_customer_rate, 2)
    # Own expense base
    own_expense = e.diesel + e.toll + e.batta + e.repair + e.other + e.firewood
    # Diesel recovery reduces our cost (but never below 0)
    own_expense_net = max(own_expense - e.diesel_from_customer_amount, 0)
    if t.vehicle_type == "supplier":
        # Auto-compute supplier freight from detailed inputs when available
        sup_qty = t.supplier_quantity if t.supplier_quantity > 0 else t.tons
        if t.supplier_freight_mode == "per_ton" and t.supplier_rate_per_ton > 0:
            t.supplier_freight = round(sup_qty * t.supplier_rate_per_ton, 2)
        elif t.supplier_freight_mode == "fixed":
            if t.supplier_round_trip_kms > 0 and t.supplier_rate_per_km_per_ton > 0:
                t.supplier_freight = round(sup_qty * t.supplier_round_trip_kms * t.supplier_rate_per_km_per_ton, 2)
            elif t.supplier_fixed_amount > 0:
                t.supplier_freight = round(t.supplier_fixed_amount, 2)
        # else keep manually entered supplier_freight
        # Net payable = freight − advance − diesel − shortage − other_recoveries + other_income
        t.supplier_net_payable = round(
            t.supplier_freight
            - t.supplier_advance
            - t.supplier_diesel
            - t.supplier_shortage_deduction
            - t.supplier_other_recoveries
            + t.supplier_other_income,
            2,
        )
        # Profit formula: Customer Freight − (Supplier Freight − Advance − Diesel − Shortage + OtherIncome − OtherRecoveries)
        # Simpler: profit = customer_billable − supplier_net_payable
        t.total_expense = round(t.supplier_net_payable, 2)
    else:
        t.total_expense = round(own_expense_net, 2)
        t.supplier_net_payable = 0.0
    # Billable freight to customer = freight + halting + excess − shortage
    # (shortage is a customer deduction from our freight; excess bonus optional add-on)
    billable = t.freight_amount + t.halting_amount + t.excess_amount - t.shortage_amount - e.shortage_amount
    t.profit = round(billable - t.total_expense, 2)
    t.net_settlement = round(billable - t.total_expense - e.cash_advance_received, 2)
    return t

def _trip_billable(t: dict) -> float:
    """Billable freight to customer for invoicing.
    = Freight + Halting + Excess − Shortage − Diesel-from-Customer − Advance-from-Customer.
    Diesel & Advance are customer-side reimbursements: the customer already paid
    (or funded) these amounts, so they must be netted off the invoice total."""
    e = t.get("expenses") or {}
    return round(
        float(t.get("freight_amount", 0))
        + float(t.get("halting_amount", 0))
        + float(t.get("excess_amount", 0))
        - float(t.get("shortage_amount", 0))
        - float(e.get("shortage_amount", 0))
        - float(e.get("diesel_from_customer_amount", 0))
        - float(e.get("cash_advance_received", 0)),
        2,
    )



async def _recompute_invoice(iid: str, user):
    inv = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        return
    trips = await db.trips.find({"user_id": user["user_id"], "id": {"$in": inv.get("trip_ids", [])}}, {"_id": 0}).to_list(500)
    freight_total = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    halting_total = round(sum(t.get("halting_amount", 0.0) for t in trips), 2)
    excess_total = round(sum(t.get("excess_amount", 0.0) for t in trips), 2)
    shortage_total = round(
        sum(t.get("shortage_amount", 0.0) + (t.get("expenses") or {}).get("shortage_amount", 0.0) for t in trips), 2,
    )
    diesel_deduction_total = round(sum((t.get("expenses") or {}).get("diesel_from_customer_amount", 0.0) for t in trips), 2)
    advance_deduction_total = round(sum((t.get("expenses") or {}).get("cash_advance_received", 0.0) for t in trips), 2)
    subtotal = round(sum(_trip_billable(t) for t in trips), 2)
    # Auto GST re-evaluation on edit (customer/company state may have changed)
    inv_company_id = inv.get("company_id", "")
    customer_doc = await db.customers.find_one({"id": inv.get("customer_id"), "user_id": user["user_id"]}, {"_id": 0}) or {}
    company_doc = await db.companies.find_one({"id": inv_company_id, "user_id": user["user_id"]}, {"_id": 0}) if inv_company_id else None
    company_doc = company_doc or await db.companies.find_one({"user_id": user["user_id"], "is_default": True}, {"_id": 0}) or {}
    home_state = (company_doc.get("state") or "").strip().lower()
    cust_state = (customer_doc.get("state") or "").strip().lower()
    if home_state and cust_state:
        gst_type = "cgst_sgst" if home_state == cust_state else "igst"
    else:
        gst_type = inv.get("gst_type", "cgst_sgst")
    cgst = round(subtotal * 2.5 / 100, 2) if gst_type == "cgst_sgst" else 0.0
    sgst = round(subtotal * 2.5 / 100, 2) if gst_type == "cgst_sgst" else 0.0
    igst = round(subtotal * 5.0 / 100, 2) if gst_type == "igst" else 0.0
    total_tax = round(cgst + sgst + igst, 2)
    gross_total = round(subtotal if inv.get("rcm") else subtotal + total_tax, 2)
    final_amount = float(int(gross_total + 0.5)) if gross_total >= 0 else -float(int(-gross_total + 0.5))
    round_off = round(final_amount - gross_total, 2)
    total_amount = final_amount
    amount_paid = round(sum(p["amount"] for p in inv.get("payments", [])), 2)
    balance_due = round(total_amount - amount_paid, 2)
    await db.invoices.update_one(
        {"id": iid, "user_id": user["user_id"]},
        {"$set": {"subtotal": subtotal, "freight_total": freight_total, "halting_total": halting_total,
                  "excess_total": excess_total, "shortage_total": shortage_total,
                  "diesel_deduction_total": diesel_deduction_total,
                  "advance_deduction_total": advance_deduction_total,
                  "gst_type": gst_type,
                  "cgst_amount": cgst, "sgst_amount": sgst, "igst_amount": igst,
                  "total_tax": total_tax, "gross_total": gross_total, "round_off": round_off,
                  "total_amount": total_amount,
                  "amount_paid": amount_paid, "balance_due": balance_due}},
    )

# ==================== Invoices ====================


async def _next_invoice_number(user_id: str) -> str:
    company = await db.companies.find_one({"user_id": user_id}, {"_id": 0})
    prefix = "INV"
    seq = 1
    if company:
        prefix = company.get("invoice_prefix") or "INV"
        seq = int(company.get("next_invoice_number") or 1)
    fy = now_utc()
    yr = fy.year % 100
    yr_next = (fy.year + 1) % 100
    fy_str = f"{yr:02d}-{yr_next:02d}" if fy.month >= 4 else f"{yr-1:02d}-{yr:02d}"
    num = f"{prefix}/{fy_str}/{seq:04d}"
    await db.companies.update_one(
        {"user_id": user_id},
        {"$set": {"next_invoice_number": seq + 1}},
        upsert=True,
    )
    return num

async def _next_invoice_number_for_company(company_id: str, user_id: str) -> str:
    """Generate next invoice number scoped to a specific company (multi-company)."""
    company = await db.companies.find_one({"id": company_id, "user_id": user_id}, {"_id": 0})
    prefix = "INV"
    seq = 1
    if company:
        prefix = company.get("invoice_prefix") or "INV"
        seq = int(company.get("next_invoice_number") or 1)
    fy = now_utc()
    yr = fy.year % 100
    yr_next = (fy.year + 1) % 100
    fy_str = f"{yr:02d}-{yr_next:02d}" if fy.month >= 4 else f"{yr-1:02d}-{yr:02d}"
    num = f"{prefix}/{fy_str}/{seq:04d}"
    await db.companies.update_one(
        {"id": company_id, "user_id": user_id},
        {"$set": {"next_invoice_number": seq + 1}},
    )
    return num



def _in_range(date_str: str, start: Optional[str], end: Optional[str]) -> bool:
    if not date_str:
        return False
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True



def _vehicle_expiry_stats(v: dict) -> dict:
    today = now_utc().date()
    fields = ["rc_expiry", "fc_expiry", "insurance_expiry", "permit_expiry", "puc_expiry"]
    v["alerts"] = {}
    soonest = None
    for f in fields:
        val = v.get(f) or ""
        if not val:
            continue
        try:
            d = datetime.fromisoformat(val).date()
            days = (d - today).days
            status = "expired" if days < 0 else ("expiring" if days <= 30 else "ok")
            v["alerts"][f] = {"date": val, "days": days, "status": status}
            if soonest is None or days < soonest:
                soonest = days
        except Exception:
            continue
    v["soonest_days"] = soonest
    return v



# Indian state → GST state code (2-digit)
STATE_CODES = {
    "andhra pradesh": "37", "andaman and nicobar islands": "35", "arunachal pradesh": "12",
    "assam": "18", "bihar": "10", "chandigarh": "04", "chhattisgarh": "22",
    "dadra and nagar haveli and daman and diu": "26", "delhi": "07", "goa": "30",
    "gujarat": "24", "haryana": "06", "himachal pradesh": "02", "jammu and kashmir": "01",
    "jharkhand": "20", "karnataka": "29", "kerala": "32", "ladakh": "38",
    "lakshadweep": "31", "madhya pradesh": "23", "maharashtra": "27", "manipur": "14",
    "meghalaya": "17", "mizoram": "15", "nagaland": "13", "odisha": "21",
    "puducherry": "34", "punjab": "03", "rajasthan": "08", "sikkim": "11",
    "tamil nadu": "33", "telangana": "36", "tripura": "16", "uttar pradesh": "09",
    "uttarakhand": "05", "west bengal": "19",
}

def _state_code(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    return STATE_CODES.get(key, "")

# Reverse map: 2-digit GST state code → canonical state name
STATE_CODE_TO_NAME = {v: k.title().replace("And ", "and ").replace("Of ", "of ") for k, v in STATE_CODES.items()}
# Manual title-case tweaks (union territories / compound names)
STATE_CODE_TO_NAME["07"] = "Delhi"
STATE_CODE_TO_NAME["35"] = "Andaman and Nicobar Islands"
STATE_CODE_TO_NAME["26"] = "Dadra and Nagar Haveli and Daman and Diu"
STATE_CODE_TO_NAME["01"] = "Jammu and Kashmir"
STATE_CODE_TO_NAME["37"] = "Andhra Pradesh"
STATE_CODE_TO_NAME["36"] = "Telangana"

# ==================== GSTIN Lookup (offline structure parse) ====================

# GSTIN format: 15 chars = <2-digit state><10-char PAN><1 entity><'Z'><1 checksum>
_GSTIN_RE = re.compile(r"^([0-9]{2})([A-Z]{5}[0-9]{4}[A-Z])([0-9A-Z])(Z)([0-9A-Z])$")
_GSTIN_CHECK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def _gstin_checksum(gstin14: str) -> str:
    """Compute the 15th checksum char of a GSTIN using the standard algorithm."""
    total = 0
    for idx, ch in enumerate(gstin14):
        v = _GSTIN_CHECK_ALPHABET.index(ch)
        factor = 2 if idx % 2 else 1
        prod = v * factor
        total += (prod // 36) + (prod % 36)
    remainder = total % 36
    return _GSTIN_CHECK_ALPHABET[(36 - remainder) % 36]



def _state_code(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    return STATE_CODES.get(key, "")

# Reverse map: 2-digit GST state code → canonical state name
STATE_CODE_TO_NAME = {v: k.title().replace("And ", "and ").replace("Of ", "of ") for k, v in STATE_CODES.items()}
# Manual title-case tweaks (union territories / compound names)
STATE_CODE_TO_NAME["07"] = "Delhi"
STATE_CODE_TO_NAME["35"] = "Andaman and Nicobar Islands"
STATE_CODE_TO_NAME["26"] = "Dadra and Nagar Haveli and Daman and Diu"
STATE_CODE_TO_NAME["01"] = "Jammu and Kashmir"
STATE_CODE_TO_NAME["37"] = "Andhra Pradesh"
STATE_CODE_TO_NAME["36"] = "Telangana"

# ==================== GSTIN Lookup (offline structure parse) ====================

# GSTIN format: 15 chars = <2-digit state><10-char PAN><1 entity><'Z'><1 checksum>
_GSTIN_RE = re.compile(r"^([0-9]{2})([A-Z]{5}[0-9]{4}[A-Z])([0-9A-Z])(Z)([0-9A-Z])$")
_GSTIN_CHECK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def _gstin_checksum(gstin14: str) -> str:
    """Compute the 15th checksum char of a GSTIN using the standard algorithm."""
    total = 0
    for idx, ch in enumerate(gstin14):
        v = _GSTIN_CHECK_ALPHABET.index(ch)
        factor = 2 if idx % 2 else 1
        prod = v * factor
        total += (prod // 36) + (prod % 36)
    remainder = total % 36
    return _GSTIN_CHECK_ALPHABET[(36 - remainder) % 36]



async def _next_lr_number(user_id: str, company_id: str = "") -> str:
    q = {"user_id": user_id, "id": company_id} if company_id else {"user_id": user_id, "is_default": True}
    company = await db.companies.find_one(q, {"_id": 0})
    if not company and company_id:
        company = await db.companies.find_one({"user_id": user_id, "id": company_id}, {"_id": 0})
    prefix = "LR"
    seq = 1
    if company:
        prefix = company.get("lr_prefix") or "LR"
        seq = int(company.get("next_lr_number") or 1)
    fy = now_utc()
    yr = fy.year % 100
    yr_next = (fy.year + 1) % 100
    fy_str = f"{yr:02d}-{yr_next:02d}" if fy.month >= 4 else f"{yr-1:02d}-{yr:02d}"
    num = f"{prefix}/{fy_str}/{seq:05d}"
    match_q = {"user_id": user_id, "id": company["id"]} if company and company.get("id") else {"user_id": user_id}
    await db.companies.update_one(
        match_q,
        {"$set": {"next_lr_number": seq + 1}},
        upsert=False,
    )
    return num

