"""Iter133 · Turn 2B — Vehicle Cost + Vehicle Repair History (read-only).

Source-of-truth map (FROZEN — do not change):
  Vehicle Cost         → canonical Expense (+ legacy Trip.expenses fallback ONLY
                          for trips where has_canonical_expenses=false)
  Vehicle Repair Cost  → canonical Expense where repair_event_id != "" (DERIVED;
                          never read from RepairEvent, VendorBill or MechanicWO)
  Vendor payable       → VendorBill − VendorPayment (Turn 2C ledger)
  Mechanic payable     → MechanicWO − MechanicPayment (Turn 2C ledger)

No cached totals. No stored `total_cost` on RepairEvent. No second calculator.
Legacy XOR: `Trip.has_canonical_expenses` gates which source projects for
that trip. Never additive.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import now_utc
from auth import get_current_user
from company import _active_company_id

router = APIRouter(prefix="/api")


_LEGACY_SCALARS = [
    ("diesel", "Diesel"), ("toll", "Toll"), ("batta", "Batta"),
    ("repair", "Repair"), ("other", "Other"), ("firewood", "Firewood"),
]


async def _ensure_vehicle(uid: str, cid: str, vid: str) -> dict:
    v = await db.vehicles.find_one({"id": vid, "user_id": uid, "company_id": cid},
                                   {"_id": 0, "user_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return v


def _date_range(q: dict, date_field: str, date_from: Optional[str], date_to: Optional[str]):
    if not (date_from or date_to):
        return
    d: dict = {}
    if date_from:
        d["$gte"] = date_from
    if date_to:
        d["$lte"] = date_to
    q[date_field] = d


async def _legacy_trip_expenses_for_vehicle(uid: str, cid: str, vid: str,
                                            date_from: Optional[str], date_to: Optional[str]):
    """Yield synthetic expense-shaped dicts for legacy Trip rows where
    has_canonical_expenses is not True. Used only as XOR fallback."""
    q = {
        "user_id": uid, "company_id": cid, "vehicle_id": vid,
        "$or": [
            {"has_canonical_expenses": {"$exists": False}},
            {"has_canonical_expenses": False},
        ],
    }
    _date_range(q, "date", date_from, date_to)
    projection = {"_id": 0, "id": 1, "date": 1, "vehicle_id": 1, "vehicle_number": 1,
                  "expenses": 1, "other_expenditures": 1}
    async for t in db.trips.find(q, projection):
        e = t.get("expenses") or {}
        for field, category in _LEGACY_SCALARS:
            try:
                amt = float(e.get(field) or 0)
            except Exception:
                amt = 0.0
            if amt > 0:
                yield {
                    "id": f"legacy:{t['id']}:{field}",
                    "date": t.get("date") or "",
                    "category": category,
                    "amount": round(amt, 2),
                    "trip_id": t["id"],
                    "vehicle_id": vid,
                    "vehicle_number": t.get("vehicle_number", ""),
                    "repair_event_id": "",
                    "source_type": "legacy_trip_fallback",
                    "source_key": f"legacy:{t['id']}:{field}",
                }
        for oe in (t.get("other_expenditures") or []):
            try:
                amt = float(oe.get("amount") or 0)
            except Exception:
                amt = 0.0
            if amt <= 0:
                continue
            d = oe.get("date") or t.get("date") or ""
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            yield {
                "id": f"legacy_oe:{t['id']}:{oe.get('id','')}",
                "date": d,
                "category": (oe.get("type") or "Other").strip() or "Other",
                "amount": round(amt, 2),
                "trip_id": t["id"],
                "vehicle_id": vid,
                "vehicle_number": t.get("vehicle_number", ""),
                "repair_event_id": "",
                "source_type": "legacy_trip_fallback",
                "source_key": f"legacy_oe:{t['id']}:{oe.get('id','')}",
            }


@router.get("/vehicles/{vid}/cost-summary")
async def vehicle_cost_summary(
    vid: str,
    request: Request,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    category: Optional[str] = None,
    trip_linked: Optional[str] = Query(None, description="'yes' | 'no' | None"),
    user=Depends(get_current_user),
):
    """Vehicle Cost — total, count, category-wise, monthly, and per-trip drill list.

    Reads canonical Expense as primary source; legacy Trip fallback ONLY for
    trips where has_canonical_expenses=false (Turn-2A XOR).
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    v = await _ensure_vehicle(uid, cid, vid)

    q = {
        "user_id": uid, "company_id": cid, "vehicle_id": vid,
        "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True},
    }
    _date_range(q, "date", date_from, date_to)
    if category:
        q["category"] = category
    if trip_linked == "yes":
        q["trip_id"] = {"$ne": ""}
    elif trip_linked == "no":
        q["$or"] = [{"trip_id": ""}, {"trip_id": {"$exists": False}}]

    # Streaming iteration — no arbitrary cap.
    rows: list = []
    async for e in db.expenses.find(q, {"_id": 0, "user_id": 0}):
        rows.append(e)

    # Legacy XOR fallback
    async for e in _legacy_trip_expenses_for_vehicle(uid, cid, vid, date_from, date_to):
        if category and e["category"] != category:
            continue
        if trip_linked == "no":
            continue  # legacy expenses always have a trip
        rows.append(e)

    total = round(sum(float(r.get("amount") or 0) for r in rows), 2)
    count = len(rows)

    # Category breakdown
    by_cat: dict = {}
    for r in rows:
        c = r.get("category") or "Other"
        by_cat[c] = round((by_cat.get(c) or 0) + float(r.get("amount") or 0), 2)
    by_category = sorted(
        [{"category": k, "amount": v} for k, v in by_cat.items()],
        key=lambda x: (-x["amount"], x["category"]),
    )

    # Monthly breakdown (YYYY-MM)
    by_month: dict = {}
    for r in rows:
        d = (r.get("date") or "")[:7]
        if not d:
            continue
        by_month[d] = round((by_month.get(d) or 0) + float(r.get("amount") or 0), 2)
    by_month_list = sorted(
        [{"month": k, "amount": v} for k, v in by_month.items()],
        key=lambda x: x["month"],
    )

    # Trip-linked vs non-trip split
    trip_linked_total = round(
        sum(float(r.get("amount") or 0) for r in rows if r.get("trip_id")),
        2,
    )
    non_trip_total = round(total - trip_linked_total, 2)

    # Repair-linked subtotal
    repair_total = round(
        sum(float(r.get("amount") or 0) for r in rows if r.get("repair_event_id")),
        2,
    )

    return {
        "vehicle_id": vid,
        "vehicle_number": v.get("vehicle_number", ""),
        "from": date_from or "",
        "to": date_to or "",
        "filters": {"category": category or "", "trip_linked": trip_linked or ""},
        "total_cost": total,
        "expense_count": count,
        "trip_linked_total": trip_linked_total,
        "non_trip_total": non_trip_total,
        "repair_total": repair_total,
        "by_category": by_category,
        "by_month": by_month_list,
        "rows": rows,   # full result set (drill list); filters constrain volume
        "generated_at": now_utc().isoformat(),
    }


