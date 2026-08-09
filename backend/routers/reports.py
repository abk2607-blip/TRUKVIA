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


# ==================== Supplier Statement (Iter41) ====================


@router.get("/reports/supplier-statement.pdf")
async def supplier_statement_pdf(
    request: Request,
    supplier_name: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Supplier-wise settlement statement — trip-by-trip listing with net_payable + remarks.

    Mirrors the Customer Statement layout. supplier_name is matched
    case-insensitively so URL encoding of arbitrary supplier strings works.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from pdf._base import _UNI_FONT, _UNI_FONT_BOLD

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
    if not trips:
        raise HTTPException(status_code=404, detail=f"No supplier trips found for '{supplier_name}'")

    total_trips = len(trips)
    total_tons = round(sum(float(t.get("tons", 0)) for t in trips), 3)
    total_customer_freight = round(sum(float(t.get("freight_amount", 0)) for t in trips), 2)
    total_supplier_freight = round(sum(float(t.get("supplier_freight", 0)) for t in trips), 2)
    total_advance = round(sum(float(t.get("supplier_advance", 0)) for t in trips), 2)
    total_diesel = round(sum(float(t.get("supplier_diesel", 0)) for t in trips), 2)
    total_shortage = round(sum(float(t.get("supplier_shortage_deduction", 0)) for t in trips), 2)
    total_recovery = round(sum(float(t.get("supplier_other_recoveries", 0)) for t in trips), 2)
    total_income = round(sum(float(t.get("supplier_other_income", 0)) for t in trips), 2)
    total_net_payable = round(sum(float(t.get("supplier_net_payable", 0)) for t in trips), 2)
    total_profit = round(total_customer_freight - total_net_payable, 2)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Supplier Statement — {supplier_name}",
    )
    styles = getSampleStyleSheet()
    title_st = ParagraphStyle("t", parent=styles["Title"], fontSize=15, leading=18, fontName=_UNI_FONT_BOLD)
    hdr_st = ParagraphStyle("h", parent=styles["Normal"], fontSize=10, textColor=colors.grey, fontName=_UNI_FONT)
    body_st = ParagraphStyle("b", parent=styles["Normal"], fontSize=8, leading=10, fontName=_UNI_FONT)
    sub_st = ParagraphStyle("sub", parent=styles["Normal"], fontSize=7, leading=9, textColor=colors.grey, fontName=_UNI_FONT)

    story: list = []
    story.append(Paragraph(f"<b>{company.get('name', '')}</b>", title_st))
    story.append(Paragraph(f"Supplier Settlement Statement — <b>{supplier_name}</b>", hdr_st))
    if start or end:
        story.append(Paragraph(f"Period: {start or 'all'} to {end or 'today'}", hdr_st))
    story.append(Spacer(1, 6))

    # Summary block
    smy = [
        ["Trips", str(total_trips), "Tons", f"{total_tons:,.3f}"],
        ["Customer Freight (₹)", f"{total_customer_freight:,.2f}", "Supplier Freight (₹)", f"{total_supplier_freight:,.2f}"],
        ["Advance Paid (₹)", f"{total_advance:,.2f}", "Diesel Funded (₹)", f"{total_diesel:,.2f}"],
        ["Shortage Deducted (₹)", f"{total_shortage:,.2f}", "Other Recoveries (₹)", f"{total_recovery:,.2f}"],
        ["Bonus / Other Income (₹)", f"{total_income:,.2f}", "Net Payable (₹)", f"{total_net_payable:,.2f}"],
        ["Trip Profit (₹)", f"{total_profit:,.2f}", "Margin %", f"{(total_profit/total_customer_freight*100.0 if total_customer_freight>0 else 0):.2f}%"],
    ]
    st = Table(smy, hAlign="LEFT", colWidths=[45 * mm, 40 * mm, 45 * mm, 40 * mm])
    st.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (0, -1), _UNI_FONT_BOLD),
        ("FONTNAME", (2, 0), (2, -1), _UNI_FONT_BOLD),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fef3c7")),
    ]))
    story.append(st)
    story.append(Spacer(1, 12))

    # Trip table — one row per trip + optional remarks row below
    story.append(Paragraph("<b>Trip-wise Settlement</b>", ParagraphStyle("h3", parent=styles["Heading3"], fontName=_UNI_FONT_BOLD)))
    trip_rows = [[
        "Date", "LR / Vehicle", "Route", "Tons", "Sup. Freight", "Adv", "Diesel", "Shortage", "Net Payable",
    ]]
    for t in trips:
        route = f"{t.get('from_location', '') or '?'} → {t.get('to_location', '') or '?'}"
        veh_cell = f"{t.get('lr_number') or '—'}\n<font color='#6b7280' size='7'>{t.get('vehicle_number','')}</font>"
        trip_rows.append([
            t.get("date", ""),
            Paragraph(veh_cell, body_st),
            Paragraph(route, body_st),
            f"{float(t.get('tons', 0)):.2f}",
            f"₹{float(t.get('supplier_freight', 0)):,.0f}",
            f"₹{float(t.get('supplier_advance', 0)):,.0f}",
            f"₹{float(t.get('supplier_diesel', 0)):,.0f}",
            f"₹{float(t.get('supplier_shortage_deduction', 0)):,.0f}",
            f"₹{float(t.get('supplier_net_payable', 0)):,.0f}",
        ])
        # Optional remarks row (spans the columns)
        rem = (t.get("supplier_settlement_remarks") or "").strip()
        if rem:
            trip_rows.append([
                "", "", Paragraph(f"<i>↳ {rem}</i>", sub_st), "", "", "", "", "", "",
            ])
    col_widths = [18 * mm, 24 * mm, 40 * mm, 12 * mm, 18 * mm, 15 * mm, 15 * mm, 17 * mm, 22 * mm]
    tt = Table(trip_rows, hAlign="LEFT", repeatRows=1, colWidths=col_widths)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Merge remarks-row description across cols 2..8 and give it a soft amber background
    r_idx = 1
    for t in trips:
        r_idx += 1  # advance past the trip row
        rem = (t.get("supplier_settlement_remarks") or "").strip()
        if rem:
            ts.append(("SPAN", (2, r_idx - 1), (8, r_idx - 1)))
            ts.append(("BACKGROUND", (0, r_idx - 1), (-1, r_idx - 1), colors.HexColor("#fff7ed")))
            r_idx += 1  # advance past the remark row
    tt.setStyle(TableStyle(ts))
    story.append(tt)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"<font size='8' color='#6b7280'>Net Payable = Supplier Freight − Advance − Diesel − Shortage − Other Recoveries + Other Income. "
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
    user=Depends(get_current_user),
):
    """Build the supplier statement PDF, upload to public object storage, and
    return a WhatsApp deeplink. Uses the supplier's saved mobile (from any
    vehicle in Vehicles master) when available so the deeplink pre-fills the
    recipient — falls back to a generic wa.me/?text= link when no mobile is
    on file."""
    resp = await supplier_statement_pdf(request, supplier_name, start, end, user)
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

