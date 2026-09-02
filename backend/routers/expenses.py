"""Iter133 · Expense CRUD (Turn 1).

Expense = canonical authoritative cost transaction. ONE real-world cost
= ONE Expense row. Trip Cost / Vehicle Cost / Expense Register are
projections of this row and always read Expense — NEVER a twin
VendorBill/MechanicWorkOrder — to guarantee no double-count.

Write-time invariants enforced (all frozen in PRD Iter133):
  • amount > 0
  • date non-empty (accrual date, NOT payment date)
  • vendor_bill_id XOR mechanic_work_order_id — never both
  • vendor_bill_id set  → party_type='vendor',   party_id = VB.vendor_id
  • mech_wo_id     set  → party_type='mechanic', party_id = WO.mechanic_id
  • supplier_owned_vehicle=False → supplier_settlement_mode must be 'n/a'
  • supplier_owned_vehicle=True  → mode ∈ {supplier_settlement_adjustment,
                                          company_borne}
Turn-1 non-goals: no Trip Cost report, no Vehicle Cost report, no ledger
projection to Supplier Statement. Those land in the reporting turn.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import Expense, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict

router = APIRouter(prefix="/api")


def _require_delete_role(user: dict) -> None:
    role = (user.get("effective_role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or Admin role required.")


async def _validate_files(uid: str, cid: str, file_ids: list) -> None:
    if not file_ids:
        return
    found = await db.files.count_documents({
        "user_id": uid, "id": {"$in": file_ids}, "is_deleted": False,
    })
    if found != len(set(file_ids)):
        raise HTTPException(status_code=400, detail="One or more file_ids invalid for this tenant")


async def _validate_and_normalise(uid: str, cid: str, payload: Expense) -> Expense:
    """Enforces every Turn-1 Expense invariant. Returns the (possibly
    denormalised) payload."""
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if not payload.date:
        raise HTTPException(status_code=400, detail="date is required (cost/accrual date)")
    if not payload.category:
        raise HTTPException(status_code=400, detail="category is required")

    # Twin FK exclusivity
    if payload.vendor_bill_id and payload.mechanic_work_order_id:
        raise HTTPException(status_code=400, detail="Expense cannot link to BOTH vendor_bill_id and mechanic_work_order_id")

    # Vendor-bill linkage rules
    if payload.vendor_bill_id:
        bill = await db.vendor_bills.find_one(
            {"id": payload.vendor_bill_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "vendor_id": 1, "vendor_name": 1},
        )
        if not bill:
            raise HTTPException(status_code=400, detail="VendorBill not found in tenant")
        if payload.party_type != "vendor":
            raise HTTPException(status_code=400, detail="party_type must be 'vendor' when vendor_bill_id is set")
        if payload.party_id and payload.party_id != bill["vendor_id"]:
            raise HTTPException(status_code=400, detail="party_id must match VendorBill.vendor_id")
        payload.party_id = bill["vendor_id"]
        payload.party_name = payload.party_name or bill.get("vendor_name", "")

    # Mechanic-WO linkage rules
    if payload.mechanic_work_order_id:
        wo = await db.mechanic_work_orders.find_one(
            {"id": payload.mechanic_work_order_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "mechanic_id": 1, "mechanic_name": 1},
        )
        if not wo:
            raise HTTPException(status_code=400, detail="MechanicWorkOrder not found in tenant")
        if payload.party_type != "mechanic":
            raise HTTPException(status_code=400, detail="party_type must be 'mechanic' when mechanic_work_order_id is set")
        if payload.party_id and payload.party_id != wo["mechanic_id"]:
            raise HTTPException(status_code=400, detail="party_id must match MechanicWorkOrder.mechanic_id")
        payload.party_id = wo["mechanic_id"]
        payload.party_name = payload.party_name or wo.get("mechanic_name", "")

    # Supplier-owned-vehicle XOR guard
    if payload.supplier_owned_vehicle:
        if payload.supplier_settlement_mode not in ("supplier_settlement_adjustment", "company_borne"):
            raise HTTPException(
                status_code=400,
                detail="supplier_owned_vehicle=true requires supplier_settlement_mode of "
                       "'supplier_settlement_adjustment' or 'company_borne' (must be explicit).",
            )
    else:
        if payload.supplier_settlement_mode != "n/a":
            raise HTTPException(
                status_code=400,
                detail="supplier_settlement_mode must be 'n/a' when supplier_owned_vehicle=false.",
            )

    # Reference-existence checks
    if payload.vehicle_id:
        veh = await db.vehicles.find_one({"id": payload.vehicle_id, "user_id": uid, "company_id": cid}, {"_id": 0, "vehicle_number": 1})
        if not veh:
            raise HTTPException(status_code=400, detail="Vehicle not found in tenant")
        payload.vehicle_number = payload.vehicle_number or veh.get("vehicle_number", "")
    if payload.trip_id:
        trip = await db.trips.find_one({"id": payload.trip_id, "user_id": uid, "company_id": cid}, {"_id": 0, "id": 1})
        if not trip:
            raise HTTPException(status_code=400, detail="Trip not found in tenant")
    if payload.repair_event_id:
        rev = await db.repair_events.find_one(
            {"id": payload.repair_event_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "id": 1},
        )
        if not rev:
            raise HTTPException(status_code=400, detail="RepairEvent not found in tenant")

    # Party existence for typed parties (vendor/mechanic/supplier/driver)
    if payload.party_id and payload.party_type in ("vendor", "mechanic", "supplier", "driver"):
        coll_map = {
            "vendor": "vendors",
            "mechanic": "mechanics",
            "supplier": "suppliers",
            "driver": "drivers",
        }
        coll = coll_map[payload.party_type]
        p = await db[coll].find_one({"id": payload.party_id, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
        if not p:
            raise HTTPException(status_code=400, detail=f"{payload.party_type} not found in tenant")
        payload.party_name = payload.party_name or p.get("name", "")

    await _validate_files(uid, cid, payload.file_ids)
    return payload


@router.get("/expenses")
async def list_expenses(
    request: Request,
    trip_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    repair_event_id: Optional[str] = None,
    vendor_bill_id: Optional[str] = None,
    mechanic_work_order_id: Optional[str] = None,
    party_type: Optional[str] = None,
    party_id: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_reversed: bool = False,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}
    if not include_reversed:
        q["is_reversed"] = {"$ne": True}
    if trip_id: q["trip_id"] = trip_id
    if vehicle_id: q["vehicle_id"] = vehicle_id
    if repair_event_id: q["repair_event_id"] = repair_event_id
    if vendor_bill_id: q["vendor_bill_id"] = vendor_bill_id
    if mechanic_work_order_id: q["mechanic_work_order_id"] = mechanic_work_order_id
    if party_type: q["party_type"] = party_type
    if party_id: q["party_id"] = party_id
    if category: q["category"] = category
    if date_from or date_to:
        d: dict = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        q["date"] = d
    rows = await db.expenses.find(q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(20000)
    return rows


@router.post("/expenses")
async def create_expense(payload: Expense, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    # Reversal fields can never be set on create (managed by dedicated reversal path).
    payload.reversal_of = ""
    payload.is_reversed = False
    payload = await _validate_and_normalise(uid, cid, payload)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.expenses.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "expense", "create", doc["id"], doc.get("category", ""), "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/expenses/{eid}")
async def get_expense(eid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.expenses.find_one(
        {"id": eid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Expense not found")
    return doc


@router.put("/expenses/{eid}")
async def update_expense(eid: str, payload: Expense, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.expenses.find_one({"id": eid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Expense not found")
    if before.get("is_reversed"):
        raise HTTPException(status_code=400, detail="Cannot edit a reversed Expense; create a corrective entry instead.")
    # Reversal fields cannot be flipped via PUT.
    payload.reversal_of = before.get("reversal_of", "")
    payload.is_reversed = bool(before.get("is_reversed", False))
    payload = await _validate_and_normalise(uid, cid, payload)
    patch = payload.model_dump(exclude={"id", "created_at", "created_by",
                                        "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.expenses.update_one({"id": eid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "expense", "update", eid, before.get("category", ""), "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/expenses/{eid}")
async def delete_expense(
    eid: str, request: Request,
    reason: str = Query(..., min_length=3),
    user=Depends(get_current_user),
):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.expenses.find_one({"id": eid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Expense not found")
    await db.expenses.update_one(
        {"id": eid},
        {"$set": {
            "is_deleted": True,
            "deleted_by": uid,
            "deleted_at": now_utc().isoformat(),
            "deletion_reason": reason.strip(),
            "modified_by": uid,
            "modified_at": now_utc().isoformat(),
        }},
    )
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "expense", "delete", eid, doc.get("category", ""), reason, {})
    except Exception:
        pass
    return {"ok": True}
