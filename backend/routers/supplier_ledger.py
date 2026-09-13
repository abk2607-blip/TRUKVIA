"""Iter150K · Turn 1 · Supplier correction router.

Mirrors routers/vendor_ledger.py + routers/mechanic_ledger.py but exposes
ONLY the correction endpoints. The supplier ledger (/api/suppliers/{sid}/ledger)
stays in routers/suppliers.py because supplier ledger semantics differ from
vendor/mechanic (trip-derived rows + supplier-owned-vehicle expenses).

Endpoints
---------
POST /api/supplier-payments/{pid}/correct
POST /api/supplier-payments/{pid}/correct-amount
GET  /api/supplier-payments/{pid}/corrections

Delegates to services_payment_corrections.py (shared with vendor/mechanic).
Owner/Admin-only per _ensure_admin guard invoked below.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request

from auth import get_current_user
from services_payment_corrections import (
    _ensure_admin,
    apply_amount_reversal_new,
    apply_attribute_correction,
    list_corrections,
)

router = APIRouter(prefix="/api", tags=["supplier-ledger"])


async def _active_company_id(request: Request, user: dict) -> str:
    from db import db
    override = request.headers.get("x-company-id") or request.headers.get("X-Company-Id") or ""
    if override:
        doc = await db.companies.find_one(
            {"id": override, "user_id": user["user_id"]}, {"id": 1, "_id": 0}
        )
        if doc:
            return override
    doc = await db.companies.find_one(
        {"user_id": user["user_id"], "is_default": True}, {"id": 1, "_id": 0}
    )
    if doc:
        return doc["id"]
    doc = await db.companies.find_one(
        {"user_id": user["user_id"]}, {"id": 1, "_id": 0}
    )
    return doc["id"] if doc else ""


@router.post("/supplier-payments/{pid}/correct")
async def correct_supplier_payment(
    pid: str, payload: dict, request: Request, user=Depends(get_current_user),
):
    await _ensure_admin(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    changes = payload.get("changes") or {}
    reason = payload.get("correction_reason") or ""
    force = bool(payload.get("force_reconciled_override") or False)
    ecc: Optional[int] = payload.get("expected_correction_count")
    return await apply_attribute_correction(
        "supplier", uid, cid, pid, user, changes, reason, force, ecc,
    )


@router.post("/supplier-payments/{pid}/correct-amount")
async def correct_supplier_payment_amount(
    pid: str, payload: dict, request: Request, user=Depends(get_current_user),
):
    await _ensure_admin(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    new_amount = float(payload.get("new_amount") or 0)
    reason = payload.get("correction_reason") or ""
    force = bool(payload.get("force_reconciled_override") or False)
    ecc: Optional[int] = payload.get("expected_correction_count")
    return await apply_amount_reversal_new(
        "supplier", uid, cid, pid, user, new_amount, reason, force, ecc,
    )


@router.get("/supplier-payments/{pid}/corrections")
async def list_supplier_payment_corrections(
    pid: str, request: Request, user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await list_corrections("supplier", uid, cid, pid)
