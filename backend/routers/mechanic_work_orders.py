"""Iter133 · MechanicWorkOrder CRUD (Turn 1).

MechanicWorkOrder = mechanic labour PAYABLE + service evidence.
Does NOT project into Vehicle/Trip/Expense-Register cost views — those
views read the linked Expense row. Never sum WO.amount alongside its
twin Expense.amount. See PRD Iter133 report source map.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import MechanicWorkOrder, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict
# Iter150A-2 Phase 4 · MechanicWorkOrder projection hook (paired-Expense
# guard lives in A-1 project_mechanic_work_order via _has_paired_expense).
from services_fin_txn_hooks import hook_after_source_write

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


async def _validate_refs(uid: str, cid: str, payload: MechanicWorkOrder) -> tuple[str, str]:
    mec = await db.mechanics.find_one({"id": payload.mechanic_id, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
    if not mec:
        raise HTTPException(status_code=400, detail="Mechanic not found in tenant")
    veh_number = payload.vehicle_number
    if payload.vehicle_id:
        veh = await db.vehicles.find_one({"id": payload.vehicle_id, "user_id": uid, "company_id": cid}, {"_id": 0, "vehicle_number": 1})
        if not veh:
            raise HTTPException(status_code=400, detail="Vehicle not found in tenant")
        veh_number = veh_number or veh.get("vehicle_number", "")
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
    return mec.get("name", ""), veh_number


@router.get("/mechanic-work-orders")
async def list_mechanic_work_orders(
    request: Request,
    mechanic_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    repair_event_id: Optional[str] = None,
    trip_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}
    if mechanic_id: q["mechanic_id"] = mechanic_id
    if vehicle_id: q["vehicle_id"] = vehicle_id
    if repair_event_id: q["repair_event_id"] = repair_event_id
    if trip_id: q["trip_id"] = trip_id
    rows = await db.mechanic_work_orders.find(q, {"_id": 0, "user_id": 0}).sort("work_date", -1).to_list(5000)
    return rows


@router.post("/mechanic-work-orders")
async def create_mechanic_work_order(payload: MechanicWorkOrder, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if not payload.work_date:
        raise HTTPException(status_code=400, detail="work_date is required")
    mec_name, veh_number = await _validate_refs(uid, cid, payload)
    await _validate_files(uid, cid, payload.file_ids)
    doc = payload.model_dump()
    doc["mechanic_name"] = doc.get("mechanic_name") or mec_name
    doc["vehicle_number"] = veh_number
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.mechanic_work_orders.insert_one(doc)
    # Iter150A-2 Phase 4 · fire hook after authoritative insert.
    await hook_after_source_write(uid, cid, "mechanic_work_order", doc["id"])
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic_work_order", "create", doc["id"], mec_name, "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/mechanic-work-orders/{wid}")
async def get_mechanic_work_order(wid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.mechanic_work_orders.find_one(
        {"id": wid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="MechanicWorkOrder not found")
    return doc


@router.put("/mechanic-work-orders/{wid}")
async def update_mechanic_work_order(wid: str, payload: MechanicWorkOrder, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.mechanic_work_orders.find_one({"id": wid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="MechanicWorkOrder not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    mec_name, veh_number = await _validate_refs(uid, cid, payload)
    await _validate_files(uid, cid, payload.file_ids)
    patch = payload.model_dump(exclude={"id", "created_at", "created_by",
                                        "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["mechanic_name"] = patch.get("mechanic_name") or mec_name
    patch["vehicle_number"] = veh_number
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.mechanic_work_orders.update_one({"id": wid}, {"$set": patch})
    # Iter150A-2 Phase 4 · fire hook after successful update.
    await hook_after_source_write(uid, cid, "mechanic_work_order", wid)
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic_work_order", "update", wid, "", "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/mechanic-work-orders/{wid}")
async def delete_mechanic_work_order(
    wid: str, request: Request,
    reason: str = Query(..., min_length=3),
    user=Depends(get_current_user),
):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.mechanic_work_orders.find_one({"id": wid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="MechanicWorkOrder not found")
    live_scope = {"user_id": uid, "company_id": cid, "mechanic_work_order_id": wid, "is_deleted": {"$ne": True}}
    exp_ct = await db.expenses.count_documents(live_scope)
    pay_ct = await db.mechanic_payments.count_documents(live_scope)
    if exp_ct or pay_ct:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete MechanicWorkOrder with linked live records "
                   f"(expenses={exp_ct}, payments={pay_ct}). Delete or reverse them first.",
        )
    await db.mechanic_work_orders.update_one(
        {"id": wid},
        {"$set": {
            "is_deleted": True,
            "deleted_by": uid,
            "deleted_at": now_utc().isoformat(),
            "deletion_reason": reason.strip(),
            "modified_by": uid,
            "modified_at": now_utc().isoformat(),
        }},
    )
    # Iter150A-2 Phase 4 · fire hook after soft-delete; A-1
    # project_mechanic_work_order short-circuits on is_deleted → 0 legs.
    await hook_after_source_write(uid, cid, "mechanic_work_order", wid)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic_work_order", "delete", wid, "", reason, {})
    except Exception:
        pass
    return {"ok": True}
