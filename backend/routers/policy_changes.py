"""Iter105 · Customer Policy Change Workflow — Phase A (Preview + Apply).

Design contract (matches the user-approved spec):
  • Effective Date is MANDATORY.
  • `apply_to_previous` is OFF by default. When OFF, this endpoint does not
    touch any historical trip; the customer master edit path (PUT /customers)
    is the responsibility of the caller.
  • When ON, the caller must send the explicit `trip_ids` selection. Only
    those trips are recomputed; every other trip is guaranteed untouched.
  • Invoiced trips are hard-filtered out at the DB level (`invoice_id` empty).
  • Historical / archived trips (`is_historical=True`) are hard-filtered out.
  • Company + user_id scoping is enforced on every query.
  • The engine (`services._compute_trip`) is used unchanged. The snapshot
    logic mirrors `routers.trips.create_trip` — Customer + Product + Supplier
    masters are re-read from CURRENT state, applied_* fields are re-written,
    and the trip is recomputed. Nothing else on the trip is mutated.
  • Every apply run records a `policy_change_events` row with the full old
    vs new snapshot, applied trip ids, per-trip old→new deltas, and actor.
    Phase B (Revert) will add revert_reason / reverted_at fields on this row.

Endpoints (Phase A):
  POST /api/policy-changes/preview   — READ-ONLY dry-run.
  POST /api/policy-changes/apply     — Persists customer + trips + event.
  GET  /api/policy-changes           — History list for a customer.
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import logging

from db import db
from models import Trip, Customer, new_id, now_utc
from auth import get_current_user
from company import _active_company_id
from services import _compute_trip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ── Snapshot / recompute helper ──────────────────────────────────────────

def _snapshot_fields_from_masters(trip_doc: dict, customer: dict,
                                  product: Optional[dict],
                                  supplier: Optional[dict]) -> dict:
    """Return a dict of the applied_* fields derived from CURRENT master data.
    Mirrors the freeze logic in `routers.trips.create_trip` exactly."""
    sc = customer.get("shortage_config") or {}
    _sc_limit = float(sc.get("limit", 0) or 0)
    _sc_method = (sc.get("method") or "").strip()

    snap = {
        "applied_freight_method": customer.get("default_freight_method") or "per_ton_loading",
        "applied_customer_shortage_method": _sc_method,
    }
    if _sc_limit > 0:
        snap["applied_customer_shortage_limit"] = _sc_limit
        snap["applied_customer_shortage_limit_type"] = sc.get("limit_type") or "pct"
    else:
        snap["applied_customer_shortage_limit"] = 0.0
        snap["applied_customer_shortage_limit_type"] = ""

    snap["applied_product_shortage_pct"] = float(
        (product or {}).get("default_shortage_allowance_pct", 0) or 0
    )

    # Supplier — mirror Iter90 per-product limit lookup with legacy fallback.
    if trip_doc.get("vehicle_type") == "supplier" and supplier:
        pid = trip_doc.get("product_id")
        psl_kg = None
        for row in (supplier.get("product_shortage_limits") or []):
            if row.get("product_id") == pid:
                try:
                    psl_kg = float(row.get("limit_kg", 0) or 0)
                except (TypeError, ValueError):
                    psl_kg = 0.0
                break
        if psl_kg is None:
            psl_kg = float(supplier.get("shortage_limit_kg", 0) or 0)
        snap["applied_supplier_shortage_limit_kg"] = psl_kg
    else:
        # non-supplier trips preserve their (usually 0) existing value
        snap["applied_supplier_shortage_limit_kg"] = float(
            trip_doc.get("applied_supplier_shortage_limit_kg", 0) or 0
        )
    return snap


def _recompute_dryrun(trip_doc: dict, snap_fields: dict) -> dict:
    """Return the trip's post-recompute financial fields WITHOUT persisting.
    Used by /preview."""
    merged = {**trip_doc, **snap_fields}
    try:
        t = Trip(**{k: v for k, v in merged.items() if k in Trip.model_fields})
    except Exception as exc:
        # Malformed legacy trip — surface as a preview-time diagnostic; skip.
        logger.warning("policy_change preview: skip malformed trip %s: %s",
                       trip_doc.get("id"), exc)
        return {}
    t = _compute_trip(t)
    out = t.model_dump()
    keep = ("freight_amount", "freight_qty_used", "shortage_qty", "excess_qty",
            "shortage_amount", "excess_amount", "supplier_freight",
            "supplier_net_payable", "supplier_shortage_deduction",
            "profit", "net_settlement", "total_expense")
    return {k: out[k] for k in keep if k in out}


# ── Eligibility query ────────────────────────────────────────────────────

def _eligibility_filter(user_id: str, company_id: str,
                        customer_id: str, effective_from: str) -> dict:
    """Uninvoiced + non-historical + on-or-after effective_from."""
    return {
        "user_id": user_id,
        "company_id": company_id,
        "customer_id": customer_id,
        # Uninvoiced — invoice_id absent, null, or empty string.
        "$or": [
            {"invoice_id": {"$exists": False}},
            {"invoice_id": None},
            {"invoice_id": ""},
        ],
        "is_historical": {"$ne": True},
        "date": {"$gte": effective_from},
    }


# ── Request DTOs ─────────────────────────────────────────────────────────

class _ShortageConfigIn(BaseModel):
    limit: float = 0.0
    limit_type: Literal["pct", "kg"] = "pct"
    method: Literal["net_shortage", "full_after_limit"] = "net_shortage"
    effective_from: str = ""
    active: bool = True
    remarks: str = ""


class _PolicyIn(BaseModel):
    default_freight_method: Literal[
        "per_ton_loading", "per_ton_unloading", "per_ton_higher_of", "fixed"
    ] = "per_ton_loading"
    shortage_config: _ShortageConfigIn = Field(default_factory=_ShortageConfigIn)


class PreviewRequest(BaseModel):
    customer_id: str
    effective_from: str          # mandatory (ISO date)
    new_policy: _PolicyIn


class ApplyRequest(BaseModel):
    customer_id: str
    effective_from: str
    new_policy: _PolicyIn
    apply_to_previous: bool = False
    trip_ids: List[str] = Field(default_factory=list)
    reason: str = ""


# ── Preview (read-only dry-run) ──────────────────────────────────────────

@router.post("/policy-changes/preview")
async def preview_policy_change(payload: PreviewRequest, request: Request,
                                user=Depends(get_current_user)):
    if not (payload.effective_from or "").strip():
        raise HTTPException(400, "effective_from is required")
    cid = await _active_company_id(request, user)

    customer = await db.customers.find_one(
        {"id": payload.customer_id, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    )
    if not customer:
        raise HTTPException(404, "Customer not found")

    # Build the hypothetical NEW customer record (in memory only)
    new_customer = {
        **customer,
        "default_freight_method": payload.new_policy.default_freight_method,
        "shortage_config": {
            **(customer.get("shortage_config") or {}),
            **payload.new_policy.shortage_config.model_dump(),
        },
    }
    old_policy_out = {
        "default_freight_method": customer.get("default_freight_method"),
        "shortage_config": customer.get("shortage_config") or {},
    }
    new_policy_out = {
        "default_freight_method": new_customer["default_freight_method"],
        "shortage_config": new_customer["shortage_config"],
    }

    # Eligible trips (uninvoiced + non-historical + date ≥ effective_from)
    eligible_cursor = db.trips.find(
        _eligibility_filter(user["user_id"], cid, payload.customer_id,
                            payload.effective_from),
        {"_id": 0, "user_id": 0},
    ).sort("date", 1)
    trips = await eligible_cursor.to_list(1000)

    # Pre-load products + suppliers used
    product_ids = {t.get("product_id") for t in trips if t.get("product_id")}
    supplier_ids = {t.get("supplier_id") for t in trips
                    if t.get("supplier_id") and t.get("vehicle_type") == "supplier"}
    products = {p["id"]: p for p in await db.products.find(
        {"id": {"$in": list(product_ids)}, "user_id": user["user_id"]},
        {"_id": 0},
    ).to_list(len(product_ids) or 1)}
    suppliers = {s["id"]: s for s in await db.suppliers.find(
        {"id": {"$in": list(supplier_ids)}, "user_id": user["user_id"]},
        {"_id": 0},
    ).to_list(len(supplier_ids) or 1)}

    # Diagnostic counts — invoiced/historical/out-of-range in the same customer
    skipped_invoiced = await db.trips.count_documents({
        "user_id": user["user_id"], "company_id": cid,
        "customer_id": payload.customer_id,
        "invoice_id": {"$exists": True, "$nin": [None, ""]},
        "date": {"$gte": payload.effective_from},
    })
    skipped_historical = await db.trips.count_documents({
        "user_id": user["user_id"], "company_id": cid,
        "customer_id": payload.customer_id,
        "is_historical": True,
        "date": {"$gte": payload.effective_from},
    })

    eligible_out = []
    for t in trips:
        snap = _snapshot_fields_from_masters(
            t, new_customer, products.get(t.get("product_id")),
            suppliers.get(t.get("supplier_id")),
        )
        new_fin = _recompute_dryrun(t, snap)
        old_snap = {
            "applied_freight_method": t.get("applied_freight_method", ""),
            "applied_customer_shortage_limit": float(t.get("applied_customer_shortage_limit", 0) or 0),
            "applied_customer_shortage_limit_type": t.get("applied_customer_shortage_limit_type", ""),
            "applied_customer_shortage_method": t.get("applied_customer_shortage_method", ""),
            "applied_product_shortage_pct": float(t.get("applied_product_shortage_pct", 0) or 0),
            "applied_supplier_shortage_limit_kg": float(t.get("applied_supplier_shortage_limit_kg", 0) or 0),
        }
        # Iter105 · Also run the OLD snapshot through the engine so the
        # displayed OLD side matches what the trip WOULD have been with a
        # clean recompute. Prevents apples-to-oranges deltas caused by
        # legacy create-time recompute gaps (e.g. net_settlement not being
        # in the phase-2 update list on older trips).
        old_fin_recomputed = _recompute_dryrun(t, old_snap) or {}
        old_fin = {
            "freight_amount": float(old_fin_recomputed.get("freight_amount", t.get("freight_amount", 0)) or 0),
            "shortage_qty": float(old_fin_recomputed.get("shortage_qty", t.get("shortage_qty", 0)) or 0),
            "shortage_amount": float(old_fin_recomputed.get("shortage_amount", t.get("shortage_amount", 0)) or 0),
            "excess_amount": float(old_fin_recomputed.get("excess_amount", t.get("excess_amount", 0)) or 0),
            "net_settlement": float(old_fin_recomputed.get("net_settlement", t.get("net_settlement", 0)) or 0),
        }
        eligible_out.append({
            "trip_id": t["id"],
            "lr_number": t.get("lr_number", ""),
            "date": t.get("date", ""),
            "vehicle_number": t.get("vehicle_number", ""),
            "loading_tons": float(t.get("tons", 0) or 0),
            "unloading_tons": float(t.get("unloaded_qty", 0) or 0),
            "product_id": t.get("product_id", ""),
            "product_name": t.get("load_details", ""),
            "old_snapshot": old_snap,
            "new_snapshot": snap,
            "old": old_fin,
            "new": {k: float(new_fin.get(k, 0) or 0) for k in old_fin.keys()},
            "delta_freight": round(float(new_fin.get("freight_amount", 0) or 0) - old_fin["freight_amount"], 2),
            "delta_shortage_amount": round(float(new_fin.get("shortage_amount", 0) or 0) - old_fin["shortage_amount"], 2),
            "delta_net_settlement": round(float(new_fin.get("net_settlement", 0) or 0) - old_fin["net_settlement"], 2),
        })

    return {
        "customer_id": payload.customer_id,
        "effective_from": payload.effective_from,
        "old_policy": old_policy_out,
        "new_policy": new_policy_out,
        "eligible_trips": eligible_out,
        "total_eligible": len(eligible_out),
        "skipped_invoiced_count": skipped_invoiced,
        "skipped_historical_count": skipped_historical,
    }


# ── Apply (persist customer + selected trips + event) ────────────────────

@router.post("/policy-changes/apply")
async def apply_policy_change(payload: ApplyRequest, request: Request,
                              user=Depends(get_current_user)):
    if not (payload.effective_from or "").strip():
        raise HTTPException(400, "effective_from is required")
    cid = await _active_company_id(request, user)

    customer = await db.customers.find_one(
        {"id": payload.customer_id, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    )
    if not customer:
        raise HTTPException(404, "Customer not found")

    old_policy = {
        "default_freight_method": customer.get("default_freight_method"),
        "shortage_config": customer.get("shortage_config") or {},
    }
    new_shortage_config = {
        **(customer.get("shortage_config") or {}),
        **payload.new_policy.shortage_config.model_dump(),
    }
    new_policy_final = {
        "default_freight_method": payload.new_policy.default_freight_method,
        "shortage_config": new_shortage_config,
    }

    # 1) Update the customer master (always — this is the primary intent).
    await db.customers.update_one(
        {"id": payload.customer_id, "user_id": user["user_id"], "company_id": cid},
        {"$set": {
            "default_freight_method": payload.new_policy.default_freight_method,
            "shortage_config": new_shortage_config,
        }},
    )
    updated_customer_doc = await db.customers.find_one(
        {"id": payload.customer_id, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    )

    applied_trip_ids: List[str] = []
    per_trip_deltas: List[dict] = []
    skipped = {"invoiced": [], "historical": [], "not_found": [], "out_of_range": []}

    if payload.apply_to_previous and payload.trip_ids:
        # Fetch the requested trips and validate eligibility one-by-one.
        found = await db.trips.find(
            {"id": {"$in": payload.trip_ids},
             "user_id": user["user_id"], "company_id": cid,
             "customer_id": payload.customer_id},
            {"_id": 0, "user_id": 0},
        ).to_list(len(payload.trip_ids))
        found_by_id = {t["id"]: t for t in found}
        for tid in payload.trip_ids:
            if tid not in found_by_id:
                skipped["not_found"].append(tid)

        # Pre-load products + suppliers
        product_ids = {t.get("product_id") for t in found if t.get("product_id")}
        supplier_ids = {t.get("supplier_id") for t in found
                        if t.get("supplier_id") and t.get("vehicle_type") == "supplier"}
        products = {p["id"]: p for p in await db.products.find(
            {"id": {"$in": list(product_ids)}, "user_id": user["user_id"]},
            {"_id": 0},
        ).to_list(len(product_ids) or 1)}
        suppliers = {s["id"]: s for s in await db.suppliers.find(
            {"id": {"$in": list(supplier_ids)}, "user_id": user["user_id"]},
            {"_id": 0},
        ).to_list(len(supplier_ids) or 1)}

        snap_now = now_utc().isoformat()
        for t in found:
            # Hard eligibility gates — invoiced / historical / date-range.
            if t.get("invoice_id"):
                skipped["invoiced"].append(t["id"])
                continue
            if t.get("is_historical"):
                skipped["historical"].append(t["id"])
                continue
            if (t.get("date") or "") < payload.effective_from:
                skipped["out_of_range"].append(t["id"])
                continue

            snap = _snapshot_fields_from_masters(
                t, updated_customer_doc,
                products.get(t.get("product_id")),
                suppliers.get(t.get("supplier_id")),
            )
            new_fin = _recompute_dryrun(t, snap)
            if not new_fin:
                # Malformed trip skipped by dryrun — leave untouched.
                skipped["not_found"].append(t["id"])
                continue

            # Capture OLD snapshot + financials for the audit event
            old_snap_row = {
                "applied_freight_method": t.get("applied_freight_method", ""),
                "applied_customer_shortage_limit": float(t.get("applied_customer_shortage_limit", 0) or 0),
                "applied_customer_shortage_limit_type": t.get("applied_customer_shortage_limit_type", ""),
                "applied_customer_shortage_method": t.get("applied_customer_shortage_method", ""),
                "applied_product_shortage_pct": float(t.get("applied_product_shortage_pct", 0) or 0),
                "applied_supplier_shortage_limit_kg": float(t.get("applied_supplier_shortage_limit_kg", 0) or 0),
                "policy_snapshot_at": t.get("policy_snapshot_at", ""),
                "freight_amount": float(t.get("freight_amount", 0) or 0),
                "shortage_qty": float(t.get("shortage_qty", 0) or 0),
                "shortage_amount": float(t.get("shortage_amount", 0) or 0),
                "excess_amount": float(t.get("excess_amount", 0) or 0),
                "net_settlement": float(t.get("net_settlement", 0) or 0),
            }
            new_snap_row = {**snap, "policy_snapshot_at": snap_now, **new_fin}

            # Persist the recomputed trip. ONLY the applied_* + recomputed
            # financial fields are updated; every other field is left alone.
            update_set = {**snap, "policy_snapshot_at": snap_now, **new_fin}
            await db.trips.update_one(
                {"id": t["id"], "user_id": user["user_id"], "company_id": cid},
                {"$set": update_set},
            )
            applied_trip_ids.append(t["id"])
            per_trip_deltas.append({
                "trip_id": t["id"],
                "lr_number": t.get("lr_number", ""),
                "date": t.get("date", ""),
                "vehicle_number": t.get("vehicle_number", ""),
                "old": old_snap_row,
                "new": new_snap_row,
                "delta_net_settlement": round(
                    float(new_fin.get("net_settlement", 0) or 0)
                    - old_snap_row["net_settlement"], 2),
            })

    # 2) Record the Policy Change Event (always — the master change is
    #    still material even when apply_to_previous is OFF).
    event_id = new_id("pce_")
    event_doc = {
        "id": event_id,
        "user_id": user["user_id"],
        "company_id": cid,
        "customer_id": payload.customer_id,
        "effective_from": payload.effective_from,
        "old_policy": old_policy,
        "new_policy": new_policy_final,
        "apply_to_previous": bool(payload.apply_to_previous),
        "applied_trip_ids": applied_trip_ids,
        "per_trip_deltas": per_trip_deltas,
        "skipped": skipped,
        "reason": payload.reason,
        "actor_email": user.get("email", ""),
        "actor_name": user.get("name", ""),
        "actor_user_id": user["user_id"],
        "created_at": now_utc().isoformat(),
        "status": "applied",
        "reverted_at": "",
        "reverted_by": "",
        "revert_reason": "",
    }
    await db.policy_change_events.insert_one(dict(event_doc))
    event_doc.pop("_id", None)

    # 3) Ledger crumb in audit_logs (mirrors the pattern used by other Iters)
    try:
        await db.audit_logs.insert_one({
            "id": new_id("audit_"),
            "user_id": user["user_id"],
            "company_id": cid,
            "action": "policy_change_apply",
            "module": "customer",
            "entity_id": payload.customer_id,
            "entity_ref": customer.get("name", ""),
            "timestamp": now_utc().isoformat(),
            "actor_email": user.get("email", ""),
            "user_email": user.get("email", ""),
            "user_name": user.get("name", ""),
            "reason": payload.reason,
            "changes": {"applied_trip_count": len(applied_trip_ids),
                        "apply_to_previous": bool(payload.apply_to_previous)},
            "detail": {"event_id": event_id},
        })
    except Exception as exc:
        logger.warning("policy_change_apply: audit crumb failed: %s", exc)

    return {
        "event_id": event_id,
        "updated_customer": True,
        "applied_trip_ids": applied_trip_ids,
        "updated_trip_count": len(applied_trip_ids),
        "skipped": skipped,
        "event": event_doc,
    }


# ── History list (for the future Revert phase + audit UI) ────────────────

@router.get("/policy-changes")
async def list_policy_change_events(request: Request, customer_id: Optional[str] = None,
                                    limit: int = 50,
                                    user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    q = {"user_id": user["user_id"], "company_id": cid}
    if customer_id:
        q["customer_id"] = customer_id
    rows = await db.policy_change_events.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(max(1, min(200, int(limit))))
    return {"items": rows, "total": len(rows)}


# ── Phase B · Revert (mandatory reason + invoice safety gate) ─────────────

class RevertRequest(BaseModel):
    reason: str


@router.post("/policy-changes/{event_id}/revert")
async def revert_policy_change(event_id: str, payload: RevertRequest,
                               request: Request,
                               user=Depends(get_current_user)):
    """Revert a previously-applied Policy Change Event.

    Contract:
      • `reason` is MANDATORY (400 if blank).
      • Only events with `status='applied'` can be reverted (400 otherwise).
      • If ANY of the previously-applied trips is now invoiced, the revert
        is REFUSED (409 Conflict) with the list of blocking trip IDs — no
        partial revert is ever performed.
      • Customer master is restored to `old_policy` on the event.
      • Each applied trip's `applied_*` snapshot + recomputed financial
        fields are restored from `per_trip_deltas[i].old`.
      • Event row status flips to `reverted` with reverted_at + reverted_by
        + revert_reason. Audit crumb dropped in `audit_logs`.
    """
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(400, "reason is required for revert")

    cid = await _active_company_id(request, user)
    event = await db.policy_change_events.find_one(
        {"id": event_id, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    )
    if not event:
        raise HTTPException(404, "Policy Change Event not found")
    if event.get("status") != "applied":
        raise HTTPException(400, f"Event is already {event.get('status')}; nothing to revert")

    applied_trip_ids = event.get("applied_trip_ids") or []
    per_trip_deltas = event.get("per_trip_deltas") or []
    delta_by_id = {d["trip_id"]: d for d in per_trip_deltas}

    # Safety gate — refuse the revert wholesale if ANY applied trip has
    # since been invoiced. We never partially revert.
    if applied_trip_ids:
        invoiced_now = await db.trips.find(
            {"id": {"$in": applied_trip_ids},
             "user_id": user["user_id"], "company_id": cid,
             "invoice_id": {"$exists": True, "$nin": [None, ""]}},
            {"_id": 0, "id": 1, "lr_number": 1, "invoice_id": 1},
        ).to_list(len(applied_trip_ids))
        if invoiced_now:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REVERT_BLOCKED_INVOICED",
                    "message": (
                        f"Cannot revert — {len(invoiced_now)} of the affected "
                        f"trip(s) have since been invoiced. Void the invoice(s) "
                        f"first, then retry revert."
                    ),
                    "invoiced_trip_ids": [t["id"] for t in invoiced_now],
                    "invoiced_lr_numbers": [t.get("lr_number", "") for t in invoiced_now],
                },
            )

    # 1) Restore the Customer master to the OLD policy captured on the event.
    old_policy = event.get("old_policy") or {}
    restore_set = {}
    if "default_freight_method" in old_policy:
        restore_set["default_freight_method"] = old_policy["default_freight_method"] or "per_ton_loading"
    if "shortage_config" in old_policy:
        restore_set["shortage_config"] = old_policy["shortage_config"] or {}
    if restore_set:
        await db.customers.update_one(
            {"id": event["customer_id"], "user_id": user["user_id"], "company_id": cid},
            {"$set": restore_set},
        )

    # 2) Restore each trip's applied_* + recomputed financial fields.
    reverted_trip_ids: List[str] = []
    for tid in applied_trip_ids:
        d = delta_by_id.get(tid)
        if not d or not d.get("old"):
            continue
        old = d["old"]
        # Only touch fields we captured. Everything else stays untouched.
        trip_set = {
            "applied_freight_method": old.get("applied_freight_method", ""),
            "applied_customer_shortage_limit": float(old.get("applied_customer_shortage_limit", 0) or 0),
            "applied_customer_shortage_limit_type": old.get("applied_customer_shortage_limit_type", ""),
            "applied_customer_shortage_method": old.get("applied_customer_shortage_method", ""),
            "applied_product_shortage_pct": float(old.get("applied_product_shortage_pct", 0) or 0),
            "applied_supplier_shortage_limit_kg": float(old.get("applied_supplier_shortage_limit_kg", 0) or 0),
            "policy_snapshot_at": old.get("policy_snapshot_at", ""),
            "freight_amount": float(old.get("freight_amount", 0) or 0),
            "shortage_qty": float(old.get("shortage_qty", 0) or 0),
            "shortage_amount": float(old.get("shortage_amount", 0) or 0),
            "excess_amount": float(old.get("excess_amount", 0) or 0),
            "net_settlement": float(old.get("net_settlement", 0) or 0),
        }
        await db.trips.update_one(
            {"id": tid, "user_id": user["user_id"], "company_id": cid},
            {"$set": trip_set},
        )
        reverted_trip_ids.append(tid)

    # 3) Flip event status → reverted.
    now = now_utc().isoformat()
    await db.policy_change_events.update_one(
        {"id": event_id, "user_id": user["user_id"], "company_id": cid},
        {"$set": {
            "status": "reverted",
            "reverted_at": now,
            "reverted_by": user.get("email", ""),
            "reverted_by_user_id": user["user_id"],
            "revert_reason": reason,
        }},
    )

    # 4) Audit crumb.
    try:
        await db.audit_logs.insert_one({
            "id": new_id("audit_"),
            "user_id": user["user_id"],
            "company_id": cid,
            "action": "policy_change_revert",
            "module": "customer",
            "entity_id": event["customer_id"],
            "entity_ref": event.get("old_policy", {}).get("default_freight_method", ""),
            "timestamp": now,
            "actor_email": user.get("email", ""),
            "user_email": user.get("email", ""),
            "user_name": user.get("name", ""),
            "reason": reason,
            "changes": {"reverted_trip_count": len(reverted_trip_ids),
                        "event_id": event_id},
            "detail": {"event_id": event_id},
        })
    except Exception as exc:
        logger.warning("policy_change_revert: audit crumb failed: %s", exc)

    refreshed = await db.policy_change_events.find_one(
        {"id": event_id, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    )
    return {
        "event_id": event_id,
        "reverted_trip_ids": reverted_trip_ids,
        "reverted_trip_count": len(reverted_trip_ids),
        "customer_restored": bool(restore_set),
        "event": refreshed,
    }
