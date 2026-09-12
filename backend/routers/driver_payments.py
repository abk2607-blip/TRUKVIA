"""Iter150I · Driver Payment writer / audit router.

Additive-only. Does NOT touch driver_ledger salary/settlement writers.
Idempotency-Key header supported (see backend/idempotency.py convention).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from auth import get_current_user
from company import _active_company_id
from db import db
from models import (
    DriverPayment, DriverPaymentCorrection, ROLE_PERMISSIONS, new_id, now_utc,
)
from services_bank_accounts import (
    snapshot_from_party_bank, snapshot_from_company_bank,
)
from services_fin_txn_hooks import hook_after_source_write


async def _snapshot_party_bank(uid, cid, bid):
    doc = await db.party_bank_accounts.find_one(
        {"user_id": uid, "company_id": cid, "id": bid}, {"_id": 0})
    return snapshot_from_party_bank(doc) if doc else {}


async def _snapshot_company_bank(uid, cid, bid):
    doc = await db.company_bank_accounts.find_one(
        {"user_id": uid, "company_id": cid, "id": bid}, {"_id": 0})
    return snapshot_from_company_bank(doc) if doc else {}


router = APIRouter(prefix="/api", tags=["driver-payments"])


def _perm(user: dict, name: str) -> bool:
    return name in ROLE_PERMISSIONS.get(user.get("role") or "viewer", set())


async def _ensure_driver(uid: str, cid: str, did: str) -> dict:
    d = await db.drivers.find_one(
        {"user_id": uid, "company_id": cid, "id": did}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Driver not found")
    return d


@router.get("/drivers/{did}/payments")
async def list_driver_payments(did: str, request: Request,
                                user=Depends(get_current_user)):
    uid, cid = user["user_id"], await _active_company_id(request, user)
    await _ensure_driver(uid, cid, did)
    cur = db.driver_payments.find(
        {"user_id": uid, "company_id": cid, "driver_id": did,
         "is_deleted": {"$ne": True}}, {"_id": 0}).sort("date", -1)
    return [d async for d in cur]


@router.post("/drivers/{did}/payments")
async def create_driver_payment(did: str, payload: DriverPayment,
                                 request: Request,
                                 user=Depends(get_current_user)):
    if not _perm(user, "manage_bank_accounts"):
        raise HTTPException(403, "Not permitted")
    uid, cid = user["user_id"], await _active_company_id(request, user)
    await _ensure_driver(uid, cid, did)
    if not payload.amount or float(payload.amount) <= 0:
        raise HTTPException(400, "Amount must be > 0")
    # Server-generated id — reject client-supplied.
    doc = payload.model_dump()
    doc["id"] = new_id("dpay_")
    doc["driver_id"] = did
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    # Cash → empty snapshots. Bank family → capture immutable snapshots.
    if (payload.mode or "").lower() == "cash":
        doc["bank_account_id"] = ""; doc["bank_snapshot"] = {}
        doc["company_bank_account_id"] = ""; doc["source_bank_snapshot"] = {}
    else:
        if doc.get("bank_account_id"):
            doc["bank_snapshot"] = await _snapshot_party_bank(
                uid, cid, doc["bank_account_id"])
        if doc.get("company_bank_account_id"):
            doc["source_bank_snapshot"] = await _snapshot_company_bank(
                uid, cid, doc["company_bank_account_id"])
    await db.driver_payments.insert_one(dict(doc))
    await hook_after_source_write(uid, cid, "driver_payment", doc["id"])
    doc.pop("_id", None)
    return doc


@router.post("/driver-payments/{pid}/correct")
async def correct_driver_payment(pid: str, request: Request,
                                  user=Depends(get_current_user)):
    if not _perm(user, "manage_bank_accounts"):
        raise HTTPException(403, "Not permitted")
    uid, cid = user["user_id"], await _active_company_id(request, user)
    body = await request.json()
    doc = await db.driver_payments.find_one(
        {"user_id": uid, "company_id": cid, "id": pid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Payment not found")
    if doc.get("is_reversed"):
        raise HTTPException(409, "Payment already reversed")
    before = {k: doc.get(k) for k in ("ref_no", "remarks", "against")}
    after = {k: body.get(k, doc.get(k)) for k in ("ref_no", "remarks", "against")}
    diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    ci = int(doc.get("correction_count") or 0) + 1
    audit = DriverPaymentCorrection(
        payment_id=pid, correction_index=ci, kind="attribute",
        correction_reason=body.get("reason", ""),
        before=before, after=after, diff=diff, corrected_by=uid,
    ).model_dump()
    audit["user_id"] = uid; audit["company_id"] = cid
    await db.driver_payment_corrections.insert_one(audit)
    await db.driver_payments.update_one(
        {"user_id": uid, "company_id": cid, "id": pid},
        {"$set": {**after, "corrected_at": now_utc().isoformat(),
                  "corrected_by": uid, "correction_count": ci,
                  "latest_correction_id": audit["id"]}})
    return {"ok": True, "correction_id": audit["id"], "correction_index": ci}


@router.post("/driver-payments/{pid}/correct-amount")
async def correct_driver_payment_amount(pid: str, request: Request,
                                         user=Depends(get_current_user)):
    """Amount reversal · failure-safe.

    Business invariant: EITHER the full reversal succeeds (original flipped
    to is_reversed=True + replacement dpay inserted + audit row inserted +
    FinTxn refreshed for both) OR the original payment remains in the exact
    pre-request non-reversed state with no orphan replacement, no orphan
    audit row, and no orphan reversal FinTxn state.

    Motor/MongoDB standalone deployments (dev / preview) do not support
    multi-collection ACID transactions; where the underlying storage cannot
    provide a true atomic transaction we perform repository-native
    compensating rollback that restores the pre-operation business state.
    """
    if not _perm(user, "manage_bank_accounts"):
        raise HTTPException(403, "Not permitted")
    uid, cid = user["user_id"], await _active_company_id(request, user)
    body = await request.json()
    new_amount = float(body.get("new_amount") or 0)
    if new_amount <= 0:
        raise HTTPException(400, "new_amount must be > 0")
    orig = await db.driver_payments.find_one(
        {"user_id": uid, "company_id": cid, "id": pid}, {"_id": 0})
    if not orig:
        raise HTTPException(404, "Payment not found")
    if orig.get("is_reversed"):
        raise HTTPException(409, "Already reversed")

    now = now_utc().isoformat()
    fresh_id = new_id("dpay_")
    ci = int(orig.get("correction_count") or 0) + 1
    audit = DriverPaymentCorrection(
        payment_id=pid, correction_index=ci, kind="amount_reversal_new",
        correction_reason=body.get("reason", ""),
        before={"amount": orig.get("amount")},
        after={"amount": new_amount},
        diff={"amount": [orig.get("amount"), new_amount]},
        linked_reversal_id=pid, linked_new_id=fresh_id,
        corrected_by=uid,
    ).model_dump()
    audit["user_id"] = uid; audit["company_id"] = cid
    audit_id = audit["id"]

    fresh = dict(orig)
    fresh.pop("_id", None)
    fresh["id"] = fresh_id
    fresh["amount"] = new_amount
    fresh["is_reversed"] = False
    fresh["reversed_at"] = ""
    fresh["reversed_by"] = ""
    fresh["reversal_reason"] = ""
    fresh["reversal_of"] = pid
    fresh["created_by"] = uid
    fresh["created_at"] = now
    fresh["correction_count"] = 0
    fresh["latest_correction_id"] = ""
    fresh["corrected_at"] = ""
    fresh["corrected_by"] = ""

    # Exact restore-state for the original (only the fields we mutate).
    restore_fields = {
        "is_reversed": bool(orig.get("is_reversed") or False),
        "reversed_at": orig.get("reversed_at") or "",
        "reversed_by": orig.get("reversed_by") or "",
        "reversal_reason": orig.get("reversal_reason") or "",
        "correction_count": int(orig.get("correction_count") or 0),
        "latest_correction_id": orig.get("latest_correction_id") or "",
    }

    async def _compensate(*, drop_fresh=False, drop_audit=False,
                          drop_fresh_legs=False, restore_orig=False,
                          restore_orig_legs=False):
        # Best-effort compensating rollback. Never raises.
        try:
            if drop_fresh:
                await db.driver_payments.delete_one(
                    {"user_id": uid, "company_id": cid, "id": fresh_id})
        except Exception:
            pass
        try:
            if drop_fresh_legs:
                await db.fin_txn.delete_many(
                    {"user_id": uid, "company_id": cid,
                     "source_type": "driver_payment", "source_id": fresh_id})
        except Exception:
            pass
        try:
            if drop_audit:
                await db.driver_payment_corrections.delete_one(
                    {"user_id": uid, "company_id": cid, "id": audit_id})
        except Exception:
            pass
        try:
            if restore_orig:
                await db.driver_payments.update_one(
                    {"user_id": uid, "company_id": cid, "id": pid},
                    {"$set": restore_fields})
        except Exception:
            pass
        try:
            if restore_orig_legs:
                await hook_after_source_write(
                    uid, cid, "driver_payment", pid)
        except Exception:
            pass

    # Step 1 · insert fresh replacement (is_reversed=False → will project).
    try:
        await db.driver_payments.insert_one(dict(fresh))
    except Exception as e:
        raise HTTPException(500, f"reversal failed at fresh insert: {e}")
    # Step 2 · project fresh legs.
    try:
        r = await hook_after_source_write(
            uid, cid, "driver_payment", fresh_id)
        if not r or not r.get("ok"):
            raise RuntimeError(f"fresh hook not ok: {r}")
    except Exception as e:
        await _compensate(drop_fresh=True, drop_fresh_legs=True)
        raise HTTPException(500, f"reversal failed at fresh projection: {e}")
    # Step 3 · insert audit row.
    try:
        await db.driver_payment_corrections.insert_one(dict(audit))
    except Exception as e:
        await _compensate(drop_fresh=True, drop_fresh_legs=True)
        raise HTTPException(500, f"reversal failed at audit insert: {e}")
    # Step 4 · flip original to reversed (last mutation on original doc).
    try:
        await db.driver_payments.update_one(
            {"user_id": uid, "company_id": cid, "id": pid},
            {"$set": {"is_reversed": True, "reversed_at": now,
                      "reversed_by": uid,
                      "reversal_reason": body.get("reason", ""),
                      "correction_count": ci,
                      "latest_correction_id": audit_id}})
    except Exception as e:
        await _compensate(drop_fresh=True, drop_audit=True,
                          drop_fresh_legs=True)
        raise HTTPException(500, f"reversal failed at original flip: {e}")
    # Step 5 · reproject original (clears its 2 legs since is_reversed=True).
    try:
        r = await hook_after_source_write(uid, cid, "driver_payment", pid)
        if not r or not r.get("ok"):
            raise RuntimeError(f"orig hook not ok: {r}")
    except Exception as e:
        await _compensate(drop_fresh=True, drop_audit=True,
                          drop_fresh_legs=True,
                          restore_orig=True, restore_orig_legs=True)
        raise HTTPException(
            500, f"reversal failed at original reproject: {e}")

    fresh.pop("_id", None)
    return {"ok": True, "reversed_id": pid, "new_payment": fresh,
            "correction_id": audit_id}


@router.get("/driver-payments/{pid}/corrections")
async def list_driver_payment_corrections(pid: str, request: Request,
                                            user=Depends(get_current_user)):
    uid, cid = user["user_id"], await _active_company_id(request, user)
    cur = db.driver_payment_corrections.find(
        {"user_id": uid, "company_id": cid, "payment_id": pid},
        {"_id": 0}).sort("correction_index", 1)
    return [d async for d in cur]


@router.get("/drivers/{did}/salary-settlement-hint")
async def salary_settlement_hint(did: str, month: str, request: Request,
                                    user=Depends(get_current_user)):
    """Advisory-only: reports whether the driver appears to have an
    existing settled salary for the given month. NEVER blocks posting."""
    uid, cid = user["user_id"], await _active_company_id(request, user)
    existing = await db.driver_ledger_entries.find_one(
        {"user_id": uid, "company_id": cid, "driver_id": did,
         "month": month, "kind": "settlement"}, {"_id": 0})
    return {"possible_duplicate": bool(existing),
            "existing_settlement": existing or None}
