"""Iter133 · Turn 2C · Mechanic Ledger + Correction endpoints (mirror pattern)."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query, Body

from db import db
from models import now_utc
from auth import get_current_user
from company import _active_company_id
from services_payment_corrections import (
    _ensure_admin,
    apply_attribute_correction,
    apply_amount_reversal_new,
    list_corrections,
)

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
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    m = await _ensure_mechanic(uid, cid, mid)

    q_wo: dict = {"user_id": uid, "company_id": cid, "mechanic_id": mid,
                  "is_deleted": {"$ne": True}}
    q_pay: dict = {"user_id": uid, "company_id": cid, "mechanic_id": mid,
                   "is_deleted": {"$ne": True}}
    if not include_reversed:
        q_pay["is_reversed"] = {"$ne": True}
    if date_from or date_to:
        d: dict = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        q_wo["work_date"] = d
        q_pay["date"] = d

    entries: list = []

    opening_type = (m.get("opening_balance_type") or "payable").lower()
    opening = float(m.get("opening_balance") or 0)
    if opening > 0:
        if opening_type == "payable":
            entries.append({"date": m.get("created_at", "")[:10] or "",
                            "kind": "opening", "ref": "Opening Balance",
                            "debit": round(opening, 2), "credit": 0.0,
                            "narration": "opening payable"})
        else:
            entries.append({"date": m.get("created_at", "")[:10] or "",
                            "kind": "opening", "ref": "Opening Advance",
                            "debit": 0.0, "credit": round(opening, 2),
                            "narration": "opening advance"})

    async for w in db.mechanic_work_orders.find(q_wo, {"_id": 0, "user_id": 0}):
        entries.append({
            "date": w.get("work_date", ""),
            "kind": "work_order",
            "ref": w.get("id"),
            "id": w.get("id"),
            "debit": round(float(w.get("amount") or 0), 2),
            "credit": 0.0,
            "narration": w.get("narration", ""),
            "vehicle_number": w.get("vehicle_number", ""),
            "repair_event_id": w.get("repair_event_id", ""),
        })

    async for p in db.mechanic_payments.find(q_pay, {"_id": 0, "user_id": 0}):
        direction = 1 if p.get("type") == "payment_out" else -1
        amt = float(p.get("amount") or 0) * direction
        entries.append({
            "date": p.get("date", ""),
            "kind": "payment",
            "ref": p.get("ref_no") or p.get("id"),
            "id": p.get("id"),
            "debit": 0.0,
            "credit": round(amt, 2),
            "narration": p.get("remarks", ""),
            "against": p.get("against", ""),
            "mechanic_work_order_id": p.get("mechanic_work_order_id", ""),
            "mode": p.get("mode", ""),
            "is_reversed": bool(p.get("is_reversed", False)),
            "correction_count": int(p.get("correction_count") or 0),
        })

    entries.sort(key=lambda x: (x.get("date") or "", 0 if x["kind"] == "opening" else 1
                                if x["kind"] == "work_order" else 2))
    running = 0.0
    for e in entries:
        running += float(e.get("debit") or 0) - float(e.get("credit") or 0)
        e["balance"] = round(running, 2)

    total_debit = round(sum(float(e.get("debit") or 0) for e in entries), 2)
    total_credit = round(sum(float(e.get("credit") or 0) for e in entries), 2)

    return {
        "mechanic_id": mid,
        "mechanic_name": m.get("name", ""),
        "from": date_from or "",
        "to": date_to or "",
        "opening_balance": round(opening, 2),
        "opening_balance_type": opening_type,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "closing_balance": round(total_debit - total_credit, 2),
        "outstanding": max(round(total_debit - total_credit, 2), 0),
        "advance": max(round(total_credit - total_debit, 2), 0),
        "entries": entries,
        "generated_at": now_utc().isoformat(),
    }


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
