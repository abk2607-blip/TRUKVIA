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

# ==================== Health ====================

