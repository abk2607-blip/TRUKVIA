"""Iter133 · Turn 2D · Cost-date vs Payment-date reporting + Supplier
settlement-adjustment projection (read-only).

FROZEN date semantics:
  Vehicle Cost / Trip Cost / Expense Register  → Expense.date  (COST DATE)
  Vendor / Mechanic cashbook                   → Payment.date  (PAYMENT DATE)
  Outstanding-as-of                            → Bills/WO<=cutoff MINUS Payments<=cutoff

FROZEN supplier-settlement-adjustment projection:
  Expense rows where `supplier_owned_vehicle=true` AND
  `supplier_settlement_mode='supplier_settlement_adjustment'` project into the
  Supplier Statement as CREDIT rows (recovery). They do NOT create a
  duplicate SupplierPayment(payment_out), and they do NOT hit company P&L.

Existing `_build_ledger` in routers/suppliers.py is NOT modified — this
projection lives on a NEW endpoint that any consumer/UI can compose with
the existing supplier statement. Locked semantics preserved.
"""
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import now_utc
from auth import get_current_user
from company import _active_company_id

router = APIRouter(prefix="/api")


# --------------------- Outstanding-as-of (Vendor/Mechanic) ---------------------

async def _outstanding_as_of(coll_bills: str, coll_pays: str, party_field: str,
                             bill_date_field: str, bill_amt_field: str,
                             uid: str, cid: str, pid: str, as_of: str) -> dict:
    bills_q = {"user_id": uid, "company_id": cid, party_field: pid,
               "is_deleted": {"$ne": True}, bill_date_field: {"$lte": as_of}}
    pays_q = {"user_id": uid, "company_id": cid, party_field: pid,
              "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True},
              "date": {"$lte": as_of}}
    bills_total = 0.0
    async for b in db[coll_bills].find(bills_q, {"_id": 0, bill_amt_field: 1}):
        bills_total += float(b.get(bill_amt_field) or 0)
    pays_out = 0.0
    pays_in = 0.0
    async for p in db[coll_pays].find(pays_q, {"_id": 0, "amount": 1, "type": 1}):
        if p.get("type") == "payment_out":
            pays_out += float(p.get("amount") or 0)
        else:
            pays_in += float(p.get("amount") or 0)
    bills_total = round(bills_total, 2)
    pays_net = round(pays_out - pays_in, 2)
    outstanding = round(bills_total - pays_net, 2)
    return {
        "as_of": as_of,
        "bills_total_as_of": bills_total,
        "payments_net_as_of": pays_net,
        "outstanding": max(outstanding, 0),
        "advance": max(-outstanding, 0),
    }


