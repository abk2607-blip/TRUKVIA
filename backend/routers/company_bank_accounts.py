"""Iter150G · Company Bank Account router (new · non-locked).

Read-only masking is enforced for callers without `view_bank_account_full`.
No ledger mutation. No fin_txn writes.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request

from db import db
from models_bank import CompanyBankAccount
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit
from services_bank_accounts import (
    mask_account_number, duplicate_exists_company, clear_primary_company,
    strip_full_number, party_role_can_manage, party_role_can_view_full,
)
from models import now_utc, new_id

router = APIRouter(prefix="/api", tags=["CompanyBankAccount"])


def _require_manage(user):
    if not party_role_can_manage(user):
        raise HTTPException(status_code=403,
                            detail="Owner or Accountant role required.")


@router.get("/company-bank-accounts")
async def list_company_bank_accounts(
    request: Request, user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    allow_full = party_role_can_view_full(user)
    rows = await db.company_bank_accounts.find(
        {"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0},
    ).sort("created_at", -1).to_list(500)
    return [strip_full_number(r, allow_full) for r in rows]


@router.post("/company-bank-accounts")
async def create_company_bank_account(
    payload: CompanyBankAccount, request: Request,
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    if not payload.account_number.strip() or not payload.ifsc.strip():
        raise HTTPException(400, "account_number and ifsc are required")
    if await duplicate_exists_company(uid, cid, payload.account_number,
                                       payload.ifsc):
        raise HTTPException(409, "Active bank account with same (account_number, ifsc) already exists")
    doc = payload.model_dump()
    doc["id"] = doc.get("id") or new_id("cba_")
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["masked_display"] = mask_account_number(doc["account_number"])
    if doc.get("is_primary"):
        await clear_primary_company(uid, cid, keep_id=doc["id"])
    await db.company_bank_accounts.insert_one(doc)
    doc.pop("_id", None)
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "company_bank_account", "create", doc["id"],
        doc.get("bank_name", ""), "", {},
    )
    return strip_full_number(doc, party_role_can_view_full(user))


@router.put("/company-bank-accounts/{bid}")
async def update_company_bank_account(
    bid: str, payload: dict, request: Request,
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.company_bank_accounts.find_one(
        {"id": bid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(404, "Bank account not found")
    # Whitelist editable scalar metadata. Account number / IFSC changes MUST
    # use the replace endpoint (creates new id) per Iter150G invariant.
    ALLOWED = {"account_holder_name", "bank_name", "branch", "account_type",
               "verification_status"}
    patch = {k: v for k, v in (payload or {}).items() if k in ALLOWED}
    if not patch:
        raise HTTPException(400, "No editable fields provided")
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.company_bank_accounts.update_one({"id": bid}, {"$set": patch})
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "company_bank_account", "edit", bid, before.get("bank_name", ""), "",
        {k: {"old": before.get(k), "new": patch.get(k)} for k in patch
         if k not in ("modified_by", "modified_at")},
    )
    return strip_full_number({**before, **patch}, party_role_can_view_full(user))


@router.post("/company-bank-accounts/{bid}/set-primary")
async def set_primary_company(
    bid: str, request: Request, user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.company_bank_accounts.find_one(
        {"id": bid, "user_id": uid, "company_id": cid, "is_active": True},
        {"_id": 0})
    if not doc:
        raise HTTPException(404, "Active bank account not found")
    await clear_primary_company(uid, cid, keep_id=bid)
    await db.company_bank_accounts.update_one(
        {"id": bid}, {"$set": {"is_primary": True,
                                "modified_by": uid,
                                "modified_at": now_utc().isoformat()}},
    )
    return {"ok": True, "id": bid, "is_primary": True}


@router.post("/company-bank-accounts/{bid}/deactivate")
async def deactivate_company(
    bid: str, payload: dict = None, request: Request = None,  # noqa
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.company_bank_accounts.find_one(
        {"id": bid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Bank account not found")
    reason = ((payload or {}).get("reason") or "").strip()[:240]
    await db.company_bank_accounts.update_one(
        {"id": bid},
        {"$set": {"is_active": False, "is_primary": False,
                   "deactivated_by": uid,
                   "deactivated_at": now_utc().isoformat(),
                   "deactivation_reason": reason,
                   "modified_by": uid,
                   "modified_at": now_utc().isoformat()}},
    )
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "company_bank_account", "deactivate", bid,
        doc.get("bank_name", ""), reason, {},
    )
    return {"ok": True, "id": bid, "is_active": False}


@router.post("/company-bank-accounts/{bid}/replace")
async def replace_company(
    bid: str, payload: CompanyBankAccount, request: Request,
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    old = await db.company_bank_accounts.find_one(
        {"id": bid, "user_id": uid, "company_id": cid, "is_active": True},
        {"_id": 0})
    if not old:
        raise HTTPException(404, "Active bank account not found")
    new_doc = payload.model_dump()
    new_doc["id"] = new_id("cba_")
    new_doc["user_id"] = uid
    new_doc["company_id"] = cid
    new_doc["created_by"] = uid
    new_doc["created_at"] = now_utc().isoformat()
    new_doc["is_active"] = True
    new_doc["masked_display"] = mask_account_number(new_doc["account_number"])
    if new_doc.get("is_primary") or old.get("is_primary"):
        await clear_primary_company(uid, cid, keep_id=new_doc["id"])
        new_doc["is_primary"] = True
    await db.company_bank_accounts.insert_one(new_doc)
    new_doc.pop("_id", None)
    await db.company_bank_accounts.update_one(
        {"id": bid},
        {"$set": {"is_active": False, "is_primary": False,
                   "deactivated_by": uid,
                   "deactivated_at": now_utc().isoformat(),
                   "deactivation_reason": f"replaced_by:{new_doc['id']}"}},
    )
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "company_bank_account", "replace", bid,
        old.get("bank_name", ""),
        f"replaced_by:{new_doc['id']}", {},
    )
    return strip_full_number(new_doc, party_role_can_view_full(user))


@router.get("/company-bank-accounts/{bid}/reveal")
async def reveal_company_full(
    bid: str, request: Request, user=Depends(get_current_user),
):
    """Owner + accountant only: full account_number reveal."""
    if not party_role_can_view_full(user):
        raise HTTPException(403, "Not permitted to reveal full account number")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.company_bank_accounts.find_one(
        {"id": bid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Bank account not found")
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "company_bank_account", "reveal", bid, doc.get("bank_name", ""), "", {},
    )
    return {"id": bid, "account_number": doc.get("account_number", "")}
