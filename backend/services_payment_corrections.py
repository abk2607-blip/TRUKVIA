"""Iter133 · Turn 2C · Payment Correction service.

Applies the FROZEN two-tier correction rule:
  * Attribute correction  → same payment row updated in place + immutable
                            PaymentCorrection audit row (kind='attribute').
  * Amount correction     → original row marked is_reversed=true; fresh row
                            inserted with corrected amount; both linked in
                            a single PaymentCorrection row
                            (kind='amount_reversal_new').

Guarantees:
  * Admin/Owner only (enforced at router).
  * Mandatory correction_reason ≥ 10 chars.
  * Optimistic concurrency via correction_count.
  * Reconciled-payment guard via force_reconciled_override.
  * Idempotent (POST with Idempotency-Key at router).
  * Ledger projection auto-reflects corrected linkage.
"""
from __future__ import annotations
from typing import Literal
from fastapi import HTTPException

from db import db
from models import now_utc, new_id

_CORRECTABLE_ATTR_FIELDS = {
    "vendor": {"vendor_id", "vendor_bill_id", "date", "mode", "ref_no",
               "against", "remarks", "account_id"},
    "mechanic": {"mechanic_id", "mechanic_work_order_id", "date", "mode",
                 "ref_no", "against", "remarks", "account_id"},
}


def _diff(before: dict, after: dict, keys: set[str]) -> dict:
    out: dict = {}
    for k in keys:
        b = before.get(k)
        a = after.get(k)
        if (b or "") != (a or "") and b != a:
            out[k] = {"old": b, "new": a}
    return out


