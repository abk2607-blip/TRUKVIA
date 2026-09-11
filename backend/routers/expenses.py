"""Iter133 · Expense CRUD (Turn 1).

Expense = canonical authoritative cost transaction. ONE real-world cost
= ONE Expense row. Trip Cost / Vehicle Cost / Expense Register are
projections of this row and always read Expense — NEVER a twin
VendorBill/MechanicWorkOrder — to guarantee no double-count.

Write-time invariants enforced (all frozen in PRD Iter133):
  • amount > 0
  • date non-empty (accrual date, NOT payment date)
  • vendor_bill_id XOR mechanic_work_order_id — never both
  • vendor_bill_id set  → party_type='vendor',   party_id = VB.vendor_id
  • mech_wo_id     set  → party_type='mechanic', party_id = WO.mechanic_id
  • supplier_owned_vehicle=False → supplier_settlement_mode must be 'n/a'
  • supplier_owned_vehicle=True  → mode ∈ {supplier_settlement_adjustment,
                                          company_borne}
Turn-1 non-goals: no Trip Cost report, no Vehicle Cost report, no ledger
projection to Supplier Statement. Those land in the reporting turn.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query, Body

from db import db
from models import Expense, now_utc
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit, _diff_dict
from services_fin_txn_hooks import hook_after_source_write
from services_expense_linkage_hooks import refresh_linked_paired_sources

router = APIRouter(prefix="/api")


def _require_delete_role(user: dict) -> None:
    role = (user.get("effective_role") or "").lower()
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or Admin role required.")


async def _validate_files(uid: str, cid: str, file_ids: list) -> None:
    if not file_ids:
        return
    found = await db.files.count_documents({
        "user_id": uid, "id": {"$in": file_ids}, "is_deleted": False,
    })
    if found != len(set(file_ids)):
        raise HTTPException(status_code=400, detail="One or more file_ids invalid for this tenant")


async def _validate_and_normalise(uid: str, cid: str, payload: Expense) -> Expense:
    """Enforces every Turn-1 Expense invariant. Returns the (possibly
    denormalised) payload."""
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if not payload.date:
        raise HTTPException(status_code=400, detail="date is required (cost/accrual date)")
    if not payload.category:
        raise HTTPException(status_code=400, detail="category is required")

    # Twin FK exclusivity
    if payload.vendor_bill_id and payload.mechanic_work_order_id:
        raise HTTPException(status_code=400, detail="Expense cannot link to BOTH vendor_bill_id and mechanic_work_order_id")

    # Vendor-bill linkage rules
    if payload.vendor_bill_id:
        bill = await db.vendor_bills.find_one(
            {"id": payload.vendor_bill_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "vendor_id": 1, "vendor_name": 1},
        )
        if not bill:
            raise HTTPException(status_code=400, detail="VendorBill not found in tenant")
        if payload.party_type != "vendor":
            raise HTTPException(status_code=400, detail="party_type must be 'vendor' when vendor_bill_id is set")
        if payload.party_id and payload.party_id != bill["vendor_id"]:
            raise HTTPException(status_code=400, detail="party_id must match VendorBill.vendor_id")
        payload.party_id = bill["vendor_id"]
        payload.party_name = payload.party_name or bill.get("vendor_name", "")

    # Mechanic-WO linkage rules
    if payload.mechanic_work_order_id:
        wo = await db.mechanic_work_orders.find_one(
            {"id": payload.mechanic_work_order_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "mechanic_id": 1, "mechanic_name": 1},
        )
        if not wo:
            raise HTTPException(status_code=400, detail="MechanicWorkOrder not found in tenant")
        if payload.party_type != "mechanic":
            raise HTTPException(status_code=400, detail="party_type must be 'mechanic' when mechanic_work_order_id is set")
        if payload.party_id and payload.party_id != wo["mechanic_id"]:
            raise HTTPException(status_code=400, detail="party_id must match MechanicWorkOrder.mechanic_id")
        payload.party_id = wo["mechanic_id"]
        payload.party_name = payload.party_name or wo.get("mechanic_name", "")

    # Supplier-owned-vehicle XOR guard
    if payload.supplier_owned_vehicle:
        if payload.supplier_settlement_mode not in ("supplier_settlement_adjustment", "company_borne"):
            raise HTTPException(
                status_code=400,
                detail="supplier_owned_vehicle=true requires supplier_settlement_mode of "
                       "'supplier_settlement_adjustment' or 'company_borne' (must be explicit).",
            )
    else:
        if payload.supplier_settlement_mode != "n/a":
            raise HTTPException(
                status_code=400,
                detail="supplier_settlement_mode must be 'n/a' when supplier_owned_vehicle=false.",
            )

    # Reference-existence checks
    if payload.vehicle_id:
        veh = await db.vehicles.find_one({"id": payload.vehicle_id, "user_id": uid, "company_id": cid}, {"_id": 0, "vehicle_number": 1})
        if not veh:
            raise HTTPException(status_code=400, detail="Vehicle not found in tenant")
        payload.vehicle_number = payload.vehicle_number or veh.get("vehicle_number", "")
    if payload.trip_id:
        trip = await db.trips.find_one({"id": payload.trip_id, "user_id": uid, "company_id": cid}, {"_id": 0, "id": 1})
        if not trip:
            raise HTTPException(status_code=400, detail="Trip not found in tenant")
    if payload.repair_event_id:
        rev = await db.repair_events.find_one(
            {"id": payload.repair_event_id, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
            {"_id": 0, "id": 1},
        )
        if not rev:
            raise HTTPException(status_code=400, detail="RepairEvent not found in tenant")

    # Party existence for typed parties (vendor/mechanic/supplier/driver)
    if payload.party_id and payload.party_type in ("vendor", "mechanic", "supplier", "driver"):
        coll_map = {
            "vendor": "vendors",
            "mechanic": "mechanics",
            "supplier": "suppliers",
            "driver": "drivers",
        }
        coll = coll_map[payload.party_type]
        p = await db[coll].find_one({"id": payload.party_id, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
        if not p:
            raise HTTPException(status_code=400, detail=f"{payload.party_type} not found in tenant")
        payload.party_name = payload.party_name or p.get("name", "")

    await _validate_files(uid, cid, payload.file_ids)
    return payload


@router.get("/expenses")
async def list_expenses(
    request: Request,
    trip_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    repair_event_id: Optional[str] = None,
    vendor_bill_id: Optional[str] = None,
    mechanic_work_order_id: Optional[str] = None,
    party_type: Optional[str] = None,
    party_id: Optional[str] = None,
    category: Optional[str] = None,
    source_type: Optional[str] = None,   # Iter148 UAT-fix: comma-separated allowed
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_reversed: bool = False,
    include_cancelled: bool = False,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid}
    # Iter140 · include_cancelled surfaces cancelled rows for the Quick Expense
    # "Today's Entries" strip; every downstream projection (Vehicle Cost /
    # Expense Register / Vendor-linked view) keeps the default filter and
    # therefore continues to hide cancelled rows.
    if not include_cancelled:
        q["is_deleted"] = {"$ne": True}
    if not include_reversed:
        q["is_reversed"] = {"$ne": True}
    if trip_id: q["trip_id"] = trip_id
    if vehicle_id: q["vehicle_id"] = vehicle_id
    if repair_event_id: q["repair_event_id"] = repair_event_id
    if vendor_bill_id: q["vendor_bill_id"] = vendor_bill_id
    if mechanic_work_order_id: q["mechanic_work_order_id"] = mechanic_work_order_id
    if party_type: q["party_type"] = party_type
    if party_id: q["party_id"] = party_id
    if category: q["category"] = category
    if source_type:
        # Iter148 UAT-fix · accept a comma-separated list so "Today's Expenses"
        # can render every canonical operational Expense source in one query
        # (quick_op + fastag_import + fleet_card_import + manual …). A single
        # value continues to work unchanged.
        parts = [s.strip() for s in source_type.split(",") if s.strip()]
        if len(parts) > 1:
            q["source_type"] = {"$in": parts}
        elif parts:
            q["source_type"] = parts[0]
    if date_from or date_to:
        d: dict = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        q["date"] = d
    rows = await db.expenses.find(q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(20000)
    return rows


@router.post("/expenses")
async def create_expense(payload: Expense, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    # Reversal fields can never be set on create (managed by dedicated reversal path).
    payload.reversal_of = ""
    payload.is_reversed = False
    payload = await _validate_and_normalise(uid, cid, payload)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.expenses.insert_one(doc)
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "expense", "create", doc["id"], doc.get("category", ""), "", {})
    except Exception:
        pass
    # Iter150A-2 Phase 3A hook — non-raising; failures land in fin_hook_failures.
    await hook_after_source_write(uid, cid, "expense", doc["id"])
    # Cross-reproject linked VendorBill / MechanicWO so paired/orphan state stays consistent.
    await refresh_linked_paired_sources(uid, cid, None, doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.get("/expenses/{eid}")
async def get_expense(eid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.expenses.find_one(
        {"id": eid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Expense not found")
    return doc


@router.put("/expenses/{eid}")
async def update_expense(eid: str, payload: Expense, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.expenses.find_one({"id": eid, "user_id": uid, "company_id": cid}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="Expense not found")
    if before.get("is_reversed"):
        raise HTTPException(status_code=400, detail="Cannot edit a reversed Expense; create a corrective entry instead.")
    # Reversal fields cannot be flipped via PUT.
    payload.reversal_of = before.get("reversal_of", "")
    payload.is_reversed = bool(before.get("is_reversed", False))
    payload = await _validate_and_normalise(uid, cid, payload)
    patch = payload.model_dump(exclude={"id", "created_at", "created_by",
                                        "is_deleted", "deleted_by", "deleted_at", "deletion_reason"})
    patch["modified_by"] = uid
    patch["modified_at"] = now_utc().isoformat()
    await db.expenses.update_one({"id": eid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "expense", "update", eid, before.get("category", ""), "", _diff_dict(before, after))
    except Exception:
        pass
    # Iter150A-2 Phase 3A hook.
    await hook_after_source_write(uid, cid, "expense", eid)
    await refresh_linked_paired_sources(uid, cid, before, after)
    after.pop("_id", None); after.pop("user_id", None)
    return after


# Iter139 P0 · Quick Operational Expense — bulk canonical writer.
@router.post("/expenses/bulk-operational")
async def bulk_operational_expenses(request: Request, body: dict = Body(...),
                                    user=Depends(get_current_user)):
    from services_quick_expense import bulk_create_operational_expenses
    role = (user.get("effective_role") or "").lower()
    if role not in ("owner", "admin", "ops"):
        raise HTTPException(status_code=403, detail="Owner, Admin, or Ops role required.")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await bulk_create_operational_expenses(uid, cid, user, body)


@router.delete("/expenses/{eid}")
async def delete_expense(
    eid: str, request: Request,
    reason: str = Query(..., min_length=3),
    user=Depends(get_current_user),
):
    _require_delete_role(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.expenses.find_one({"id": eid, "user_id": uid, "company_id": cid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Expense not found")
    await db.expenses.update_one(
        {"id": eid},
        {"$set": {
            "is_deleted": True,
            "deleted_by": uid,
            "deleted_at": now_utc().isoformat(),
            "deletion_reason": reason.strip(),
            "modified_by": uid,
            "modified_at": now_utc().isoformat(),
        }},
    )
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "expense", "delete", eid, doc.get("category", ""), reason, {})
    except Exception:
        pass
    # Iter150A-2 Phase 3A hook — A-1 short-circuits on is_deleted; linked
    # VB / WO transition paired → orphan and must refresh.
    await hook_after_source_write(uid, cid, "expense", eid)
    await refresh_linked_paired_sources(uid, cid, doc, {**doc, "is_deleted": True})
    return {"ok": True}


# ── Iter140 · Quick-Op Diesel edit ─────────────────────────────────────────
# A Diesel-safe edit endpoint that mirrors the create-time authority:
#   • Amount is computed from qty × rate on the server.
#   • Optional vendor_id links to the existing Vendor master (party_type /
#     party_id / party_name — same fields validated at create time).
#   • Narration is composed server-side ("{qty}L @ ₹{rate:.2f} · filled_at
#     · vendor_name").
# NO new schema field. NO VendorBill / VendorPayment side-effect. Vendor
# Ledger untouched. Only source_type='quick_op' + category='Diesel' rows
# can use this endpoint.
@router.put("/expenses/{eid}/quick-diesel")
async def update_quick_diesel_expense(
    eid: str, body: dict = Body(...),
    request: Request = None, user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    before = await db.expenses.find_one(
        {"id": eid, "user_id": uid, "company_id": cid},
        {"_id": 0},
    )
    if not before:
        raise HTTPException(status_code=404, detail="Expense not found")
    if before.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Cannot edit a cancelled Expense.")
    if before.get("is_reversed"):
        raise HTTPException(status_code=400, detail="Cannot edit a reversed Expense; create a corrective entry instead.")
    if before.get("category") != "Diesel":
        raise HTTPException(status_code=400, detail="quick-diesel edit is only valid for Diesel expenses.")
    if before.get("source_type") != "quick_op":
        raise HTTPException(status_code=400, detail="quick-diesel edit is only valid for source_type='quick_op' rows.")

    try:
        qty = float(body.get("qty") or 0)
    except Exception:
        qty = 0.0
    try:
        rate = float(body.get("rate") or 0)
    except Exception:
        rate = 0.0
    if qty <= 0 or rate <= 0:
        raise HTTPException(status_code=400, detail="qty and rate must both be > 0 for Diesel.")
    server_amount = round(qty * rate, 2)

    # Optional vendor linkage — same validation surface as create.
    party_type = "cash"
    party_id = ""
    party_name = ""
    vid_link = str(body.get("vendor_id") or "").strip()
    if vid_link:
        ven = await db.vendors.find_one(
            {"id": vid_link, "user_id": uid, "company_id": cid},
            {"_id": 0, "name": 1, "is_active": 1},
        )
        if not ven:
            raise HTTPException(status_code=400, detail="Selected Vendor not found in tenant.")
        if ven.get("is_active") is False:
            raise HTTPException(status_code=400, detail="Selected Vendor is inactive.")
        party_type = "vendor"
        party_id = vid_link
        party_name = ven.get("name", "")

    filled_at = str(body.get("filled_at") or "").strip()
    parts = [f"{qty}L @ ₹{rate:.2f}"]
    if filled_at:
        parts.append(filled_at)
    if party_name:
        parts.append(party_name)
    narration = " · ".join(parts)[:400]

    patch = {
        "amount": server_amount,
        "narration": narration,
        "remarks": str(body.get("remarks") or "")[:400],
        "party_type": party_type,
        "party_id": party_id,
        "party_name": party_name,
        "modified_by": uid,
        "modified_at": now_utc().isoformat(),
    }
    await db.expenses.update_one({"id": eid}, {"$set": patch})
    after = {**before, **patch}
    try:
        await _log_audit({"user_id": uid, "company_id": cid, "email": user.get("email", ""), "name": user.get("name", "")},
                         "expense", "update", eid, "Diesel", "quick-diesel-edit",
                         _diff_dict(before, after))
    except Exception:
        pass
    # Iter150A-2 Phase 3A hook — amount/party may change; no linkage change
    # possible on this endpoint, but helper is no-op when linkage unchanged.
    await hook_after_source_write(uid, cid, "expense", eid)
    await refresh_linked_paired_sources(uid, cid, before, after)
    after.pop("_id", None); after.pop("user_id", None)
    return after



# ── Iter149 P0 · Toll Trip Linkage ────────────────────────────────────────
# Narrow, source-preserving endpoint that lets an operator attach a
# FASTag-imported canonical Toll Expense to an existing Trip (or unlink).
# Zero accounting side-effects: writes ONLY `expense.trip_id` +
# `modified_by`/`modified_at`. Every downstream projection (Trip View,
# Vehicle Workspace → Trip Cost, Vehicle Cost KPI, Vehicle PDF/Excel,
# Expense Register, Today's Expenses) auto-reflects the change via the
# existing Iter133 canonical read paths.
#
# Safety rails (frozen for Iter149 P0):
#   • Only source_type == "fastag_import" AND category == "Toll" rows.
#   • Not is_deleted, not is_reversed.
#   • Trip must exist in tenant.
#   • Trip.vehicle_id must match Expense.vehicle_id.
#   • L.1 · Trip.has_canonical_expenses must be true (legacy trips
#     blocked — no auto-flip).
#   • Trip.date within ±2 days of Expense.date unless force=true.
#   • Idempotent — re-posting the same trip_id is a no-op.
#   • trip_id="" unlinks (audit-logged; always allowed).
#   • Role gate: Owner / Admin / Ops.
@router.patch("/expenses/{eid}/toll-trip")
async def link_toll_expense_to_trip(
    eid: str, request: Request, body: dict = Body(...),
    user=Depends(get_current_user),
):
    role = (user.get("effective_role") or "").lower()
    if role not in ("owner", "admin", "ops"):
        raise HTTPException(status_code=403, detail="Owner, Admin, or Ops role required.")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    new_tid = str(body.get("trip_id") or "").strip()   # "" == unlink
    force = bool(body.get("force"))

    before = await db.expenses.find_one(
        {"id": eid, "user_id": uid, "company_id": cid},
        {"_id": 0},
    )
    if not before:
        raise HTTPException(status_code=404, detail="Expense not found")
    if before.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Cannot link a cancelled Expense.")
    if before.get("is_reversed"):
        raise HTTPException(
            status_code=400,
            detail="Cannot link a reversed Expense; create a corrective entry instead.",
        )
    if (before.get("source_type") or "") != "fastag_import":
        raise HTTPException(
            status_code=400,
            detail="This endpoint is limited to FASTag-imported Toll rows "
                   "(source_type='fastag_import').",
        )
    if (before.get("category") or "") != "Toll":
        raise HTTPException(status_code=400, detail="Only Toll rows are linkable here.")

    prev_tid = before.get("trip_id", "") or ""
    trip = None

    if new_tid:
        trip = await db.trips.find_one(
            {"id": new_tid, "user_id": uid, "company_id": cid},
            {"_id": 0, "id": 1, "vehicle_id": 1, "vehicle_number": 1,
             "date": 1, "lr_number": 1, "has_canonical_expenses": 1,
             "expenses": 1, "other_expenditures": 1},
        )
        if not trip:
            raise HTTPException(status_code=400, detail="Trip not found in tenant")
        # L.1 REVISED (2026-09-10) · Only block trips whose legacy Toll
        # surface would conflict with the canonical projection. Empty /
        # modern trips with no legacy Toll scalar (and no Toll-typed
        # other_expenditures row) are eligible even when
        # has_canonical_expenses is false.
        from services_expense_bridge import is_legacy_conflicting_toll_trip
        if is_legacy_conflicting_toll_trip(trip):
            raise HTTPException(
                status_code=400,
                detail="Cannot link Toll to a legacy-conflicting Trip "
                       "(this trip already carries a legacy Toll amount "
                       "in Trip.expenses.toll or a Toll-typed "
                       "other_expenditure). Convert the legacy Toll to "
                       "canonical first, or link to a different trip.",
            )
        # Vehicle match — never link across vehicles.
        if (trip.get("vehicle_id") or "") != (before.get("vehicle_id") or ""):
            raise HTTPException(
                status_code=400,
                detail="Trip.vehicle_id does not match Expense.vehicle_id",
            )
        # ±2-day window unless force=true.
        if not force:
            e_date = before.get("date", "") or ""
            t_date = trip.get("date", "") or ""
            try:
                from datetime import date as _dt
                ed = _dt.fromisoformat(e_date)
                td = _dt.fromisoformat(t_date)
                if abs((ed - td).days) > 2:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Trip date {t_date} is more than ±2 days from "
                               f"Expense date {e_date}. Pass force=true to override.",
                    )
            except HTTPException:
                raise
            except Exception:
                # Malformed dates: don't block; audit + proceed.
                pass

    if new_tid == prev_tid:
        before.pop("_id", None); before.pop("user_id", None)
        return {"ok": True, "unchanged": True, "expense": before}

    patch = {
        "trip_id": new_tid,
        "modified_by": uid,
        "modified_at": now_utc().isoformat(),
    }
    await db.expenses.update_one({"id": eid}, {"$set": patch})
    after = {**before, **patch}

    # Audit — capture prev/new trip explicitly.
    action_desc = (
        f"toll-trip link · {prev_tid or '—'} → {new_tid or '—'}"
        + (f" · LR {trip.get('lr_number', '')}" if trip and trip.get("lr_number") else "")
        + (" · force=true" if (new_tid and force) else "")
    )
    try:
        await _log_audit(
            {"user_id": uid, "company_id": cid,
             "email": user.get("email", ""), "name": user.get("name", "")},
            "expense", "update", eid, "Toll", action_desc,
            _diff_dict(before, after),
        )
    except Exception:
        pass

    # Iter150A-2 Phase 3A hook — only trip_id changes; FinTxn.trip_id denorm
    # refreshes; amount/account unchanged. No linkage change on this endpoint.
    await hook_after_source_write(uid, cid, "expense", eid)
    await refresh_linked_paired_sources(uid, cid, before, after)

    after.pop("_id", None); after.pop("user_id", None)
    return {
        "ok": True,
        "unchanged": False,
        "previous_trip_id": prev_tid,
        "expense": after,
    }
