"""Iter45 — Supplier Management Module.

Endpoints (all `/api` prefixed, company-scoped via X-Company-Id header):

  GET    /suppliers                     — list (search + active filter)
  POST   /suppliers                     — create
  GET    /suppliers/{sid}               — get one
  PUT    /suppliers/{sid}               — update
  DELETE /suppliers/{sid}               — soft delete (mark inactive)
  GET    /suppliers/{sid}/vehicles      — vehicles linked to supplier
  GET    /suppliers/{sid}/payments      — list payments
  POST   /suppliers/{sid}/payments      — create payment
  PUT    /suppliers/{sid}/payments/{pid}— edit
  DELETE /suppliers/{sid}/payments/{pid}?reason=... — soft delete (audit)
  GET    /suppliers/{sid}/ledger        — Debit/Credit/Balance list
  GET    /suppliers/{sid}/outstanding   — current net payable
  GET    /suppliers-dashboard           — 6-KPI snapshot

Ledger correctness rules
  * Supplier freight, supplier_advance, supplier_diesel, cust.diesel adj,
    shortage_deduction, other_recoveries, other_income, halting flow into
    the ledger DIRECTLY from trip rows (vehicle_type='supplier', supplier_id
    matches). Never duplicated as separate SupplierPayment rows.
  * SupplierPayment stores only real cash movements (bank/UPI/etc).
  * Opening balance seeds the ledger's running balance at date 0.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import Supplier, SupplierPayment, now_utc, new_id, LIVE_ONLY_FILTER
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------
# Supplier master CRUD
# --------------------------------------------------------------------------

@router.get("/suppliers")
async def list_suppliers(
    request: Request,
    q: Optional[str] = None,
    active_only: bool = False,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    query: dict = {"user_id": uid, "company_id": cid}
    if active_only:
        query["is_active"] = True
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"mobile": {"$regex": q, "$options": "i"}},
            {"contact_person": {"$regex": q, "$options": "i"}},
        ]
    # Iter72 — Raise cap from 2000 → 20000 for parity with /api/customers +
    # /api/vehicles. Demo tenant accumulates supplier fixtures from tests and
    # 2000-cap silently drops rows from the SupplierSection picker.
    rows = await db.suppliers.find(query, {"_id": 0, "user_id": 0}).sort("name", 1).to_list(20000)
    return rows


@router.post("/suppliers")
async def create_supplier(payload: Supplier, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    # Duplicate name check (per company)
    existing = await db.suppliers.find_one({
        "user_id": uid, "company_id": cid,
        "name": {"$regex": f"^{doc['name'].strip()}$", "$options": "i"},
    })
    if existing:
        raise HTTPException(status_code=409, detail=f"Supplier '{doc['name']}' already exists")
    await db.suppliers.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid}, "supplier", "create", doc["id"], doc.get("name", ""), "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/suppliers/{sid}")
async def get_supplier(sid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = await db.suppliers.find_one({"id": sid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return doc


@router.put("/suppliers/{sid}")
async def update_supplier(sid: str, payload: Supplier, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.suppliers.find_one({"id": sid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Supplier not found")
    patch = payload.model_dump(exclude={"id", "created_at", "created_by"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.suppliers.update_one({"id": sid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid}, "supplier", "update", sid, before.get("name", ""), "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/suppliers/{sid}")
async def delete_supplier(sid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.suppliers.find_one({"id": sid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Supplier not found")
    # Soft delete: mark inactive to preserve ledger history
    await db.suppliers.update_one({"id": sid}, {"$set": {"is_active": False, "modified_by": uid, "modified_at": now_utc().isoformat()}})
    try:
        await _log_audit({"user_id": uid, "company_id": cid}, "supplier", "delete", sid, doc.get("name", ""), "soft-delete", {})
    except Exception:
        pass
    return {"ok": True}


# --------------------------------------------------------------------------
# Vehicles linked to a supplier
# --------------------------------------------------------------------------

@router.get("/suppliers/{sid}/vehicles")
async def supplier_vehicles(sid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    sup = await db.suppliers.find_one({"id": sid, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")
    # Match by supplier_id OR (legacy) by supplier_name
    query = {
        "user_id": uid, "company_id": cid, "vehicle_type": "supplier",
        "$or": [
            {"supplier_id": sid},
            {"supplier_name": {"$regex": f"^{sup['name']}$", "$options": "i"}},
        ],
    }
    veh = await db.vehicles.find(query, {"_id": 0, "user_id": 0}).sort("vehicle_number", 1).to_list(500)
    return veh


# --------------------------------------------------------------------------
# Supplier Payments CRUD
# --------------------------------------------------------------------------

@router.get("/suppliers/{sid}/payments")
async def list_payments(sid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    rows = await db.supplier_payments.find(
        {"user_id": uid, "company_id": cid, "supplier_id": sid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    ).sort("date", -1).to_list(5000)
    return rows


@router.post("/suppliers/{sid}/payments")
async def create_payment(sid: str, payload: SupplierPayment, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    sup = await db.suppliers.find_one({"id": sid, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    doc = payload.model_dump()
    doc["id"] = doc.get("id") or new_id("sp_")
    doc["supplier_id"] = sid
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.supplier_payments.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid}, "supplier_payment", "create", doc["id"], sup.get("name", ""), "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.put("/suppliers/{sid}/payments/{pid}")
async def update_payment(sid: str, pid: str, payload: SupplierPayment, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.supplier_payments.find_one({"id": pid, "supplier_id": sid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Payment not found")
    patch = payload.model_dump(exclude={"id", "supplier_id", "created_at", "created_by", "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.supplier_payments.update_one({"id": pid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid}, "supplier_payment", "update", pid, "", "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/suppliers/{sid}/payments/{pid}")
async def delete_payment(
    sid: str, pid: str, request: Request,
    reason: str = Query(..., min_length=3, description="Mandatory deletion reason (>=3 chars)"),
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.supplier_payments.find_one({"id": pid, "supplier_id": sid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payment not found")
    patch = {
        "is_deleted": True,
        "deleted_by": uid,
        "deleted_at": now_utc().isoformat(),
        "deletion_reason": reason.strip(),
    }
    await db.supplier_payments.update_one({"id": pid}, {"$set": patch})
    try:
        await _log_audit({"user_id": uid, "company_id": cid}, "supplier_payment", "delete", pid, "", reason, {})
    except Exception:
        pass
    return {"ok": True}


# --------------------------------------------------------------------------
# Ledger + Outstanding
# --------------------------------------------------------------------------

async def _build_ledger(uid: str, cid: str, sid: str, start: Optional[str], end: Optional[str]):
    """Assemble a chronological Debit/Credit/Balance ledger for a supplier.

    Debit  = amount owed TO the supplier (increases payable): Supplier Freight,
             Other Income (from us), Halting-if-shared, Bonus, plus any
             receipt_in payment (rare).
    Credit = amount reducing what we owe: Advance, Diesel Funded, Cust. Diesel Adj,
             Shortage Deducted, Other Recoveries, actual money-out Payments.
    Balance is a running total (positive = we owe supplier).
    """
    sup = await db.suppliers.find_one({"id": sid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")

    entries: list = []

    # 1) Opening balance
    opening_amt = float(sup.get("opening_balance") or 0)
    opening_type = sup.get("opening_balance_type") or "payable"
    open_debit = opening_amt if opening_type == "payable" else 0.0
    open_credit = opening_amt if opening_type == "advance" else 0.0
    entries.append({
        "date": "0000-00-00",  # sentinel — always first
        "type": "opening",
        "particulars": "Opening Balance",
        "lr_number": "",
        "vehicle_number": "",
        "trip_id": "",
        "ref_no": "",
        "remarks": sup.get("remarks") or "",
        "debit": round(open_debit, 2),
        "credit": round(open_credit, 2),
    })

    # 2) Supplier trips (vehicle_type='supplier' and supplier_id match, or legacy name match)
    # Iter86 — supplier ledger excludes historical/imported trips
    trip_q = {
        "user_id": uid, "company_id": cid, "vehicle_type": "supplier", **LIVE_ONLY_FILTER,
        "$or": [
            {"supplier_id": sid},
            {"supplier_name": {"$regex": f"^{sup['name']}$", "$options": "i"}},
        ],
    }
    trips = await db.trips.find(trip_q, {"_id": 0, "user_id": 0}).to_list(10000)
    # Attach customer name
    customer_ids = list({t.get("customer_id") for t in trips if t.get("customer_id")})
    cust_map: dict = {}
    if customer_ids:
        cust_docs = await db.customers.find(
            {"user_id": uid, "company_id": cid, "id": {"$in": customer_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(2000)
        cust_map = {c["id"]: c["name"] for c in cust_docs}

    def _num(x):
        try: return float(x or 0)
        except Exception: return 0.0

    for t in trips:
        d = t.get("date", "")
        if start and d < start: continue
        if end and d > end: continue
        lr = t.get("lr_number") or ""
        veh = t.get("vehicle_number") or ""
        cust = cust_map.get(t.get("customer_id"), "")
        # Supplier freight — DEBIT (we owe supplier this)
        sf = _num(t.get("supplier_freight"))
        if sf > 0:
            entries.append({
                "date": d, "type": "trip_freight",
                "particulars": f"Supplier Freight — {cust or 'Trip'}",
                "lr_number": lr, "vehicle_number": veh,
                "trip_id": t.get("id"), "ref_no": "",
                "remarks": "", "debit": round(sf, 2), "credit": 0.0,
            })
        # Iter92 — Supplier Halting (INDEPENDENT of customer halting_amount) —
        # DEBIT to supplier when manually entered. Never auto-copied from
        # customer halting; office user enters it as an independent commercial
        # decision.
        sup_halt = _num(t.get("supplier_halting_amount"))
        if sup_halt > 0:
            days = _num(t.get("supplier_halting_days"))
            rate = _num(t.get("supplier_halting_rate_per_day"))
            desc = f"Supplier Halting — {cust or 'Trip'}"
            if days > 0 and rate > 0:
                desc += f" · {days:g}d @ ₹{rate:g}"
            entries.append({
                "date": d, "type": "trip_halting",
                "particulars": desc,
                "lr_number": lr, "vehicle_number": veh,
                "trip_id": t.get("id"), "ref_no": "",
                "remarks": t.get("supplier_halting_remarks") or "",
                "debit": round(sup_halt, 2), "credit": 0.0,
            })

        # Halting on trip — DEBIT (extra owed to supplier if we pass it through)
        # Note: halting is billed to customer AND paid to supplier per business rule.
        # We include it in supplier ledger for transparency (owed to supplier).
        # Halting is already netted in supplier_net_payable if configured that way; here we
        # record it separately for clarity. This can be tuned per business flow later.
        # Currently: halting is NOT included in supplier_net_payable formula; skip.

        # Advance paid at trip time — CREDIT
        # Iter91 — Prefer per-entry rows so each Advance shows as its own
        # ledger row with mode / reference / remarks. Falls back to the flat
        # `supplier_advance` for legacy trips that haven't been migrated yet.
        adv_entries = [e for e in (t.get("supplier_advance_entries") or []) if not e.get("deleted")]
        if adv_entries:
            for e in adv_entries:
                amt = _num(e.get("amount"))
                if amt <= 0:
                    continue
                entries.append({
                    "date": e.get("date") or d, "type": "trip_advance",
                    "particulars": f"Advance to Supplier{(' · ' + e.get('mode')) if e.get('mode') else ''}",
                    "lr_number": lr, "vehicle_number": veh,
                    "trip_id": t.get("id"), "ref_no": e.get("reference") or "",
                    "remarks": e.get("remarks") or "",
                    "debit": 0.0, "credit": round(amt, 2),
                })
        else:
            adv = _num(t.get("supplier_advance"))
            if adv > 0:
                entries.append({
                    "date": d, "type": "trip_advance",
                    "particulars": "Trip-time Advance to Supplier",
                    "lr_number": lr, "vehicle_number": veh,
                    "trip_id": t.get("id"), "ref_no": "",
                    "remarks": "", "debit": 0.0, "credit": round(adv, 2),
                })
        # Diesel provided by us — CREDIT (per-entry rows, else fallback)
        dsl_entries = [e for e in (t.get("supplier_diesel_entries") or []) if not e.get("deleted")]
        if dsl_entries:
            for e in dsl_entries:
                amt = _num(e.get("amount"))
                if amt <= 0:
                    continue
                qty = _num(e.get("quantity"))
                rate = _num(e.get("rate"))
                part = "Diesel Funded by Us"
                if qty > 0 and rate > 0:
                    part += f" · {qty:g}L @ ₹{rate:g}"
                elif e.get("mode"):
                    part += f" · {e.get('mode')}"
                entries.append({
                    "date": e.get("date") or d, "type": "trip_diesel",
                    "particulars": part,
                    "lr_number": lr, "vehicle_number": veh,
                    "trip_id": t.get("id"), "ref_no": e.get("reference") or "",
                    "remarks": e.get("remarks") or "",
                    "debit": 0.0, "credit": round(amt, 2),
                })
        else:
            dsl = _num(t.get("supplier_diesel"))
            if dsl > 0:
                entries.append({
                    "date": d, "type": "trip_diesel",
                    "particulars": "Diesel Funded by Us",
                    "lr_number": lr, "vehicle_number": veh,
                    "trip_id": t.get("id"), "ref_no": "",
                    "remarks": "", "debit": 0.0, "credit": round(dsl, 2),
                })
        # Customer Diesel Adjustment — CREDIT (customer funded fuel used on this supplier's trip)
        cust_dsl = round(sum(
            _num(r.get("amount")) for r in (t.get("customer_receipts") or [])
            if (r.get("type") or "").lower() == "diesel"
        ), 2)
        if cust_dsl > 0:
            entries.append({
                "date": d, "type": "cust_diesel_adj",
                "particulars": "Customer Diesel Adjustment",
                "lr_number": lr, "vehicle_number": veh,
                "trip_id": t.get("id"), "ref_no": "",
                "remarks": "", "debit": 0.0, "credit": cust_dsl,
            })
        # Shortage deducted — CREDIT (recovered from supplier)
        short = _num(t.get("supplier_shortage_deduction"))
        if short > 0:
            entries.append({
                "date": d, "type": "trip_shortage",
                "particulars": "Shortage Recovery",
                "lr_number": lr, "vehicle_number": veh,
                "trip_id": t.get("id"), "ref_no": "",
                "remarks": "", "debit": 0.0, "credit": round(short, 2),
            })
        # Other recoveries — CREDIT
        recov = _num(t.get("supplier_other_recoveries"))
        if recov > 0:
            entries.append({
                "date": d, "type": "trip_recovery",
                "particulars": "Other Recovery",
                "lr_number": lr, "vehicle_number": veh,
                "trip_id": t.get("id"), "ref_no": "",
                "remarks": "", "debit": 0.0, "credit": round(recov, 2),
            })
        # Other income (bonus paid TO supplier) — DEBIT
        inc = _num(t.get("supplier_other_income"))
        if inc > 0:
            entries.append({
                "date": d, "type": "trip_bonus",
                "particulars": "Bonus / Other Income to Supplier",
                "lr_number": lr, "vehicle_number": veh,
                "trip_id": t.get("id"), "ref_no": "",
                "remarks": "", "debit": round(inc, 2), "credit": 0.0,
            })

    # 3) Explicit payments — Iter86: exclude historical
    pays = await db.supplier_payments.find(
        {"user_id": uid, "company_id": cid, "supplier_id": sid, "is_deleted": {"$ne": True}, **LIVE_ONLY_FILTER},
        {"_id": 0, "user_id": 0},
    ).to_list(10000)
    for p in pays:
        d = p.get("date", "")
        if start and d < start: continue
        if end and d > end: continue
        is_out = p.get("type", "payment_out") == "payment_out"
        entries.append({
            "date": d,
            "type": ("payment_out" if is_out else "receipt_in"),
            "particulars": f"Payment {p.get('mode','')}{' - ' + p.get('against','') if p.get('against') else ''}",
            "lr_number": p.get("lr_number") or "",
            "vehicle_number": "",
            "trip_id": p.get("trip_id") or "",
            "ref_no": p.get("ref_no") or "",
            "remarks": p.get("remarks") or "",
            "debit": 0.0 if is_out else round(float(p["amount"]), 2),
            "credit": round(float(p["amount"]), 2) if is_out else 0.0,
            "payment_id": p.get("id"),
        })

    # 4) Chronological sort — opening always first
    entries.sort(key=lambda e: (e["date"], 0 if e["type"] == "opening" else 1))

    # 5) Running balance
    bal = 0.0
    for e in entries:
        bal += e["debit"] - e["credit"]
        e["balance"] = round(bal, 2)

    tot_debit = round(sum(e["debit"] for e in entries), 2)
    tot_credit = round(sum(e["credit"] for e in entries), 2)
    return {
        "supplier": {"id": sup["id"], "name": sup["name"], "mobile": sup.get("mobile", "")},
        "period": {"start": start, "end": end},
        "entries": entries,
        "totals": {
            "debit": tot_debit,
            "credit": tot_credit,
            "closing_balance": round(bal, 2),
            "closing_type": "payable" if bal >= 0 else "advance",
        },
    }


@router.get("/suppliers/{sid}/ledger")
async def supplier_ledger(
    sid: str, request: Request,
    start: Optional[str] = None, end: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await _build_ledger(uid, cid, sid, start, end)


@router.get("/suppliers/{sid}/outstanding")
async def supplier_outstanding(sid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    data = await _build_ledger(uid, cid, sid, None, None)
    tot = data["totals"]
    # Aging: bucket the closing balance by oldest unmatched debit (best-effort)
    from datetime import datetime as _dt
    today = _dt.utcnow().date()
    buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
    for e in data["entries"]:
        if e["type"] == "opening" or e["debit"] <= 0:
            continue
        try:
            d = _dt.fromisoformat(e["date"]).date()
            age = (today - d).days
        except Exception:
            age = 0
        key = "0-30" if age <= 30 else "31-60" if age <= 60 else "61-90" if age <= 90 else "90+"
        buckets[key] += e["debit"]
    return {
        "supplier_id": sid,
        "supplier_name": data["supplier"]["name"],
        "closing_balance": tot["closing_balance"],
        "closing_type": tot["closing_type"],
        "outstanding_payable": max(tot["closing_balance"], 0),
        "outstanding_advance": max(-tot["closing_balance"], 0),
        "aging": {k: round(v, 2) for k, v in buckets.items()},
    }


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

@router.get("/suppliers-dashboard")
async def suppliers_dashboard(request: Request, user=Depends(get_current_user)):
    """Iter73 — Rewritten for scale.

    Previously this endpoint looped through every supplier and called
    `_build_ledger` per supplier (~30k DB roundtrips on the demo tenant with
    9.5k suppliers → ~58s response). Now it does 3 bulk queries total and
    aggregates in memory in ~200 ms.
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    def _num(x):
        try: return float(x or 0)
        except Exception: return 0.0

    # 1) All suppliers for this company (single query)
    suppliers = await db.suppliers.find(
        {"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}
    ).to_list(20000)
    total_suppliers = len(suppliers)
    active_suppliers = sum(1 for s in suppliers if s.get("is_active", True))
    sup_by_id = {s["id"]: s for s in suppliers}
    # Legacy: some old trips carry only supplier_name (no supplier_id). Build
    # a case-insensitive name→id lookup so those still count.
    name_to_id = {s["name"].casefold(): s["id"] for s in suppliers if s.get("name")}

    # 2) All supplier vehicles count (single query)
    active_vehicles = await db.vehicles.count_documents({
        "user_id": uid, "company_id": cid, "vehicle_type": "supplier", "is_active": True,
    })

    # 3) All supplier trips in this company (single query, projected fields only)
    # Iter86 — settlement summary excludes historical
    trip_docs = await db.trips.find(
        {"user_id": uid, "company_id": cid, "vehicle_type": "supplier", **LIVE_ONLY_FILTER},
        {
            "_id": 0, "supplier_id": 1, "supplier_name": 1, "date": 1,
            "supplier_freight": 1, "supplier_advance": 1, "supplier_diesel": 1,
            "supplier_advance_entries": 1, "supplier_diesel_entries": 1,
            "supplier_shortage_deduction": 1, "supplier_other_recoveries": 1,
            "supplier_other_income": 1, "customer_receipts": 1,
            "supplier_halting_amount": 1,  # Iter92
        },
    ).to_list(200000)

    # 4) All supplier payments (single query, projected fields only) — Iter86: exclude historical
    pay_docs = await db.supplier_payments.find(
        {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}, **LIVE_ONLY_FILTER},
        {"_id": 0, "supplier_id": 1, "amount": 1, "type": 1},
    ).to_list(200000)

    # Aggregate — per_sid dict[str, dict] with {freight, advances, payments, debit, credit}
    per_sid: dict = {}

    def _slot(sid: str):
        return per_sid.setdefault(sid, {"freight": 0.0, "advances": 0.0, "payments": 0.0, "debit": 0.0, "credit": 0.0})

    for t in trip_docs:
        sid = t.get("supplier_id") or ""
        if not sid:
            legacy = (t.get("supplier_name") or "").strip().casefold()
            sid = name_to_id.get(legacy, "")
        if not sid or sid not in sup_by_id:
            continue
        slot = _slot(sid)
        sf = _num(t.get("supplier_freight"))
        # Iter91 — prefer entries; fallback to flat
        _adv_entries = [e for e in (t.get("supplier_advance_entries") or []) if not e.get("deleted")]
        _dsl_entries = [e for e in (t.get("supplier_diesel_entries") or []) if not e.get("deleted")]
        adv = round(sum(_num(e.get("amount")) for e in _adv_entries), 2) if _adv_entries else _num(t.get("supplier_advance"))
        dsl = round(sum(_num(e.get("amount")) for e in _dsl_entries), 2) if _dsl_entries else _num(t.get("supplier_diesel"))
        shr = _num(t.get("supplier_shortage_deduction"))
        rec = _num(t.get("supplier_other_recoveries"))
        inc = _num(t.get("supplier_other_income"))
        halt = _num(t.get("supplier_halting_amount"))  # Iter92
        cust_dsl = sum(
            _num(r.get("amount")) for r in (t.get("customer_receipts") or [])
            if (r.get("type") or "").lower() == "diesel"
        )
        slot["freight"] += sf
        slot["advances"] += adv
        slot["debit"] += sf + inc + halt
        slot["credit"] += adv + dsl + cust_dsl + shr + rec

    for p in pay_docs:
        sid = p.get("supplier_id") or ""
        if sid not in sup_by_id:
            continue
        slot = _slot(sid)
        amt = _num(p.get("amount"))
        is_out = (p.get("type") or "payment_out") == "payment_out"
        if is_out:
            slot["payments"] += amt
            slot["credit"] += amt
        else:
            slot["debit"] += amt

    total_freight = 0.0; total_advances = 0.0; total_payments = 0.0; total_outstanding = 0.0
    per_supplier = []
    for s in suppliers:
        sid = s["id"]
        slot = per_sid.get(sid, {"freight": 0.0, "advances": 0.0, "payments": 0.0, "debit": 0.0, "credit": 0.0})
        # Opening balance sign
        opening_amt = _num(s.get("opening_balance"))
        opening_type = s.get("opening_balance_type") or "payable"
        open_debit = opening_amt if opening_type == "payable" else 0.0
        open_credit = opening_amt if opening_type == "advance" else 0.0
        closing = (open_debit + slot["debit"]) - (open_credit + slot["credit"])
        outstanding = max(closing, 0)
        total_freight += slot["freight"]
        total_advances += slot["advances"]
        total_payments += slot["payments"]
        total_outstanding += outstanding
        per_supplier.append({
            "supplier_id": sid,
            "supplier_name": s.get("name") or "",
            "mobile": s.get("mobile", ""),
            "closing_balance": round(closing, 2),
            "closing_type": "payable" if closing > 0 else ("advance" if closing < 0 else "zero"),
            "outstanding_payable": round(outstanding, 2),
            "is_active": s.get("is_active", True),
        })
    per_supplier.sort(key=lambda x: -x["outstanding_payable"])
    return {
        "totals": {
            "total_suppliers": total_suppliers,
            "active_suppliers": active_suppliers,
            "active_vehicles": active_vehicles,
            "total_freight": round(total_freight, 2),
            "total_advances": round(total_advances, 2),
            "total_payments": round(total_payments, 2),
            "total_outstanding": round(total_outstanding, 2),
        },
        "suppliers": per_supplier,
    }