@router.get("/vendors/{vid}/outstanding-as-of")
async def vendor_outstanding_as_of(vid: str, request: Request,
                                   as_of: str = Query(..., description="YYYY-MM-DD"),
                                   user=Depends(get_current_user)):
    uid = user["user_id"]; cid = await _active_company_id(request, user)
    if not await db.vendors.find_one({"id": vid, "user_id": uid, "company_id": cid},
                                     {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Vendor not found")
    r = await _outstanding_as_of("vendor_bills", "vendor_payments",
                                 "vendor_id", "bill_date", "bill_amount",
                                 uid, cid, vid, as_of)
    return {"vendor_id": vid, **r, "generated_at": now_utc().isoformat()}


@router.get("/mechanics/{mid}/outstanding-as-of")
async def mechanic_outstanding_as_of(mid: str, request: Request,
                                     as_of: str = Query(..., description="YYYY-MM-DD"),
                                     user=Depends(get_current_user)):
    uid = user["user_id"]; cid = await _active_company_id(request, user)
    if not await db.mechanics.find_one({"id": mid, "user_id": uid, "company_id": cid},
                                       {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Mechanic not found")
    r = await _outstanding_as_of("mechanic_work_orders", "mechanic_payments",
                                 "mechanic_id", "work_date", "amount",
                                 uid, cid, mid, as_of)
    return {"mechanic_id": mid, **r, "generated_at": now_utc().isoformat()}


# --------------------- Payment cashbook (Payment.date) ---------------------

@router.get("/payment-cashbook")
async def payment_cashbook(
    request: Request,
    party_type: Literal["vendor", "mechanic"] = Query(...),
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    include_reversed: bool = False,
    user=Depends(get_current_user),
):
    """Cashbook by PAYMENT DATE (never Cost Date)."""
    uid = user["user_id"]; cid = await _active_company_id(request, user)
    coll = "vendor_payments" if party_type == "vendor" else "mechanic_payments"
    q = {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}
    if not include_reversed:
        q["is_reversed"] = {"$ne": True}
    if date_from or date_to:
        d: dict = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        q["date"] = d
    rows: list = []
    out_total = 0.0
    in_total = 0.0
    async for p in db[coll].find(q, {"_id": 0, "user_id": 0}).sort("date", -1):
        rows.append(p)
        if p.get("type") == "payment_out":
            out_total += float(p.get("amount") or 0)
        else:
            in_total += float(p.get("amount") or 0)
    return {
        "party_type": party_type,
        "date_basis": "payment_date",
        "from": date_from or "",
        "to": date_to or "",
        "count": len(rows),
        "payment_out_total": round(out_total, 2),
        "receipt_in_total": round(in_total, 2),
        "net_out": round(out_total - in_total, 2),
        "rows": rows,
        "generated_at": now_utc().isoformat(),
    }


# --------------------- Supplier settlement-adjustment projection ---------------------

@router.get("/suppliers/{sid}/settlement-adjustments")
async def supplier_settlement_adjustments(
    sid: str, request: Request,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    user=Depends(get_current_user),
):
    """Iter133 · Turn 2D · Supplier settlement projection (read-only).

    Returns canonical Expense rows for supplier-owned vehicles where
    `supplier_settlement_mode='supplier_settlement_adjustment'` — these are
    CREDIT/recovery entries on the Supplier Statement. Does NOT create
    duplicate SupplierPayment(payment_out); the projection IS the recovery.

    NOTE: the resolution supplier→vehicle_id is via the Vehicle master
    (vehicle.supplier_id). Existing `_build_ledger` remains untouched; this
    endpoint composes cleanly with it.
    """
    uid = user["user_id"]; cid = await _active_company_id(request, user)
    sup = await db.suppliers.find_one({"id": sid, "user_id": uid, "company_id": cid},
                                      {"_id": 0, "name": 1})
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # Resolve the vehicle ids owned by this supplier.
    veh_ids: list = []
    async for v in db.vehicles.find(
        {"user_id": uid, "company_id": cid, "supplier_id": sid,
         "vehicle_type": "supplier"},
        {"_id": 0, "id": 1},
    ):
        veh_ids.append(v["id"])

    q = {
        "user_id": uid, "company_id": cid,
        "supplier_owned_vehicle": True,
        "supplier_settlement_mode": "supplier_settlement_adjustment",
        "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True},
    }
    if veh_ids:
        q["vehicle_id"] = {"$in": veh_ids}
    else:
        # No vehicles for this supplier → empty projection
        return {"supplier_id": sid, "supplier_name": sup.get("name", ""),
                "from": date_from or "", "to": date_to or "",
                "count": 0, "total_credit": 0.0, "rows": [],
                "generated_at": now_utc().isoformat()}

    if date_from or date_to:
        d: dict = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        q["date"] = d

    rows: list = []
    total = 0.0
    async for e in db.expenses.find(q, {"_id": 0, "user_id": 0}):
        rows.append(e)
        total += float(e.get("amount") or 0)
    return {
        "supplier_id": sid,
        "supplier_name": sup.get("name", ""),
        "from": date_from or "",
        "to": date_to or "",
        "count": len(rows),
        "total_credit": round(total, 2),
        "rows": rows,
        "generated_at": now_utc().isoformat(),
        "note": "CREDIT/recovery projection into Supplier Statement. "
                "Never duplicated as a SupplierPayment(payment_out).",
    }