@router.get("/vehicles/{vid}/repair-history")
async def vehicle_repair_history(
    vid: str,
    request: Request,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    mechanic_id: Optional[str] = None,
    trip_linked: Optional[str] = Query(None, description="'yes' | 'no' | None"),
    user=Depends(get_current_user),
):
    """Vehicle Repair History.

    Reads RepairEvent + linked Expenses/Bills/WOs/Payments for THIS vehicle.
    RepairEvent has NO stored total. Every total is derived from Expense rows
    (source-of-truth for cost) — NEVER from Bill/WO amounts (those are the
    payable side, read by ledgers).
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    v = await _ensure_vehicle(uid, cid, vid)

    q = {
        "user_id": uid, "company_id": cid, "vehicle_id": vid,
        "is_deleted": {"$ne": True},
    }
    _date_range(q, "event_date", date_from, date_to)
    if status:
        q["status"] = status
    if trip_linked == "yes":
        q["trip_id"] = {"$ne": ""}
    elif trip_linked == "no":
        q["$or"] = [{"trip_id": ""}, {"trip_id": {"$exists": False}}]

    events: list = []
    async for ev in db.repair_events.find(q, {"_id": 0, "user_id": 0}).sort("event_date", -1):
        events.append(ev)

    if not events:
        return {
            "vehicle_id": vid,
            "vehicle_number": v.get("vehicle_number", ""),
            "count": 0,
            "total_repair_cost": 0.0,
            "events": [],
            "generated_at": now_utc().isoformat(),
        }

    event_ids = [e["id"] for e in events]
    scope = {"user_id": uid, "company_id": cid, "repair_event_id": {"$in": event_ids},
             "is_deleted": {"$ne": True}}

    # Preload children in bounded IN-queries (no N+1)
    child_exp: dict = {}
    async for x in db.expenses.find({**scope, "is_reversed": {"$ne": True}},
                                    {"_id": 0, "user_id": 0}):
        child_exp.setdefault(x["repair_event_id"], []).append(x)

    child_bills: dict = {}
    async for b in db.vendor_bills.find(scope, {"_id": 0, "user_id": 0}):
        child_bills.setdefault(b["repair_event_id"], []).append(b)

    child_wos: dict = {}
    async for w in db.mechanic_work_orders.find(scope, {"_id": 0, "user_id": 0}):
        child_wos.setdefault(w["repair_event_id"], []).append(w)

    # Preload payments referencing this batch of bills/WOs (best-effort)
    bill_ids = [b["id"] for bs in child_bills.values() for b in bs]
    wo_ids = [w["id"] for ws in child_wos.values() for w in ws]

    vp_by_bill: dict = {}
    if bill_ids:
        async for p in db.vendor_payments.find(
            {"user_id": uid, "company_id": cid, "vendor_bill_id": {"$in": bill_ids},
             "is_deleted": {"$ne": True}},
            {"_id": 0, "user_id": 0},
        ):
            vp_by_bill.setdefault(p["vendor_bill_id"], []).append(p)

    mp_by_wo: dict = {}
    if wo_ids:
        async for p in db.mechanic_payments.find(
            {"user_id": uid, "company_id": cid, "mechanic_work_order_id": {"$in": wo_ids},
             "is_deleted": {"$ne": True}},
            {"_id": 0, "user_id": 0},
        ):
            mp_by_wo.setdefault(p["mechanic_work_order_id"], []).append(p)

    grand_total = 0.0
    out_events: list = []
    for ev in events:
        eid = ev["id"]
        exps = child_exp.get(eid, [])
        bills = child_bills.get(eid, [])
        wos = child_wos.get(eid, [])

        if vendor_id:
            if not any(b.get("vendor_id") == vendor_id for b in bills):
                continue
        if mechanic_id:
            if not any(w.get("mechanic_id") == mechanic_id for w in wos):
                continue

        # DERIVED totals — Expense only (never Bill + Expense)
        total_repair_cost = round(sum(float(x.get("amount") or 0) for x in exps), 2)
        parts_cost = round(
            sum(float(x.get("amount") or 0) for x in exps if x.get("vendor_bill_id")), 2,
        )
        labour_cost = round(
            sum(float(x.get("amount") or 0) for x in exps if x.get("mechanic_work_order_id")), 2,
        )
        other_cost = round(total_repair_cost - parts_cost - labour_cost, 2)

        # Payable totals from Bill/WO (independent of Expense — do NOT mix)
        vendor_payable = round(sum(float(b.get("bill_amount") or 0) for b in bills), 2)
        mechanic_payable = round(sum(float(w.get("amount") or 0) for w in wos), 2)

        # Paid totals from Payments
        vendor_paid = 0.0
        for b in bills:
            for p in vp_by_bill.get(b["id"], []):
                if p.get("type") == "payment_out":
                    vendor_paid += float(p.get("amount") or 0)
                elif p.get("type") == "receipt_in":
                    vendor_paid -= float(p.get("amount") or 0)
        mechanic_paid = 0.0
        for w in wos:
            for p in mp_by_wo.get(w["id"], []):
                if p.get("type") == "payment_out":
                    mechanic_paid += float(p.get("amount") or 0)
                elif p.get("type") == "receipt_in":
                    mechanic_paid -= float(p.get("amount") or 0)
        vendor_paid = round(vendor_paid, 2)
        mechanic_paid = round(mechanic_paid, 2)
        vendor_outstanding = round(vendor_payable - vendor_paid, 2)
        mechanic_outstanding = round(mechanic_payable - mechanic_paid, 2)

        grand_total = round(grand_total + total_repair_cost, 2)

        out_events.append({
            **ev,
            "total_repair_cost": total_repair_cost,
            "parts_cost": parts_cost,
            "labour_cost": labour_cost,
            "other_cost": other_cost,
            "vendor_payable": vendor_payable,
            "vendor_paid": vendor_paid,
            "vendor_outstanding": vendor_outstanding,
            "mechanic_payable": mechanic_payable,
            "mechanic_paid": mechanic_paid,
            "mechanic_outstanding": mechanic_outstanding,
            "expenses": exps,
            "vendor_bills": bills,
            "mechanic_work_orders": wos,
        })

    return {
        "vehicle_id": vid,
        "vehicle_number": v.get("vehicle_number", ""),
        "from": date_from or "",
        "to": date_to or "",
        "filters": {
            "status": status or "",
            "vendor_id": vendor_id or "",
            "mechanic_id": mechanic_id or "",
            "trip_linked": trip_linked or "",
        },
        "count": len(out_events),
        "total_repair_cost": grand_total,
        "events": out_events,
        "generated_at": now_utc().isoformat(),
    }


# ── Iter142 P0 · Vehicle-wise PDF + Excel reports (additive, pure projection) ──
from fastapi.responses import StreamingResponse
from io import BytesIO
from pdf.vehicle_cost import build_vehicle_cost_pdf
from xlsx.vehicle_cost import build_vehicle_cost_xlsx

MAX_PDF_ENTRIES = 5000


def _fname_stem(reg: str, dfrom, dto) -> str:
    reg_s = (reg or "vehicle").replace(" ", "_").replace("/", "_")
    if dfrom or dto:
        return f"Vehicle_{reg_s}_Cost_{dfrom or 'All'}_{dto or 'All'}"
    return f"Vehicle_{reg_s}_Cost_All"


async def _report_context(request, user, vid, dfrom, dto, category):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    vehicle = await _ensure_vehicle(uid, cid, vid)
    company = await db.companies.find_one({"id": cid, "user_id": uid}, {"_id": 0}) or {}
    cost = await vehicle_cost_summary(vid, request=request, date_from=dfrom, date_to=dto,
                                      category=category, trip_linked=None, user=user)
    repairs = await vehicle_repair_history(vid, request=request, date_from=dfrom, date_to=dto, user=user)
    return company, vehicle, cost, repairs


@router.get("/vehicles/{vid}/cost-summary.pdf")
async def vehicle_cost_summary_pdf(
    vid: str, request: Request,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    category: Optional[str] = None,
    user=Depends(get_current_user),
):
    company, vehicle, cost, repairs = await _report_context(request, user, vid, date_from, date_to, category)
    if len(cost.get("rows") or []) > MAX_PDF_ENTRIES:
        raise HTTPException(status_code=413,
            detail=f"Vehicle report contains {len(cost['rows']):,} rows for this range. "
                   f"Narrow the date range (PDF limit: {MAX_PDF_ENTRIES:,}) or use the Excel export.")
    pdf_bytes = build_vehicle_cost_pdf(company, vehicle, cost, repairs,
                                       {"from": date_from, "to": date_to, "category": category})
    fname = _fname_stem(vehicle.get("vehicle_number"), date_from, date_to) + ".pdf"
    return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/vehicles/{vid}/cost-summary.xlsx")
async def vehicle_cost_summary_xlsx(
    vid: str, request: Request,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    category: Optional[str] = None,
    user=Depends(get_current_user),
):
    company, vehicle, cost, repairs = await _report_context(request, user, vid, date_from, date_to, category)
    xlsx_bytes = build_vehicle_cost_xlsx(company, vehicle, cost, repairs,
                                         {"from": date_from, "to": date_to, "category": category})
    fname = _fname_stem(vehicle.get("vehicle_number"), date_from, date_to) + ".xlsx"
    return StreamingResponse(BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
