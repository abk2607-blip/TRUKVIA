"""Iter133 · VendorBill CRUD (Turn 1).

VendorBill = spare-parts vendor PAYABLE + bill document evidence.
Turn-1 hard constraint (frozen): 1 VendorBill → at most 1 vehicle_id.
Multi-vehicle split is P1 and DEFERRED.

The bill does NOT project into Vehicle/Trip/Expense-Register cost views —
those views read the linked Expense row(s). See PRD Iter133 report source
map. Never sum VendorBill.bill_amount alongside its twin Expense.amount.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import VendorBill, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict
# Iter150A-2 Phase 4 · VendorBill projection hook (paired-Expense guard
# lives in A-1 project_vendor_bill via _has_paired_expense).
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


async def _validate_refs(uid: str, cid: str, payload: VendorBill) -> tuple[str, str]:
    ven = await db.vendors.find_one({"id": payload.vendor_id, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
    if not ven:
        raise HTTPException(status_code=400, detail="Vendor not found in tenant")
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
    return ven.get("name", ""), veh_number


@router.get("/vendor-bills")
async def list_vendor_bills(
    request: Request,
    vendor_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    repair_event_id: Optional[str] = None,
    trip_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}
    if vendor_id: q["vendor_id"] = vendor_id
    if vehicle_id: q["vehicle_id"] = vehicle_id
    if repair_event_id: q["repair_event_id"] = repair_event_id
    if trip_id: q["trip_id"] = trip_id
    rows = await db.vendor_bills.find(q, {"_id": 0, "user_id": 0}).sort("bill_date", -1).to_list(5000)
    return rows


@router.post("/vendor-bills")
async def create_vendor_bill(payload: VendorBill, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    if payload.bill_amount <= 0:
        raise HTTPException(status_code=400, detail="bill_amount must be positive")
    if not payload.bill_date:
        raise HTTPException(status_code=400, detail="bill_date is required")
    ven_name, veh_number = await _validate_refs(uid, cid, payload)
    await _validate_files(uid, cid, payload.file_ids)
    # Duplicate-bill guard (soft — unique (vendor_id, bill_number) per tenant when bill_number is set)
    if payload.bill_number:
        dup = await db.vendor_bills.find_one({
            "user_id": uid, "company_id": cid, "vendor_id": payload.vendor_id,
            "bill_number": payload.bill_number, "is_deleted": {"$ne": True},
        }, {"_id": 0, "id": 1})
        if dup:
            raise HTTPException(status_code=409, detail=f"Bill number '{payload.bill_number}' already exists for this vendor")
    doc = payload.model_dump()
    doc["vendor_name"] = doc.get("vendor_name") or ven_name
    doc["vehicle_number"] = veh_number
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.vendor_bills.insert_one(doc)
    # Iter150A-2 Phase 4 · fire hook after authoritative insert.
    await hook_after_source_write(uid, cid, "vendor_bill", doc["id"])
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor_bill", "create", doc["id"], doc.get("bill_number", ""), "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/vendor-bills/{bid}")
async def get_vendor_bill(bid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.vendor_bills.find_one(
        {"id": bid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="VendorBill not found")
    return doc


@router.put("/vendor-bills/{bid}")
async def update_vendor_bill(bid: str, payload: VendorBill, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.vendor_bills.find_one({"id": bid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="VendorBill not found")
    if payload.bill_amount <= 0:
        raise HTTPException(status_code=400, detail="bill_amount must be positive")
    ven_name, veh_number = await _validate_refs(uid, cid, payload)
    await _validate_files(uid, cid, payload.file_ids)
    patch = payload.model_dump(exclude={"id", "created_at", "created_by",
                                        "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["vendor_name"] = patch.get("vendor_name") or ven_name
    patch["vehicle_number"] = veh_number
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.vendor_bills.update_one({"id": bid}, {"$set": patch})
    # Iter150A-2 Phase 4 · fire hook after successful update.
    await hook_after_source_write(uid, cid, "vendor_bill", bid)
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor_bill", "update", bid, before.get("bill_number", ""), "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/vendor-bills/{bid}")
async def delete_vendor_bill(
    bid: str, request: Request,
    reason: str = Query(..., min_length=3),
    user=Depends(get_current_user),
):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.vendor_bills.find_one({"id": bid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="VendorBill not found")
    # Block delete if a live twin Expense or live Payment still references it.
    live_scope = {"user_id": uid, "company_id": cid, "vendor_bill_id": bid, "is_deleted": {"$ne": True}}
    exp_ct = await db.expenses.count_documents(live_scope)
    pay_ct = await db.vendor_payments.count_documents(live_scope)
    if exp_ct or pay_ct:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete VendorBill with linked live records "
                   f"(expenses={exp_ct}, payments={pay_ct}). Delete or reverse them first.",
        )
    await db.vendor_bills.update_one(
        {"id": bid},
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
    # project_vendor_bill short-circuits on is_deleted → 0 legs.
    await hook_after_source_write(uid, cid, "vendor_bill", bid)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor_bill", "delete", bid, doc.get("bill_number", ""), reason, {})
    except Exception:
        pass
    return {"ok": True}
