"""Iter150B · WalletRecharge CRUD — BANK/CASH → WALLET write-path.

Business rules (frozen per Iter150B authorisation):
  * Canonical accounting: `wallet_code` DEBIT + `_mode_account(funding_mode)`
    CREDIT — 2 legs, no SUSPENSE default.
  * Funding mode restricted to {"Bank", "Cash"} at the model layer.
  * Wallet code restricted to {"WALLET_FASTAG", "WALLET_FUEL"}.
  * Business date independent of created_at — any past date allowed.
  * Soft-delete via `is_deleted=True`. Canonical legs cleared through the
    reproject/delete cycle. Historical audit remains intact.
  * Router MUST NOT touch fin_txn directly — projection is owned by the
    canonical hook chain.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends

from db import db
from models import WalletRecharge, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict
from services_fin_txn_hooks import hook_after_source_write

router = APIRouter(prefix="/api")


@router.get("/wallet-recharges")
async def list_wallet_recharges(
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
    rows = await db.wallet_recharges.find(
        q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(5000)
    return rows


@router.post("/wallet-recharges")
async def create_wallet_recharge(
    payload: WalletRecharge, request: Request,
    user=Depends(get_current_user),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be > 0")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.wallet_recharges.insert_one(doc)
    await _log_audit(
        user, "wallet_recharge", "create",
        entity_id=doc["id"], entity_ref=doc["wallet_code"],
        changes={"amount": doc["amount"], "funding_mode": doc["funding_mode"],
                 "date": doc["date"], "reference": doc.get("reference", "")},
    )
    await hook_after_source_write(uid, cid, "wallet_recharge", doc["id"])
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.put("/wallet-recharges/{wr_id}")
async def update_wallet_recharge(
    wr_id: str, payload: WalletRecharge, request: Request,
    user=Depends(get_current_user),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be > 0")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    existing = await db.wallet_recharges.find_one(
        {"id": wr_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="WalletRecharge not found")
    if existing.get("is_deleted"):
        raise HTTPException(status_code=409,
                            detail="Cannot edit a deleted recharge")
    doc = payload.model_dump()
    doc["id"] = wr_id
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = existing.get("created_by", "")
    doc["created_at"] = existing.get("created_at", "")
    doc["is_deleted"] = False
    await db.wallet_recharges.update_one({"id": wr_id, "user_id": uid}, {"$set": doc})
    changes = _diff_dict(
        existing, doc,
        ["amount", "wallet_code", "funding_mode", "date",
         "reference", "remarks"],
    )
    await _log_audit(
        user, "wallet_recharge", "update",
        entity_id=wr_id, entity_ref=doc["wallet_code"], changes=changes,
    )
    await hook_after_source_write(uid, cid, "wallet_recharge", wr_id)
    doc.pop("user_id", None)
    return doc


@router.delete("/wallet-recharges/{wr_id}")
async def delete_wallet_recharge(
    wr_id: str, request: Request,
    reason: str = "", user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    existing = await db.wallet_recharges.find_one(
        {"id": wr_id, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="WalletRecharge not found")
    if existing.get("is_deleted"):
        return {"ok": True, "already_deleted": True}
    await db.wallet_recharges.update_one(
        {"id": wr_id, "user_id": uid}, {"$set": {"is_deleted": True}})
    await _log_audit(
        user, "wallet_recharge", "delete",
        entity_id=wr_id, entity_ref=existing.get("wallet_code", ""),
        reason=reason,
        changes={"snapshot": {k: existing.get(k) for k in
                              ("amount", "funding_mode", "date",
                               "reference", "wallet_code")}},
    )
    await hook_after_source_write(uid, cid, "wallet_recharge", wr_id)
    return {"ok": True}
