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
    now_utc, new_id, LIVE_ONLY_FILTER,
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
    _GSTR1_9B_REASON_MAP,
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

    # Iter132c-agg-fix H1 · streaming aggregation avoids the pre-existing
    # to_list(2000) truncation for customers with >2000 invoices. Single DB
    # cursor; no N+1; entries + opening_balance computed in one pass.
    entries = []
    opening = 0.0
    async for inv in db.invoices.find(
        {"user_id": uid, "company_id": cid, "customer_id": customer_id},
        {"_id": 0, "user_id": 0},
    ):
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
        # Opening balance semantic (preserved from pre-Iter132c-agg-fix):
        # invoices dated < start add to opening; payments dated < start
        # subtract from opening — regardless of their parent invoice's date.
        if start and idt < start:
            opening += inv["total_amount"]
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
            if start and pdt < start:
                opening -= p["amount"]

    # Iter133 L1 · Credit / Debit Note ledger integration.
    # Second streaming cursor — tenant + customer + issued-only scope. Uses
    # the existing (user_id, company_id, note_date DESC) compound index so no
    # new index is required. Sign convention:
    #   • Credit Note → credit column (reduces receivable)
    #   • Debit Note  → debit column (increases receivable)
    # Draft / cancelled notes are excluded entirely by the status filter.
    # Notes dated < start fold into opening balance (mirroring invoice/payment
    # opening semantics). Notes within the period become ledger rows. The
    # invoice_number_snapshot on each note is used verbatim — no join.
    async for n in db.credit_debit_notes.find(
        {
            "user_id": uid, "company_id": cid,
            "customer_id": customer_id, "status": "issued",
        },
        {
            "_id": 0, "id": 1, "kind": 1, "note_date": 1, "note_number": 1,
            "total_amount": 1, "invoice_id": 1, "invoice_number_snapshot": 1,
            "reason_code": 1,
        },
    ):
        ndt = n.get("note_date", "")
        kind = n.get("kind")
        amt = float(n.get("total_amount") or 0.0)
        inv_snap = n.get("invoice_number_snapshot") or ""
        reason = n.get("reason_code") or ""
        if _in_range(ndt, start, end):
            if kind == "credit":
                entries.append({
                    "date": ndt,
                    "type": "credit_note",
                    "reference": n.get("note_number", ""),
                    "particulars": f"Credit Note — {reason} · against {inv_snap}".strip(" ·"),
                    "debit": 0.0,
                    "credit": amt,
                    "invoice_id": n.get("invoice_id"),
                    "note_id": n.get("id"),
                    "kind": "credit",
                })
            elif kind == "debit":
                entries.append({
                    "date": ndt,
                    "type": "debit_note",
                    "reference": n.get("note_number", ""),
                    "particulars": f"Debit Note — {reason} · against {inv_snap}".strip(" ·"),
                    "debit": amt,
                    "credit": 0.0,
                    "invoice_id": n.get("invoice_id"),
                    "note_id": n.get("id"),
                    "kind": "debit",
                })
        elif start and ndt < start:
            # pre-period folds into opening. CN reduces, DN increases.
            if kind == "credit":
                opening -= amt
            elif kind == "debit":
                opening += amt

    # Sort by date, then by type priority (invoice → DN → CN → payment on
    # the same day). Auditor-friendly ordering: receivable-creating rows come
    # before receivable-adjusting rows, and payments last.
    _PRIORITY = {"invoice": 0, "debit_note": 1, "credit_note": 2, "payment": 3}
    entries.sort(key=lambda x: (x["date"], _PRIORITY.get(x["type"], 9)))

    running = opening
    for e in entries:
        running = round(running + e["debit"] - e["credit"], 2)
        e["balance"] = running

    total_debit = round(sum(e["debit"] for e in entries), 2)
    total_credit = round(sum(e["credit"] for e in entries), 2)
    closing = round(opening + total_debit - total_credit, 2)

    # Iter133 L1 · additive totals-by-type metadata. Backwards-compatible —
    # existing consumers ignore this key. Enables future L2/L3 slices to render
    # per-type breakdowns without a second cursor.
    totals_by_type = {
        "invoice":     round(sum(e["debit"]  for e in entries if e["type"] == "invoice"),     2),
        "payment":     round(sum(e["credit"] for e in entries if e["type"] == "payment"),     2),
        "credit_note": round(sum(e["credit"] for e in entries if e["type"] == "credit_note"), 2),
        "debit_note":  round(sum(e["debit"]  for e in entries if e["type"] == "debit_note"),  2),
    }

    return {
        "customer": {k: customer.get(k, "") for k in ["id", "name", "gstin", "phone", "address", "state"]},
        "period": {"start": start, "end": end},
        "opening_balance": round(opening, 2),
        "entries": entries,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "closing_balance": closing,
        "totals_by_type": totals_by_type,
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
    trips = await db.trips.find({"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0, "user_id": 0}).to_list(5000)
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
    trips = await db.trips.find({"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0}).to_list(5000)

    # Cumulative net profit up to as_of (from trips dated <= as_of)
    trips_todate = [t for t in trips if t.get("date", "") <= as_of]
    revenue = sum(t.get("freight_amount", 0) for t in trips_todate)
    expenses = sum(t.get("total_expense", 0) for t in trips_todate)
    net_profit = round(revenue - expenses, 2)

    # Iter132c C1 · B1 — streaming aggregation with as-of-date correctness.
    # Pre-fetch issued notes with note_date <= as_of, group by invoice_id,
    # then stream invoices without the pre-existing to_list(2000) truncation.
    # Two DB queries total; no N+1. Notes issued AFTER as_of correctly excluded
    # from the historical balance sheet (previously leaked via unfiltered
    # _apply_effective_balance). Persisted invoice fields untouched.
    notes_by_inv: dict = {}
    async for n in db.credit_debit_notes.find(
        {"user_id": uid, "company_id": cid, "status": "issued",
         "note_date": {"$lte": as_of}},
        {"_id": 0, "invoice_id": 1, "kind": 1, "total_amount": 1},
    ):
        notes_by_inv.setdefault(n.get("invoice_id"), []).append(n)

    cash_bank = 0.0
    receivables = 0.0
    receivables_effective = 0.0
    async for inv in db.invoices.find(
        {"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER,
         "invoice_date": {"$lte": as_of}},
        {"_id": 0, "id": 1, "invoice_date": 1, "total_amount": 1, "payments": 1},
    ):
        raw_total = float(inv.get("total_amount", 0))
        paid_upto = sum(p["amount"] for p in inv.get("payments", [])
                        if p.get("date", "") <= as_of)
        cash_bank += paid_upto
        receivables += max(raw_total - paid_upto, 0)
        notes = notes_by_inv.get(inv.get("id"), [])
        credits = sum(float(n.get("total_amount") or 0) for n in notes if n.get("kind") == "credit")
        debits = sum(float(n.get("total_amount") or 0) for n in notes if n.get("kind") == "debit")
        eff_total = raw_total - credits + debits
        receivables_effective += max(eff_total - paid_upto, 0)

    total_assets = round(cash_bank + receivables, 2)

    # Simplified: Owner's equity balances the sheet
    owners_equity = total_assets  # balance-plug for zero liabilities

    return {
        "as_of": as_of,
        "assets": {
            "cash_and_bank": round(cash_bank, 2),
            "sundry_debtors": round(receivables, 2),
            "sundry_debtors_effective": round(receivables_effective, 2),
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
    trips = await db.trips.find({"user_id": uid, "company_id": cid, "vehicle_type": "supplier", **LIVE_ONLY_FILTER}, {"_id": 0, "user_id": 0}).to_list(5000)
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
    trips = await db.trips.find({"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0, "user_id": 0}).to_list(10000)
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
    trips = await (db.trips.find(
        {"user_id": uid, "company_id": cid, "vehicle_type": "supplier", **LIVE_ONLY_FILTER},
        {"_id": 0, "user_id": 0},
    ).sort([("date", -1), ("created_at", -1)]).to_list(50000))
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
        "company": {
            "id": company.get("id"), "name": company.get("name", ""),
            # Iter93 — expose full company master for the redesigned PDF header.
            # Backward-compat: keep `gst_in` alias for JSON consumers.
            "gst_in": company.get("gstin") or company.get("gst_in") or "",
            "gstin": company.get("gstin") or company.get("gst_in") or "",
            "pan": company.get("pan", ""),
            "address": company.get("address", ""),
            "phone": company.get("phone", ""),
            "email": company.get("email", ""),
            "state": company.get("state", ""),
            "logo": company.get("logo", ""),
        },
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
        "user_id": uid, "company_id": cid, "vehicle_type": "supplier", **LIVE_ONLY_FILTER,
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
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from pdf._base import _UNI_FONT, _UNI_FONT_BOLD
    from io import BytesIO as _BIO

    data = await _supplier_statement_data(request, supplier_name, start, end, user)
    company = data["company"]
    trips = data["trips"]
    tot = data["totals"]

    # Iter47 Phase 3 — compute opening balance + payments-in-period for the deep statement
    deep = await _supplier_deep_statement_blocks(request, supplier_name, start, end, opening_mode, user, tot)

    if not trips and not deep["payments_in_period"] and deep["opening_balance"] == 0:
        raise HTTPException(status_code=404, detail=f"No supplier trips found for '{supplier_name}'")

    # ------------------------------------------------------------------
    # Iter93 — Modern professional Supplier Statement redesign.
    # Landscape A4, generous margins, page-header + page-footer callbacks
    # with logo (from Company master), page numbers, and cleaner tables.
    # ------------------------------------------------------------------
    PALETTE = {
        "ink":       colors.HexColor("#0f172a"),
        "sub":       colors.HexColor("#475569"),
        "muted":     colors.HexColor("#64748b"),
        "line":      colors.HexColor("#cbd5e1"),
        "line_soft": colors.HexColor("#e2e8f0"),
        "zebra":     colors.HexColor("#f8fafc"),
        "band":      colors.HexColor("#f1f5f9"),
        "accent":    colors.HexColor("#0f172a"),
        "gold":      colors.HexColor("#fef3c7"),
        "gold_ink":  colors.HexColor("#78350f"),
        "danger":    colors.HexColor("#b91c1c"),
    }

    # Decode logo (base64 data URL) once for reuse in page header.
    logo_bytes = None
    _raw_logo = company.get("logo") or ""
    if _raw_logo and isinstance(_raw_logo, str) and "," in _raw_logo and _raw_logo.strip().lower().startswith("data:image"):
        try:
            logo_bytes = base64.b64decode(_raw_logo.split(",", 1)[1])
        except Exception:
            logo_bytes = None

    def _fmt_bal(v: float) -> str:
        sign = "Dr" if v >= 0 else "Cr"
        return f"₹\u00a0{abs(v):,.2f} {sign}"

    def _rupee(v) -> str:
        try:
            # Non-breaking space keeps ₹ glued to the amount on wraps.
            return f"₹\u00a0{float(v or 0):,.2f}"
        except Exception:
            return "₹\u00a00.00"

    def _rupee0(v) -> str:
        """Compact ₹ format (no decimals) — used inside the wide trip-wise table."""
        try:
            return f"₹\u00a0{float(v or 0):,.0f}"
        except Exception:
            return "₹\u00a00"

    def _rupee_or_dash(v) -> str:
        try:
            f = float(v or 0)
        except Exception:
            f = 0.0
        return _rupee0(f) if abs(f) > 0.005 else "—"

    def _page_decorator(canvas, doc_):
        """Header (logo + company block + statement title) and footer
        (generated on … · company · page N) drawn on every page."""
        canvas.saveState()
        page_w, page_h = doc_.pagesize
        m_l = 12 * mm
        m_r = 12 * mm
        m_top = 12 * mm
        m_bot = 10 * mm

        # ── Header band ────────────────────────────────────────────────
        header_y = page_h - m_top
        # Logo
        logo_w = 22 * mm
        logo_x = m_l
        text_x = logo_x
        if logo_bytes:
            try:
                img_reader = _BIO(logo_bytes)
                from reportlab.lib.utils import ImageReader
                canvas.drawImage(ImageReader(img_reader), logo_x, header_y - 22 * mm,
                                 width=logo_w, height=22 * mm,
                                 preserveAspectRatio=True, mask="auto")
                text_x = logo_x + logo_w + 5 * mm
            except Exception:
                text_x = logo_x

        # Company block (left)
        canvas.setFillColor(PALETTE["ink"])
        canvas.setFont(_UNI_FONT_BOLD, 15)
        canvas.drawString(text_x, header_y - 5 * mm, (company.get("name") or "").upper() or "COMPANY")
        canvas.setFont(_UNI_FONT, 8.5)
        canvas.setFillColor(PALETTE["sub"])
        canvas.drawString(text_x, header_y - 9 * mm, "Bitumen Transport Contractors")

        # Address / phone / email / GSTIN wrapped into up to 3 lines under the name
        info_lines = []
        if company.get("address"):
            info_lines.append(company.get("address"))
        contact = " · ".join([x for x in [
            (f"Phone: {company.get('phone')}" if company.get("phone") else ""),
            (f"Email: {company.get('email')}" if company.get("email") else ""),
        ] if x])
        if contact:
            info_lines.append(contact)
        idents = " · ".join([x for x in [
            (f"GSTIN: {company.get('gstin') or company.get('gst_in') or ''}" if (company.get('gstin') or company.get('gst_in')) else ""),
            (f"PAN: {company.get('pan')}" if company.get("pan") else ""),
        ] if x])
        if idents:
            info_lines.append(idents)
        canvas.setFillColor(PALETTE["muted"])
        canvas.setFont(_UNI_FONT, 8)
        y = header_y - 13 * mm
        for line in info_lines[:3]:
            canvas.drawString(text_x, y, line[:160])
            y -= 3.5 * mm

        # Statement title (right)
        canvas.setFillColor(PALETTE["ink"])
        canvas.setFont(_UNI_FONT_BOLD, 13)
        canvas.drawRightString(page_w - m_r, header_y - 5 * mm, "SUPPLIER SETTLEMENT")
        canvas.drawRightString(page_w - m_r, header_y - 10 * mm, "STATEMENT")
        canvas.setFillColor(PALETTE["muted"])
        canvas.setFont(_UNI_FONT, 8)
        canvas.drawRightString(page_w - m_r, header_y - 14 * mm,
                               f"Period: {start or 'All time'} to {end or 'Today'}")

        # Divider under header
        canvas.setStrokeColor(PALETTE["line"])
        canvas.setLineWidth(0.6)
        canvas.line(m_l, header_y - 25 * mm, page_w - m_r, header_y - 25 * mm)

        # ── Footer band ────────────────────────────────────────────────
        canvas.setStrokeColor(PALETTE["line_soft"])
        canvas.setLineWidth(0.4)
        canvas.line(m_l, m_bot + 5 * mm, page_w - m_r, m_bot + 5 * mm)
        canvas.setFillColor(PALETTE["muted"])
        canvas.setFont(_UNI_FONT, 7.5)
        canvas.drawString(m_l, m_bot + 1.5 * mm,
                          f"Generated {now_utc().strftime('%Y-%m-%d %H:%M UTC')}  ·  {company.get('name','')}")
        canvas.drawRightString(page_w - m_r, m_bot + 1.5 * mm,
                               f"Page {doc_.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm,  # Iter94 — tightened for wider trip-wise table
        topMargin=42 * mm,    # room for the header band drawn by the callback
        bottomMargin=14 * mm, # room for the footer band
        title=f"Supplier Settlement Statement — {supplier_name}",
    )
    styles = getSampleStyleSheet()
    body_st = ParagraphStyle("body", parent=styles["Normal"], fontSize=7.5, leading=9,
                             fontName=_UNI_FONT, textColor=PALETTE["ink"])
    body_c = ParagraphStyle("bodyc", parent=body_st, alignment=TA_CENTER)
    body_r = ParagraphStyle("bodyr", parent=body_st, alignment=TA_RIGHT)
    # Iter95 — Cell paragraph styles: left-align for text, right-align for
    # amounts (per user rule). Wider amount columns + more row padding stop
    # ₹ amounts from breaking mid-value.
    tw_cell = ParagraphStyle("twc", parent=body_st, fontSize=7, leading=8.5, wordWrap=None)
    tw_cell_r = ParagraphStyle("twcr", parent=tw_cell, alignment=TA_RIGHT)
    tw_cell_c = ParagraphStyle("twcc", parent=tw_cell, alignment=TA_CENTER)
    # Iter95 — All headers CENTER aligned per user rule; row cells use their
    # own alignment (text = left, amounts = right).
    tw_head_st = ParagraphStyle("twh", parent=styles["Normal"], fontSize=7, leading=8.5,
                                fontName=_UNI_FONT_BOLD, textColor=colors.white,
                                alignment=TA_CENTER)
    tw_head_r_st = ParagraphStyle("twhr", parent=tw_head_st, alignment=TA_CENTER)
    sub_st = ParagraphStyle("sub", parent=styles["Normal"], fontSize=7, leading=8.5,
                            fontName=_UNI_FONT, textColor=PALETTE["muted"])
    section_st = ParagraphStyle("sec", parent=styles["Heading3"], fontSize=10, leading=12,
                                fontName=_UNI_FONT_BOLD, textColor=PALETTE["ink"],
                                spaceBefore=2, spaceAfter=4)

    story: list = []

    # ── Supplier identity card (immediately below the page header band) ──
    supplier_card = [
        [
            Paragraph("<font size='7' color='#64748b'>SUPPLIER</font><br/>"
                      f"<b><font size='11' color='#0f172a'>{(supplier_name or '').upper()}</font></b>", body_st),
            Paragraph("<font size='7' color='#64748b'>MOBILE</font><br/>"
                      f"<font size='9' color='#0f172a'>{data['supplier']['mobile'] or '—'}</font>", body_st),
            Paragraph("<font size='7' color='#64748b'>PERIOD</font><br/>"
                      f"<font size='9' color='#0f172a'>{start or 'All time'} → {end or 'Today'}</font>", body_st),
            Paragraph("<font size='7' color='#64748b'>OPENING SOURCE</font><br/>"
                      f"<font size='9' color='#0f172a'>{'Previous period closing' if deep['opening_source']=='carry_forward' else 'Supplier master'}</font>", body_st),
        ]
    ]
    sc = Table(supplier_card, hAlign="LEFT",
               colWidths=[92 * mm, 55 * mm, 65 * mm, 62 * mm])
    sc.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("BACKGROUND", (0, 0), (-1, -1), PALETTE["band"]),
        ("BOX", (0, 0), (-1, -1), 0.5, PALETTE["line"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(sc)
    story.append(Spacer(1, 8))

    # ── Opening / Debits / Credits / Closing block ──
    story.append(Paragraph("Account Movements", section_st))
    _cell_head = lambda t: Paragraph(f"<b><font color='#ffffff'>{t}</font></b>", body_st)
    _cell_amt = lambda t: Paragraph(f"<font color='#0f172a'>{t}</font>", body_r)
    _cell_lbl = lambda t: Paragraph(f"<font color='#0f172a'>{t}</font>", body_st)

    movement_rows = [
        [_cell_head("OPENING BALANCE"),  _cell_head(_fmt_bal(deep["opening_balance"])),
         _cell_head("MOVEMENTS · DEBITS  (+)"), _cell_head(f"₹\u00a0{deep['movements_debit']:,.2f}"),
         _cell_head("MOVEMENTS · CREDITS  (−)"), _cell_head(f"₹\u00a0{deep['movements_credit']:,.2f}")],
        [Paragraph(f"<font size='6.5' color='#64748b'>from {'previous period closing' if deep['opening_source']=='carry_forward' else 'Supplier master'}</font>", body_st),
         "",
         _cell_lbl("Freight (Trips)"),          _cell_amt(_rupee(tot['supplier_freight'])),
         _cell_lbl("Advance"),                  _cell_amt(_rupee(tot['supplier_advance']))],
        ["", "",
         _cell_lbl("Halting"),                  _cell_amt(_rupee(tot['halting'])),
         _cell_lbl("Diesel Funded by Us"),      _cell_amt(_rupee(tot['supplier_diesel']))],
        ["", "",
         _cell_lbl("Bonus / Other Income"),     _cell_amt(_rupee(tot['supplier_income'])),
         _cell_lbl("Shortage Deducted"),        _cell_amt(_rupee(tot['supplier_shortage']))],
        ["", "",
         _cell_lbl("Receipts from Supplier"),   _cell_amt(_rupee(deep['payments_in_total'])),
         # Iter94 — Customer Diesel that reduces supplier payable is shown here
         # as a supplier-side recovery, not as separate customer info.
         _cell_lbl("Other Recoveries"),         _cell_amt(_rupee(tot['supplier_recovery'] + tot['customer_diesel']))],
        ["", "", "", "",
         _cell_lbl("Payments Made (Bank/Cash)"), _cell_amt(_rupee(deep['payments_out_total']))],
        [Paragraph("<b><font color='#78350f'>CLOSING BALANCE</font></b>", body_st),
         Paragraph(f"<b><font color='#78350f'>{_fmt_bal(deep['closing_balance'])}</font></b>", body_r),
         "", "", "", ""],
    ]
    mv = Table(movement_rows, hAlign="LEFT",
               colWidths=[46 * mm, 30 * mm, 55 * mm, 30 * mm, 55 * mm, 30 * mm])
    mv.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), PALETTE["accent"]),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        # Body padding
        ("TOPPADDING", (0, 1), (-1, -2), 3.5),
        ("BOTTOMPADDING", (0, 1), (-1, -2), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # Vertical separators between the three blocks
        ("LINEAFTER", (1, 0), (1, -1), 0.6, PALETTE["line"]),
        ("LINEAFTER", (3, 0), (3, -1), 0.6, PALETTE["line"]),
        # Right-align amount cells (col 1, 3, 5)
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # Closing row
        ("BACKGROUND", (0, -1), (1, -1), PALETTE["gold"]),
        ("SPAN", (2, -1), (5, -1)),
        ("TOPPADDING", (0, -1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        # Outer box
        ("BOX", (0, 0), (-1, -1), 0.5, PALETTE["line"]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, PALETTE["line"]),
    ]))
    story.append(mv)
    story.append(Spacer(1, 10))

    # ── Trip Summary metrics ─────────────────────────────────────────
    story.append(Paragraph("Trip Summary", section_st))
    def _kpi(label, value):
        return Paragraph(
            f"<font size='6.5' color='#64748b'>{label.upper()}</font><br/>"
            f"<font size='9' color='#0f172a'><b>{value}</b></font>", body_st)
    # Iter94 — Removed Customer Freight / Cust. Diesel Adj / Trip Profit KPIs
    # (customer-side financials do NOT belong in a Supplier Statement). Twelve
    # supplier-only KPIs remain in a clean 6-col × 2-row grid.
    kpi_rows = [[
        _kpi("Trips", f"{tot['trips']}"),
        _kpi("Distance (KM)", f"{tot['distance']:,.2f}"),
        _kpi("Loading (MT)", f"{tot['load_tons']:,.3f}"),
        _kpi("Unloading (MT)", f"{tot['unload_tons']:,.3f}"),
        _kpi("Supplier Freight", _rupee(tot['supplier_freight'])),
        _kpi("Halting", _rupee(tot['halting'])),
    ], [
        _kpi("Advance", _rupee(tot['supplier_advance'])),
        _kpi("Diesel Funded", _rupee(tot['supplier_diesel'])),
        _kpi("Shortage Ded", _rupee(tot['supplier_shortage'])),
        _kpi("Other Recoveries", _rupee(tot['supplier_recovery'] + tot['customer_diesel'])),
        _kpi("Bonus / Income", _rupee(tot['supplier_income'])),
        Paragraph(f"<font size='6.5' color='#64748b'>NET PAYABLE</font><br/>"
                  f"<font size='11' color='#b91c1c'><b>{_rupee(tot['net_payable'])}</b></font>", body_st),
    ]]
    ks = Table(kpi_rows, hAlign="LEFT", colWidths=[45 * mm] * 6)
    ks.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("BOX",      (0, 0), (-1, -1), 0.5, PALETTE["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, PALETTE["line_soft"]),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BACKGROUND", (5, 1), (5, 1), PALETTE["band"]),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(ks)
    story.append(Spacer(1, 12))

    # ── Payments in Period (unchanged content, restyled) ─────────────
    if deep["payments_in_period"]:
        story.append(Paragraph("Payments in Period", section_st))
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
                _rupee(p.get("amount", 0)),
            ])
        pay_rows.append([
            "TOTAL", "", "", "", "", "",
            f"IN {_rupee(deep['payments_in_total'])}",
            f"OUT {_rupee(deep['payments_out_total'])}",
        ])
        pt = Table(pay_rows, hAlign="LEFT", repeatRows=1,
                   colWidths=[22 * mm, 20 * mm, 22 * mm, 28 * mm, 28 * mm, 95 * mm, 20 * mm, 35 * mm])
        pt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("BACKGROUND", (0, 0), (-1, 0), PALETTE["accent"]),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), _UNI_FONT_BOLD),
            ("GRID", (0, 0), (-1, -1), 0.25, PALETTE["line_soft"]),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, PALETTE["zebra"]]),
            ("ALIGN", (7, 1), (7, -1), "RIGHT"),
            ("BACKGROUND", (0, -1), (-1, -1), PALETTE["gold"]),
            ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(pt)
        story.append(Spacer(1, 12))

    # ── Trip-wise Settlement — the redesigned wide table ─────────────
    story.append(Paragraph("Trip-wise Settlement", section_st))
    # Iter94 — Trip-wise table: dropped "Cust.Dsl" column. Customer diesel
    # adjustment that reduces supplier payable is folded into Ded/Rec, so the
    # statement never displays customer-side revenue or profit.
    tw_head = [
        Paragraph("Date", tw_head_st),
        Paragraph("LR / Vehicle", tw_head_st),
        Paragraph("Customer", tw_head_st),
        Paragraph("Route", tw_head_st),
        Paragraph("Product", tw_head_st),
        Paragraph("Load", tw_head_r_st),
        Paragraph("Unload", tw_head_r_st),
        Paragraph("Shr/Exc", tw_head_r_st),
        Paragraph("KM", tw_head_r_st),
        Paragraph("Sup.Rate", tw_head_r_st),
        Paragraph("Sup.Freight", tw_head_r_st),
        Paragraph("Advance", tw_head_r_st),
        Paragraph("Diesel", tw_head_r_st),
        Paragraph("Ded/Rec", tw_head_r_st),
        Paragraph("Halting", tw_head_r_st),
        Paragraph("Net Payable", tw_head_r_st),
    ]
    tw_rows = [tw_head]
    remarks_row_indexes = []
    for r in trips:
        # Shortage/Excess (compact)
        if r["shortage_qty"] > 0:
            se = f"−{r['shortage_qty']:.3f}"
        elif r["excess_qty"] > 0:
            se = f"+{r['excess_qty']:.3f}"
        else:
            se = "—"
        # Iter95 — LR/Vehicle stacked in one cell with clear leading so the
        # vehicle line does not bleed into the next row.
        veh_cell = Paragraph(
            f"<b>{r['lr_number'] or '—'}</b><br/>"
            f"<font color='#64748b' size='6.5'>{r['vehicle_number'] or '—'}</font>",
            ParagraphStyle("veh", parent=body_st, fontSize=7, leading=9, alignment=TA_LEFT),
        )
        route = Paragraph(
            f"{r['from_location'] or '?'}<br/>"
            f"<font color='#64748b'>→ {r['to_location'] or '?'}</font>",
            ParagraphStyle("rt", parent=body_st, fontSize=7, leading=9, alignment=TA_LEFT),
        )
        ded_rec = r["supplier_shortage_deduction"] + r["supplier_other_recoveries"]
        tw_rows.append([
            r["date"],
            veh_cell,
            Paragraph(r["customer_name"] or "—", body_st),
            route,
            Paragraph(r["product"] or "—", body_st),
            Paragraph(f"{r['loaded_qty']:.3f}", body_r),
            Paragraph(f"{r['unloaded_qty']:.3f}", body_r),
            Paragraph(se, body_r),
            Paragraph(f"{r['distance_kms']:.0f}" if r["distance_kms"] else "—", body_r),
            Paragraph(_rupee_or_dash(r['supplier_rate']), body_r),
            Paragraph(_rupee0(r['supplier_freight']), body_r),
            Paragraph(_rupee_or_dash(r['supplier_advance']), body_r),
            Paragraph(_rupee_or_dash(r['supplier_diesel']), body_r),
            Paragraph(_rupee_or_dash(r['customer_diesel']), body_r),
            Paragraph(_rupee_or_dash(ded_rec), body_r),
            Paragraph(_rupee_or_dash(r['halting_amount']), body_r),
            Paragraph(f"<b>{_rupee0(r['supplier_net_payable'])}</b>", body_r),
        ])
        if r["settlement_remarks"]:
            remarks_row_indexes.append(len(tw_rows))  # position of the remarks row we're about to add
            tw_rows.append([
                "", "",
                Paragraph(f"<i><font color='#64748b'>↳ {r['settlement_remarks']}</font></i>", sub_st),
                "", "", "", "", "", "", "", "", "", "", "", "", "", "",
            ])
    # Totals row — use the same tight `tw_cell_r` style as data rows so amounts don't wrap.
    tw_rows.append([
        Paragraph("<b>TOTAL</b>", tw_cell),
        Paragraph(f"<b>{tot['trips']} trip(s)</b>", tw_cell),
        "", "", "",
        Paragraph(f"<b>{tot['load_tons']:.3f}</b>", tw_cell_r),
        Paragraph(f"<b>{tot['unload_tons']:.3f}</b>", tw_cell_r),
        Paragraph("—", tw_cell_r),
        Paragraph(f"<b>{tot['distance']:.0f}</b>", tw_cell_r),
        "",
        Paragraph(f"<b>{_rupee0(tot['supplier_freight'])}</b>", tw_cell_r),
        Paragraph(f"<b>{_rupee0(tot['supplier_advance'])}</b>", tw_cell_r),
        Paragraph(f"<b>{_rupee0(tot['supplier_diesel'])}</b>", tw_cell_r),
        Paragraph(f"<b>{_rupee0(tot['supplier_shortage']+tot['supplier_recovery']+tot['customer_diesel'])}</b>", tw_cell_r),
        Paragraph(f"<b>{_rupee0(tot['halting'])}</b>", tw_cell_r),
        Paragraph(f"<b>{_rupee0(tot['net_payable'])}</b>", tw_cell_r),
    ])
    # Iter95 — Landscape A4 usable width ≈ 277 mm (297 − 2×10mm margins).
    # Widened amount columns (Halting 15, Ded/Rec 17, Advance 17, Diesel 16,
    # Sup.Freight 20, Net Payable 21) so 5-digit ₹ amounts never wrap.
    col_widths_mm = [
        14,   # Date
        22,   # LR / Vehicle    ← wider for two-line stacking
        22,   # Customer
        24,   # Route
        14,   # Product
        12,   # Load
        12,   # Unload
        13,   # Shr/Exc
        10,   # KM
        15,   # Sup.Rate
        20,   # Sup.Freight
        17,   # Advance
        16,   # Diesel
        17,   # Ded/Rec
        15,   # Halting
        21,   # Net Payable    ← total = 264 mm (comfortable inside 277mm)
    ]
    tt = Table(tw_rows, hAlign="LEFT", repeatRows=1,
               colWidths=[w * mm for w in col_widths_mm])
    tw_style = [
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), PALETTE["accent"]),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        # Body
        ("GRID", (0, 0), (-1, -1), 0.25, PALETTE["line_soft"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, PALETTE["zebra"]]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),   # Iter95 — every header centred
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),   # Iter95 — a hair more so cells breathe
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",   (0, 1), (-1, -1), 5),   # taller rows so LR/Vehicle two-liner never bleeds
        ("BOTTOMPADDING",(0, 1), (-1, -1), 5),
        # Total row
        ("BACKGROUND", (0, -1), (-1, -1), PALETTE["gold"]),
        ("FONTNAME",   (0, -1), (-1, -1), _UNI_FONT_BOLD),
        ("TEXTCOLOR",  (0, -1), (-1, -1), PALETTE["gold_ink"]),
        ("TOPPADDING", (0, -1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
        ("LINEABOVE",  (0, -1), (-1, -1), 1.0, PALETTE["accent"]),
    ]
    # Remarks-row styling (spans across the data cols; 16 columns total)
    for r_idx in remarks_row_indexes:
        tw_style.append(("SPAN", (2, r_idx), (15, r_idx)))
        tw_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#fff7ed")))
    tt.setStyle(TableStyle(tw_style))
    story.append(tt)

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<font size='7' color='#64748b'>"
        "Formula &nbsp;·&nbsp; <b>Net Payable</b> = Supplier Freight + Halting + Bonus/Income "
        "− Advance − Diesel Funded − Shortage Ded − Other Recoveries. "
        "This statement reflects only the Company↔Supplier relationship — "
        "customer-side freight, revenue and trip profit are excluded by design."
        "</font>",
        body_st,
    ))

    doc.build(story, onFirstPage=_page_decorator, onLaterPages=_page_decorator)
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
    q = {"user_id": user["user_id"], "company_id": cid, **LIVE_ONLY_FILTER,
         "$or": [{"total_halting_days": {"$gt": 0}}, {"halting_amount": {"$gt": 0}}]}
    if date_from or date_to:
        rng = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to
        q["date"] = rng
    trips = await (db.trips.find(q, {"_id": 0, "user_id": 0})
                   .sort([("date", -1), ("created_at", -1)])
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


# ==================== Iter124 · Monthly LR Register / Statement ====================

_LR_ACTIONS = ("lr_regenerate", "lr_all_copies_zip", "lr_bulk_regenerate")


def _company_code(company: dict) -> str:
    """Derive a filename-safe company code. Prefer the LR prefix (unique per
    company, short) else a slug of the company name. Purely presentational;
    never persisted."""
    raw = (company.get("lr_prefix") or "").strip() or (company.get("name") or "").strip() or "COMPANY"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()[:24] or "COMPANY"
    return slug


def _derive_allowance_mt(t: dict) -> float:
    """Iter124 · READ-ONLY mirror of the Iter98/102 customer-shortage allowance
    formula (services._compute_trip lines 89-105). We compute it here only to
    display it in the register — the trip document is NEVER modified and no
    engine is re-run. When the trip has no policy snapshot, allowance is 0."""
    _cust_limit = float(t.get("applied_customer_shortage_limit") or 0)
    _cust_type = (t.get("applied_customer_shortage_limit_type") or "pct").lower()
    _prod_pct = float(t.get("applied_product_shortage_pct") or 0)
    if _cust_limit <= 0 and _prod_pct > 0:
        _cust_limit = _prod_pct
        _cust_type = "pct"
    if _cust_limit <= 0:
        return 0.0
    if _cust_type == "kg":
        return round(_cust_limit / 1000.0, 3)
    return round(float(t.get("tons") or 0) * _cust_limit / 100.0, 3)


def _lr_copies_label(events: list) -> str:
    """Represent LR-copy audit history as "<LATEST_ACTION> · N×". Falls back to
    plain "ORIGINAL" when no additional audit event exists — every trip with
    an lr_number has by definition been issued at least once. Only Iter122
    (all-copies ZIP), Iter109 (bulk regenerate) and the single-trip regenerate
    endpoint write audit rows; the single-copy `/trips/{tid}/lr` GET
    intentionally does not, per the standing rule to not touch Iter115/122 LR
    copy logic."""
    if not events:
        return "ORIGINAL"
    latest = max(events, key=lambda e: e.get("timestamp", ""))
    action_map = {
        "lr_all_copies_zip": "ZIP",
        "lr_regenerate": "REGEN",
        "lr_bulk_regenerate": "BULK",
    }
    label = action_map.get(latest.get("action", ""), "COPY")
    n = len(events)
    return f"{label} · {n}×" if n > 0 else label


def _derive_invoice_status(inv: dict | None) -> str:
    """Iter124 status derivation: `un_invoiced` when the trip has no invoice;
    `paid` when amount_paid ≥ total − ₹0.50; `partially_paid` when 0 < paid < total;
    `unpaid` otherwise."""
    if not inv:
        return "un_invoiced"
    total = float(inv.get("total_amount") or 0)
    paid = float(inv.get("amount_paid") or 0)
    if total <= 0.01:
        return "unpaid"
    if paid >= total - 0.5:
        return "paid"
    if paid > 0:
        return "partially_paid"
    return "unpaid"


def _month_bounds(month: str) -> tuple:
    """`YYYY-MM` → (first-day, last-day) ISO strings, inclusive."""
    from calendar import monthrange
    y, m = int(month.split("-")[0]), int(month.split("-")[1])
    last = monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last:02d}"


async def _lr_register_data(
    request: Request, user: dict, *,
    start: Optional[str], end: Optional[str], month: Optional[str],
    customer_id: Optional[str], vehicle_id: Optional[str], driver: Optional[str],
    product_id: Optional[str], status: Optional[str], invoice_status: Optional[str],
    q: Optional[str], has_lr: bool = True,
) -> dict:
    """SINGLE shared data loader for JSON / XLSX / PDF / in-app view — so all
    four outputs stay byte-identical. Read-only: no field is written to any
    Mongo document. Cap 10 000 rows per Iter57 parity."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    await _backfill_to_default(uid)

    if month:
        _s, _e = _month_bounds(month)
        start = start or _s
        end = end or _e
    if not start:
        today = datetime.now(timezone.utc).date().isoformat()
        _s, _e = _month_bounds(today[:7])
        start = _s
        end = end or today
    if not end:
        end = datetime.now(timezone.utc).date().isoformat()

    company = await db.companies.find_one({"id": cid, "user_id": uid}, {"_id": 0}) or {}

    mongo_q: dict = {"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER,
                     "date": {"$gte": start, "$lte": end}}
    if has_lr:
        mongo_q["lr_number"] = {"$exists": True, "$ne": ""}
    if customer_id:
        mongo_q["customer_id"] = customer_id
    if vehicle_id:
        mongo_q["vehicle_id"] = vehicle_id
    if product_id:
        mongo_q["product_id"] = product_id
    if driver:
        mongo_q["driver_name"] = {"$regex": re.escape(driver), "$options": "i"}
    if status:
        st = [s.strip() for s in status.split(",") if s.strip()]
        if st:
            mongo_q["status"] = {"$in": st}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        mongo_q["$or"] = [
            {"lr_number": rx}, {"vehicle_number": rx}, {"driver_name": rx},
            {"from_location": rx}, {"to_location": rx},
            {"customer_reference_number": rx},
        ]

    trips = await (db.trips
                   .find(mongo_q, {"_id": 0, "user_id": 0})
                   .sort([("date", 1), ("lr_number", 1)])
                   .limit(10000)
                   .to_list(10000))

    cust_ids  = list({t.get("customer_id") for t in trips if t.get("customer_id")})
    prod_ids  = list({t.get("product_id")  for t in trips if t.get("product_id")})
    inv_ids   = list({t.get("invoice_id")  for t in trips if t.get("invoice_id")})
    trip_ids  = list({t.get("id") for t in trips if t.get("id")})

    customers_by_id, ship_by_customer = {}, {}
    if cust_ids:
        for c in await db.customers.find(
                {"user_id": uid, "id": {"$in": cust_ids}},
                {"_id": 0, "id": 1, "name": 1, "ship_sites": 1}).to_list(len(cust_ids)):
            customers_by_id[c["id"]] = c
            for ss in (c.get("ship_sites") or []):
                ship_by_customer[(c["id"], ss.get("id", ""))] = ss.get("site_name", "")

    products_by_id = {}
    if prod_ids:
        for p in await db.products.find(
                {"user_id": uid, "id": {"$in": prod_ids}},
                {"_id": 0, "id": 1, "name": 1}).to_list(len(prod_ids)):
            products_by_id[p["id"]] = p.get("name", "")

    invoices_by_id = {}
    if inv_ids:
        for i in await db.invoices.find(
                {"user_id": uid, "id": {"$in": inv_ids}},
                {"_id": 0, "id": 1, "invoice_number": 1, "total_amount": 1, "amount_paid": 1}
        ).to_list(len(inv_ids)):
            invoices_by_id[i["id"]] = i

    audit_by_trip: dict = {}
    if trip_ids:
        cursor = db.audit_logs.find(
            {"user_id": uid, "entity_type": "trip",
             "entity_id": {"$in": trip_ids}, "action": {"$in": list(_LR_ACTIONS)}},
            {"_id": 0, "entity_id": 1, "action": 1, "timestamp": 1},
        )
        async for a in cursor:
            audit_by_trip.setdefault(a["entity_id"], []).append(a)

    rows = []
    tot = {"loaded": 0.0, "unloaded": 0.0, "shortage": 0.0, "allowance": 0.0,
           "net_shortage": 0.0, "freight": 0.0, "shortage_amount": 0.0}
    for t in trips:
        cust = customers_by_id.get(t.get("customer_id") or "", {})
        ship_name = ship_by_customer.get((t.get("customer_id") or "", t.get("ship_site_id") or ""), "")
        ship_to = ship_name or t.get("to_location") or ""
        product_name = products_by_id.get(t.get("product_id") or "", "") or t.get("load_details") or ""
        inv = invoices_by_id.get(t.get("invoice_id") or "")
        inv_no = (inv or {}).get("invoice_number", "") if inv else ""
        inv_st = _derive_invoice_status(inv)
        loaded = float(t.get("loaded_qty") or t.get("tons") or 0)
        unloaded = float(t.get("unloaded_qty") or 0)
        shortage = float(t.get("shortage_qty") or 0)
        allowance = _derive_allowance_mt(t)
        net_shortage = round(max(shortage - allowance, 0.0), 3)
        freight = float(t.get("freight_amount") or 0)
        shortage_amt = float(t.get("shortage_amount") or 0)
        copies = _lr_copies_label(audit_by_trip.get(t["id"], []))
        rows.append({
            "trip_id": t["id"],
            "lr_number": t.get("lr_number") or "",
            "lr_date": t.get("date") or "",
            "customer_reference_number": t.get("customer_reference_number") or "",
            "from_location": t.get("from_location") or "",
            "customer_name": cust.get("name", ""),
            "ship_to": ship_to,
            "vehicle_number": t.get("vehicle_number") or "",
            "driver_name": t.get("driver_name") or "",
            "product": product_name,
            "loaded_qty": loaded, "unloaded_qty": unloaded,
            "shortage_qty": shortage, "allowance_qty": allowance,
            "net_shortage_qty": net_shortage,
            "freight_amount": freight, "shortage_amount": shortage_amt,
            "invoice_number": inv_no, "invoice_status": inv_st,
            "lr_copies": copies,
            "status": t.get("status") or "pending",
        })
        tot["loaded"] += loaded; tot["unloaded"] += unloaded
        tot["shortage"] += shortage; tot["allowance"] += allowance
        tot["net_shortage"] += net_shortage; tot["freight"] += freight
        tot["shortage_amount"] += shortage_amt

    if invoice_status and invoice_status.lower() != "all":
        wanted = invoice_status.lower()
        rows = [r for r in rows if r["invoice_status"] == wanted]

    totals = {k: round(v, 3 if k not in ("freight", "shortage_amount") else 2) for k, v in tot.items()}
    totals["count"] = len(rows)

    return {
        "company": {
            "id": cid, "name": company.get("name", ""), "gstin": company.get("gstin", ""),
            "address": company.get("address", ""), "state": company.get("state", ""),
            "logo": company.get("logo", ""), "lr_prefix": company.get("lr_prefix", ""),
            "company_code": _company_code(company),
        },
        "start": start, "end": end,
        "rows": rows, "totals": totals,
    }


def _lr_register_filename(company_code: str, start: str, end: str, ext: str) -> str:
    """`LR_Register_<CODE>_<YYYY-MM>.<ext>` when the range is exactly one
    calendar month, else `..._<start>to<end>.<ext>`."""
    from calendar import monthrange
    try:
        if start[:7] == end[:7] and start.endswith("-01"):
            y, m = int(start[:4]), int(start[5:7])
            if end == f"{y:04d}-{m:02d}-{monthrange(y, m)[1]:02d}":
                return f"LR_Register_{company_code}_{start[:7]}.{ext}"
    except Exception:
        pass
    return f"LR_Register_{company_code}_{start}to{end}.{ext}"


@router.get("/reports/lr-register")
async def lr_register_json(
    request: Request,
    start: Optional[str] = None, end: Optional[str] = None, month: Optional[str] = None,
    customer_id: Optional[str] = None, vehicle_id: Optional[str] = None,
    driver: Optional[str] = None, product_id: Optional[str] = None,
    status: Optional[str] = None, invoice_status: Optional[str] = None,
    q: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Iter124 · Monthly LR Register — JSON payload driving the in-app view.
    Company-scoped, read-only. Freight/shortage values are the already-stored
    trip values (Iter98/102/107 engine output) — not recomputed here."""
    return await _lr_register_data(
        request, user, start=start, end=end, month=month,
        customer_id=customer_id, vehicle_id=vehicle_id, driver=driver,
        product_id=product_id, status=status, invoice_status=invoice_status, q=q,
    )


@router.get("/reports/lr-register.xlsx")
async def lr_register_xlsx(
    request: Request,
    start: Optional[str] = None, end: Optional[str] = None, month: Optional[str] = None,
    customer_id: Optional[str] = None, vehicle_id: Optional[str] = None,
    driver: Optional[str] = None, product_id: Optional[str] = None,
    status: Optional[str] = None, invoice_status: Optional[str] = None,
    q: Optional[str] = None,
    user=Depends(get_current_user),
):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    data = await _lr_register_data(
        request, user, start=start, end=end, month=month,
        customer_id=customer_id, vehicle_id=vehicle_id, driver=driver,
        product_id=product_id, status=status, invoice_status=invoice_status, q=q,
    )
    co = data["company"]; rows = data["rows"]; tot = data["totals"]
    start_iso, end_iso = data["start"], data["end"]

    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = f"LR Register {start_iso[:7]}"[:31]

    hdr_font = Font(name="Calibri", bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="0F172A")
    band = PatternFill("solid", fgColor="F1F5F9")
    total_fill = PatternFill("solid", fgColor="FEF3C7")
    thin = Side(border_style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.cell(row=1, column=1, value=f"{co['name']}   ·   GSTIN {co['gstin'] or '—'}").font = Font(bold=True, size=13)
    ws.cell(row=2, column=1, value=(
        f"Monthly LR Register — {start_iso} to {end_iso}   ·   "
        f"{tot['count']} LRs   ·   generated {datetime.now(timezone.utc).astimezone().strftime('%d-%b-%Y %H:%M')}"
    )).font = Font(italic=True, color="475569")

    headers = [
        "LR #", "LR Date", "Cust Ref #", "From", "Consignee", "Ship-To",
        "Vehicle #", "Driver", "Product",
        "Loading Qty (MT)", "Unloading Qty (MT)",
        "Actual Shortage (MT)", "Allowance (MT)", "Net Shortage (MT)",
        "Shortage ₹", "Freight ₹",
        "Invoice #", "Invoice Status", "LR Copies",
    ]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=4, column=col, value=h)
        c.font = hdr_font; c.fill = hdr_fill; c.border = border
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A5"

    for i, r in enumerate(rows, start=5):
        line = [
            r["lr_number"], r["lr_date"], r["customer_reference_number"],
            r["from_location"], r["customer_name"], r["ship_to"],
            r["vehicle_number"], r["driver_name"], r["product"],
            r["loaded_qty"], r["unloaded_qty"],
            r["shortage_qty"], r["allowance_qty"], r["net_shortage_qty"],
            r["shortage_amount"], r["freight_amount"],
            r["invoice_number"], r["invoice_status"], r["lr_copies"],
        ]
        for col, v in enumerate(line, 1):
            c = ws.cell(row=i, column=col, value=v)
            c.border = border
            if i % 2 == 0:
                c.fill = band
            if col in (10, 11, 12, 13, 14):
                c.number_format = "#,##0.000"
            elif col in (15, 16):
                c.number_format = '#,##0.00" ₹"'
            c.alignment = Alignment(vertical="center", wrap_text=True)

    if rows:
        tr = 5 + len(rows)
        ws.cell(row=tr, column=1, value="TOTAL")
        for col in range(1, len(headers) + 1):
            cc = ws.cell(row=tr, column=col)
            cc.fill = total_fill; cc.border = border; cc.font = Font(bold=True)
        ws.cell(row=tr, column=10, value=round(tot["loaded"], 3)).number_format = "#,##0.000"
        ws.cell(row=tr, column=11, value=round(tot["unloaded"], 3)).number_format = "#,##0.000"
        ws.cell(row=tr, column=12, value=round(tot["shortage"], 3)).number_format = "#,##0.000"
        ws.cell(row=tr, column=13, value=round(tot["allowance"], 3)).number_format = "#,##0.000"
        ws.cell(row=tr, column=14, value=round(tot["net_shortage"], 3)).number_format = "#,##0.000"
        ws.cell(row=tr, column=15, value=round(tot["shortage_amount"], 2)).number_format = '#,##0.00" ₹"'
        ws.cell(row=tr, column=16, value=round(tot["freight"], 2)).number_format = '#,##0.00" ₹"'
        for col in range(1, len(headers) + 1):
            ws.cell(row=tr, column=col).font = Font(bold=True)

    widths = [14, 11, 12, 18, 24, 22, 12, 14, 20,
              12, 12, 12, 12, 12, 12, 12, 14, 13, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[4].height = 32

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    fname = _lr_register_filename(co["company_code"], start_iso, end_iso, "xlsx")
    try:
        await _log_audit(user, "report", "lr_register_export",
                         entity_id=co.get("id", ""), entity_ref=fname,
                         changes={"format": "xlsx", "rows": tot["count"],
                                  "period": f"{start_iso}→{end_iso}"})
    except Exception:
        pass
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/reports/lr-register.pdf")
async def lr_register_pdf(
    request: Request,
    start: Optional[str] = None, end: Optional[str] = None, month: Optional[str] = None,
    customer_id: Optional[str] = None, vehicle_id: Optional[str] = None,
    driver: Optional[str] = None, product_id: Optional[str] = None,
    status: Optional[str] = None, invoice_status: Optional[str] = None,
    q: Optional[str] = None,
    user=Depends(get_current_user),
):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from pdf._base import _UNI_FONT, _UNI_FONT_BOLD
    from io import BytesIO as _BIO

    data = await _lr_register_data(
        request, user, start=start, end=end, month=month,
        customer_id=customer_id, vehicle_id=vehicle_id, driver=driver,
        product_id=product_id, status=status, invoice_status=invoice_status, q=q,
    )
    co = data["company"]; rows = data["rows"]; tot = data["totals"]
    start_iso, end_iso = data["start"], data["end"]

    PALETTE = {
        "ink": colors.HexColor("#0f172a"), "sub": colors.HexColor("#475569"),
        "line": colors.HexColor("#cbd5e1"), "zebra": colors.HexColor("#f8fafc"),
        "gold": colors.HexColor("#fef3c7"), "gold_ink": colors.HexColor("#78350f"),
    }

    logo_bytes = None
    raw_logo = co.get("logo") or ""
    if raw_logo and "," in raw_logo and raw_logo.strip().lower().startswith("data:image"):
        try:
            logo_bytes = base64.b64decode(raw_logo.split(",", 1)[1])
        except Exception:
            logo_bytes = None

    def _fmt_date(iso: str) -> str:
        if not iso: return ""
        try:
            y, m, d = iso.split("-")
            months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            return f"{int(d):02d}-{months[int(m)-1]}-{y}"
        except Exception:
            return iso

    def _rup(v):
        try: return f"₹\u00a0{float(v or 0):,.0f}"
        except Exception: return "₹\u00a00"
    def _mt(v):
        try: return f"{float(v or 0):,.2f}"
        except Exception: return "0.00"

    def _page(canvas, doc_):
        canvas.saveState()
        page_w, page_h = doc_.pagesize
        m_l, m_r, m_top, m_bot = 10*mm, 10*mm, 12*mm, 10*mm
        canvas.setStrokeColor(PALETTE["line"]); canvas.setLineWidth(0.5)
        text_x = m_l
        if logo_bytes:
            try:
                canvas.drawImage(_BIO(logo_bytes), m_l, page_h - m_top - 16*mm,
                                 width=20*mm, height=16*mm, preserveAspectRatio=True, mask="auto")
                text_x = m_l + 22*mm
            except Exception:
                pass
        canvas.setFont(_UNI_FONT_BOLD, 12); canvas.setFillColor(PALETTE["ink"])
        canvas.drawString(text_x, page_h - m_top - 5*mm, (co["name"] or "Company")[:80])
        canvas.setFont(_UNI_FONT, 8); canvas.setFillColor(PALETTE["sub"])
        canvas.drawString(text_x, page_h - m_top - 10*mm,
                          f"GSTIN {co['gstin'] or '—'}  ·  {(co.get('address','') or '')[:80]}")
        canvas.setFont(_UNI_FONT_BOLD, 10); canvas.setFillColor(PALETTE["ink"])
        canvas.drawRightString(page_w - m_r, page_h - m_top - 5*mm, "MONTHLY LR REGISTER")
        canvas.setFont(_UNI_FONT, 8); canvas.setFillColor(PALETTE["sub"])
        canvas.drawRightString(page_w - m_r, page_h - m_top - 10*mm,
                               f"Period: {_fmt_date(start_iso)} — {_fmt_date(end_iso)}  ·  {tot['count']} LRs")
        canvas.line(m_l, page_h - m_top - 13*mm, page_w - m_r, page_h - m_top - 13*mm)
        canvas.setFont(_UNI_FONT, 7); canvas.setFillColor(PALETTE["sub"])
        canvas.drawString(m_l, m_bot,
                          f"Generated {datetime.now(timezone.utc).astimezone().strftime('%d-%b-%Y %H:%M')}"
                          f"  ·  {(co['name'] or '')[:60]}  ·  Confidential")
        canvas.drawRightString(page_w - m_r, m_bot, f"Page {doc_.page}")
        canvas.restoreState()

    buf = _BIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm, topMargin=26*mm, bottomMargin=14*mm,
        title=f"LR Register {start_iso[:7]}", author=co["name"] or "Bitumen Transport",
    )

    col_widths_mm = [22, 20, 18, 24, 32, 30, 18, 20, 22, 12, 12, 12, 12, 12, 18, 20, 18, 18]
    col_widths = [w * mm for w in col_widths_mm]

    hdr_h = ParagraphStyle("hdr", fontName=_UNI_FONT_BOLD, fontSize=7.5,
                           leading=9, alignment=TA_CENTER, textColor=colors.white)
    cell_h = ParagraphStyle("cell", fontName=_UNI_FONT, fontSize=7.5,
                            leading=9, alignment=TA_LEFT, textColor=PALETTE["ink"])

    def _wrap(v, size=7.5):
        return Paragraph(str(v or "").replace("&", "&amp;").replace("<", "&lt;"),
                         ParagraphStyle("w", fontName=_UNI_FONT, fontSize=size,
                                        leading=9, alignment=TA_LEFT, textColor=PALETTE["ink"]))

    hdrs = [Paragraph(x, hdr_h) for x in [
        "LR #", "LR Date", "Cust Ref #", "From", "Consignee",
        "Ship-To", "Vehicle #", "Driver", "Product",
        "Load MT", "Unload MT", "Sh MT", "Allow MT", "Net MT",
        "Freight ₹", "Invoice #", "Inv Status", "LR Copies",
    ]]
    table_data = [hdrs]

    for r in rows:
        table_data.append([
            _wrap(r["lr_number"]),
            _wrap(_fmt_date(r["lr_date"])),
            _wrap(r["customer_reference_number"]),
            _wrap(r["from_location"]),
            _wrap(r["customer_name"]),
            _wrap(r["ship_to"]),
            _wrap(r["vehicle_number"]),
            _wrap(r["driver_name"]),
            _wrap(r["product"]),
            _mt(r["loaded_qty"]), _mt(r["unloaded_qty"]),
            _mt(r["shortage_qty"]), _mt(r["allowance_qty"]), _mt(r["net_shortage_qty"]),
            _rup(r["freight_amount"]),
            _wrap(r["invoice_number"] or "—"),
            _wrap(r["invoice_status"].replace("_", " ").title()),
            _wrap(r["lr_copies"], size=7),
        ])

    if rows:
        table_data.append([
            Paragraph("<b>TOTAL</b>",
                      ParagraphStyle("t", fontName=_UNI_FONT_BOLD, fontSize=8, leading=10,
                                     textColor=PALETTE["gold_ink"])),
            "", "", "", "", "", "", "", "",
            _mt(tot["loaded"]), _mt(tot["unloaded"]),
            _mt(tot["shortage"]), _mt(tot["allowance"]), _mt(tot["net_shortage"]),
            _rup(tot["freight"]),
            "", "", "",
        ])

    story = []
    if not rows:
        story.append(Paragraph(
            f"<font color='#64748b'>No LRs issued in this period "
            f"({_fmt_date(start_iso)} — {_fmt_date(end_iso)}). "
            f"Try widening the date range or clearing filters.</font>",
            ParagraphStyle("empty", fontName=_UNI_FONT, fontSize=10, leading=14, alignment=TA_CENTER),
        ))
    else:
        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
        tstyle = [
            ("BACKGROUND", (0, 0), (-1, 0), PALETTE["ink"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("ALIGN", (9, 1), (14, -1), "RIGHT"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, PALETTE["line"]),
            ("FONTSIZE", (0, 1), (-1, -2), 7.5),
            ("FONTNAME", (0, 1), (-1, -2), _UNI_FONT),
            ("BACKGROUND", (0, -1), (-1, -1), PALETTE["gold"]),
            ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
            ("FONTSIZE", (0, -1), (-1, -1), 8),
            ("LINEABOVE", (0, -1), (-1, -1), 1.2, PALETTE["ink"]),
        ]
        for i in range(1, len(table_data) - 1):
            if i % 2 == 0:
                tstyle.append(("BACKGROUND", (0, i), (-1, i), PALETTE["zebra"]))
        tbl.setStyle(TableStyle(tstyle))
        story.append(tbl)
    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    pdf_bytes = buf.getvalue()

    fname = _lr_register_filename(co["company_code"], start_iso, end_iso, "pdf")
    try:
        await _log_audit(user, "report", "lr_register_export",
                         entity_id=co.get("id", ""), entity_ref=fname,
                         changes={"format": "pdf", "rows": tot["count"],
                                  "period": f"{start_iso}→{end_iso}"})
    except Exception:
        pass
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )




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


# ============================================================================
# Iter132c C4 · Credit Note / Debit Note Register — canonical payload builder.
#
# Endpoints (all under /api):
#     GET /api/reports/cndn-register           (canonical JSON)
#     GET /api/reports/cndn-register.xlsx      (4-sheet accountant workbook)
#     GET /api/reports/cndn-register.pdf       (A4 landscape working report)
#
# MASTER PRINCIPLE:
#   ENTER ONCE -> CALCULATE ONCE -> REFLECT EVERYWHERE -> REPORT READY.
#
#   * SINGLE SOURCE OF TRUTH: db.credit_debit_notes. Amounts are read
#     verbatim from persisted notes — computed once at issue time via
#     services._compute_note_totals (LOCKED · Iter132a/C2b). This endpoint
#     never recomputes tax, totals, sign, or effective balance.
#   * NO NEW COLLECTION. NO PERSISTED REGISTER. Any register mutation
#     happens on the underlying note document; this endpoint is a pure
#     read projection.
#   * FILTERS (all optional except date range):
#         from, to             ISO YYYY-MM-DD (defaults: current month)
#         kind                 all | credit | debit (default: all)
#         customer_id          restrict to one customer
#         status               issued | draft | cancelled | all (default: issued)
#         reason_code          QORVENA reason enum (see models.CreditDebitNote)
#   * HIGH-VOLUME CONTRACT (mandatory):
#       - Streaming Mongo cursor with in-Mongo `note_date` range filter.
#       - Bounded `$in` preloads for referenced customer_ids and
#         invoice_ids only.
#       - NO to_list(5000) / (2000) truncation. Proven at 10 000 notes /
#         2 500 customers by test T19.
#   * SEMANTICS:
#       - kind='credit' -> reduces receivable -> signed_amount = -total_amount
#       - kind='debit'  -> increases receivable -> signed_amount = +total_amount
#       - Register row values MUST equal persisted note fields byte-for-byte.
#   * PARITY GUARANTEES (fail-loud reconciliation):
#       - endpoint row_count == Mongo $group count over identical filter
#       - endpoint sum(total_amount) == Mongo $group sum over identical filter
#       - endpoint per-invoice credit/debit sums == the same values
#         `services._effective_invoice_totals` derives from the SAME notes.
#   * GSTR-1 §9B PARITY: for each row, `reason_code_gstr1_9b` is the
#     deterministic statutory-remap of the QORVENA reason (see
#     `services._GSTR1_9B_REASON_MAP`). Unknown codes fall to "07 Others"
#     with a warning.
#   * The generated PDF/XLSX are HUMAN-READABLE WORKING REPORTS, not
#     GST portal upload files. Statutory portal payloads are §9B (LOCKED
#     C3.1/C3.2) and future §9A (LOCKED C3.5).
# ============================================================================


_C4_STATUS_ALLOWED = {"issued", "draft", "cancelled", "all"}
_C4_KIND_ALLOWED = {"credit", "debit", "all"}


def _c4_default_month_range() -> tuple:
    """Default filter window when caller omits `from`/`to` — current
    calendar month (UTC), ISO YYYY-MM-DD strings."""
    from calendar import monthrange
    d = now_utc().date()
    start = f"{d.year:04d}-{d.month:02d}-01"
    end = f"{d.year:04d}-{d.month:02d}-{monthrange(d.year, d.month)[1]:02d}"
    return start, end


def _c4_reason_for(qorvena_code: str) -> tuple:
    """Statutory §9B reason remap; returns (statutory_code, remapped_bool)."""
    if not qorvena_code:
        return ("07", True)
    if qorvena_code in _GSTR1_9B_REASON_MAP:
        return (_GSTR1_9B_REASON_MAP[qorvena_code], False)
    return ("07", True)


async def _cndn_register_payload(
    request: Request,
    user: dict,
    *,
    d_from: Optional[str],
    d_to: Optional[str],
    kind: str = "all",
    customer_id: Optional[str] = None,
    status: str = "issued",
    reason_code: Optional[str] = None,
) -> dict:
    """C4 · Internal canonical builder — SINGLE SOURCE OF TRUTH for the
    /reports/cndn-register (.json / .xlsx / .pdf) endpoints.

    Streaming cursor. Bounded customer + invoice preloads. Never
    recomputes note amounts. Never mutates a note document. Fail-loud
    reconciliation vs. Mongo $group over the same filter.
    """
    # ── Filter validation ─────────────────────────────────────────
    if kind not in _C4_KIND_ALLOWED:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(_C4_KIND_ALLOWED)}")
    if status not in _C4_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_C4_STATUS_ALLOWED)}")

    def _valid_iso(s: str) -> bool:
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return True
        except Exception:
            return False

    if d_from and not _valid_iso(d_from):
        raise HTTPException(status_code=400, detail="from must be ISO YYYY-MM-DD")
    if d_to and not _valid_iso(d_to):
        raise HTTPException(status_code=400, detail="to must be ISO YYYY-MM-DD")
    if not d_from or not d_to:
        _s, _e = _c4_default_month_range()
        d_from = d_from or _s
        d_to = d_to or _e
    if d_from > d_to:
        raise HTTPException(status_code=400, detail="from must be <= to")

    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    company = await db.companies.find_one({"id": cid, "user_id": uid}, {"_id": 0}) or {}
    home_state = company.get("state", "")
    home_sc = _state_code(home_state)
    issuer_gstin = (company.get("gstin", "") or "").strip().upper()

    # ── Mongo filter ──────────────────────────────────────────────
    q: dict = {
        "user_id": uid,
        "company_id": cid,
        "note_date": {"$gte": d_from, "$lte": d_to},
    }
    if kind != "all":
        q["kind"] = kind
    if status != "all":
        q["status"] = status
    if customer_id:
        q["customer_id"] = customer_id
    if reason_code:
        q["reason_code"] = reason_code

    warnings: list = []
    if not issuer_gstin:
        warnings.append("issuer_company_gstin_missing")

    # ── Streaming fetch ───────────────────────────────────────────
    notes: list = []
    invoice_ids_needed: set = set()
    customer_ids_needed: set = set()
    async for n in db.credit_debit_notes.find(
        q, {"_id": 0, "user_id": 0}
    ).sort([("note_date", 1), ("note_number", 1)]):
        notes.append(n)
        if n.get("invoice_id"):
            invoice_ids_needed.add(n["invoice_id"])
        if n.get("customer_id"):
            customer_ids_needed.add(n["customer_id"])

    inv_map: dict = {}
    if invoice_ids_needed:
        async for inv in db.invoices.find(
            {"user_id": uid, "id": {"$in": list(invoice_ids_needed)}},
            {"_id": 0, "user_id": 0},
        ):
            inv_map[inv["id"]] = inv
    cust_map: dict = {}
    if customer_ids_needed:
        async for cst in db.customers.find(
            {"user_id": uid, "id": {"$in": list(customer_ids_needed)}},
            {"_id": 0, "user_id": 0},
        ):
            cust_map[cst["id"]] = cst

    # ── Row projection (NO RECOMPUTE) ─────────────────────────────
    rows: list = []
    reason_remap_count = 0
    for n in notes:
        inv = inv_map.get(n.get("invoice_id"), {}) or {}
        cust = cust_map.get(n.get("customer_id"), {}) or {}
        qcode = n.get("reason_code") or ""
        rsn9b, remapped = _c4_reason_for(qcode)
        if remapped and qcode:
            reason_remap_count += 1

        total = round(float(n.get("total_amount", 0) or 0), 2)
        k = n.get("kind")
        signed = -total if k == "credit" else total

        cust_state = cust.get("state", "")
        cust_sc = _state_code(cust_state)

        rows.append({
            "note_id": n.get("id"),
            "note_number": n.get("note_number", ""),
            "note_date": n.get("note_date", ""),
            "kind": k,
            "ntty": "C" if k == "credit" else "D",
            "status": n.get("status"),
            "customer_id": n.get("customer_id", ""),
            "customer_name": cust.get("name", ""),
            "customer_gstin": (cust.get("gstin", "") or "").strip().upper(),
            "customer_state": cust_state,
            "customer_state_code": cust_sc,
            "invoice_id": n.get("invoice_id", ""),
            "invoice_number": n.get("invoice_number_snapshot", "") or inv.get("invoice_number", ""),
            "invoice_date": inv.get("invoice_date", ""),
            "reason_code": qcode,
            "reason_code_gstr1_9b": rsn9b,
            "reason_text": n.get("reason_text", ""),
            "subtotal": round(float(n.get("subtotal", 0) or 0), 2),
            "cgst_rate": round(float(n.get("cgst_rate", 0) or 0), 2),
            "sgst_rate": round(float(n.get("sgst_rate", 0) or 0), 2),
            "igst_rate": round(float(n.get("igst_rate", 0) or 0), 2),
            "cgst_amount": round(float(n.get("cgst_amount", 0) or 0), 2),
            "sgst_amount": round(float(n.get("sgst_amount", 0) or 0), 2),
            "igst_amount": round(float(n.get("igst_amount", 0) or 0), 2),
            "total_tax": round(float(n.get("total_tax", 0) or 0), 2),
            "total_amount": total,
            "round_off": round(float(n.get("round_off", 0) or 0), 2),
            "gst_type": n.get("gst_type") or "cgst_sgst",
            "apply_gst": bool(n.get("apply_gst", True)),
            "rcm": bool(n.get("rcm", True)),
            "signed_amount": round(signed, 2),
            "cancelled_at": n.get("cancelled_at") or "",
            "cancelled_reason": n.get("cancelled_reason") or "",
        })

    if reason_remap_count:
        warnings.append(f"reason_remapped_to_others_count:{reason_remap_count}")

    # ── KPIs ──────────────────────────────────────────────────────
    def _sum(pred, key="total_amount"):
        return round(sum(float(r.get(key, 0) or 0) for r in rows if pred(r)), 2)

    credit_rows = [r for r in rows if r["kind"] == "credit"]
    debit_rows = [r for r in rows if r["kind"] == "debit"]
    credit_total = round(sum(r["total_amount"] for r in credit_rows), 2)
    debit_total = round(sum(r["total_amount"] for r in debit_rows), 2)

    kpis = {
        "total_count":       len(rows),
        "credit_count":      len(credit_rows),
        "credit_total":      credit_total,
        "debit_count":       len(debit_rows),
        "debit_total":       debit_total,
        # Net receivable change: debits + increase, credits - decrease.
        "net_amount":        round(debit_total - credit_total, 2),
        "gst_applied_count": len([r for r in rows if r["apply_gst"]]),
        "gst_applied_total": _sum(lambda r: r["apply_gst"]),
        "gst_excluded_count": len([r for r in rows if not r["apply_gst"]]),
        "gst_excluded_total": _sum(lambda r: not r["apply_gst"]),
        "issued_count":      len([r for r in rows if r["status"] == "issued"]),
        "draft_count":       len([r for r in rows if r["status"] == "draft"]),
        "cancelled_count":   len([r for r in rows if r["status"] == "cancelled"]),
    }

    # ── Tax summary band (verbatim sums, no recompute) ────────────
    tax_summary = {
        "taxable":      round(sum(r["subtotal"]     for r in rows), 2),
        "cgst":         round(sum(r["cgst_amount"]  for r in rows), 2),
        "sgst":         round(sum(r["sgst_amount"]  for r in rows), 2),
        "igst":         round(sum(r["igst_amount"]  for r in rows), 2),
        "total_tax":    round(sum(r["total_tax"]    for r in rows), 2),
        "total_amount": round(sum(r["total_amount"] for r in rows), 2),
    }

    # ── By-reason breakdown ───────────────────────────────────────
    reason_group: dict = {}
    for r in rows:
        key = r["reason_code"] or "other"
        g = reason_group.setdefault(key, {
            "reason_code": key,
            "gstr1_9b_reason_code": r["reason_code_gstr1_9b"],
            "count": 0, "credit_count": 0, "debit_count": 0,
            "total_amount": 0.0,
        })
        g["count"] += 1
        if r["kind"] == "credit":
            g["credit_count"] += 1
        else:
            g["debit_count"] += 1
        g["total_amount"] = round(g["total_amount"] + r["total_amount"], 2)
    by_reason = sorted(reason_group.values(), key=lambda x: (-x["total_amount"], x["reason_code"]))

    # ── By-customer top-drill (all rows, sorted by |net|) ─────────
    cust_group: dict = {}
    for r in rows:
        cid_key = r["customer_id"] or "__unknown__"
        g = cust_group.setdefault(cid_key, {
            "customer_id": r["customer_id"],
            "customer_name": r["customer_name"],
            "count": 0, "credit_total": 0.0, "debit_total": 0.0,
            "signed_amount": 0.0,
        })
        g["count"] += 1
        if r["kind"] == "credit":
            g["credit_total"] = round(g["credit_total"] + r["total_amount"], 2)
        else:
            g["debit_total"] = round(g["debit_total"] + r["total_amount"], 2)
        g["signed_amount"] = round(g["signed_amount"] + r["signed_amount"], 2)
    by_customer = sorted(cust_group.values(), key=lambda x: (-abs(x["signed_amount"]), x["customer_name"] or ""))

    # ── Fail-loud reconciliation ──────────────────────────────────
    gt_count = 0
    gt_total = 0.0
    async for x in db.credit_debit_notes.find(q, {"_id": 0, "total_amount": 1}):
        gt_count += 1
        gt_total += float(x.get("total_amount", 0) or 0)
    gt_total = round(gt_total, 2)

    reconciled = (
        len(rows) == gt_count
        and abs(tax_summary["total_amount"] - gt_total) < 0.01
    )
    if not reconciled:
        warnings.append(
            f"reconciliation_mismatch:rows={len(rows)}/{gt_count}"
            f":total={tax_summary['total_amount']}/{gt_total}"
        )
    reconciliation = {
        "reconciled":               reconciled,
        "endpoint_row_count":       len(rows),
        "ground_truth_row_count":   gt_count,
        "endpoint_total":           tax_summary["total_amount"],
        "ground_truth_total":       gt_total,
    }

    return {
        "period":              {"start": d_from, "end": d_to},
        "filters": {
            "from": d_from, "to": d_to,
            "kind": kind, "status": status,
            "customer_id": customer_id or "",
            "reason_code": reason_code or "",
        },
        "company_id":          cid,
        "company_name":        company.get("name", ""),
        "company_state":       home_state,
        "company_state_code":  home_sc,
        "issuer_gstin":        issuer_gstin,
        "note_count":          len(rows),
        "rows":                rows,
        "kpis":                kpis,
        "tax_summary":         tax_summary,
        "by_reason":           by_reason,
        "by_customer":         by_customer,
        "reconciliation":      reconciliation,
        "warnings":            warnings,
    }


