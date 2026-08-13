from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64

from db import db
from models import (
    Company, Customer, Expenses, Driver, Trip, Product, Party, Vehicle,
    MaintenanceLog, Fuel, Payment, Invoice, TeamMember, ROLE_PERMISSIONS,
    InvoiceCreateRequest, InvoiceUpdateRequest, PaymentAdd, FileRef, AuditLog,
    now_utc, new_id,
)
from auth import get_current_user, _has_perm, require_perm
from company import (
    _active_company_id, _get_or_create_default_company,
    _backfill_company_id, _backfill_to_default,
)
from audit import _log_audit, _diff_dict
from services import (
    _compute_trip, _trip_billable, _recompute_invoice,
    _next_invoice_number, _next_invoice_number_for_company,
    _next_lr_number, _in_range, _vehicle_expiry_stats,
    _state_code, _gstin_checksum,
)

router = APIRouter(prefix="/api")

from pdf import build_ledger_pdf

@router.get("/reports/ledger")
async def report_ledger(
    request: Request,
    customer_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    customer = await db.customers.find_one({"id": customer_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    invoices = await db.invoices.find({"user_id": uid, "company_id": cid, "customer_id": customer_id}, {"_id": 0, "user_id": 0}).to_list(2000)

    # Build entries: invoice (debit), payment (credit)
    entries = []
    for inv in invoices:
        idt = inv.get("invoice_date", "")
        if _in_range(idt, start, end):
            entries.append({
                "date": idt,
                "type": "invoice",
                "reference": inv["invoice_number"],
                "particulars": f"Sales - {len(inv['trip_ids'])} trip(s)",
                "debit": inv["total_amount"],
                "credit": 0.0,
                "invoice_id": inv["id"],
            })
        for p in inv.get("payments", []):
            pdt = p.get("date", "")
            if _in_range(pdt, start, end):
                entries.append({
                    "date": pdt,
                    "type": "payment",
                    "reference": inv["invoice_number"],
                    "particulars": f"Payment received ({p.get('mode','Cash')}) - {p.get('note','')}".strip(" -"),
                    "debit": 0.0,
                    "credit": p["amount"],
                    "invoice_id": inv["id"],
                })

    # Sort by date, then type (invoice before payment on same day)
    entries.sort(key=lambda x: (x["date"], 0 if x["type"] == "invoice" else 1))

    # Opening balance = balances before 'start'
    opening = 0.0
    if start:
        for inv in invoices:
            if inv.get("invoice_date", "") < start:
                opening += inv["total_amount"]
            for p in inv.get("payments", []):
                if p.get("date", "") < start:
                    opening -= p["amount"]

    running = opening
    for e in entries:
        running = round(running + e["debit"] - e["credit"], 2)
        e["balance"] = running

    total_debit = round(sum(e["debit"] for e in entries), 2)
    total_credit = round(sum(e["credit"] for e in entries), 2)
    closing = round(opening + total_debit - total_credit, 2)

    return {
        "customer": {k: customer.get(k, "") for k in ["id", "name", "gstin", "phone", "address", "state"]},
        "period": {"start": start, "end": end},
        "opening_balance": round(opening, 2),
        "entries": entries,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "closing_balance": closing,
    }

@router.get("/reports/ledger/pdf")
async def report_ledger_pdf(
    request: Request,
    customer_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    ledger = await report_ledger(request=request, customer_id=customer_id, start=start, end=end, user=user)
    cid = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}
    pdf_bytes = build_ledger_pdf(company, ledger)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="ledger_{ledger["customer"]["name"].replace(" ", "_")}.pdf"'},
    )

@router.get("/reports/pl")
async def report_profit_loss(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(5000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]

    freight_revenue = round(sum(t.get("freight_amount", 0) for t in trips), 2)
    halting_revenue = round(sum(t.get("halting_amount", 0) for t in trips), 2)
    excess_revenue = round(sum(t.get("excess_amount", 0) for t in trips), 2)
    shortage_deduction = round(
        sum(t.get("shortage_amount", 0) + (t.get("expenses") or {}).get("shortage_amount", 0) for t in trips), 2,
    )
    revenue = round(freight_revenue + halting_revenue + excess_revenue - shortage_deduction, 2)
    diesel = round(sum((t.get("expenses") or {}).get("diesel", 0) for t in trips), 2)
    toll = round(sum((t.get("expenses") or {}).get("toll", 0) for t in trips), 2)
    batta = round(sum((t.get("expenses") or {}).get("batta", 0) for t in trips), 2)
    repair = round(sum((t.get("expenses") or {}).get("repair", 0) for t in trips), 2)
    other = round(sum((t.get("expenses") or {}).get("other", 0) for t in trips), 2)
    supplier_cost = round(sum(t.get("total_expense", 0) if t.get("vehicle_type") == "supplier" else 0 for t in trips), 2)
    total_expense = round(sum(t.get("total_expense", 0) for t in trips), 2)
    net_profit = round(revenue - total_expense, 2)
    margin = round((net_profit / revenue * 100.0), 2) if revenue > 0 else 0.0

    # Per-customer breakdown
    customers = await db.customers.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(2000)
    cmap = {c["id"]: c.get("name", "Unknown") for c in customers}
    per_customer = {}
    for t in trips:
        cust_id = t.get("customer_id")
        b = per_customer.setdefault(cust_id, {"customer_id": cust_id, "customer_name": cmap.get(cust_id, "Unknown"), "trips": 0, "revenue": 0.0, "expense": 0.0, "profit": 0.0, "tons": 0.0})
        b["trips"] += 1
        billable = float(t.get("freight_amount", 0)) + float(t.get("halting_amount", 0)) + float(t.get("excess_amount", 0)) - float(t.get("shortage_amount", 0)) - float((t.get("expenses") or {}).get("shortage_amount", 0))
        b["revenue"] += billable
        b["expense"] += t.get("total_expense", 0)
        b["profit"] += t.get("profit", 0)
        b["tons"] += t.get("tons", 0)
    for b in per_customer.values():
        for k in ("revenue", "expense", "profit", "tons"):
            b[k] = round(b[k], 2)

    return {
        "period": {"start": start, "end": end},
        "trip_count": len(trips),
        "revenue": revenue,
        "freight_revenue": freight_revenue,
        "halting_revenue": halting_revenue,
        "excess_revenue": excess_revenue,
        "shortage_deduction": shortage_deduction,
        "expenses": {
            "diesel": diesel, "toll": toll, "batta": batta, "repair": repair, "other": other,
            "supplier_net_payable": supplier_cost,
            "total": total_expense,
        },
        "net_profit": net_profit,
        "margin_pct": margin,
        "per_customer": sorted(per_customer.values(), key=lambda x: -x["revenue"]),
    }

@router.get("/reports/balance-sheet")
async def report_balance_sheet(
    request: Request,
    as_of: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    as_of = as_of or now_utc().date().isoformat()
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(5000)
    invoices = await db.invoices.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(2000)

    # Cumulative net profit up to as_of (from trips dated <= as_of)
    trips_todate = [t for t in trips if t.get("date", "") <= as_of]
    revenue = sum(t.get("freight_amount", 0) for t in trips_todate)
    expenses = sum(t.get("total_expense", 0) for t in trips_todate)
    net_profit = round(revenue - expenses, 2)

    # Cash & Bank (approximate) = total payments received up to as_of
    cash_bank = 0.0
    receivables = 0.0
    payments_by_customer = {}
    for inv in invoices:
        if inv.get("invoice_date", "") <= as_of:
            billed = inv.get("total_amount", 0)
            paid_upto = sum(p["amount"] for p in inv.get("payments", []) if p.get("date", "") <= as_of)
            cash_bank += paid_upto
            receivables += max(billed - paid_upto, 0)

    total_assets = round(cash_bank + receivables, 2)

    # Simplified: Owner's equity balances the sheet
    owners_equity = total_assets  # balance-plug for zero liabilities

    return {
        "as_of": as_of,
        "assets": {
            "cash_and_bank": round(cash_bank, 2),
            "sundry_debtors": round(receivables, 2),
            "total": total_assets,
        },
        "liabilities": {
            "current_liabilities": 0.0,
            "total": 0.0,
        },
        "equity": {
            "retained_earnings": net_profit,
            "owners_capital": round(owners_equity - net_profit, 2),
            "total": round(owners_equity, 2),
        },
        "note": "Simplified statement. Balance-plug on Owner's Capital. Add loans / opening capital in future for full balance sheet.",
    }

# ==================== Vehicles ====================


@router.get("/reports/supplier-pl")
async def report_supplier_pl(request: Request, start: Optional[str] = None, end: Optional[str] = None, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid, "vehicle_type": "supplier"}, {"_id": 0, "user_id": 0}).to_list(5000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]
    by = {}
    for t in trips:
        name = (t.get("supplier_name") or "—").strip() or "—"
        s = by.setdefault(name, {"supplier_name": name, "trips": 0, "tons": 0.0, "customer_freight": 0.0,
                                  "supplier_freight": 0.0, "supplier_advance": 0.0, "supplier_other_recoveries": 0.0,
                                  "net_payable": 0.0, "profit": 0.0, "margin_pct": 0.0})
        s["trips"] += 1
        s["tons"] += float(t.get("tons", 0))
        s["customer_freight"] += float(t.get("freight_amount", 0))
        s["supplier_freight"] += float(t.get("supplier_freight", 0))
        s["supplier_advance"] += float(t.get("supplier_advance", 0))
        s["supplier_other_recoveries"] += float(t.get("supplier_other_recoveries", 0))
    total = {"trips": 0, "tons": 0.0, "customer_freight": 0.0, "supplier_freight": 0.0,
             "supplier_advance": 0.0, "supplier_other_recoveries": 0.0, "net_payable": 0.0, "profit": 0.0}
    for s in by.values():
        s["net_payable"] = round(s["supplier_freight"] - s["supplier_advance"] - s["supplier_other_recoveries"], 2)
        # Profit = Customer Freight - (Supplier Freight - Supplier Advance)
        s["profit"] = round(s["customer_freight"] - (s["supplier_freight"] - s["supplier_advance"]), 2)
        s["margin_pct"] = round((s["profit"] / s["customer_freight"] * 100.0), 2) if s["customer_freight"] > 0 else 0.0
        for k in ("tons", "customer_freight", "supplier_freight", "supplier_advance", "supplier_other_recoveries"):
            s[k] = round(s[k], 2)
        total["trips"] += s["trips"]; total["tons"] += s["tons"]
        total["customer_freight"] += s["customer_freight"]; total["supplier_freight"] += s["supplier_freight"]
        total["supplier_advance"] += s["supplier_advance"]; total["supplier_other_recoveries"] += s["supplier_other_recoveries"]
        total["net_payable"] += s["net_payable"]; total["profit"] += s["profit"]
    for k in ("tons", "customer_freight", "supplier_freight", "supplier_advance", "supplier_other_recoveries", "net_payable", "profit"):
        total[k] = round(total[k], 2)
    return {
        "period": {"start": start, "end": end},
        "suppliers": sorted(by.values(), key=lambda x: -x["profit"]),
        "totals": total,
    }

# ==================== Consignor / Consignee Master ====================



@router.get("/reports/halting")
async def report_halting(request: Request, start: Optional[str] = None, end: Optional[str] = None, user=Depends(get_current_user)):
    """Monthly / range summary of halting per customer.

    Response includes rows per customer with total trips, total halting days,
    chargeable halting days and halting revenue, plus overall totals.
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(10000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]
    customers = await db.customers.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(2000)
    cmap = {c["id"]: c.get("name", "Unknown") for c in customers}

    by = {}
    for t in trips:
        halt = float(t.get("halting_amount", 0) or 0)
        total_days = int(t.get("total_halting_days", 0) or 0)
        charge_days = int(t.get("chargeable_halting_days", 0) or 0)
        if halt <= 0 and charge_days == 0:
            continue
        cust_id = t.get("customer_id")
        b = by.setdefault(cust_id, {
            "customer_id": cust_id, "customer_name": cmap.get(cust_id, "Unknown"),
            "trips_with_halting": 0, "total_days": 0, "chargeable_days": 0,
            "halting_revenue": 0.0, "avg_rate": 0.0,
        })
        b["trips_with_halting"] += 1
        b["total_days"] += total_days
        b["chargeable_days"] += charge_days
        b["halting_revenue"] += halt
    total = {"trips_with_halting": 0, "total_days": 0, "chargeable_days": 0, "halting_revenue": 0.0}
    for b in by.values():
        b["halting_revenue"] = round(b["halting_revenue"], 2)
        b["avg_rate"] = round(b["halting_revenue"] / b["chargeable_days"], 2) if b["chargeable_days"] > 0 else 0.0
        for k in ("trips_with_halting", "total_days", "chargeable_days"):
            total[k] += b[k]
        total["halting_revenue"] += b["halting_revenue"]
    total["halting_revenue"] = round(total["halting_revenue"], 2)
    return {
        "period": {"start": start, "end": end},
        "customers": sorted(by.values(), key=lambda x: -x["halting_revenue"]),
        "totals": total,
    }

# ==================== GST Summary Widget ====================



@router.get("/reports/gst-summary")
async def report_gst_summary(request: Request, user=Depends(get_current_user)):
    """Compact GST breakup for the current month + current FY + next filing due date."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    today = now_utc().date()
    month_start = today.replace(day=1).isoformat()
    month_end = today.isoformat()
    # Financial year: Apr - Mar
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    fy_start = f"{fy_start_year:04d}-04-01"
    fy_end = f"{fy_start_year + 1:04d}-03-31"

    def _agg(rows):
        return {
            "invoices": len(rows),
            "taxable": round(sum(i.get("subtotal", 0) for i in rows), 2),
            "cgst": round(sum(i.get("cgst_amount", 0) for i in rows), 2),
            "sgst": round(sum(i.get("sgst_amount", 0) for i in rows), 2),
            "igst": round(sum(i.get("igst_amount", 0) for i in rows), 2),
            "total_tax": round(sum(i.get("total_tax", 0) for i in rows), 2),
            "total": round(sum(i.get("total_amount", 0) for i in rows), 2),
        }

    invoices = await db.invoices.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(10000)
    month_rows = [i for i in invoices if month_start <= i.get("invoice_date", "") <= month_end]
    fy_rows = [i for i in invoices if fy_start <= i.get("invoice_date", "") <= fy_end]

    # Next GSTR-1 filing date: 11th of following month
    y = today.year + (1 if today.month == 12 else 0)
    m = 1 if today.month == 12 else today.month + 1
    gstr1_due = f"{y:04d}-{m:02d}-11"
    # Next GSTR-3B: 20th of following month
    gstr3b_due = f"{y:04d}-{m:02d}-20"

    return {
        "current_month": {"start": month_start, "end": month_end, **_agg(month_rows)},
        "current_fy": {"start": fy_start, "end": fy_end, **_agg(fy_rows)},
        "next_gstr1_due": gstr1_due,
        "next_gstr3b_due": gstr3b_due,
    }

# ==================== Overdue Invoices — see /invoices/overdue defined above /invoices/{iid} ====================


# ==================== Supplier Statement (Iter41 + Iter44 expanded) ====================


@router.get("/reports/suppliers")
async def list_suppliers(request: Request, user=Depends(get_current_user)):
    """List unique supplier names for the active company — used in the
    Reports → Supplier Statement dropdown.
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    # From trip records
    trip_sups = await db.trips.distinct(
        "supplier_name",
        {"user_id": uid, "company_id": cid, "vehicle_type": "supplier"},
    )
    # And from vehicles master (in case a supplier is defined but no trip yet)
    veh_sups = await db.vehicles.distinct(
        "supplier_name",
        {"user_id": uid, "company_id": cid, "vehicle_type": "supplier"},
    )
    seen = set()
    result = []
    for name in (trip_sups + veh_sups):
        n = (name or "").strip()
        key = n.lower()
        if not n or key in seen:
            continue
        seen.add(key)
        # Find any mobile for the supplier
        mob = ""
        v = await db.vehicles.find_one(
            {"user_id": uid, "company_id": cid, "vehicle_type": "supplier",
             "supplier_name": {"$regex": f"^{n}$", "$options": "i"}},
            {"_id": 0, "supplier_mobile": 1, "owner_phone": 1},
        )
        if v:
            mob = (v.get("supplier_mobile") or v.get("owner_phone") or "").strip()
        result.append({"name": n, "mobile": mob})
    result.sort(key=lambda x: x["name"].lower())
    return result


async def _supplier_statement_data(request: Request, supplier_name: str, start, end, user):
    """Shared aggregation for JSON + PDF endpoints."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": cid, "user_id": uid}, {"_id": 0}) or {}
    trips = await db.trips.find(
        {"user_id": uid, "company_id": cid, "vehicle_type": "supplier"},
        {"_id": 0, "user_id": 0},
    ).to_list(10000)
    sn_lc = (supplier_name or "").strip().lower()
    trips = [t for t in trips if (t.get("supplier_name") or "").strip().lower() == sn_lc]
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]
    trips.sort(key=lambda t: (t.get("date", ""), t.get("created_at", "")))

    # Attach customer name per trip for the enriched view
    customer_ids = list({t.get("customer_id") for t in trips if t.get("customer_id")})
    customers = await db.customers.find(
        {"user_id": uid, "company_id": cid, "id": {"$in": customer_ids}}, {"_id": 0}
    ).to_list(2000)
    cmap = {c["id"]: c.get("name", "Unknown") for c in customers}

    # Supplier mobile
    supplier_mobile = ""
    v = await db.vehicles.find_one(
        {"user_id": uid, "company_id": cid, "vehicle_type": "supplier",
         "supplier_name": {"$regex": f"^{supplier_name}$", "$options": "i"}},
        {"_id": 0, "supplier_mobile": 1, "owner_phone": 1},
    )
    if v:
        supplier_mobile = (v.get("supplier_mobile") or v.get("owner_phone") or "").strip()

    def _num(x):
        try: return float(x or 0)
        except Exception: return 0.0

    trip_rows = []
    tot = {"trips": 0, "load_tons": 0.0, "unload_tons": 0.0,
           "distance": 0.0, "supplier_freight": 0.0, "supplier_advance": 0.0,
           "supplier_diesel": 0.0, "customer_diesel": 0.0,
           "supplier_shortage": 0.0, "supplier_recovery": 0.0,
           "supplier_income": 0.0, "halting": 0.0, "net_payable": 0.0,
           "customer_freight": 0.0}
    for t in trips:
        # Customer diesel adjustment — trip-level from receipts
        cust_diesel = round(sum(
            _num(r.get("amount")) for r in (t.get("customer_receipts") or [])
            if (r.get("type") or "").lower() == "diesel"
        ), 2)
        row = {
            "trip_id": t.get("id"),
            "date": t.get("date", ""),
            "lr_number": t.get("lr_number") or "",
            "vehicle_number": t.get("vehicle_number") or "",
            "customer_name": cmap.get(t.get("customer_id"), "Unknown"),
            "product": t.get("load_details") or t.get("product_type") or "",
            "from_location": t.get("from_location") or "",
            "to_location": t.get("to_location") or "",
            "loaded_qty": round(_num(t.get("tons") or t.get("loaded_qty")), 3),
            "unloaded_qty": round(_num(t.get("unloaded_qty")), 3),
            "shortage_qty": round(_num(t.get("shortage_qty")), 3),
            "excess_qty": round(_num(t.get("excess_qty")), 3),
            "distance_kms": round(_num(t.get("supplier_round_trip_kms") or t.get("round_trip_kms")), 2),
            "supplier_rate": round(_num(t.get("supplier_rate_per_ton")), 2),
            "supplier_freight": round(_num(t.get("supplier_freight")), 2),
            "supplier_advance": round(_num(t.get("supplier_advance")), 2),
            "supplier_diesel": round(_num(t.get("supplier_diesel")), 2),
            "customer_diesel": cust_diesel,
            "supplier_shortage_deduction": round(_num(t.get("supplier_shortage_deduction")), 2),
            "supplier_other_recoveries": round(_num(t.get("supplier_other_recoveries")), 2),
            "supplier_other_income": round(_num(t.get("supplier_other_income")), 2),
            "halting_amount": round(_num(t.get("halting_amount")), 2),
            "halting_days": int(t.get("chargeable_halting_days") or 0),
            "halting_rate": round(_num(t.get("halting_rate_per_day")), 2),
            "supplier_net_payable": round(_num(t.get("supplier_net_payable")), 2),
            "settlement_remarks": t.get("supplier_settlement_remarks") or "",
            "customer_freight": round(_num(t.get("freight_amount")), 2),
        }
        trip_rows.append(row)
        tot["trips"] += 1
        tot["load_tons"] += row["loaded_qty"]
        tot["unload_tons"] += row["unloaded_qty"]
        tot["distance"] += row["distance_kms"]
        tot["supplier_freight"] += row["supplier_freight"]
        tot["supplier_advance"] += row["supplier_advance"]
        tot["supplier_diesel"] += row["supplier_diesel"]
        tot["customer_diesel"] += row["customer_diesel"]
        tot["supplier_shortage"] += row["supplier_shortage_deduction"]
        tot["supplier_recovery"] += row["supplier_other_recoveries"]
        tot["supplier_income"] += row["supplier_other_income"]
        tot["halting"] += row["halting_amount"]
        tot["net_payable"] += row["supplier_net_payable"]
        tot["customer_freight"] += row["customer_freight"]

    for k, v in tot.items():
        if isinstance(v, float):
            tot[k] = round(v, 2)
    tot["profit"] = round(tot["customer_freight"] - tot["net_payable"], 2)
    tot["margin_pct"] = round((tot["profit"] / tot["customer_freight"] * 100.0) if tot["customer_freight"] > 0 else 0, 2)
    return {
        "supplier": {"name": supplier_name, "mobile": supplier_mobile},
        "company": {"id": company.get("id"), "name": company.get("name", ""),
                    "gst_in": company.get("gst_in", ""), "address": company.get("address", "")},
        "period": {"start": start, "end": end},
        "trips": trip_rows,
        "totals": tot,
    }


