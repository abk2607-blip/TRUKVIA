"""Iter150G · Party Bank Account router (new · non-locked)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from db import db
from models_bank import PartyBankAccount, PARTY_TYPES
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit
from services_bank_accounts import (
    mask_account_number, duplicate_exists_party, clear_primary_party,
    strip_full_number, party_role_can_manage, party_role_can_view_full,
)
from models import now_utc, new_id

router = APIRouter(prefix="/api", tags=["PartyBankAccount"])

_PARTY_COLL = {
    "supplier": "suppliers", "vendor": "vendors", "mechanic": "mechanics",
    "driver": "drivers", "customer": "customers",
}


def _require_manage(user):
    if not party_role_can_manage(user):
        raise HTTPException(status_code=403,
                            detail="Owner or Accountant role required.")


async def _ensure_party_exists(uid: str, cid: str, party_type: str, party_id: str):
    if party_type not in PARTY_TYPES:
        raise HTTPException(400, f"unsupported party_type. Allowed: {PARTY_TYPES}")
    coll = _PARTY_COLL[party_type]
    q = {"id": party_id, "user_id": uid}
    # Company-scope only where the party master has company_id (drivers may not)
    if party_type in ("supplier", "vendor", "mechanic", "customer"):
        q["company_id"] = cid
    doc = await db[coll].find_one(q, {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(404, f"{party_type} not found in this tenant")


@router.get("/party-bank-accounts")
async def list_party_bank_accounts(
    request: Request,
    party_type: str = Query(...),
    party_id: str = Query(...),
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    if party_type not in PARTY_TYPES:
        raise HTTPException(400, f"unsupported party_type. Allowed: {PARTY_TYPES}")
    allow_full = party_role_can_view_full(user)
    rows = await db.party_bank_accounts.find(
        {"user_id": uid, "party_type": party_type, "party_id": party_id},
        {"_id": 0, "user_id": 0},
    ).sort("created_at", -1).to_list(500)
    return [strip_full_number(r, allow_full) for r in rows]


@router.post("/party-bank-accounts")
async def create_party_bank_account(
    payload: PartyBankAccount, request: Request,
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    await _ensure_party_exists(uid, cid, payload.party_type, payload.party_id)
    if not payload.account_number.strip() or not payload.ifsc.strip():
        raise HTTPException(400, "account_number and ifsc are required")
    if await duplicate_exists_party(uid, payload.party_type, payload.party_id,
                                     payload.account_number, payload.ifsc):
        raise HTTPException(409, "Active bank account with same (account_number, ifsc) already exists for this party")
    doc = payload.model_dump()
    doc["id"] = doc.get("id") or new_id("pba_")
    doc["user_id"] = uid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["masked_display"] = mask_account_number(doc["account_number"])
    if doc.get("is_primary"):
        await clear_primary_party(uid, doc["party_type"], doc["party_id"],
                                  keep_id=doc["id"])
    await db.party_bank_accounts.insert_one(doc)
    doc.pop("_id", None)
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "party_bank_account", "create", doc["id"],
        f"{doc['party_type']}:{doc['party_id']}", "", {},
    )
    return strip_full_number(doc, party_role_can_view_full(user))


@router.put("/party-bank-accounts/{bid}")
async def update_party_bank_account(
    bid: str, payload: dict, request: Request,
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.party_bank_accounts.find_one(
        {"id": bid, "user_id": uid}, {"_id": 0})
    if not before:
        raise HTTPException(404, "Bank account not found")
    ALLOWED = {"account_holder_name", "bank_name", "branch", "account_type",
               "verification_status"}
    patch = {k: v for k, v in (payload or {}).items() if k in ALLOWED}
    if not patch:
        raise HTTPException(400, "No editable fields provided")
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.party_bank_accounts.update_one({"id": bid}, {"$set": patch})
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "party_bank_account", "edit", bid,
        f"{before['party_type']}:{before['party_id']}", "",
        {k: {"old": before.get(k), "new": patch.get(k)} for k in patch
         if k not in ("modified_by", "modified_at")},
    )
    return strip_full_number({**before, **patch}, party_role_can_view_full(user))


@router.post("/party-bank-accounts/{bid}/set-primary")
async def set_primary_party_ep(
    bid: str, request: Request, user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    doc = await db.party_bank_accounts.find_one(
        {"id": bid, "user_id": uid, "is_active": True}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Active bank account not found")
    await clear_primary_party(uid, doc["party_type"], doc["party_id"], keep_id=bid)
    await db.party_bank_accounts.update_one(
        {"id": bid}, {"$set": {"is_primary": True,
                                "modified_by": uid,
                                "modified_at": now_utc().isoformat()}},
    )
    return {"ok": True, "id": bid, "is_primary": True}


@router.post("/party-bank-accounts/{bid}/deactivate")
async def deactivate_party(
    bid: str, request: Request, payload: dict = None,
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.party_bank_accounts.find_one(
        {"id": bid, "user_id": uid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Bank account not found")
    reason = ((payload or {}).get("reason") or "").strip()[:240]
    await db.party_bank_accounts.update_one(
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
        "party_bank_account", "deactivate", bid,
        f"{doc['party_type']}:{doc['party_id']}", reason, {},
    )
    return {"ok": True, "id": bid, "is_active": False}


@router.post("/party-bank-accounts/{bid}/replace")
async def replace_party(
    bid: str, payload: PartyBankAccount, request: Request,
    user=Depends(get_current_user),
):
    _require_manage(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    old = await db.party_bank_accounts.find_one(
        {"id": bid, "user_id": uid, "is_active": True}, {"_id": 0})
    if not old:
        raise HTTPException(404, "Active bank account not found")
    if payload.party_type != old["party_type"] or payload.party_id != old["party_id"]:
        raise HTTPException(400, "Replacement must retain same party_type + party_id")
    new_doc = payload.model_dump()
    new_doc["id"] = new_id("pba_")
    new_doc["user_id"] = uid
    new_doc["created_by"] = uid
    new_doc["created_at"] = now_utc().isoformat()
    new_doc["is_active"] = True
    new_doc["masked_display"] = mask_account_number(new_doc["account_number"])
    if new_doc.get("is_primary") or old.get("is_primary"):
        await clear_primary_party(uid, new_doc["party_type"],
                                  new_doc["party_id"], keep_id=new_doc["id"])
        new_doc["is_primary"] = True
    await db.party_bank_accounts.insert_one(new_doc)
    new_doc.pop("_id", None)
    await db.party_bank_accounts.update_one(
        {"id": bid},
        {"$set": {"is_active": False, "is_primary": False,
                   "deactivated_by": uid,
                   "deactivated_at": now_utc().isoformat(),
                   "deactivation_reason": f"replaced_by:{new_doc['id']}"}},
    )
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "party_bank_account", "replace", bid,
        f"{old['party_type']}:{old['party_id']}",
        f"replaced_by:{new_doc['id']}", {},
    )
    return strip_full_number(new_doc, party_role_can_view_full(user))


@router.get("/party-bank-accounts/{bid}/reveal")
async def reveal_party_full(
    bid: str, request: Request, user=Depends(get_current_user),
):
    if not party_role_can_view_full(user):
        raise HTTPException(403, "Not permitted to reveal full account number")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.party_bank_accounts.find_one(
        {"id": bid, "user_id": uid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Bank account not found")
    await _log_audit(
        {"user_id": uid, "company_id": cid,
         "email": user.get("email", ""), "name": user.get("name", "")},
        "party_bank_account", "reveal", bid,
        f"{doc['party_type']}:{doc['party_id']}", "", {},
    )
    return {"id": bid, "account_number": doc.get("account_number", "")}
