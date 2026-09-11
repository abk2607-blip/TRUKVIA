"""Iter133 · Vendor master CRUD (Turn 1).

Vendor = spare-parts / workshop vendor. DISTINCT identity from Supplier
(hired-vehicle owner) and Mechanic (labour). See PRD Iter133 party
architecture freeze.

Endpoints (all `/api` prefixed, company-scoped via X-Company-Id header):
  GET    /vendors                              — list (search + active filter)
  POST   /vendors                              — create
  GET    /vendors/{vid}                        — get one
  PUT    /vendors/{vid}                        — update
  DELETE /vendors/{vid}                        — soft delete (Owner/Admin only)
  POST   /vendors/{vid}/reactivate             — Owner/Admin only

Minimal payment compatibility (Turn 1; NO ledger UI / NO outstanding report):
  GET    /vendors/{vid}/payments               — list
  POST   /vendors/{vid}/payments               — create
  PUT    /vendors/{vid}/payments/{pid}         — update
  DELETE /vendors/{vid}/payments/{pid}         — soft delete (owner/admin)
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import Vendor, VendorPayment, now_utc, new_id
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict
# Iter150A-2 Phase 2 · post-write FinTxn projection hook (never raises).
from services_fin_txn_hooks import hook_after_source_write

router = APIRouter(prefix="/api")


def _require_delete_role(user: dict) -> None:
    role = (user.get("effective_role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or Admin role required.")


# ---------------------- Vendor master ----------------------

@router.get("/vendors")
async def list_vendors(
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
    rows = await db.vendors.find(query, {"_id": 0, "user_id": 0}).sort("name", 1).to_list(20000)
    return rows


@router.post("/vendors")
async def create_vendor(payload: Vendor, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    await db.vendors.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor", "create", doc["id"], doc.get("name", ""), "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/vendors/{vid}")
async def get_vendor(vid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = await db.vendors.find_one(
        {"id": vid, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return doc


@router.put("/vendors/{vid}")
async def update_vendor(vid: str, payload: Vendor, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.vendors.find_one({"id": vid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Vendor not found")
    patch = payload.model_dump(exclude={"id", "created_at", "created_by"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.vendors.update_one({"id": vid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor", "update", vid, before.get("name", ""), "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/vendors/{vid}")
async def delete_vendor(vid: str, request: Request, reason: str = "", user=Depends(get_current_user)):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.vendors.find_one({"id": vid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Vendor not found")
    reason_clean = (reason or "").strip()[:240]
    await db.vendors.update_one(
        {"id": vid},
        {"$set": {
            "is_active": False,
            "deactivated_by": uid,
            "deactivated_at": now_utc().isoformat(),
            "deactivation_reason": reason_clean,
            "modified_by": uid,
            "modified_at": now_utc().isoformat(),
        }},
    )
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor", "deactivate", vid, doc.get("name", ""), reason_clean, {})
    except Exception:
        pass
    return {"ok": True, "id": vid, "is_active": False}


@router.post("/vendors/{vid}/reactivate")
async def reactivate_vendor(vid: str, request: Request, user=Depends(get_current_user)):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.vendors.find_one({"id": vid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Vendor not found")
    await db.vendors.update_one(
        {"id": vid},
        {"$set": {
            "is_active": True,
            "modified_by": uid,
            "modified_at": now_utc().isoformat(),
        }},
    )
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor", "reactivate", vid, doc.get("name", ""), "", {})
    except Exception:
        pass
    return {"ok": True, "id": vid, "is_active": True}


# ---------------------- Vendor Payment (minimal) ----------------------

@router.get("/vendors/{vid}/payments")
async def list_vendor_payments(vid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    rows = await db.vendor_payments.find(
        {"user_id": uid, "company_id": cid, "vendor_id": vid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    ).sort("date", -1).to_list(5000)
    return rows


@router.post("/vendors/{vid}/payments")
async def create_vendor_payment(vid: str, payload: VendorPayment, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    ven = await db.vendors.find_one({"id": vid, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
    if not ven:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if payload.vendor_bill_id:
        bill = await db.vendor_bills.find_one(
            {"id": payload.vendor_bill_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "id": 1, "vendor_id": 1},
        )
        if not bill:
            raise HTTPException(status_code=400, detail="Referenced vendor bill not found in tenant")
        if bill["vendor_id"] != vid:
            raise HTTPException(status_code=400, detail="Bill belongs to a different vendor")
    doc = payload.model_dump()
    doc["id"] = doc.get("id") or new_id("vpay_")
    doc["vendor_id"] = vid
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.vendor_payments.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor_payment", "create", doc["id"], ven.get("name", ""), "", {})
    except Exception:
        pass
    # Iter150A-2 Phase 2 hook (never raises; failures land in fin_hook_failures).
    await hook_after_source_write(uid, cid, "vendor_payment", doc["id"])
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.put("/vendors/{vid}/payments/{pid}")
async def update_vendor_payment(vid: str, pid: str, payload: VendorPayment, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.vendor_payments.find_one({"id": pid, "vendor_id": vid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    patch = payload.model_dump(exclude={"id", "vendor_id", "created_at", "created_by",
                                        "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.vendor_payments.update_one({"id": pid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor_payment", "update", pid, "", "", _diff_dict(before, after))
    except Exception:
        pass
    # Iter150A-2 Phase 2 hook.
    await hook_after_source_write(uid, cid, "vendor_payment", pid)
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/vendors/{vid}/payments/{pid}")
async def delete_vendor_payment(
    vid: str, pid: str, request: Request,
    reason: str = Query(..., min_length=3),
    user=Depends(get_current_user),
):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.vendor_payments.find_one({"id": pid, "vendor_id": vid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payment not found")
    patch = {
        "is_deleted": True,
        "deleted_by": uid,
        "deleted_at": now_utc().isoformat(),
        "deletion_reason": reason.strip(),
    }
    await db.vendor_payments.update_one({"id": pid}, {"$set": patch})
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "vendor_payment", "delete", pid, "", reason, {})
    except Exception:
        pass
    # Iter150A-2 Phase 2 hook — A-1 projection short-circuits on is_deleted → stale legs removed.
    await hook_after_source_write(uid, cid, "vendor_payment", pid)
    return {"ok": True}