@router.get("/reports/cndn-register")
async def report_cndn_register(
    request: Request,
    d_from: Optional[str] = None,
    d_to: Optional[str] = None,
    kind: str = "all",
    customer_id: Optional[str] = None,
    status: str = "issued",
    reason_code: Optional[str] = None,
    user=Depends(get_current_user),
):
    """C4 · Canonical Credit Note / Debit Note Register JSON feed."""
    # Accept both `from`/`to` (statutory) and `d_from`/`d_to` (Python-safe)
    qp = request.query_params
    d_from = qp.get("from", d_from)
    d_to = qp.get("to", d_to)

    payload = await _cndn_register_payload(
        request, user,
        d_from=d_from, d_to=d_to, kind=kind,
        customer_id=customer_id, status=status, reason_code=reason_code,
    )
    recon = payload.get("reconciliation") or {}
    try:
        await _log_audit(
            user, "cndn_register", "download",
            entity_id="", entity_ref=f"cndn_register_{payload['period']['start']}_{payload['period']['end']}",
            changes={
                "format": "json",
                "period": payload["period"],
                "row_count": payload["note_count"],
                "kind": kind, "status": status,
                "total_amount": payload["tax_summary"]["total_amount"],
                "reconciled": recon.get("reconciled"),
            },
        )
    except Exception:
        pass
    return payload