@router.get("/reports/supplier-statement")
async def supplier_statement_json(
    request: Request,
    supplier_name: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    opening_mode: str = "master",   # Iter47 Phase 3
    user=Depends(get_current_user),
):
    """JSON payload driving the Reports → Supplier Statement in-app View."""
    data = await _supplier_statement_data(request, supplier_name, start, end, user)
    # Iter47 Phase 3: attach the Deep Monthly Statement blocks (opening/closing)
    data["deep"] = await _supplier_deep_statement_blocks(request, supplier_name, start, end, opening_mode, user, data["totals"])
    return data


async def _supplier_deep_statement_blocks(request: Request, supplier_name: str, start, end, opening_mode, user, tot):
    """Iter47 Phase 3 — Compute Opening Balance + explicit Payments-in-period for the
    Deep Monthly Statement layout. Returns a dict with:
      opening_balance (float, +ve = payable/Dr, -ve = advance/Cr)
      opening_type    ("payable" | "advance")
      opening_source  ("master" | "carry_forward")
      payments_in_period (list of {date, mode, ref_no, amount})
      payments_out_total (float — money paid to supplier)
      payments_in_total  (float — money received back from supplier, rare)
      closing_balance (float, running: opening + movements)
      closing_type    ("payable" | "advance")
    All values in ₹."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    # Find the supplier master record by name (case-insensitive)
    sup = await db.suppliers.find_one(
        {"user_id": uid, "company_id": cid,
         "name": {"$regex": f"^{supplier_name}$", "$options": "i"}},
        {"_id": 0},
    )

    # 1. Opening balance
    opening = 0.0
    if sup:
        opening = float(sup.get("opening_balance") or 0.0)
        if sup.get("opening_balance_type") == "advance":
            opening = -opening

    if opening_mode == "carry_forward" and start and sup:
        # Compute closing as of (start - 1 day) by rebuilding the ledger up to that date
        try:
            from suppliers_ledger_helper import _build_ledger_upto  # optional shortcut
        except Exception:
            _build_ledger_upto = None
        # Use inline computation:
        prev_end = _iso_prev_day(start)
        opening = await _supplier_ledger_closing(uid, cid, sup["id"], prev_end)

    opening_type = "payable" if opening >= 0 else "advance"

    # 2. Payments in period
    pay_q = {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}
    if sup:
        pay_q["supplier_id"] = sup["id"]
    else:
        # No linked supplier — no payments
        pay_q["supplier_id"] = "__none__"
    pays_cursor = db.supplier_payments.find(pay_q, {"_id": 0, "user_id": 0}).sort("date", 1)
    payments_all = await pays_cursor.to_list(5000)
    payments_in_period = [p for p in payments_all if _in_range(p.get("date", ""), start, end)]
    payments_out_total = round(sum(float(p.get("amount", 0)) for p in payments_in_period if p.get("type", "payment_out") == "payment_out"), 2)
    payments_in_total = round(sum(float(p.get("amount", 0)) for p in payments_in_period if p.get("type") == "receipt_in"), 2)

    # 3. Movements in the current period (Debits + Credits)
    # Debits: supplier_freight + supplier_other_income + receipt_in
    # Credits: supplier_advance + supplier_diesel + customer_diesel + supplier_shortage + supplier_recovery + payments_out
    movements_debit = round(tot.get("supplier_freight", 0.0) + tot.get("supplier_income", 0.0) + payments_in_total, 2)
    movements_credit = round(
        tot.get("supplier_advance", 0.0) + tot.get("supplier_diesel", 0.0)
        + tot.get("customer_diesel", 0.0) + tot.get("supplier_shortage", 0.0)
        + tot.get("supplier_recovery", 0.0) + payments_out_total, 2)
    closing = round(opening + movements_debit - movements_credit, 2)

    return {
        "opening_balance": round(opening, 2),
        "opening_type": opening_type,
        "opening_source": opening_mode,
        "payments_in_period": payments_in_period,
        "payments_out_total": payments_out_total,
        "payments_in_total": payments_in_total,
        "movements_debit": movements_debit,
        "movements_credit": movements_credit,
        "closing_balance": closing,
        "closing_type": "payable" if closing >= 0 else "advance",
    }


def _iso_prev_day(iso_date: str) -> str:
    from datetime import date as _date
    try:
        y, m, d = [int(x) for x in iso_date.split("-")]
        prev = _date(y, m, d) - timedelta(days=1)
        return prev.isoformat()
    except Exception:
        return iso_date


async def _supplier_ledger_closing(uid: str, cid: str, sid: str, upto_date: str) -> float:
    """Rebuild the supplier ledger up to (and including) `upto_date` and return
    the running balance. Positive = payable, negative = advance."""
    sup = await db.suppliers.find_one({"id": sid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not sup:
        return 0.0
    running = float(sup.get("opening_balance") or 0.0)
    if sup.get("opening_balance_type") == "advance":
        running = -running

    # Trips
    trip_q = {
        "user_id": uid, "company_id": cid, "vehicle_type": "supplier",
        "$or": [
            {"supplier_id": sid},
            {"supplier_name": {"$regex": f"^{sup['name']}$", "$options": "i"}},
        ],
    }
    trips = await db.trips.find(trip_q, {"_id": 0, "user_id": 0}).to_list(20000)
    for t in trips:
        d = t.get("date", "")
        if not d or d > upto_date:
            continue
        _num = lambda x: (float(x) if x else 0.0)
        # Debits
        running += _num(t.get("supplier_freight"))
        running += _num(t.get("supplier_other_income"))
        # Credits
        running -= _num(t.get("supplier_advance"))
        running -= _num(t.get("supplier_diesel"))
        cust_dsl = sum(_num(r.get("amount")) for r in (t.get("customer_receipts") or []) if (r.get("type") or "").lower() == "diesel")
        running -= cust_dsl
        running -= _num(t.get("supplier_shortage_deduction"))
        running -= _num(t.get("supplier_other_recoveries"))

    # Payments
    pays = await db.supplier_payments.find(
        {"user_id": uid, "company_id": cid, "supplier_id": sid, "is_deleted": {"$ne": True}},
        {"_id": 0, "amount": 1, "type": 1, "date": 1},
    ).to_list(20000)
    for p in pays:
        d = p.get("date", "")
        if not d or d > upto_date:
            continue
        amt = float(p.get("amount") or 0)
        if p.get("type", "payment_out") == "payment_out":
            running -= amt
        else:
            running += amt
    return round(running, 2)


@router.get("/reports/supplier-statement.pdf")
async def supplier_statement_pdf(
    request: Request,
    supplier_name: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    opening_mode: str = "master",   # Iter47 Phase 3: "master" or "carry_forward"
    user=Depends(get_current_user),
):
    """Supplier-wise settlement statement — LANDSCAPE with all trip fields.
    Iter47 Phase 3: "Deep Monthly Statement" — shows Opening + Movements + Closing blocks.
    opening_mode:
      - "master"        (default): use Supplier.opening_balance from master
      - "carry_forward": compute closing balance as of start-1 day (previous period closing)
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from pdf._base import _UNI_FONT, _UNI_FONT_BOLD

    data = await _supplier_statement_data(request, supplier_name, start, end, user)
    company = data["company"]
    trips = data["trips"]
    tot = data["totals"]

    # Iter47 Phase 3 — compute opening balance + payments-in-period for the deep statement
    deep = await _supplier_deep_statement_blocks(request, supplier_name, start, end, opening_mode, user, tot)

    if not trips and not deep["payments_in_period"] and deep["opening_balance"] == 0:
        raise HTTPException(status_code=404, detail=f"No supplier trips found for '{supplier_name}'")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=12 * mm, bottomMargin=10 * mm,
        title=f"Supplier Statement — {supplier_name}",
    )
    styles = getSampleStyleSheet()
    title_st = ParagraphStyle("t", parent=styles["Title"], fontSize=14, leading=16, fontName=_UNI_FONT_BOLD)
    hdr_st = ParagraphStyle("h", parent=styles["Normal"], fontSize=9, textColor=colors.grey, fontName=_UNI_FONT)
    body_st = ParagraphStyle("b", parent=styles["Normal"], fontSize=7, leading=8.5, fontName=_UNI_FONT)
    sub_st = ParagraphStyle("sub", parent=styles["Normal"], fontSize=6.5, leading=8, textColor=colors.grey, fontName=_UNI_FONT)

    story: list = []
    story.append(Paragraph(f"<b>{company.get('name', '')}</b>", title_st))
    if company.get("gst_in"):
        story.append(Paragraph(f"GSTIN: {company.get('gst_in','')} · {company.get('address','')}", hdr_st))
    story.append(Paragraph(f"Supplier Settlement Statement — <b>{supplier_name}</b>"
                           + (f" · {data['supplier']['mobile']}" if data["supplier"]["mobile"] else ""), hdr_st))
    story.append(Paragraph(f"Period: {start or 'all'} to {end or 'today'}", hdr_st))
    story.append(Spacer(1, 8))

    # ---- Iter47 Phase 3: Deep Monthly Statement blocks ----
    def _fmt_bal(v: float) -> str:
        sign = "Dr" if v >= 0 else "Cr"
        return f"₹{abs(v):,.2f} {sign}"
    opening_label = "Opening Balance"
    opening_src = "(from previous period closing)" if deep["opening_source"] == "carry_forward" else "(from Supplier master)"
    deep_blocks = [
        ["OPENING BALANCE", _fmt_bal(deep["opening_balance"]), "MOVEMENTS · DEBITS (+)", f"₹{deep['movements_debit']:,.2f}"],
        [opening_src, "", "MOVEMENTS · CREDITS (−)", f"₹{deep['movements_credit']:,.2f}"],
        ["Freight (Trips)", f"₹{tot['supplier_freight']:,.2f}", "Advance", f"₹{tot['supplier_advance']:,.2f}"],
        ["Bonus / Other Income", f"₹{tot['supplier_income']:,.2f}", "Diesel Funded by Us", f"₹{tot['supplier_diesel']:,.2f}"],
        ["Receipts from Supplier", f"₹{deep['payments_in_total']:,.2f}", "Cust. Diesel Adjustment", f"₹{tot['customer_diesel']:,.2f}"],
        ["", "", "Shortage Deducted", f"₹{tot['supplier_shortage']:,.2f}"],
        ["", "", "Other Recoveries", f"₹{tot['supplier_recovery']:,.2f}"],
        ["", "", "Payments Made (Bank/Cash)", f"₹{deep['payments_out_total']:,.2f}"],
        ["CLOSING BALANCE", _fmt_bal(deep["closing_balance"]), "", ""],
    ]
    dbt = Table(deep_blocks, hAlign="LEFT", colWidths=[55 * mm, 45 * mm, 55 * mm, 45 * mm])
    dbt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        # Header rows (opening + movement labels)
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        # Opening source note
        ("FONTSIZE", (0, 1), (1, 1), 6.5),
        ("TEXTCOLOR", (0, 1), (1, 1), colors.grey),
        # Closing row highlight
        ("BACKGROUND", (0, -1), (1, -1), colors.HexColor("#fef3c7")),
        ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
        ("FONTSIZE", (0, -1), (-1, -1), 10),
        ("SPAN", (2, -1), (3, -1)),
        # Left-side vs right-side separator
        ("LINEAFTER", (1, 0), (1, -1), 1.2, colors.HexColor("#0f172a")),
    ]))
    story.append(dbt)
    story.append(Spacer(1, 10))

    # Summary block — 3 columns of KPIs
    smy = [
        ["Trips", str(tot["trips"]), "Loading (MT)", f"{tot['load_tons']:,.3f}", "Unloading (MT)", f"{tot['unload_tons']:,.3f}"],
        ["Distance (KM)", f"{tot['distance']:,.2f}", "Customer Freight (₹)", f"{tot['customer_freight']:,.2f}", "Supplier Freight (₹)", f"{tot['supplier_freight']:,.2f}"],
        ["Advance (₹)", f"{tot['supplier_advance']:,.2f}", "Diesel Funded (₹)", f"{tot['supplier_diesel']:,.2f}", "Cust. Diesel Adj (₹)", f"{tot['customer_diesel']:,.2f}"],
        ["Shortage Ded (₹)", f"{tot['supplier_shortage']:,.2f}", "Other Recov. (₹)", f"{tot['supplier_recovery']:,.2f}", "Bonus / Income (₹)", f"{tot['supplier_income']:,.2f}"],
        ["Halting (₹)", f"{tot['halting']:,.2f}", "Net Payable (₹)", f"{tot['net_payable']:,.2f}", "Trip Profit (₹)", f"{tot['profit']:,.2f} ({tot['margin_pct']}%)"],
    ]
    st = Table(smy, hAlign="LEFT", colWidths=[38 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm])
    st.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (4, 0), (4, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (0, -1), _UNI_FONT_BOLD),
        ("FONTNAME", (2, 0), (2, -1), _UNI_FONT_BOLD),
        ("FONTNAME", (4, 0), (4, -1), _UNI_FONT_BOLD),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fef3c7")),
    ]))
    story.append(st)
    story.append(Spacer(1, 10))

    # ---- Iter47 Phase 3: Payments in Period block ----
    if deep["payments_in_period"]:
        story.append(Paragraph("<b>Payments in Period</b>",
            ParagraphStyle("h3", parent=styles["Heading3"], fontName=_UNI_FONT_BOLD)))
        pay_hdr = ["Date", "Mode", "Against", "Ref No.", "LR / Trip", "Remarks", "Type", "Amount"]
        pay_rows = [pay_hdr]
        for p in deep["payments_in_period"]:
            pay_rows.append([
                p.get("date", ""),
                p.get("mode", ""),
                (p.get("against") or "").capitalize(),
                p.get("ref_no", "") or "—",
                p.get("lr_number", "") or "—",
                Paragraph(p.get("remarks", "") or "—", body_st),
                "OUT" if p.get("type", "payment_out") == "payment_out" else "IN",
                f"₹{float(p.get('amount', 0)):,.2f}",
            ])
        pay_rows.append([
            "TOTAL", "", "", "", "", "",
            f"IN: ₹{deep['payments_in_total']:,.0f}",
            f"OUT: ₹{deep['payments_out_total']:,.2f}",
        ])
        pt = Table(pay_rows, hAlign="LEFT", repeatRows=1,
                   colWidths=[22, 20, 22, 30, 30, 90, 20, 42])
        pt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
            ("ALIGN", (7, 1), (7, -1), "RIGHT"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fef3c7")),
            ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
        ]))
        story.append(pt)
        story.append(Spacer(1, 10))

    # Trip-wise table — landscape width ~277mm
    story.append(Paragraph("<b>Trip-wise Settlement</b>", ParagraphStyle("h3", parent=styles["Heading3"], fontName=_UNI_FONT_BOLD)))
    headers = [
        "Date", "LR / Vehicle", "Customer", "Route", "Product",
        "Load", "Unload", "S/E", "KM",
        "Sup.Rate", "Freight", "Adv", "Diesel", "Cust.Dsl", "Ded/Rec", "Halt", "Net Pay",
    ]
    rows = [headers]
    for r in trips:
        se = ""
        if r["shortage_qty"] > 0: se = f"-{r['shortage_qty']:.3f}"
        elif r["excess_qty"] > 0: se = f"+{r['excess_qty']:.3f}"
        veh_cell = Paragraph(
            f"{r['lr_number'] or '—'}<br/><font color='#6b7280' size='6'>{r['vehicle_number']}</font>",
            body_st,
        )
        route = Paragraph(f"{r['from_location'] or '?'}<br/>→ {r['to_location'] or '?'}", body_st)
        ded_rec = r["supplier_shortage_deduction"] + r["supplier_other_recoveries"]
        rows.append([
            r["date"], veh_cell,
            Paragraph(r["customer_name"], body_st),
            route,
            Paragraph(r["product"], body_st),
            f"{r['loaded_qty']:.2f}",
            f"{r['unloaded_qty']:.2f}",
            se or "—",
            f"{r['distance_kms']:.0f}" if r["distance_kms"] else "—",
            f"₹{r['supplier_rate']:,.0f}" if r["supplier_rate"] else "—",
            f"₹{r['supplier_freight']:,.0f}",
            f"₹{r['supplier_advance']:,.0f}",
            f"₹{r['supplier_diesel']:,.0f}",
            f"₹{r['customer_diesel']:,.0f}",
            f"₹{ded_rec:,.0f}",
            f"₹{r['halting_amount']:,.0f}" if r["halting_amount"] else "—",
            f"₹{r['supplier_net_payable']:,.0f}",
        ])
        if r["settlement_remarks"]:
            rows.append(["", "", Paragraph(f"<i>↳ {r['settlement_remarks']}</i>", sub_st),
                         "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
    # Totals row
    rows.append([
        "TOTAL", f"{tot['trips']} trip(s)", "", "", "",
        f"{tot['load_tons']:.2f}",
        f"{tot['unload_tons']:.2f}",
        "—",
        f"{tot['distance']:.0f}",
        "",
        f"₹{tot['supplier_freight']:,.0f}",
        f"₹{tot['supplier_advance']:,.0f}",
        f"₹{tot['supplier_diesel']:,.0f}",
        f"₹{tot['customer_diesel']:,.0f}",
        f"₹{(tot['supplier_shortage']+tot['supplier_recovery']):,.0f}",
        f"₹{tot['halting']:,.0f}",
        f"₹{tot['net_payable']:,.0f}",
    ])
    col_widths = [15, 20, 22, 26, 16, 11, 11, 13, 11, 17, 20, 17, 17, 18, 17, 15, 28]  # mm; wider Net Pay col
    col_widths = [c * mm for c in col_widths]
    tt = Table(rows, hAlign="LEFT", repeatRows=1, colWidths=col_widths)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fef3c7")),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Remarks-row styling
    r_idx = 1
    for r in trips:
        r_idx += 1
        if r["settlement_remarks"]:
            ts.append(("SPAN", (2, r_idx - 1), (16, r_idx - 1)))
            ts.append(("BACKGROUND", (0, r_idx - 1), (-1, r_idx - 1), colors.HexColor("#fff7ed")))
            r_idx += 1
    tt.setStyle(TableStyle(ts))
    story.append(tt)

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<font size='7' color='#6b7280'>Net Payable = Supplier Freight − Advance − Diesel Funded − Cust.Diesel Adj − Shortage Ded − Other Recoveries + Bonus + Halting. "
        f"Generated on {now_utc().date().isoformat()} for {company.get('name','')}.</font>",
        ParagraphStyle("f", parent=styles["Normal"], fontName=_UNI_FONT),
    ))

    doc.build(story)
    buf.seek(0)
    fname = f"supplier_statement_{(supplier_name or 'supplier').replace(' ', '_')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.post("/reports/supplier-statement/share")
