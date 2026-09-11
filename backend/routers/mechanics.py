"""Iter133 · Mechanic master CRUD (Turn 1).

Mechanic = labour / service provider. DISTINCT identity from Vendor
(parts) and Supplier (hired vehicle). See PRD Iter133 party architecture.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query

from db import db
from models import Mechanic, MechanicPayment, now_utc, new_id
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


# ---------------------- Mechanic master ----------------------

@router.get("/mechanics")
async def list_mechanics(
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
            {"skill": {"$regex": q, "$options": "i"}},
        ]
    rows = await db.mechanics.find(query, {"_id": 0, "user_id": 0}).sort("name", 1).to_list(20000)
    return rows


@router.post("/mechanics")
async def create_mechanic(payload: Mechanic, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    await db.mechanics.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic", "create", doc["id"], doc.get("name", ""), "", {})
    except Exception:
        pass
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/mechanics/{mid}")
async def get_mechanic(mid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = await db.mechanics.find_one(
        {"id": mid, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Mechanic not found")
    return doc


@router.put("/mechanics/{mid}")
async def update_mechanic(mid: str, payload: Mechanic, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.mechanics.find_one({"id": mid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Mechanic not found")
    patch = payload.model_dump(exclude={"id", "created_at", "created_by"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.mechanics.update_one({"id": mid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic", "update", mid, before.get("name", ""), "", _diff_dict(before, after))
    except Exception:
        pass
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/mechanics/{mid}")
async def delete_mechanic(mid: str, request: Request, reason: str = "", user=Depends(get_current_user)):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.mechanics.find_one({"id": mid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Mechanic not found")
    reason_clean = (reason or "").strip()[:240]
    await db.mechanics.update_one(
        {"id": mid},
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
                         "mechanic", "deactivate", mid, doc.get("name", ""), reason_clean, {})
    except Exception:
        pass
    return {"ok": True, "id": mid, "is_active": False}


@router.post("/mechanics/{mid}/reactivate")
async def reactivate_mechanic(mid: str, request: Request, user=Depends(get_current_user)):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.mechanics.find_one({"id": mid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Mechanic not found")
    await db.mechanics.update_one(
        {"id": mid},
        {"$set": {"is_active": True, "modified_by": uid, "modified_at": now_utc().isoformat()}},
    )
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic", "reactivate", mid, doc.get("name", ""), "", {})
    except Exception:
        pass
    return {"ok": True, "id": mid, "is_active": True}


# ---------------------- Mechanic Payment (minimal) ----------------------

@router.get("/mechanics/{mid}/payments")
async def list_mechanic_payments(mid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    rows = await db.mechanic_payments.find(
        {"user_id": uid, "company_id": cid, "mechanic_id": mid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    ).sort("date", -1).to_list(5000)
    return rows


@router.post("/mechanics/{mid}/payments")
async def create_mechanic_payment(mid: str, payload: MechanicPayment, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    mec = await db.mechanics.find_one({"id": mid, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
    if not mec:
        raise HTTPException(status_code=404, detail="Mechanic not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if payload.mechanic_work_order_id:
        wo = await db.mechanic_work_orders.find_one(
            {"id": payload.mechanic_work_order_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "id": 1, "mechanic_id": 1},
        )
        if not wo:
            raise HTTPException(status_code=400, detail="Referenced work-order not found in tenant")
        if wo["mechanic_id"] != mid:
            raise HTTPException(status_code=400, detail="Work-order belongs to a different mechanic")
    doc = payload.model_dump()
    doc["id"] = doc.get("id") or new_id("mpay_")
    doc["mechanic_id"] = mid
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.mechanic_payments.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic_payment", "create", doc["id"], mec.get("name", ""), "", {})
    except Exception:
        pass
    # Iter150A-2 Phase 2 hook (never raises; failures land in fin_hook_failures).
    await hook_after_source_write(uid, cid, "mechanic_payment", doc["id"])
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.put("/mechanics/{mid}/payments/{pid}")
async def update_mechanic_payment(mid: str, pid: str, payload: MechanicPayment, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.mechanic_payments.find_one({"id": pid, "mechanic_id": mid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    patch = payload.model_dump(exclude={"id", "mechanic_id", "created_at", "created_by",
                                        "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.mechanic_payments.update_one({"id": pid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic_payment", "update", pid, "", "", _diff_dict(before, after))
    except Exception:
        pass
    # Iter150A-2 Phase 2 hook.
    await hook_after_source_write(uid, cid, "mechanic_payment", pid)
    after.pop("_id", None); after.pop("user_id", None)
    return after


@router.delete("/mechanics/{mid}/payments/{pid}")
async def delete_mechanic_payment(
    mid: str, pid: str, request: Request,
    reason: str = Query(..., min_length=3),
    user=Depends(get_current_user),
):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.mechanic_payments.find_one({"id": pid, "mechanic_id": mid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payment not found")
    patch = {
        "is_deleted": True,
        "deleted_by": uid,
        "deleted_at": now_utc().isoformat(),
        "deletion_reason": reason.strip(),
    }
    await db.mechanic_payments.update_one({"id": pid}, {"$set": patch})
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "mechanic_payment", "delete", pid, "", reason, {})
    except Exception:
        pass
    # Iter150A-2 Phase 2 hook — A-1 projection short-circuits on is_deleted → stale legs removed.
    await hook_after_source_write(uid, cid, "mechanic_payment", pid)
    return {"ok": True}
