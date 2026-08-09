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

@router.get("/dashboard")
async def dashboard(request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(5000)
    invoices = await db.invoices.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(2000)
    customers = await db.customers.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(2000)

    total_revenue = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    total_expense = round(sum(t.get("total_expense", 0.0) for t in trips), 2)
    total_profit = round(total_revenue - total_expense, 2)
    trip_count = len(trips)
    pending_trips = len([t for t in trips if t.get("status") == "pending"])
    invoiced_trips = trip_count - pending_trips

    total_billed = round(sum(i.get("total_amount", 0.0) for i in invoices), 2)
    total_received = round(sum(i.get("amount_paid", 0.0) for i in invoices), 2)
    total_receivable = round(total_billed - total_received, 2)

    # Customer-wise receivables (with phone + oldest invoice for overdue calc)
    cust_map = {c["id"]: c for c in customers}
    receivables = {}
    today = now_utc().date()
    for i in invoices:
        cust_id = i["customer_id"]
        bal = i.get("balance_due", 0.0)
        if bal <= 0:
            continue
        c = cust_map.get(cust_id, {})
        rec = receivables.setdefault(cust_id, {
            "customer_id": cust_id,
            "customer_name": c.get("name", "Unknown"),
            "customer_phone": c.get("phone", ""),
            "balance": 0.0,
            "invoices": 0,
            "oldest_days": 0,
        })
        rec["balance"] = round(rec["balance"] + bal, 2)
        rec["invoices"] += 1
        try:
            inv_date = datetime.fromisoformat(i["invoice_date"]).date()
            days = (today - inv_date).days
            if days > rec["oldest_days"]:
                rec["oldest_days"] = days
        except Exception:
            pass

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
        "total_received": total_received,
        "total_receivable": total_receivable,
        "customer_count": len(customers),
        "invoice_count": len(invoices),
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
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0, "date": 1, "other_expenditures": 1}).to_list(20000)
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

# ==================== Drivers ====================

