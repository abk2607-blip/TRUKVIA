"""Iter59 · Phase A — Driver Shortage Policy Master.

CRUD for the effective-dated policy table plus a helper that resolves the
policy applicable to a given (company_id, trip_date, product_category?).
This helper is called during Trip save so the Trip stores a historical
SNAPSHOT of the policy — future policy changes NEVER recalculate old Trips.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

from db import db
from auth import get_current_user
from company import _active_company_id
from models import new_id

router = APIRouter(prefix="/api")


class ShortagePolicyIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    shortage_limit_kg: float = Field(..., ge=0)
    unit: str = Field(default="KG", max_length=8)
    effective_from: str = Field(..., min_length=10, max_length=10)  # YYYY-MM-DD
    effective_to: Optional[str] = None
    product_category: Optional[str] = None
    active: bool = True
    remarks: Optional[str] = None


async def resolve_policy_for_trip(
    user_id: str, company_id: str, trip_date: str,
    product_category: Optional[str] = None,
) -> Optional[dict]:
    """Iter59 — Return the shortage policy applicable to a Trip based on
    the Trip Date (NEVER the current date). This is called at trip-save
    time; the return value is snapshotted onto the trip so future policy
    edits do not retroactively change old trips.

    Selection rules:
     * active=True
     * effective_from <= trip_date
     * effective_to is null OR effective_to >= trip_date
     * product_category matches OR policy's product_category is null (catch-all)
     * If multiple policies match, prefer the most-specific one (matching
       product_category) then the most recent effective_from.
    """
    if not trip_date:
        return None
    q_base = {
        "user_id": user_id, "company_id": company_id, "active": True,
        "effective_from": {"$lte": trip_date},
        "$or": [
            {"effective_to": {"$exists": False}},
            {"effective_to": None},
            {"effective_to": {"$gte": trip_date}},
        ],
    }
    # First pass: match product_category exactly
    if product_category:
        p = await db.driver_shortage_policies.find_one(
            {**q_base, "product_category": product_category},
            sort=[("effective_from", -1), ("version", -1)],
        )
        if p:
            p.pop("_id", None)
            return p
    # Second pass: catch-all (product_category is null / empty)
    p = await db.driver_shortage_policies.find_one(
        {**q_base, "$and": [
            {"$or": [{"product_category": {"$exists": False}}, {"product_category": None}, {"product_category": ""}]}
        ]},
        sort=[("effective_from", -1), ("version", -1)],
    )
    if p:
        p.pop("_id", None)
    return p


def compute_driver_recovery(
    actual_shortage_kg: float, allowed_limit_kg: float, product_rate: float,
) -> dict:
    """Iter59 — Default recovery formula:
        recoverable = max(0, actual - limit)
        amount = recoverable × product_rate

    Returns the individual pieces so both actual + system values can be
    stored on the Trip for audit."""
    actual = max(float(actual_shortage_kg or 0), 0.0)
    limit = max(float(allowed_limit_kg or 0), 0.0)
    rate = max(float(product_rate or 0), 0.0)
    recoverable = round(max(0.0, actual - limit), 3)
    amount = round(recoverable * rate, 2)
    return {
        "actual_shortage_kg": actual,
        "allowed_limit_kg": limit,
        "product_rate": rate,
        "system_recoverable_shortage_kg": recoverable,
        "system_recovery_amount": amount,
    }


async def build_trip_driver_recovery_snapshot(
    user_id: str, company_id: str, trip: dict,
) -> Optional[dict]:
    """Called on Trip CREATE only. Returns the driver_recovery snapshot
    dict or None if there is no shortage / no driver / no applicable
    policy. This snapshot is stored on the trip and is NEVER refreshed
    on subsequent updates (historical accuracy).
    """
    if not trip.get("driver_id"):
        return None
    # shortage_qty is in MT (tons). Convert to KG for the policy comparison.
    shortage_mt = float(trip.get("shortage_qty") or 0)
    shortage_kg = round(shortage_mt * 1000, 3)
    product_rate = float(trip.get("product_rate_per_mt") or 0)
    trip_date = trip.get("date") or ""
    policy = await resolve_policy_for_trip(
        user_id, company_id, trip_date,
        product_category=trip.get("product_category") or None,
    )
    if not policy:
        # No policy → no recovery, but still snapshot the raw values
        # so the UI can show "no policy applied".
        return {
            "policy_id": None, "policy_version": None,
            "allowed_limit_kg": None, "effective_from": None,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "actual_shortage_kg": shortage_kg,
            "product_rate": product_rate,
            "system_recoverable_shortage_kg": None,
            "system_recovery_amount": None,
            "final_recovery_amount": 0.0,
            "override": None,
            "policy_missing": True,
        }
    calc = compute_driver_recovery(shortage_kg, policy["shortage_limit_kg"], product_rate)
    return {
        "policy_id": policy["id"],
        "policy_version": policy.get("version", 1),
        "policy_name": policy.get("name"),
        "allowed_limit_kg": policy["shortage_limit_kg"],
        "effective_from": policy["effective_from"],
        "applied_at": datetime.now(timezone.utc).isoformat(),
        **calc,
        "final_recovery_amount": calc["system_recovery_amount"],
        "override": None,
        "policy_missing": False,
    }


async def refresh_trip_driver_recovery_from_snapshot(trip: dict) -> Optional[dict]:
    """Called on Trip UPDATE — recomputes system_recoverable + system_amount
    using the EXISTING snapshot's allowed_limit_kg (never re-resolving the
    policy). This preserves historical policy attachment even if the
    shortage_qty or product_rate is edited later. Overrides are preserved.

    Returns the updated `driver_recovery` dict, or None if the trip had
    no prior snapshot (e.g. trip existed before Iter59 was deployed —
    those trips remain unaffected until they are edited).
    """
    prev = trip.get("driver_recovery")
    if not prev:
        return None
    shortage_mt = float(trip.get("shortage_qty") or 0)
    shortage_kg = round(shortage_mt * 1000, 3)
    product_rate = float(trip.get("product_rate_per_mt") or 0)
    allowed_limit = prev.get("allowed_limit_kg")
    if allowed_limit is None:
        # Snapshot recorded "no policy applied" — keep it that way
        prev["actual_shortage_kg"] = shortage_kg
        prev["product_rate"] = product_rate
        return prev
    calc = compute_driver_recovery(shortage_kg, allowed_limit, product_rate)
    # Preserve historical policy fields
    updated = {**prev, **calc}
    # If NOT overridden, final = system amount; else keep override value
    if updated.get("override"):
        updated["final_recovery_amount"] = updated["override"].get("amount", calc["system_recovery_amount"])
    else:
        updated["final_recovery_amount"] = calc["system_recovery_amount"]
    return updated


@router.get("/driver-shortage-policies")
async def list_policies(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    docs = await db.driver_shortage_policies.find(
        {"user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    ).sort([("effective_from", -1), ("version", -1)]).to_list(500)
    return docs


@router.post("/driver-shortage-policies")
async def create_policy(payload: ShortagePolicyIn, request: Request,
                        user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": new_id("dsp"),
        "user_id": user["user_id"],
        "company_id": cid,
        "version": 1,
        "name": payload.name.strip(),
        "shortage_limit_kg": float(payload.shortage_limit_kg),
        "unit": payload.unit or "KG",
        "effective_from": payload.effective_from,
        "effective_to": payload.effective_to or None,
        "product_category": (payload.product_category or "").strip() or None,
        "active": bool(payload.active),
        "remarks": (payload.remarks or "").strip() or None,
        "created_at": now, "created_by": user["user_id"],
        "updated_at": now, "updated_by": user["user_id"],
    }
    await db.driver_shortage_policies.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/driver-shortage-policies/{pid}")
async def update_policy(pid: str, payload: ShortagePolicyIn, request: Request,
                        user=Depends(get_current_user)):
    """Update a policy. Bumps `version` so historical snapshots on old
    trips remain identifiable (they carry policy_version at snapshot time)."""
    cid = await _active_company_id(request, user)
    existing = await db.driver_shortage_policies.find_one(
        {"id": pid, "user_id": user["user_id"], "company_id": cid}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Policy not found")
    now = datetime.now(timezone.utc).isoformat()
    update = {
        "name": payload.name.strip(),
        "shortage_limit_kg": float(payload.shortage_limit_kg),
        "unit": payload.unit or "KG",
        "effective_from": payload.effective_from,
        "effective_to": payload.effective_to or None,
        "product_category": (payload.product_category or "").strip() or None,
        "active": bool(payload.active),
        "remarks": (payload.remarks or "").strip() or None,
        "version": int(existing.get("version", 1)) + 1,
        "updated_at": now,
        "updated_by": user["user_id"],
    }
    await db.driver_shortage_policies.update_one(
        {"id": pid, "user_id": user["user_id"], "company_id": cid},
        {"$set": update},
    )
    doc = await db.driver_shortage_policies.find_one(
        {"id": pid}, {"_id": 0},
    )
    return doc


@router.delete("/driver-shortage-policies/{pid}")
async def delete_policy(pid: str, request: Request,
                        user=Depends(get_current_user)):
    """Soft-deactivate the policy (never hard delete — historical snapshots
    on old Trips may still reference this policy by id/version)."""
    cid = await _active_company_id(request, user)
    r = await db.driver_shortage_policies.update_one(
        {"id": pid, "user_id": user["user_id"], "company_id": cid},
        {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if r.modified_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"ok": True, "deactivated": True}


@router.get("/driver-shortage-policies/resolve")
async def resolve_policy_endpoint(
    request: Request, user=Depends(get_current_user),
    trip_date: str = "", product_category: str = "",
):
    """Diagnostic endpoint — returns the policy that WOULD apply to a
    given trip_date. Used by the frontend to preview before saving a Trip."""
    if not trip_date:
        raise HTTPException(status_code=400, detail="trip_date required (YYYY-MM-DD)")
    cid = await _active_company_id(request, user)
    p = await resolve_policy_for_trip(
        user["user_id"], cid, trip_date,
        product_category=product_category or None,
    )
    return {"policy": p, "trip_date": trip_date}


class RecoveryOverrideIn(BaseModel):
    override_amount: Optional[float] = None
    override_recoverable_kg: Optional[float] = None
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/trips/{tid}/driver-recovery/override")
async def override_driver_recovery(
    tid: str, payload: RecoveryOverrideIn, request: Request,
    user=Depends(get_current_user),
):
    """Iter59 — Authorised user can override the auto-computed driver
    recovery on a Trip. The system-calculated values are PRESERVED alongside
    the override so both remain auditable.

    Body: {override_amount: float, override_recoverable_kg?: float, reason: str}
    Pass `override_amount = null` to clear a previous override (reverts to
    system calculation).
    """
    cid = await _active_company_id(request, user)
    trip = await db.trips.find_one(
        {"id": tid, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    dr = trip.get("driver_recovery") or {}
    if not dr:
        raise HTTPException(status_code=400,
                            detail="Trip has no driver recovery snapshot yet — save the Trip first")
    now = datetime.now(timezone.utc).isoformat()
    if payload.override_amount is None:
        # Clear override → revert to system calc
        dr["override"] = None
        dr["final_recovery_amount"] = dr.get("system_recovery_amount") or 0
        audit = {"action": "clear", "reason": payload.reason,
                 "by": user["user_id"], "at": now}
    else:
        dr["override"] = {
            "amount": round(float(payload.override_amount), 2),
            "recoverable_kg": (
                round(float(payload.override_recoverable_kg), 3)
                if payload.override_recoverable_kg is not None else None
            ),
            "reason": payload.reason,
            "by": user["user_id"],
            "at": now,
        }
        dr["final_recovery_amount"] = round(float(payload.override_amount), 2)
        audit = {"action": "override", "amount": dr["override"]["amount"],
                 "reason": payload.reason, "by": user["user_id"], "at": now}
    # Persist to trip + append to driver_recovery_history for audit
    history = trip.get("driver_recovery_history") or []
    history.append(audit)
    await db.trips.update_one(
        {"id": tid, "user_id": user["user_id"], "company_id": cid},
        {"$set": {"driver_recovery": dr, "driver_recovery_history": history}},
    )
    return {"ok": True, "driver_recovery": dr, "history": history}