async def share_supplier_statement(
    request: Request,
    supplier_name: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    opening_mode: str = "master",   # Iter47 Phase 3
    user=Depends(get_current_user),
):
    """Build the supplier statement PDF, upload to public object storage, and
    return a WhatsApp deeplink. Uses the supplier's saved mobile (from any
    vehicle in Vehicles master) when available so the deeplink pre-fills the
    recipient — falls back to a generic wa.me/?text= link when no mobile is
    on file."""
    resp = await supplier_statement_pdf(request, supplier_name, start, end, opening_mode, user)
    body_bytes = b""
    async for chunk in resp.body_iterator:
        body_bytes += chunk

    cid = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}

    # Find supplier's mobile from Vehicles master (any vehicle with this supplier_name)
    sn_lc = (supplier_name or "").strip().lower()
    vehicles = await db.vehicles.find(
        {"user_id": user["user_id"], "company_id": cid, "vehicle_type": "supplier"},
        {"_id": 0, "supplier_name": 1, "supplier_mobile": 1, "owner_phone": 1},
    ).to_list(500)
    supplier_mobile = ""
    for v in vehicles:
        if (v.get("supplier_name") or "").strip().lower() == sn_lc:
            supplier_mobile = (v.get("supplier_mobile") or v.get("owner_phone") or "").strip()
            if supplier_mobile:
                break

    obj_path = f"public/supplier_statements/{user['user_id']}/{sn_lc.replace(' ','_') or 'supplier'}_{secrets.token_hex(4)}.pdf"
    try:
        from storage_client import put_object
        put_object(obj_path, body_bytes, "application/pdf")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upload failed: {e}")

    frontend_base = _public_base_url(request)
    public_url = f"{frontend_base}/api/files/public/{obj_path}"

    msg = (
        f"*Supplier Settlement Statement — {company.get('name', 'Our Company')}*\n"
        f"Supplier: {supplier_name}\n"
        f"Period: {start or 'all'} → {end or 'today'}\n\n"
        f"Download PDF: {public_url}"
    )
    import urllib.parse
    if supplier_mobile:
        # Sanitize to digits only for wa.me; default to +91 if no country code
        digits = "".join(ch for ch in supplier_mobile if ch.isdigit())
        if digits and len(digits) == 10:
            digits = "91" + digits
        wa_url = f"https://wa.me/{digits}?text={urllib.parse.quote(msg)}"
    else:
        wa_url = f"https://wa.me/?text={urllib.parse.quote(msg)}"
    return {
        "public_url": public_url,
        "whatsapp_url": wa_url,
        "whatsapp_text": msg,
        "supplier_mobile": supplier_mobile or "",
        "supplier_mobile_available": bool(supplier_mobile),
    }