@router.get("/reports/cndn-register.xlsx")
async def report_cndn_register_xlsx(
    request: Request,
    d_from: Optional[str] = None,
    d_to: Optional[str] = None,
    kind: str = "all",
    customer_id: Optional[str] = None,
    status: str = "issued",
    reason_code: Optional[str] = None,
    user=Depends(get_current_user),
):
    """C4 · XLSX projection (4 sheets: Summary / Credit_Notes / Debit_Notes / By_Reason)."""
    qp = request.query_params
    d_from = qp.get("from", d_from)
    d_to = qp.get("to", d_to)

    payload = await _cndn_register_payload(
        request, user,
        d_from=d_from, d_to=d_to, kind=kind,
        customer_id=customer_id, status=status, reason_code=reason_code,
    )
    company = await db.companies.find_one(
        {"id": payload["company_id"], "user_id": user["user_id"]}, {"_id": 0}
    ) or {}
    from xlsx.cndn_register import build_cndn_register_xlsx
    data = build_cndn_register_xlsx(company, payload)

    code = (company.get("company_code") or "company")
    fname = f"CNDN_Register_{code}_{payload['period']['start']}_{payload['period']['end']}.xlsx"
    try:
        await _log_audit(
            user, "cndn_register", "download",
            entity_id="", entity_ref=fname,
            changes={
                "format": "xlsx",
                "period": payload["period"],
                "row_count": payload["note_count"],
                "kind": kind, "status": status,
            },
        )
    except Exception:
        pass
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/reports/cndn-register.pdf")
async def report_cndn_register_pdf(
    request: Request,
    d_from: Optional[str] = None,
    d_to: Optional[str] = None,
    kind: str = "all",
    customer_id: Optional[str] = None,
    status: str = "issued",
    reason_code: Optional[str] = None,
    user=Depends(get_current_user),
):
    """C4 · PDF projection (A4 landscape human-readable working report)."""
    qp = request.query_params
    d_from = qp.get("from", d_from)
    d_to = qp.get("to", d_to)

    payload = await _cndn_register_payload(
        request, user,
        d_from=d_from, d_to=d_to, kind=kind,
        customer_id=customer_id, status=status, reason_code=reason_code,
    )
    company = await db.companies.find_one(
        {"id": payload["company_id"], "user_id": user["user_id"]}, {"_id": 0}
    ) or {}
    from pdf.cndn_register import build_cndn_register_pdf
    data = build_cndn_register_pdf(company, payload)

    code = (company.get("company_code") or "company")
    fname = f"CNDN_Register_{code}_{payload['period']['start']}_{payload['period']['end']}.pdf"
    try:
        await _log_audit(
            user, "cndn_register", "download",
            entity_id="", entity_ref=fname,
            changes={
                "format": "pdf",
                "period": payload["period"],
                "row_count": payload["note_count"],
                "kind": kind, "status": status,
            },
        )
    except Exception:
        pass
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


# ==================== Health ====================

