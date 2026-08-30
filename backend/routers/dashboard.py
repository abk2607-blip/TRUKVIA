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
)

router = APIRouter(prefix="/api")

@router.get("/dashboard")
async def dashboard(request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    # Iter86 — LIVE_ONLY_FILTER excludes historical/imported records from KPIs.
    trips = await db.trips.find({"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0, "user_id": 0}).to_list(5000)
    customers = await db.customers.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(2000)

    total_revenue = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    total_expense = round(sum(t.get("total_expense", 0.0) for t in trips), 2)
    total_profit = round(total_revenue - total_expense, 2)
    trip_count = len(trips)
    pending_trips = len([t for t in trips if t.get("status") == "pending"])
    invoiced_trips = trip_count - pending_trips

    # Iter132c C1 · B1 — streaming aggregation avoids to_list(2000) truncation
    # on companies with >2000 invoices. Pre-fetch issued notes ONCE for the
    # company, group by invoice_id, then stream invoices via async cursor.
    # Two DB queries total (notes + invoices); no N+1. Cancelled notes are
    # naturally excluded via status="issued". Persisted invoice fields untouched.
    notes_by_inv: dict = {}
    async for n in db.credit_debit_notes.find(
        {"user_id": uid, "company_id": cid, "status": "issued"},
        {"_id": 0, "invoice_id": 1, "kind": 1, "total_amount": 1},
    ):
        notes_by_inv.setdefault(n.get("invoice_id"), []).append(n)

    cust_map = {c["id"]: c for c in customers}
    receivables: dict = {}
    today = now_utc().date()
    total_billed = 0.0
    total_received = 0.0
    total_billed_effective = 0.0
    total_receivable_effective = 0.0
    total_credits = 0.0
    total_debits = 0.0
    invoice_count = 0

    async for i in db.invoices.find(
        {"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER},
        {"_id": 0, "user_id": 0},
    ):
        invoice_count += 1
        raw_total = float(i.get("total_amount", 0.0))
        paid = float(i.get("amount_paid", 0.0))
        raw_bal = float(i.get("balance_due", 0.0))
        notes = notes_by_inv.get(i.get("id"), [])
        credits = sum(float(n.get("total_amount") or 0) for n in notes if n.get("kind") == "credit")
        debits = sum(float(n.get("total_amount") or 0) for n in notes if n.get("kind") == "debit")
        eff_total = raw_total - credits + debits
        eff_bal = eff_total - paid

        total_billed += raw_total
        total_received += paid
        total_billed_effective += eff_total
        total_receivable_effective += eff_bal
        total_credits += credits
        total_debits += debits

        if raw_bal > 0 or eff_bal > 0:
            cust_id = i.get("customer_id")
            c = cust_map.get(cust_id, {})
            rec = receivables.setdefault(cust_id, {
                "customer_id": cust_id,
                "customer_name": c.get("name", "Unknown"),
                "customer_phone": c.get("phone", ""),
                "balance": 0.0,
                "balance_effective": 0.0,
                "invoices": 0,
                "oldest_days": 0,
            })
            rec["balance"] += raw_bal
            rec["balance_effective"] += eff_bal
            rec["invoices"] += 1
            try:
                inv_date = datetime.fromisoformat(i["invoice_date"]).date()
                days = (today - inv_date).days
                if days > rec["oldest_days"]:
                    rec["oldest_days"] = days
            except Exception:
                pass

    for rec in receivables.values():
        rec["balance"] = round(rec["balance"], 2)
        rec["balance_effective"] = round(rec["balance_effective"], 2)

    total_billed = round(total_billed, 2)
    total_received = round(total_received, 2)
    total_receivable = round(total_billed - total_received, 2)
    total_billed_effective = round(total_billed_effective, 2)
    total_receivable_effective = round(total_receivable_effective, 2)
    total_credits = round(total_credits, 2)
    total_debits = round(total_debits, 2)

    receivables_list = sorted(receivables.values(), key=lambda x: -x["balance"])

    recent_trips = sorted(trips, key=lambda t: t.get("date", ""), reverse=True)[:8]
    for rt in recent_trips:
        rt["customer_name"] = cust_map.get(rt.get("customer_id"), {}).get("name", "")

    # Vehicle expiry alerts (within 60 days or expired)
    vehicles = await db.vehicles.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(500)
    expiry_alerts = []
    for v in vehicles:
        v = _vehicle_expiry_stats(v)
        for field, info in (v.get("alerts") or {}).items():
            if info["status"] in ("expired", "expiring"):
                expiry_alerts.append({
                    "vehicle_number": v.get("vehicle_number"),
                    "document": field.replace("_expiry", "").upper(),
                    "date": info["date"],
                    "days": info["days"],
                    "status": info["status"],
                })
    expiry_alerts.sort(key=lambda x: x["days"])

    return {
        "total_revenue": total_revenue,
        "total_expense": total_expense,
        "total_profit": total_profit,
        "trip_count": trip_count,
        "pending_trips": pending_trips,
        "invoiced_trips": invoiced_trips,
        "total_billed": total_billed,
        "total_billed_effective": total_billed_effective,
        "total_received": total_received,
        "total_receivable": total_receivable,
        "total_receivable_effective": total_receivable_effective,
        "credits_total": total_credits,
        "debits_total": total_debits,
        "customer_count": len(customers),
        "invoice_count": invoice_count,
        "receivables": receivables_list,
        "recent_trips": recent_trips,
        "expiry_alerts": expiry_alerts,
    }


@router.get("/dashboard/expenditure-breakdown")
async def dashboard_expenditure_breakdown(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Aggregate the dynamic Other-Expenditure entries across every trip for the
    active company in the given date range, grouped by type.

    Returns:
      {
        "period": {"start": start, "end": end},
        "total": <sum>,
        "trip_count": <trips with any expenditure>,
        "by_type": [{"type": "Driver Food", "amount": 3200.0, "count": 12, "pct": 34.5}, ...]
      }
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0, "date": 1, "other_expenditures": 1}).to_list(20000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]
    by_type: dict = {}
    trip_ids_with = 0
    total = 0.0
    for t in trips:
        rows = t.get("other_expenditures") or []
        if not rows:
            continue
        counted = False
        for r in rows:
            try:
                amt = float(r.get("amount") or 0)
            except Exception:
                amt = 0.0
            if amt <= 0:
                continue
            k = (r.get("type") or "Others").strip() or "Others"
            b = by_type.setdefault(k, {"type": k, "amount": 0.0, "count": 0})
            b["amount"] += amt
            b["count"] += 1
            total += amt
            counted = True
        if counted:
            trip_ids_with += 1
    for b in by_type.values():
        b["amount"] = round(b["amount"], 2)
        b["pct"] = round(b["amount"] / total * 100.0, 2) if total > 0 else 0.0
    return {
        "period": {"start": start, "end": end},
        "total": round(total, 2),
        "trip_count": trip_ids_with,
        "by_type": sorted(by_type.values(), key=lambda x: -x["amount"]),
    }


@router.get("/dashboard/expenditure-detail")
async def dashboard_expenditure_detail(
    request: Request,
    type: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Drill-down: return every trip that spent on the given expenditure `type`
    within the range for the active company. One row per matching expenditure
    entry (a trip can have multiple entries of the same type).

    Returns: {type, period, total, count, trips: [{trip_id, date, lr_number,
                vehicle_number, from_location, to_location, amount, remarks}]}
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    match_type = (type or "").strip().lower()
    if not match_type:
        raise HTTPException(status_code=400, detail="type is required")
    # Iter69 — Push the date filter down into the mongo query so tenants with
    # >20k trips (formerly capped in-memory) don't silently drop rows.
    q: dict = {"user_id": uid, "company_id": cid, **LIVE_ONLY_FILTER}
    if start or end:
        drange: dict = {}
        if start:
            drange["$gte"] = start
        if end:
            drange["$lte"] = end
        q["date"] = drange
    trips = await db.trips.find(
        q,
        {"_id": 0, "id": 1, "date": 1, "lr_number": 1, "vehicle_number": 1,
         "from_location": 1, "to_location": 1, "other_expenditures": 1},
    ).to_list(20000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]
    rows = []
    total = 0.0
    for t in trips:
        for r in (t.get("other_expenditures") or []):
            rt = (r.get("type") or "").strip().lower()
            if rt != match_type:
                continue
            try:
                amt = float(r.get("amount") or 0)
            except Exception:
                amt = 0.0
            if amt <= 0:
                continue
            rows.append({
                "trip_id": t.get("id"),
                "date": r.get("date") or t.get("date", ""),
                "lr_number": t.get("lr_number") or "",
                "vehicle_number": t.get("vehicle_number") or "",
                "from_location": t.get("from_location") or "",
                "to_location": t.get("to_location") or "",
                "amount": round(amt, 2),
                "remarks": r.get("remarks") or "",
            })
            total += amt
    rows.sort(key=lambda r: (r["date"], r["trip_id"]), reverse=True)
    return {
        "type": type,
        "period": {"start": start, "end": end},
        "total": round(total, 2),
        "count": len(rows),
        "trips": rows,
    }

# ==================== Drivers ====================