async def _ensure_admin(user: dict) -> None:
    role = (user.get("effective_role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only Owner or Admin can correct a payment.")


async def _load_payment(payment_type: str, uid: str, cid: str, pid: str) -> dict:
    coll = "vendor_payments" if payment_type == "vendor" else "mechanic_payments"
    doc = await db[coll].find_one({"id": pid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payment not found")
    if doc.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Payment is soft-deleted; cannot correct")
    if doc.get("is_reversed"):
        raise HTTPException(status_code=400, detail="Payment is already reversed; corrections are frozen")
    return doc


async def _validate_targets_vendor(uid: str, cid: str, patch: dict) -> None:
    vid = patch.get("vendor_id")
    if vid:
        ven = await db.vendors.find_one({"id": vid, "user_id": uid, "company_id": cid},
                                        {"_id": 0, "id": 1})
        if not ven:
            raise HTTPException(status_code=400, detail="New vendor not found in tenant")
    bill_id = patch.get("vendor_bill_id")
    if bill_id:
        b = await db.vendor_bills.find_one(
            {"id": bill_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "vendor_id": 1},
        )
        if not b:
            raise HTTPException(status_code=400, detail="New vendor bill not found in tenant")
        if vid and b["vendor_id"] != vid:
            raise HTTPException(status_code=400, detail="New vendor bill does not belong to target vendor")


async def _validate_targets_mechanic(uid: str, cid: str, patch: dict) -> None:
    mid = patch.get("mechanic_id")
    if mid:
        mec = await db.mechanics.find_one({"id": mid, "user_id": uid, "company_id": cid},
                                          {"_id": 0, "id": 1})
        if not mec:
            raise HTTPException(status_code=400, detail="New mechanic not found in tenant")
    wo_id = patch.get("mechanic_work_order_id")
    if wo_id:
        w = await db.mechanic_work_orders.find_one(
            {"id": wo_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "mechanic_id": 1},
        )
        if not w:
            raise HTTPException(status_code=400, detail="New work order not found in tenant")
        if mid and w["mechanic_id"] != mid:
            raise HTTPException(status_code=400, detail="New work order does not belong to target mechanic")


async def apply_attribute_correction(
    payment_type: Literal["vendor", "mechanic"],
    uid: str, cid: str, pid: str, user: dict,
    changes: dict, correction_reason: str,
    force_reconciled_override: bool,
    expected_correction_count: int | None,
) -> dict:
    reason = (correction_reason or "").strip()
    if len(reason) < 10:
        raise HTTPException(status_code=400, detail="correction_reason must be at least 10 characters")

    doc = await _load_payment(payment_type, uid, cid, pid)

    if "amount" in changes:
        raise HTTPException(
            status_code=400,
            detail="amount changes must use the /correct-amount endpoint (two-tier rule)",
        )

    if doc.get("reconciled_at") and not force_reconciled_override:
        raise HTTPException(
            status_code=409,
            detail="Payment is reconciled — set force_reconciled_override=true to correct",
        )

    if expected_correction_count is not None and doc.get("correction_count", 0) != expected_correction_count:
        raise HTTPException(status_code=409, detail="correction_count mismatch (concurrent edit)")

    allowed = _CORRECTABLE_ATTR_FIELDS[payment_type]
    patch: dict = {}
    for k, v in (changes or {}).items():
        if k not in allowed:
            raise HTTPException(status_code=400, detail=f"Field '{k}' is not attribute-correctable")
        patch[k] = v

    if not patch:
        raise HTTPException(status_code=400, detail="No correctable fields supplied")

    if payment_type == "vendor":
        await _validate_targets_vendor(uid, cid, patch)
    else:
        await _validate_targets_mechanic(uid, cid, patch)

    before = {k: doc.get(k) for k in allowed}
    after = {**before, **patch}
    diff = _diff(before, after, allowed)
    if not diff:
        raise HTTPException(status_code=400, detail="No effective change to correct")

    now_iso = now_utc().isoformat()
    correction_id = new_id("pcr_")
    new_count = int(doc.get("correction_count") or 0) + 1

    coll = "vendor_payments" if payment_type == "vendor" else "mechanic_payments"
    update = {
        **patch,
        "modified_by": uid,
        "modified_at": now_iso,
        "corrected_by": uid,
        "corrected_at": now_iso,
        "correction_count": new_count,
        "latest_correction_id": correction_id,
    }
    await db[coll].update_one({"id": pid}, {"$set": update})

    correction_doc = {
        "id": correction_id,
        "user_id": uid,
        "company_id": cid,
        "payment_type": payment_type,
        "payment_id": pid,
        "correction_index": new_count,
        "kind": "attribute",
        "correction_reason": reason,
        "before": before,
        "after": after,
        "diff": diff,
        "linked_reversal_id": "",
        "linked_new_id": "",
        "force_reconciled_override": bool(force_reconciled_override),
        "corrected_by": uid,
        "corrected_at": now_iso,
    }
    await db.payment_corrections.insert_one(correction_doc)

    updated = await db[coll].find_one({"id": pid}, {"_id": 0, "user_id": 0})
    correction_doc.pop("_id", None); correction_doc.pop("user_id", None)
    return {"payment": updated, "correction": correction_doc}


async def apply_amount_reversal_new(
    payment_type: Literal["vendor", "mechanic"],
    uid: str, cid: str, pid: str, user: dict,
    new_amount: float, correction_reason: str,
    force_reconciled_override: bool,
    expected_correction_count: int | None,
) -> dict:
    reason = (correction_reason or "").strip()
    if len(reason) < 10:
        raise HTTPException(status_code=400, detail="correction_reason must be at least 10 characters")

    try:
        amt = float(new_amount)
    except Exception:
        amt = 0.0
    if amt <= 0:
        raise HTTPException(status_code=400, detail="new_amount must be positive")

    doc = await _load_payment(payment_type, uid, cid, pid)
    if abs(amt - float(doc.get("amount") or 0)) < 0.005:
        raise HTTPException(status_code=400, detail="new_amount equals current amount — nothing to correct")

    if doc.get("reconciled_at") and not force_reconciled_override:
        raise HTTPException(
            status_code=409,
            detail="Payment is reconciled — set force_reconciled_override=true to correct amount",
        )

    if expected_correction_count is not None and doc.get("correction_count", 0) != expected_correction_count:
        raise HTTPException(status_code=409, detail="correction_count mismatch (concurrent edit)")

    now_iso = now_utc().isoformat()
    correction_id = new_id("pcr_")

    coll = "vendor_payments" if payment_type == "vendor" else "mechanic_payments"

    # Step 1: mark original reversed.
    await db[coll].update_one(
        {"id": pid},
        {"$set": {
            "is_reversed": True,
            "reversed_by": uid,
            "reversed_at": now_iso,
            "reversal_reason": reason,
            "corrected_by": uid,
            "corrected_at": now_iso,
            "latest_correction_id": correction_id,
            "modified_by": uid,
            "modified_at": now_iso,
        }, "$inc": {"correction_count": 1}},
    )

    # Step 2: create the fresh corrected row.
    new_row_id = new_id("vpay_" if payment_type == "vendor" else "mpay_")
    fresh = {
        **{k: v for k, v in doc.items() if k not in {
            "id", "amount", "is_reversed", "reversed_by", "reversed_at",
            "reversal_reason", "correction_count", "corrected_at", "corrected_by",
            "latest_correction_id", "created_at", "modified_at", "modified_by",
        }},
        "id": new_row_id,
        "amount": round(amt, 2),
        "reversal_of": pid,
        "is_reversed": False,
        "reversed_by": "",
        "reversed_at": "",
        "reversal_reason": "",
        "correction_count": 0,
        "latest_correction_id": "",
        "corrected_at": "",
        "corrected_by": "",
        "user_id": uid,
        "company_id": cid,
        "created_by": uid,
        "created_at": now_iso,
        "modified_by": "",
        "modified_at": "",
    }
    await db[coll].insert_one(fresh)

    # Step 3: single immutable audit row linking both.
    reloaded_orig = await db[coll].find_one({"id": pid}, {"_id": 0, "user_id": 0})
    orig_count = int(reloaded_orig.get("correction_count") or 1)
    before = {"amount": float(doc.get("amount") or 0), "id": pid}
    after = {"amount": round(amt, 2), "id": new_row_id}
    correction_doc = {
        "id": correction_id,
        "user_id": uid,
        "company_id": cid,
        "payment_type": payment_type,
        "payment_id": pid,
        "correction_index": orig_count,
        "kind": "amount_reversal_new",
        "correction_reason": reason,
        "before": before,
        "after": after,
        "diff": {"amount": {"old": before["amount"], "new": after["amount"]}},
        "linked_reversal_id": pid,
        "linked_new_id": new_row_id,
        "force_reconciled_override": bool(force_reconciled_override),
        "corrected_by": uid,
        "corrected_at": now_iso,
    }
    await db.payment_corrections.insert_one(correction_doc)

    correction_doc.pop("_id", None); correction_doc.pop("user_id", None)
    reloaded_orig.pop("_id", None)
    fresh.pop("_id", None); fresh.pop("user_id", None)
    return {"original": reloaded_orig, "fresh": fresh, "correction": correction_doc}


async def list_corrections(payment_type: str, uid: str, cid: str, pid: str) -> list:
    rows = await db.payment_corrections.find(
        {"user_id": uid, "company_id": cid, "payment_type": payment_type, "payment_id": pid},
        {"_id": 0, "user_id": 0},
    ).sort("correction_index", 1).to_list(1000)
    return rows
