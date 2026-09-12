"""Iter150G · Bank Account service helpers (new · non-locked · pure).

Zero ledger mutation. Zero fin_txn writes. Zero new source_type.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from db import db
from models_bank import BANK_SNAPSHOT_KEYS


def mask_account_number(acc: str) -> str:
    """Return XXXXXX<last4> for the given raw account number. Empty → ''."""
    s = (acc or "").strip()
    if not s:
        return ""
    if len(s) <= 4:
        return "X" * len(s)
    return "X" * (len(s) - 4) + s[-4:]


def snapshot_from_party_bank(pba: dict) -> Dict[str, str]:
    """Build the frozen immutable snapshot dict — never includes full
    account number. Keys are exactly `BANK_SNAPSHOT_KEYS`."""
    return {
        "bank_name": pba.get("bank_name", ""),
        "masked_number": pba.get("masked_display") or mask_account_number(
            pba.get("account_number", "")
        ),
        "ifsc": pba.get("ifsc", ""),
        "holder_name": pba.get("account_holder_name", ""),
    }


def snapshot_from_company_bank(cba: dict) -> Dict[str, str]:
    """Iter150H · Build the frozen immutable source-bank snapshot dict — never
    includes full account number. Keys are exactly the five approved keys:
    bank_name, masked_number, ifsc, branch, holder_name."""
    return {
        "bank_name": cba.get("bank_name", ""),
        "masked_number": cba.get("masked_display") or mask_account_number(
            cba.get("account_number", "")
        ),
        "ifsc": cba.get("ifsc", ""),
        "branch": cba.get("branch", ""),
        "holder_name": cba.get("account_holder_name", ""),
    }


async def find_active_party_bank(
    uid: str, party_type: str, party_id: str, bank_account_id: str
) -> Optional[dict]:
    """Fetch an active party bank account belonging to the given party.
    Returns None if not found or cross-party / inactive / cross-tenant."""
    if not bank_account_id:
        return None
    doc = await db.party_bank_accounts.find_one(
        {
            "id": bank_account_id,
            "user_id": uid,
            "party_type": party_type,
            "party_id": party_id,
            "is_active": True,
        },
        {"_id": 0},
    )
    return doc


async def find_active_company_bank(
    uid: str, company_id: str, bank_account_id: str
) -> Optional[dict]:
    if not bank_account_id:
        return None
    return await db.company_bank_accounts.find_one(
        {
            "id": bank_account_id,
            "user_id": uid,
            "company_id": company_id,
            "is_active": True,
        },
        {"_id": 0},
    )


async def duplicate_exists_company(
    uid: str, company_id: str, account_number: str, ifsc: str,
    exclude_id: str = "",
) -> bool:
    q = {
        "user_id": uid, "company_id": company_id,
        "account_number": account_number, "ifsc": ifsc,
        "is_active": True,
    }
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    return bool(await db.company_bank_accounts.find_one(q, {"_id": 0, "id": 1}))


async def duplicate_exists_party(
    uid: str, party_type: str, party_id: str,
    account_number: str, ifsc: str, exclude_id: str = "",
) -> bool:
    q = {
        "user_id": uid, "party_type": party_type, "party_id": party_id,
        "account_number": account_number, "ifsc": ifsc, "is_active": True,
    }
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    return bool(await db.party_bank_accounts.find_one(q, {"_id": 0, "id": 1}))


async def clear_primary_company(uid: str, company_id: str, keep_id: str = ""):
    q = {"user_id": uid, "company_id": company_id, "is_primary": True}
    if keep_id:
        q["id"] = {"$ne": keep_id}
    await db.company_bank_accounts.update_many(q, {"$set": {"is_primary": False}})


async def clear_primary_party(
    uid: str, party_type: str, party_id: str, keep_id: str = ""
):
    q = {"user_id": uid, "party_type": party_type, "party_id": party_id,
         "is_primary": True}
    if keep_id:
        q["id"] = {"$ne": keep_id}
    await db.party_bank_accounts.update_many(q, {"$set": {"is_primary": False}})


def strip_full_number(doc: dict, allow_full: bool) -> dict:
    """Redact full account_number unless the caller has view_bank_account_full."""
    if not doc:
        return doc
    out = dict(doc)
    if not allow_full:
        out["account_number"] = out.get("masked_display") or mask_account_number(
            out.get("account_number", "")
        )
    return out


def party_role_can_manage(user: dict) -> bool:
    role = (user.get("effective_role") or user.get("role") or "").lower()
    return role in ("owner", "accountant", "admin")


def party_role_can_view_full(user: dict) -> bool:
    role = (user.get("effective_role") or user.get("role") or "").lower()
    return role in ("owner", "accountant", "admin")
