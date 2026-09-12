"""Iter150B · WalletAdjustment CRUD + APPEND-ONLY reversal.

Business rules (frozen per Iter150B authorisation):
  * Canonical accounting against SUSPENSE contra account.
  * Positive: wallet DEBIT + SUSPENSE CREDIT.
  * Negative: wallet CREDIT + SUSPENSE DEBIT.
  * Reversal: NEW WalletAdjustment with `reverses_id` = original id and
    opposite direction. Original doc never mutated. Both stay projected
    → net-zero effect while preserving history + audit trail.
  * Editing / deleting a WA that has an active downstream reversal is
    blocked with 409 Conflict.
  * A reversal WA is itself immutable (edit/delete/reverse → 409).
  * Backdate allowed on every action, including reversal.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends, Body

from db import db
from models import WalletAdjustment, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict
from services_fin_txn_hooks import hook_after_source_write

router = APIRouter(prefix="/api")


async def _find_active_reversal(uid: str, cid: str, wa_id: str) -> Optional[dict]:
    return await db.wallet_adjustments.find_one(
        {"user_id": uid, "company_id": cid,
         "reverses_id": wa_id, "is_deleted": {"$ne": True}},
        {"_id": 0, "id": 1},
    )


@router.get("/wallet-adjustments")
async def list_wallet_adjustments(
    request: Request,
    wallet_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_deleted: bool = False,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid}
    if not include_deleted:
        q["is_deleted"] = {"$ne": True}
    if wallet_code:
        q["wallet_code"] = wallet_code
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    rows = await db.wallet_adjustments.find(
        q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(5000)
    return rows


@router.post("/wallet-adjustments")
async def create_wallet_adjustment(
    payload: WalletAdjustment, request: Request,
    user=Depends(get_current_user),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be > 0")
    if not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="reason is required")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    # `reverses_id` is only set via the dedicated /reverse endpoint —
    # ignore any client-supplied value here to preserve append-only
    # reversal semantics.
    doc["reverses_id"] = ""
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.wallet_adjustments.insert_one(doc)
    await _log_audit(
        user, "wallet_adjustment", "create", entity_id=doc["id"],
        entity_ref=f"{doc['wallet_code']} {doc['direction']}",
        changes={"amount": doc["amount"], "date": doc["date"],
                 "reason": doc["reason"],
                 "reference": doc.get("reference", "")},
    )
    await hook_after_source_write(uid, cid, "wallet_adjustment", doc["id"])
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.put("/wallet-adjustments/{wa_id}")
async def update_wallet_adjustment(
    wa_id: str, payload: WalletAdjustment, request: Request,
    user=Depends(get_current_user),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be > 0")
    if not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="reason is required")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    existing = await db.wallet_adjustments.find_one(
        {"id": wa_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="WalletAdjustment not found")
    if existing.get("is_deleted"):
        raise HTTPException(status_code=409,
                            detail="Cannot edit a deleted adjustment")
    if existing.get("reverses_id"):
        raise HTTPException(status_code=409,
                            detail="Reversal adjustments are immutable")
    if await _find_active_reversal(uid, cid, wa_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot edit an adjustment that has an active reversal",
        )
    doc = payload.model_dump()
    doc["id"] = wa_id
    doc["user_id"] = uid
    doc["company_id"] = cid
    # Preserve immutable fields from the original document.
    doc["reverses_id"] = existing.get("reverses_id", "")
    doc["created_by"] = existing.get("created_by", "")
    doc["created_at"] = existing.get("created_at", "")
    doc["is_deleted"] = False
    await db.wallet_adjustments.update_one(
        {"id": wa_id, "user_id": uid}, {"$set": doc})
    changes = _diff_dict(
        existing, doc,
        ["amount", "wallet_code", "direction", "date", "reason", "reference"],
    )
    await _log_audit(
        user, "wallet_adjustment", "update", entity_id=wa_id,
        entity_ref=f"{doc['wallet_code']} {doc['direction']}",
        changes=changes,
    )
    await hook_after_source_write(uid, cid, "wallet_adjustment", wa_id)
    doc.pop("user_id", None)
    return doc


@router.delete("/wallet-adjustments/{wa_id}")
async def delete_wallet_adjustment(
    wa_id: str, request: Request,
    reason: str = "", user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    existing = await db.wallet_adjustments.find_one(
        {"id": wa_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="WalletAdjustment not found")
    if existing.get("is_deleted"):
        return {"ok": True, "already_deleted": True}
    if existing.get("reverses_id"):
        raise HTTPException(status_code=409,
                            detail="Reversal adjustments are immutable")
    if await _find_active_reversal(uid, cid, wa_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete an adjustment that has an active reversal",
        )
    await db.wallet_adjustments.update_one(
        {"id": wa_id, "user_id": uid}, {"$set": {"is_deleted": True}})
    await _log_audit(
        user, "wallet_adjustment", "delete", entity_id=wa_id,
        entity_ref=f"{existing.get('wallet_code','')} {existing.get('direction','')}",
        reason=reason,
        changes={"snapshot": {k: existing.get(k) for k in
                              ("amount", "wallet_code", "direction",
                               "date", "reason", "reference")}},
    )
    await hook_after_source_write(uid, cid, "wallet_adjustment", wa_id)
    return {"ok": True}


@router.post("/wallet-adjustments/{wa_id}/reverse")
async def reverse_wallet_adjustment(
    wa_id: str, request: Request,
    body: dict = Body(...),
    user=Depends(get_current_user),
):
    """Append-only reversal — creates a NEW WA doc with `reverses_id`
    pointing to the original and opposite direction. Original is never
    mutated. Both stay projected → net zero, full history preserved.
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    original = await db.wallet_adjustments.find_one(
        {"id": wa_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not original:
        raise HTTPException(status_code=404, detail="WalletAdjustment not found")
    if original.get("is_deleted"):
        raise HTTPException(status_code=409,
                            detail="Cannot reverse a deleted adjustment")
    if original.get("reverses_id"):
        raise HTTPException(status_code=409,
                            detail="Cannot reverse a reversal")
    if await _find_active_reversal(uid, cid, wa_id):
        raise HTTPException(status_code=409,
                            detail="Adjustment already has an active reversal")
    payload_reason = str(body.get("reason") or "").strip()
    if not payload_reason:
        raise HTTPException(status_code=422, detail="reason is required")
    rev_date = str(body.get("date") or "").strip() or \
        now_utc().date().isoformat()
    opposite = "decrease" if original["direction"] == "increase" else "increase"
    rev_doc = WalletAdjustment(
        wallet_code=original["wallet_code"], direction=opposite,
        amount=float(original["amount"]), date=rev_date,
        reason=f"Reversal of {wa_id}: {payload_reason}",
        reference=original.get("reference", ""),
        reverses_id=wa_id,
    ).model_dump()
    rev_doc["user_id"] = uid
    rev_doc["company_id"] = cid
    rev_doc["created_by"] = uid
    rev_doc["created_at"] = now_utc().isoformat()
    rev_doc["is_deleted"] = False
    await db.wallet_adjustments.insert_one(rev_doc)
    await _log_audit(
        user, "wallet_adjustment", "reverse", entity_id=rev_doc["id"],
        entity_ref=f"reverses:{wa_id}",
        changes={"reversed_id": wa_id, "amount": rev_doc["amount"],
                 "direction": rev_doc["direction"], "date": rev_doc["date"]},
    )
    await hook_after_source_write(uid, cid, "wallet_adjustment", rev_doc["id"])
    rev_doc.pop("_id", None); rev_doc.pop("user_id", None)
    return rev_doc
