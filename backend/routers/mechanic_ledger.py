"""Iter133 · Turn 2C · Mechanic Ledger + Correction endpoints (mirror pattern).
Iter135 · JSON + PDF delegate to the authoritative party-ledger builder.

Source-of-truth: `services_party_ledger.build_party_ledger` — one dataset
serves both consumers, guaranteeing UI totals ≡ PDF totals.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query, Body
from fastapi.responses import Response

from db import db
from auth import get_current_user
from company import _active_company_id
from services_party_ledger import build_party_ledger, guard_pdf_size
from services_payment_corrections import (
    _ensure_admin,
    apply_attribute_correction,
    apply_amount_reversal_new,
    list_corrections,
)
from pdf.party_ledger import build_party_ledger_pdf

router = APIRouter(prefix="/api")


async def _ensure_mechanic(uid: str, cid: str, mid: str) -> dict:
    m = await db.mechanics.find_one({"id": mid, "user_id": uid, "company_id": cid},
                                    {"_id": 0, "user_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Mechanic not found")
    return m


@router.get("/mechanics/{mid}/ledger")
async def mechanic_ledger(
    mid: str,
    request: Request,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    include_reversed: bool = False,
    vehicle_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    await _ensure_mechanic(uid, cid, mid)
    return await build_party_ledger(
        party_type="mechanic", uid=uid, cid=cid, pid=mid,
        date_from=date_from, date_to=date_to,
        include_reversed=include_reversed, vehicle_id=vehicle_id,
    )


@router.get("/mechanics/{mid}/ledger.pdf")
async def mechanic_ledger_pdf(
    mid: str,
    request: Request,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    include_reversed: bool = False,
    vehicle_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    await _ensure_mechanic(uid, cid, mid)
    dataset = await build_party_ledger(
        party_type="mechanic", uid=uid, cid=cid, pid=mid,
        date_from=date_from, date_to=date_to,
        include_reversed=include_reversed, vehicle_id=vehicle_id,
    )
    guard_pdf_size(dataset)
    pdf_bytes = build_party_ledger_pdf(dataset)
    slug = (dataset.get("party_name") or "mechanic").replace("/", "_").replace(" ", "_")
    fname = f"Mechanic-Ledger_{slug}_{date_from or 'all'}_{date_to or 'today'}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@router.post("/mechanic-payments/{pid}/correct")
async def correct_mechanic_payment(pid: str, request: Request,
                                   payload: dict = Body(...),
                                   user=Depends(get_current_user)):
    await _ensure_admin(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await apply_attribute_correction(
        payment_type="mechanic",
        uid=uid, cid=cid, pid=pid, user=user,
        changes=payload.get("changes") or {},
        correction_reason=payload.get("correction_reason", ""),
        force_reconciled_override=bool(payload.get("force_reconciled_override", False)),
        expected_correction_count=payload.get("expected_correction_count"),
    )


@router.post("/mechanic-payments/{pid}/correct-amount")
async def correct_mechanic_payment_amount(pid: str, request: Request,
                                          payload: dict = Body(...),
                                          user=Depends(get_current_user)):
    await _ensure_admin(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await apply_amount_reversal_new(
        payment_type="mechanic",
        uid=uid, cid=cid, pid=pid, user=user,
        new_amount=float(payload.get("new_amount") or 0),
        correction_reason=payload.get("correction_reason", ""),
        force_reconciled_override=bool(payload.get("force_reconciled_override", False)),
        expected_correction_count=payload.get("expected_correction_count"),
    )


@router.get("/mechanic-payments/{pid}/corrections")
async def get_mechanic_payment_corrections(pid: str, request: Request,
                                           user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await list_corrections("mechanic", uid, cid, pid)
