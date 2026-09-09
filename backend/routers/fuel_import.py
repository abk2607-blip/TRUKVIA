"""Iter147 P0 · Fleet-card fuel import + unified fuel log + vehicle map.

Endpoints (all under /api):
  POST   /api/fuel-import/preview   (multipart: file=@statement.xls|xlsx)
  POST   /api/fuel-import/commit    (json:  {source, rows})
  GET    /api/fuel/vehicle-maps
  POST   /api/fuel/vehicle-maps
  DELETE /api/fuel/vehicle-maps/{fvm_id}
  GET    /api/fuel-log              (unified operator view)
  POST   /api/fuel-manual           (canonical manual Diesel Expense)

Additive to Iter133–146 — reuses canonical Expense writer.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Request, Body

from db import db
from auth import get_current_user
from company import _active_company_id
from models import FuelVehicleMap, Expense, now_utc, new_id
from audit import _log_audit, _diff_dict
from services_fuel_import import (
    parse_fuel_file, build_preview, commit_rows, unified_fuel_log,
    MAX_ROWS_P0, make_source_key, _content_key,
)

router = APIRouter(prefix="/api")

_MAX_UPLOAD_BYTES = 8 * 1024 * 1024   # 8 MB — synchronous ceiling


# ── Vehicle Mapping CRUD ───────────────────────────────────────────────
@router.get("/fuel/vehicle-maps")
async def list_fuel_vehicle_maps(request: Request, user=Depends(get_current_user),
                                 source: Optional[str] = None):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid}
    if source in ("iocl", "bpcl"):
        q["source"] = source
    docs = await db.fuel_vehicle_maps.find(q, {"_id": 0, "user_id": 0}) \
        .sort("source_vehicle_ref", 1).to_list(5000)
    return docs


@router.post("/fuel/vehicle-maps")
async def upsert_fuel_vehicle_map(request: Request, body: dict = Body(...),
                                  user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    source = str(body.get("source") or "").strip().lower()
    if source not in ("iocl", "bpcl"):
        raise HTTPException(status_code=400, detail="source must be 'iocl' or 'bpcl'")
    sref = str(body.get("source_vehicle_ref") or "").strip()
    vid = str(body.get("vehicle_id") or "").strip()
    if not sref:
        raise HTTPException(status_code=400, detail="source_vehicle_ref is required")
    if not vid:
        raise HTTPException(status_code=400, detail="vehicle_id is required")
    veh = await db.vehicles.find_one(
        {"id": vid, "user_id": uid, "company_id": cid},
        {"_id": 0, "vehicle_number": 1, "is_active": 1},
    )
    if not veh:
        raise HTTPException(status_code=400, detail="Vehicle not found in tenant")
    payload = FuelVehicleMap(
        source=source, source_vehicle_ref=sref,
        vehicle_id=vid, vehicle_number=veh.get("vehicle_number", ""),
        created_by=uid,
    )
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    # Upsert on (company_id, source, source_vehicle_ref) — preserve id if exists.
    existing = await db.fuel_vehicle_maps.find_one(
        {"user_id": uid, "company_id": cid, "source": source,
         "source_vehicle_ref": sref},
        {"_id": 0, "id": 1},
    )
    if existing:
        doc["id"] = existing["id"]
        doc["modified_by"] = uid
        doc["modified_at"] = now_utc().isoformat()
        await db.fuel_vehicle_maps.update_one(
            {"user_id": uid, "company_id": cid, "source": source,
             "source_vehicle_ref": sref},
            {"$set": doc},
        )
    else:
        await db.fuel_vehicle_maps.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.delete("/fuel/vehicle-maps/{fvm_id}")
async def delete_fuel_vehicle_map(fvm_id: str, request: Request,
                                  user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    res = await db.fuel_vehicle_maps.delete_one(
        {"id": fvm_id, "user_id": uid, "company_id": cid}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"ok": True}


# ── Import Preview ─────────────────────────────────────────────────────
@router.post("/fuel-import/preview")
async def fuel_import_preview(request: Request,
                              file: UploadFile = File(...),
                              user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(blob) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413,
            detail=f"File exceeds {_MAX_UPLOAD_BYTES // (1024*1024)} MB; please split.")

    source, rows = parse_fuel_file(file.filename or "", blob)
    if source is None:
        raise HTTPException(status_code=400,
            detail="Unrecognised file format. Expected IOCL (.xls) or BPCL (.xlsx) fleet-card statement.")
    if len(rows) == 0:
        return {"source": source, "total_rows": 0,
                "counts": {"ready": 0, "vehicle_mapping_required": 0,
                           "possible_duplicate": 0, "exact_duplicate": 0, "error": 0},
                "rows": [], "unmapped_refs": [],
                "notice": "No Diesel Sale rows found in this statement."}
    if len(rows) > MAX_ROWS_P0:
        raise HTTPException(status_code=413,
            detail=f"File contains {len(rows)} rows (> P0 limit of {MAX_ROWS_P0}). Please split the file.")

    return await build_preview(uid, cid, source, rows)


# ── Import Commit ──────────────────────────────────────────────────────
@router.post("/fuel-import/commit")
async def fuel_import_commit(request: Request, body: dict = Body(...),
                             user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    source = str(body.get("source") or "").strip().lower()
    if source not in ("iocl", "bpcl"):
        raise HTTPException(status_code=400, detail="source must be 'iocl' or 'bpcl'")
    rows = body.get("rows") or []
    return await commit_rows(uid, cid, source, rows)


# ── Manual Fuel Entry (canonical writer) ───────────────────────────────
@router.post("/fuel-manual")
async def create_manual_fuel_expense(request: Request, body: dict = Body(...),
                                     user=Depends(get_current_user)):
    """Manual Diesel entry from Fuel Log → canonical Expense (source_type='manual').

    Server-authoritative amount = round(qty × rate, 2). Reuses the Iter133
    canonical writer (`_validate_and_normalise`) — same accounting path
    as Quick Op and imports.
    """
    from routers.expenses import _validate_and_normalise
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    date = str(body.get("date") or "").strip()
    vid = str(body.get("vehicle_id") or "").strip()
    try:
        qty = float(body.get("litres") or 0)
    except Exception:
        qty = 0.0
    try:
        rate = float(body.get("rate") or 0)
    except Exception:
        rate = 0.0
    station = str(body.get("station_name") or "").strip()
    try:
        odo = float(body.get("odometer") or 0)
    except Exception:
        odo = 0.0
    remarks_in = str(body.get("remarks") or "").strip()

    if not date:
        raise HTTPException(status_code=400, detail="date is required (YYYY-MM-DD)")
    if not vid:
        raise HTTPException(status_code=400, detail="vehicle_id is required")
    if qty <= 0 or rate <= 0:
        raise HTTPException(status_code=400, detail="litres and rate must both be > 0")
    veh = await db.vehicles.find_one(
        {"id": vid, "user_id": uid, "company_id": cid},
        {"_id": 0, "vehicle_number": 1, "is_active": 1},
    )
    if not veh:
        raise HTTPException(status_code=400, detail="Vehicle not found in tenant")
    if veh.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Vehicle is inactive")

    amount = round(qty * rate, 2)
    narration_parts = [f"{qty} L @ ₹{rate:.2f}"]
    if station:
        narration_parts.append(station)
    narration = " · ".join(narration_parts)[:400]
    remarks_parts = []
    if odo > 0:
        remarks_parts.append(f"ODO: {odo}")
    if remarks_in:
        remarks_parts.append(remarks_in)
    remarks = " · ".join(remarks_parts)[:400]

    src_key = "manual:fuel:" + new_id()
    payload = Expense(
        date=date, category="Diesel", amount=amount,
        narration=narration, remarks=remarks,
        vehicle_id=vid, vehicle_number=veh.get("vehicle_number", ""),
        trip_id="", repair_event_id="",
        party_type="cash", party_id="", party_name="",
        vendor_bill_id="", mechanic_work_order_id="",
        supplier_owned_vehicle=False, supplier_settlement_mode="n/a",
        settlement_mode="cash_now",
        source_type="manual", source_key=src_key,
        source="", source_txn_ref="",
        source_trip_id="", file_ids=[],
    )
    payload = await _validate_and_normalise(uid, cid, payload)
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["created_by"] = uid
    doc["created_at"] = now_utc().isoformat()
    doc["is_deleted"] = False
    await db.expenses.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


# ── Unified Fuel Log ───────────────────────────────────────────────────
@router.get("/fuel-log")
async def get_unified_fuel_log(request: Request,
                               date_from: Optional[str] = None,
                               date_to: Optional[str] = None,
                               vehicle_id: Optional[str] = None,
                               source_label: Optional[str] = None,
                               limit: int = 5000,
                               user=Depends(get_current_user)):
    """Operator-facing unified Diesel view. Read-only projection over:
       canonical Expense{category="Diesel"} + legacy db.fuel + Trip legacy Diesel.
    Never contributes to Vehicle Cost / Expense Register / Trip Cost."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await unified_fuel_log(
        uid, cid,
        date_from=date_from, date_to=date_to,
        vehicle_id=vehicle_id, source_filter=source_label,
        limit=max(1, min(limit, 10000)),
    )


