"""Iter133 · RepairEvent CRUD (Turn 1).

RepairEvent = operational envelope only. NEVER stores a monetary total.
Vehicle Repair Cost = Σ Expense.amount where repair_event_id = this.id.

The Pydantic model has `extra='forbid'` so any client attempt to smuggle
`total_cost` in the payload triggers 422 — this is the guard against
introducing a second source of truth.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import RepairEvent, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict

router = APIRouter(prefix="/api")


def _require_delete_role(user: dict) -> None:
    role = (user.get("effective_role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or Admin role required.")


async def _validate_files(uid: str, cid: str, file_ids: list) -> None:
    """Every file_id must belong to this user tenant. Cheap membership check."""
    if not file_ids:
        return
    found = await db.files.count_documents({
        "user_id": uid, "id": {"$in": file_ids}, "is_deleted": False,
    })
    if found != len(set(file_ids)):
        raise HTTPException(status_code=400, detail="One or more file_ids invalid for this tenant")


@router.get("/repair-events")
async def list_repair_events(
    request: Request,
    vehicle_id: Optional[str] = None,
    trip_id: Optional[str] = None,
    status: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}
    if vehicle_id: q["vehicle_id"] = vehicle_id
    if trip_id: q["trip_id"] = trip_id
    if status: q["status"] = status
    rows = await db.repair_events.find(q, {"_id": 0, "user_id": 0}).sort("event_date", -1).to_list(5000)
    return rows


@router.post("/repair-events")
async def create_repair_event(payload: RepairEvent, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    if not payload.event_date:
        raise HTTPException(status_code=400, detail="event_date is required")
    # Optional vehicle/trip existence checks (soft — only validate if provided)
    if payload.vehicle_id:
        veh = await db.vehicles.find_one({"id": payload.vehicle_id, "user_id": uid, "company_id": cid}, {"_id": 0, "vehicle_number": 1})
        if not veh:
            raise HTTPException(status_code=400, detail="Vehicle not found in tenant")
        # denormalise vehicle_number if not supplied
        payload.vehicle_number = payload.vehicle_number or veh.get("vehicle_number", "")
    if payload.trip_id:
        trip = await db.trips.find_one({"id": payload.trip_id, "user_id": uid, "company_id": cid}, {"_id": 0, "id": 1})
        if not trip:
            raise HTTPException(status_code=400, detail="Trip not found in tenant")
    await _validate_files(uid, cid, payload.file_ids)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.repair_events.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "repair_event", "create", doc["id"], doc.get("workshop_name", ""), "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/repair-events/{rid}")
async def get_repair_event(rid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.repair_events.find_one(
        {"id": rid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="RepairEvent not found")
    return doc


@router.put("/repair-events/{rid}")
async def update_repair_event(rid: str, payload: RepairEvent, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.repair_events.find_one({"id": rid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="RepairEvent not found")
    await _validate_files(uid, cid, payload.file_ids)
    patch = payload.model_dump(exclude={"id", "created_at", "created_by",
                                        "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.repair_events.update_one({"id": rid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "repair_event", "update", rid, before.get("workshop_name", ""), "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/repair-events/{rid}")
async def delete_repair_event(
    rid: str, request: Request,
    reason: str = Query(..., min_length=3),
    user=Depends(get_current_user),
):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.repair_events.find_one({"id": rid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="RepairEvent not found")
    # If linked expenses/bills/WOs still active, block deletion; user must delete them first.
    live_scope = {"user_id": uid, "company_id": cid, "repair_event_id": rid, "is_deleted": {"$ne": True}}
    exp_ct = await db.expenses.count_documents(live_scope)
    bill_ct = await db.vendor_bills.count_documents(live_scope)
    wo_ct = await db.mechanic_work_orders.count_documents(live_scope)
    if exp_ct or bill_ct or wo_ct:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete RepairEvent with linked live records "
                   f"(expenses={exp_ct}, bills={bill_ct}, work_orders={wo_ct}). "
                   f"Delete or unlink them first.",
        )
    await db.repair_events.update_one(
        {"id": rid},
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
                         "repair_event", "delete", rid, doc.get("workshop_name", ""), reason, {})
    except Exception:
        pass
    return {"ok": True}
