"""Iter150B · WalletTransfer CRUD — 2-leg direct wallet-to-wallet.

Business rules (frozen per Iter150B authorisation):
  * Canonical accounting: `source_wallet_code` CREDIT +
    `destination_wallet_code` DEBIT. NO INTER_ACCOUNT contra.
  * Same-wallet transfer rejected with 422.
  * Cross-company transfer structurally impossible — every read/write
    is scoped by (user_id, company_id).
  * Backdate allowed.
  * Soft-delete via `is_deleted=True`. Legs cleared through the
    reproject/delete cycle.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends

from db import db
from models import WalletTransfer, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict
from services_fin_txn_hooks import hook_after_source_write

router = APIRouter(prefix="/api")


@router.get("/wallet-transfers")
async def list_wallet_transfers(
    request: Request,
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
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    rows = await db.wallet_transfers.find(
        q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(5000)
    return rows


@router.post("/wallet-transfers")
async def create_wallet_transfer(
    payload: WalletTransfer, request: Request,
    user=Depends(get_current_user),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be > 0")
    if payload.source_wallet_code == payload.destination_wallet_code:
        raise HTTPException(
            status_code=422,
            detail="source_wallet_code and destination_wallet_code must differ",
        )
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.wallet_transfers.insert_one(doc)
    await _log_audit(
        user, "wallet_transfer", "create",
        entity_id=doc["id"],
        entity_ref=f"{doc['source_wallet_code']}→{doc['destination_wallet_code']}",
        changes={"amount": doc["amount"], "date": doc["date"],
                 "reference": doc.get("reference", "")},
    )
    await hook_after_source_write(uid, cid, "wallet_transfer", doc["id"])
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.put("/wallet-transfers/{wt_id}")
async def update_wallet_transfer(
    wt_id: str, payload: WalletTransfer, request: Request,
    user=Depends(get_current_user),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be > 0")
    if payload.source_wallet_code == payload.destination_wallet_code:
        raise HTTPException(
            status_code=422,
            detail="source_wallet_code and destination_wallet_code must differ",
        )
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    existing = await db.wallet_transfers.find_one(
        {"id": wt_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="WalletTransfer not found")
    if existing.get("is_deleted"):
        raise HTTPException(status_code=409,
                            detail="Cannot edit a deleted transfer")
    doc = payload.model_dump()
    doc["id"] = wt_id
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = existing.get("created_by", "")
    doc["created_at"] = existing.get("created_at", "")
    doc["is_deleted"] = False
    await db.wallet_transfers.update_one({"id": wt_id, "user_id": uid}, {"$set": doc})
    changes = _diff_dict(
        existing, doc,
        ["amount", "source_wallet_code", "destination_wallet_code",
         "date", "reference", "remarks"],
    )
    await _log_audit(
        user, "wallet_transfer", "update", entity_id=wt_id,
        entity_ref=f"{doc['source_wallet_code']}→{doc['destination_wallet_code']}",
        changes=changes,
    )
    await hook_after_source_write(uid, cid, "wallet_transfer", wt_id)
    doc.pop("user_id", None)
    return doc


@router.delete("/wallet-transfers/{wt_id}")
async def delete_wallet_transfer(
    wt_id: str, request: Request,
    reason: str = "", user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    existing = await db.wallet_transfers.find_one(
        {"id": wt_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="WalletTransfer not found")
    if existing.get("is_deleted"):
        return {"ok": True, "already_deleted": True}
    await db.wallet_transfers.update_one(
        {"id": wt_id, "user_id": uid}, {"$set": {"is_deleted": True}})
    await _log_audit(
        user, "wallet_transfer", "delete", entity_id=wt_id,
        entity_ref=f"{existing.get('source_wallet_code','')}→{existing.get('destination_wallet_code','')}",
        reason=reason,
        changes={"snapshot": {k: existing.get(k) for k in
                              ("amount", "source_wallet_code",
                               "destination_wallet_code", "date",
                               "reference")}},
    )
    await hook_after_source_write(uid, cid, "wallet_transfer", wt_id)
    return {"ok": True}