# ── Iter147 P0 UAT · Post-import Vehicle Correction ────────────────────
# Narrow, row-level correction endpoint for canonical fleet-card imported
# Diesel Expenses. ONE Expense.vehicle_id + vehicle_number gets rewritten;
# everything else that identifies the source transaction stays intact
# (source, source_txn_ref, source_key, date, amount, narration/remarks
# with litres, rate, station). No new Expense is created — the same row
# is updated in place, so Vehicle Cost / Expense Register / Trip Cost /
# Fuel Log automatically reflect the correction via the existing Iter133
# canonical read paths.
#
# Explicit safety rails:
#   • ONLY `source_type == "fleet_card_import"` rows are editable here.
#   • Reversed or soft-deleted rows are rejected.
#   • FuelVehicleMap is untouched unless the operator opts in via
#     `persist_mapping=true` on the request body. Even then, the map is
#     an opt-in HINT for future imports — it never back-mutates any
#     existing Expense.
@router.patch("/expenses/{eid}/fleet-card-vehicle")
async def correct_fleet_card_expense_vehicle(
    eid: str, request: Request, body: dict = Body(...),
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    new_vid = str(body.get("vehicle_id") or "").strip()
    if not new_vid:
        raise HTTPException(status_code=400, detail="vehicle_id is required")

    before = await db.expenses.find_one(
        {"id": eid, "user_id": uid, "company_id": cid},
        {"_id": 0},
    )
    if not before:
        raise HTTPException(status_code=404, detail="Expense not found")
    if before.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Cannot edit a cancelled Expense.")
    if before.get("is_reversed"):
        raise HTTPException(status_code=400,
            detail="Cannot edit a reversed Expense; create a corrective entry instead.")
    if (before.get("source_type") or "") != "fleet_card_import":
        raise HTTPException(status_code=400,
            detail="This endpoint is limited to fleet-card imported Diesel rows. "
                   "Manual/Quick Op edits use their own endpoints; legacy db.fuel is not editable here.")
    if (before.get("category") or "") != "Diesel":
        raise HTTPException(status_code=400, detail="Only Diesel rows are editable here.")

    veh = await db.vehicles.find_one(
        {"id": new_vid, "user_id": uid, "company_id": cid},
        {"_id": 0, "vehicle_number": 1, "is_active": 1},
    )
    if not veh:
        raise HTTPException(status_code=400, detail="Vehicle not found in tenant")

    prev_vid = before.get("vehicle_id", "")
    prev_vnum = before.get("vehicle_number", "")
    new_vnum = veh.get("vehicle_number", "")

    if new_vid == prev_vid:
        # No-op guard — return the row unchanged.
        before.pop("_id", None); before.pop("user_id", None)
        return {"ok": True, "unchanged": True, "expense": before}

    patch = {
        "vehicle_id": new_vid,
        "vehicle_number": new_vnum,
        "modified_by": uid,
        "modified_at": now_utc().isoformat(),
    }
    await db.expenses.update_one({"id": eid}, {"$set": patch})
    after = {**before, **patch}

    # Audit trail — capture prev/new vehicle explicitly so the correction
    # is discoverable in /api/audit-logs (existing Iter133 pattern).
    try:
        await _log_audit(
            {"user_id": uid, "company_id": cid,
             "email": user.get("email", ""), "name": user.get("name", "")},
            "expense", "update", eid,
            before.get("category", "Diesel"),
            f"fleet-card vehicle correction · {prev_vnum or prev_vid} → {new_vnum or new_vid}",
            _diff_dict(before, after),
        )
    except Exception:
        pass

    # Opt-in only: persist / update the FuelVehicleMap so FUTURE imports
    # auto-resolve this source_vehicle_ref to the corrected vehicle.
    # NEVER runs silently — the checkbox on the dialog controls this.
    persist = bool(body.get("persist_mapping"))
    persisted_map = None
    if persist:
        src = str(before.get("source") or "").lower()
        # Prefer the caller-supplied source_vehicle_ref (row-scoped and
        # exact). Fallback: look up an existing FuelVehicleMap whose
        # vehicle_id matched THIS row's previous vehicle — a deterministic
        # reverse lookup that never mutates other Expenses.
        sref = str(body.get("source_vehicle_ref") or "").strip()
        if not sref:
            existing_map = await db.fuel_vehicle_maps.find_one(
                {"user_id": uid, "company_id": cid, "source": src,
                 "vehicle_id": prev_vid},
                {"_id": 0, "source_vehicle_ref": 1},
            )
            sref = str(existing_map.get("source_vehicle_ref") or "") if existing_map else ""
        if src in ("iocl", "bpcl") and sref:
            existing = await db.fuel_vehicle_maps.find_one(
                {"user_id": uid, "company_id": cid, "source": src,
                 "source_vehicle_ref": sref},
                {"_id": 0, "id": 1},
            )
            payload = FuelVehicleMap(
                source=src, source_vehicle_ref=sref,
                vehicle_id=new_vid, vehicle_number=new_vnum,
                created_by=uid,
            )
            doc = payload.model_dump()
            doc["user_id"] = uid
            doc["company_id"] = cid
            if existing:
                doc["id"] = existing["id"]
                doc["modified_by"] = uid
                doc["modified_at"] = now_utc().isoformat()
                await db.fuel_vehicle_maps.update_one(
                    {"user_id": uid, "company_id": cid, "source": src,
                     "source_vehicle_ref": sref},
                    {"$set": doc},
                )
            else:
                await db.fuel_vehicle_maps.insert_one(doc)
            doc.pop("_id", None); doc.pop("user_id", None)
            persisted_map = doc

    after.pop("_id", None); after.pop("user_id", None)
    return {
        "ok": True,
        "unchanged": False,
        "previous_vehicle_id": prev_vid,
        "previous_vehicle_number": prev_vnum,
        "expense": after,
        "persisted_map": persisted_map,   # None unless operator opted in
    }