# ============ Iter65 · Priority 1 — Halting Live Verification ============
@router.get("/reports/halting-verify")
async def halting_verify(request: Request, user=Depends(get_current_user),
                          date_from: str = "", date_to: str = "",
                          only_mismatches: bool = False, limit: int = 200):
    """Return every Trip that has halting activity in the window, along with
    per-stage values so we can verify Halting is consistent across
    Trip Entry → Auto Calc → Trip View → Invoice → Supplier Settlement.

    All values come from server-persisted Trip records — no re-derivation
    happens here so any mismatch reveals a real data-integrity issue.
    """
    cid = await _active_company_id(request, user)
    q = {"user_id": user["user_id"], "company_id": cid,
         "$or": [{"total_halting_days": {"$gt": 0}}, {"halting_amount": {"$gt": 0}}]}
    if date_from or date_to:
        rng = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to
        q["date"] = rng
    trips = await (db.trips.find(q, {"_id": 0, "user_id": 0})
                   .sort("date", -1)
                   .to_list(min(max(50, limit), 1000)))
    # Bulk-load invoices referenced by these trips
    invoice_ids = list({t.get("invoice_id") for t in trips if t.get("invoice_id")})
    invoices_by_id = {}
    if invoice_ids:
        async for inv in db.invoices.find(
            {"user_id": user["user_id"], "company_id": cid, "id": {"$in": invoice_ids}},
            {"_id": 0, "user_id": 0},
        ):
            invoices_by_id[inv["id"]] = inv
    rows = []
    mismatches = 0
    for t in trips:
        # ---- Stage A: Trip Entry inputs (as stored) ----
        loading_date = t.get("loading_date") or ""
        unloading_date = t.get("unloading_date") or ""
        grace_days = int(t.get("grace_days") or 0)
        stored_total = int(t.get("total_halting_days") or 0)
        stored_chargeable = int(t.get("chargeable_halting_days") or 0)
        stored_rate = float(t.get("halting_rate_per_day") or 0)
        stored_amount = float(t.get("halting_amount") or 0)
        override = bool(t.get("halting_amount_override"))
        # ---- Stage B: Recompute using the same formula (services.compute_totals) ----
        dates_present = False
        expected_total = stored_total
        if loading_date and unloading_date:
            try:
                _ld = datetime.fromisoformat(loading_date).date()
                _ud = datetime.fromisoformat(unloading_date).date()
                expected_total = max((_ud - _ld).days, 0)
                dates_present = True
            except Exception:
                pass
        expected_chargeable = max(expected_total - grace_days, 0)
        expected_amount = round(expected_chargeable * stored_rate, 2) if not override else stored_amount
        # ---- Stage C: Invoice mirror ----
        invoice_stage = None
        inv = invoices_by_id.get(t.get("invoice_id"))
        if inv:
            # Invoices reference trips by trip_ids list; per-line halting is
            # not stored, but the invoice halting_total is the sum of all
            # referenced trips' halting_amount.  We verify that this trip is
            # actually in trip_ids (data-integrity link) and report the
            # invoice's aggregate halting.
            invoice_stage = {
                "invoice_id": inv["id"],
                "invoice_number": inv.get("invoice_number"),
                "invoice_status": inv.get("status"),
                "trip_linked": t["id"] in (inv.get("trip_ids") or []),
                "invoice_line_halting": float(stored_amount),          # this trip's contribution
                "invoice_total_halting": float(inv.get("halting_total", 0)),
            }
        # ---- Stage D: Supplier settlement ----
        # Halting is CUSTOMER-side (customer billable). Supplier gets their own
        # supplier_freight and is not affected by halting_amount. Explicitly show
        # this so operators know it's expected.
        supplier_stage = None
        if t.get("vehicle_type") == "supplier":
            supplier_stage = {
                "supplier_id": t.get("supplier_id"),
                "supplier_name": t.get("supplier_name"),
                "supplier_freight": float(t.get("supplier_freight", 0)),
                "note": "Halting is customer-side revenue; supplier settlement does NOT include it.",
            }
        # ---- Mismatch flags ----
        flags = []
        if dates_present and stored_total != expected_total:
            flags.append(f"total_halting_days stored={stored_total}, expected from dates={expected_total}")
        if stored_chargeable != expected_chargeable and not override:
            flags.append(f"chargeable_halting_days stored={stored_chargeable}, expected={expected_chargeable}")
        if not override and abs(stored_amount - expected_amount) > 0.01:
            flags.append(f"halting_amount stored={stored_amount}, expected={expected_amount:.2f}")
        if invoice_stage and not invoice_stage["trip_linked"]:
            flags.append(f"invoice {invoice_stage['invoice_number']} does not list this trip in trip_ids")
        if flags:
            mismatches += 1
        if only_mismatches and not flags:
            continue
        rows.append({
            "trip_id": t["id"],
            "trip_number": t.get("trip_number"),
            "date": t.get("date"),
            "lr_number": t.get("lr_number"),
            "vehicle_number": t.get("vehicle_number"),
            "vehicle_type": t.get("vehicle_type", "own"),
            "customer_name": t.get("customer_name"),
            "trip_entry": {
                "loading_date": loading_date, "unloading_date": unloading_date,
                "dates_present": dates_present,
                "grace_days": grace_days,
                "halting_rate_per_day": stored_rate,
                "halting_amount_override": override,
            },
            "halting_calc": {
                "total_halting_days_stored": stored_total,
                "total_halting_days_expected": expected_total,
                "grace_days_applied": grace_days,
                "chargeable_halting_days_stored": stored_chargeable,
                "chargeable_halting_days_expected": expected_chargeable,
                "halting_amount_stored": stored_amount,
                "halting_amount_expected": expected_amount,
            },
            "invoice_stage": invoice_stage,
            "supplier_stage": supplier_stage,
            "flags": flags,
            "status": "OK" if not flags else "MISMATCH",
        })
    return {
        "total": len(trips),
        "returned": len(rows),
        "mismatch_count": mismatches,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "rows": rows,
    }


def _public_base_url(request):
    """Return the public HTTPS base URL for building share links."""
    url = os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get("PUBLIC_BASE_URL")
    if not url:
        try:
            with open("/app/frontend/.env", "r") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
    if not url:
        url = str(request.base_url).rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"
    return url.rstrip("/")


# ==================== Health ====================

