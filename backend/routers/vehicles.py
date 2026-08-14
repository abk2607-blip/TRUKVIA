from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64

from db import db
from models import (
    Company, Customer, Expenses, Driver, Trip, Product, Party, Vehicle,
    MaintenanceLog, Fuel, Payment, Invoice, TeamMember, ROLE_PERMISSIONS,
    InvoiceCreateRequest, InvoiceUpdateRequest, PaymentAdd, FileRef, AuditLog,
    now_utc, new_id,
)
from auth import get_current_user, _has_perm, require_perm
from company import (
    _active_company_id, _get_or_create_default_company,
    _backfill_company_id, _backfill_to_default,
)
from audit import _log_audit, _diff_dict
from services import (
    _compute_trip, _trip_billable, _recompute_invoice,
    _next_invoice_number, _next_invoice_number_for_company,
    _next_lr_number, _in_range, _vehicle_expiry_stats,
    _state_code, _gstin_checksum,
)

router = APIRouter(prefix="/api")

@router.get("/vehicles")
async def list_vehicles(request: Request, user=Depends(get_current_user), active_only: bool = False):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    q = {"user_id": user["user_id"], "company_id": cid}
    if active_only:
        # Iter63 — trip picker filter. Treat missing/legacy is_active as active
        q["$or"] = [{"is_active": True}, {"is_active": {"$exists": False}}]
    docs = await db.vehicles.find(q, {"_id": 0, "user_id": 0}).to_list(20000)
    return [_vehicle_expiry_stats(v) for v in docs]

@router.post("/vehicles")
async def create_vehicle(payload: Vehicle, request: Request, user=Depends(get_current_user)):
    """Iter72 — Root-cause hardening:
    * Trim + upper-case vehicle_number; reject blanks.
    * Deduplicate: if a vehicle with the same vehicle_number already exists in
      this company, return the existing record instead of inserting a duplicate.
    * For supplier vehicles, validate supplier_id belongs to this company AND
      hydrate supplier_name / mobile / gstin / state / contact_person from the
      supplier master so the vehicle row is the source of truth (frontend can't
      accidentally store stale text).
    """
    cid = await _active_company_id(request, user)
    payload.vehicle_number = (payload.vehicle_number or "").upper().strip()
    if not payload.vehicle_number:
        raise HTTPException(status_code=400, detail="vehicle_number is required")

    # Dedup — return existing row (idempotent Quick Add)
    existing = await db.vehicles.find_one(
        {"user_id": user["user_id"], "company_id": cid, "vehicle_number": payload.vehicle_number},
        {"_id": 0, "user_id": 0},
    )
    if existing:
        return _vehicle_expiry_stats(existing)

    # Supplier hydration + validation
    if payload.vehicle_type == "supplier":
        if not (payload.supplier_id or "").strip():
            raise HTTPException(status_code=400, detail="supplier_id is required for supplier vehicles")
        sup = await db.suppliers.find_one(
            {"id": payload.supplier_id, "user_id": user["user_id"], "company_id": cid},
            {"_id": 0},
        )
        if not sup:
            raise HTTPException(status_code=400, detail="Supplier not found in this company")
        # Source of truth: supplier master
        payload.supplier_name = sup.get("name") or ""
        payload.supplier_contact_person = sup.get("contact_person") or ""
        payload.supplier_mobile = sup.get("mobile") or ""
        payload.supplier_state = sup.get("state") or ""
        payload.supplier_gstin = sup.get("gst_in") or sup.get("gstin") or ""
    else:
        # Own/Hired vehicles never carry supplier text.
        payload.supplier_id = ""
        payload.supplier_name = ""
        payload.supplier_contact_person = ""
        payload.supplier_mobile = ""
        payload.supplier_state = ""
        payload.supplier_gstin = ""

    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.vehicles.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return _vehicle_expiry_stats(doc)

@router.put("/vehicles/{vid}")
async def update_vehicle(vid: str, payload: Vehicle, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.id = vid
    payload.vehicle_number = payload.vehicle_number.upper().strip()
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.vehicles.update_one({"id": vid, "user_id": user["user_id"], "company_id": cid}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return _vehicle_expiry_stats(doc)


# ============ Iter64 · Priority 2 — Deactivated Vehicle Audit ============
from pydantic import BaseModel as _BM, Field as _FLD

class VehicleStatusChangeIn(_BM):
    is_active: bool
    reason: str = _FLD(..., min_length=3, max_length=500)
    effective_date: str = _FLD(..., min_length=10, max_length=10)


@router.patch("/vehicles/{vid}/status")
async def change_vehicle_status(vid: str, payload: VehicleStatusChangeIn, request: Request,
                                user=Depends(get_current_user)):
    """Toggle a vehicle Active/Inactive with a mandatory reason + effective date.

    Historical Trips referencing the vehicle are UNTOUCHED — inactive
    vehicles simply become non-selectable for new Trips (filtered by the
    `active_only` flag on GET /api/vehicles).
    """
    cid = await _active_company_id(request, user)
    existing = await db.vehicles.find_one(
        {"id": vid, "user_id": user["user_id"], "company_id": cid})
    if not existing:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    prev_active = existing.get("is_active", True) is not False
    if prev_active == payload.is_active:
        raise HTTPException(status_code=400,
                            detail=f"Vehicle is already {'active' if payload.is_active else 'inactive'}")
    now = now_utc().isoformat()
    audit_doc = {
        "id": new_id("vsa"),
        "user_id": user["user_id"], "company_id": cid,
        "vehicle_id": vid,
        "vehicle_number": existing.get("vehicle_number"),
        "action": "reactivated" if payload.is_active else "deactivated",
        "reason": payload.reason.strip(),
        "effective_date": payload.effective_date,
        "prev_is_active": prev_active,
        "new_is_active": payload.is_active,
        "changed_by": user["user_id"],
        "changed_by_email": user.get("email", ""),
        "changed_at": now,
    }
    await db.vehicle_status_audit_log.insert_one(audit_doc)
    await db.vehicles.update_one(
        {"id": vid, "user_id": user["user_id"], "company_id": cid},
        {"$set": {
            "is_active": payload.is_active,
            "last_status_change_at": now,
            "last_status_change_reason": payload.reason.strip(),
            "last_status_change_effective_date": payload.effective_date,
            "last_status_change_action": audit_doc["action"],
        }},
    )
    await _log_audit(user, "vehicle_status", audit_doc["action"], entity_id=vid,
                     entity_ref=existing.get("vehicle_number", ""),
                     changes={"reason": payload.reason.strip(), "effective_date": payload.effective_date})
    audit_doc.pop("_id", None); audit_doc.pop("user_id", None)
    return audit_doc


@router.get("/vehicles/{vid}/status-audit")
async def list_vehicle_status_audit(vid: str, request: Request, user=Depends(get_current_user)):
    """Return the full deactivate/reactivate history for a vehicle
    (newest first).  Historical entries are IMMUTABLE."""
    cid = await _active_company_id(request, user)
    v = await db.vehicles.find_one(
        {"id": vid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    docs = await (db.vehicle_status_audit_log
                  .find({"user_id": user["user_id"], "company_id": cid, "vehicle_id": vid},
                        {"_id": 0, "user_id": 0})
                  .sort("changed_at", -1)
                  .to_list(500))
    return {
        "vehicle": {"id": v["id"], "vehicle_number": v.get("vehicle_number"),
                     "is_active": v.get("is_active", True) is not False},
        "items": docs,
        "total": len(docs),
    }


@router.delete("/vehicles/{vid}")
async def delete_vehicle(vid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.vehicles.delete_one({"id": vid, "user_id": user["user_id"], "company_id": cid})
    return {"ok": True}

# ============ Iter64 · Priority 3 — Bulk Vehicle Import (CSV + XLSX) ============
_CSV_HEADERS = [
    "vehicle_number", "vehicle_type", "supplier_name", "supplier_id",
    "owner_name", "owner_phone", "make_model", "capacity_tons",
    "remarks", "is_active",
]
_ALIAS = {
    "vehicle no": "vehicle_number", "vehicle #": "vehicle_number", "vehicle_no": "vehicle_number",
    "type": "vehicle_type", "own/supplier": "vehicle_type",
    "supplier": "supplier_name", "supplier name": "supplier_name",
    "owner": "owner_name", "owner name": "owner_name",
    "phone": "owner_phone", "owner phone": "owner_phone",
    "make": "make_model", "model": "make_model", "make/model": "make_model", "make model": "make_model",
    "capacity": "capacity_tons", "capacity tons": "capacity_tons", "capacity (tons)": "capacity_tons",
    "active": "is_active", "status": "is_active",
}


def _parse_upload(file_bytes: bytes, filename: str) -> tuple:
    """Return (headers, rows) as list[str] & list[dict]."""
    import csv as _csv
    fn = (filename or "").lower()
    if fn.endswith(".xlsx") or fn.endswith(".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return [], []
        headers = [str(h or "").strip() for h in rows[0]]
        out = []
        for r in rows[1:]:
            if not any(v is not None and str(v).strip() != "" for v in r):
                continue
            out.append({headers[i]: r[i] for i in range(len(headers)) if i < len(r)})
        return headers, out
    # default: CSV
    text = file_bytes.decode("utf-8-sig", errors="ignore")
    reader = _csv.DictReader(io.StringIO(text))
    return reader.fieldnames or [], list(reader)


def _normalise_row(raw: dict) -> dict:
    """Lowercase headers, apply aliases."""
    out = {}
    for k, v in (raw or {}).items():
        if k is None:
            continue
        key = str(k).strip().lower()
        key = _ALIAS.get(key, key)
        out[key] = v if v is not None else ""
    return out


def _bool_field(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s not in {"", "0", "false", "no", "n", "inactive"}


async def _validate_import_rows(uid: str, cid: str, rows: list) -> tuple:
    """Return (valid_rows_ready_for_insert, errors_list)."""
    # Existing vehicles for duplicate check (case-insensitive, whitespace-stripped)
    existing = await db.vehicles.find(
        {"user_id": uid, "company_id": cid},
        {"_id": 0, "vehicle_number": 1},
    ).to_list(20000)
    existing_nums = {(v.get("vehicle_number") or "").upper().strip() for v in existing}
    # Iter64 · fix — targeted supplier lookup (DB may contain 10k+ suppliers).
    # Collect the specific ids + names referenced in the CSV and query only those.
    wanted_ids: set = set()
    wanted_names_lc: set = set()
    for raw in rows:
        r = _normalise_row(raw)
        sid = str(r.get("supplier_id") or "").strip()
        sname = str(r.get("supplier_name") or "").strip().lower()
        if sid: wanted_ids.add(sid)
        if sname: wanted_names_lc.add(sname)
    sup_by_id: dict = {}
    sup_by_name: dict = {}
    if wanted_ids or wanted_names_lc:
        # Case-insensitive name match using $in on the lowercase set via regex is
        # expensive; simpler: fetch by ids OR by exact-name (any case) and
        # normalise into a lc map on the app side.
        or_clauses = []
        if wanted_ids:
            or_clauses.append({"id": {"$in": list(wanted_ids)}})
        if wanted_names_lc:
            # Do a case-insensitive lookup by building regex-anchor per name.
            import re as _re
            regex_list = [{"name": {"$regex": f"^{_re.escape(n)}$", "$options": "i"}} for n in wanted_names_lc]
            or_clauses.extend(regex_list)
        q = {"user_id": uid, "company_id": cid, "$or": or_clauses}
        async for s in db.suppliers.find(q, {"_id": 0, "id": 1, "name": 1, "mobile": 1, "gst_in": 1, "state": 1}):
            sup_by_id[s["id"]] = s
            sup_by_name[(s.get("name") or "").strip().lower()] = s
    valid = []
    errors = []
    within_batch = set()
    for idx, raw in enumerate(rows, start=2):  # header is row 1
        r = _normalise_row(raw)
        row_errs = []
        vno = str(r.get("vehicle_number") or "").upper().strip()
        if not vno:
            row_errs.append("vehicle_number is required")
        elif vno in existing_nums:
            row_errs.append(f"Duplicate — vehicle {vno} already exists")
        elif vno in within_batch:
            row_errs.append(f"Duplicate in file — {vno} appears more than once")
        vtype = str(r.get("vehicle_type") or "own").strip().lower()
        if vtype not in {"own", "supplier"}:
            row_errs.append("vehicle_type must be 'own' or 'supplier'")
        sup_id = str(r.get("supplier_id") or "").strip()
        sup_name = str(r.get("supplier_name") or "").strip()
        matched_supplier = None
        if vtype == "supplier":
            if sup_id and sup_id in sup_by_id:
                matched_supplier = sup_by_id[sup_id]
            elif sup_name and sup_name.lower() in sup_by_name:
                matched_supplier = sup_by_name[sup_name.lower()]
            if not matched_supplier:
                row_errs.append(f"Supplier '{sup_id or sup_name}' not found — must exist in Supplier master")
        try:
            cap = float(str(r.get("capacity_tons") or 0).replace(",", "") or 0)
        except Exception:
            cap = 0
            row_errs.append("capacity_tons must be numeric")
        row_out = {
            "row_number": idx,
            "vehicle_number": vno,
            "vehicle_type": vtype if vtype in {"own", "supplier"} else "own",
            "is_active": _bool_field(r.get("is_active", True) if str(r.get("is_active", "")).strip() != "" else True),
            "owner_name": str(r.get("owner_name") or "").strip(),
            "owner_phone": str(r.get("owner_phone") or "").strip(),
            "make_model": str(r.get("make_model") or "").strip(),
            "capacity_tons": cap,
            "remarks": str(r.get("remarks") or "").strip(),
            "supplier_id": matched_supplier["id"] if matched_supplier else "",
            "supplier_name": matched_supplier["name"] if matched_supplier else (sup_name if vtype == "supplier" else ""),
            "supplier_mobile": matched_supplier.get("mobile", "") if matched_supplier else "",
            "supplier_gstin": matched_supplier.get("gst_in", "") if matched_supplier else "",
            "supplier_state": matched_supplier.get("state", "") if matched_supplier else "",
        }
        if row_errs:
            errors.append({"row_number": idx, "vehicle_number": vno,
                            "errors": row_errs, "row_data": row_out})
        else:
            within_batch.add(vno)
            valid.append(row_out)
    return valid, errors


@router.post("/vehicles/bulk-import/preview")
async def bulk_import_preview(request: Request, file: UploadFile = File(...),
                              user=Depends(get_current_user)):
    """Parse the uploaded CSV/XLSX and return validation preview.
    No writes happen at this stage — user must call /bulk-import to commit."""
    cid = await _active_company_id(request, user)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")
    try:
        _, rows = _parse_upload(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")
    valid, errors = await _validate_import_rows(user["user_id"], cid, rows)
    return {
        "total_rows": len(rows),
        "valid_count": len(valid),
        "error_count": len(errors),
        "valid": valid[:200],       # cap the preview payload
        "errors": errors[:200],
        "truncated": len(valid) > 200 or len(errors) > 200,
    }


@router.post("/vehicles/bulk-import")
async def bulk_import_commit(request: Request, file: UploadFile = File(...),
                             user=Depends(get_current_user)):
    """Commit the import.  Re-validates server-side — inserts ONLY the rows
    that pass validation.  Returns per-row status."""
    cid = await _active_company_id(request, user)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")
    _, rows = _parse_upload(content, file.filename)
    valid, errors = await _validate_import_rows(user["user_id"], cid, rows)
    inserted = 0
    now = now_utc().isoformat()
    for r in valid:
        veh_id = new_id("veh_")
        doc = {
            "id": veh_id,
            "user_id": user["user_id"], "company_id": cid,
            "vehicle_number": r["vehicle_number"],
            "vehicle_type": r["vehicle_type"],
            "is_active": r["is_active"],
            "owner_name": r["owner_name"],
            "owner_phone": r["owner_phone"],
            "supplier_id": r["supplier_id"],
            "supplier_name": r["supplier_name"],
            "supplier_mobile": r["supplier_mobile"],
            "supplier_gstin": r["supplier_gstin"],
            "supplier_state": r["supplier_state"],
            "supplier_contact_person": "",
            "make_model": r["make_model"],
            "capacity_tons": r["capacity_tons"],
            "rc_expiry": "", "fc_expiry": "", "insurance_expiry": "", "permit_expiry": "", "puc_expiry": "",
            "remarks": r["remarks"], "notes": "",
            "owner_state": "",
            "created_at": now, "created_by": user["user_id"],
        }
        try:
            await db.vehicles.insert_one(doc)
            inserted += 1
        except Exception as e:
            errors.append({"row_number": r["row_number"], "vehicle_number": r["vehicle_number"],
                            "errors": [f"Insert failed: {e}"], "row_data": r})
    await _log_audit(user, "vehicle", "bulk_import",
                     entity_id="bulk", entity_ref=file.filename,
                     changes={"inserted": inserted, "errors": len(errors)})
    return {
        "inserted": inserted,
        "total_rows": len(rows),
        "error_count": len(errors),
        "errors": errors[:500],
    }


@router.get("/vehicles/bulk-import/sample.xlsx")
async def bulk_import_sample_xlsx(user=Depends(get_current_user)):
    """Iter65 · Priority 3 — Downloadable XLSX template for Bulk Vehicle Import."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vehicles"
    headers = [
        "vehicle_number", "vehicle_type", "supplier_id", "supplier_name",
        "owner_name", "owner_phone", "make_model", "capacity_tons",
        "remarks", "is_active",
    ]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1E293B")
    for c_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    # Sample rows
    samples = [
        ["AP16TA1001", "own", "", "", "Ravi Kumar", "9998887777", "Tata LPT 3118", 25, "Own truck", "true"],
        ["AP16TA1002", "supplier", "", "Kondapalli Fleet Owners", "", "", "Ashok Leyland 3720", 32, "Hired", "true"],
        ["AP16TA1003", "own", "", "", "Sita Rao", "", "BharatBenz 2823", 26, "Under maintenance", "false"],
    ]
    for r_idx, row in enumerate(samples, start=2):
        for c_idx, val in enumerate(row, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)
    # Instructions sheet
    ws2 = wb.create_sheet("Instructions")
    inst = [
        ["Column", "Required", "Description"],
        ["vehicle_number", "YES", "e.g. AP16TA1234. Must be unique. Case-insensitive."],
        ["vehicle_type", "YES", "'own' or 'supplier'."],
        ["supplier_id", "For supplier only", "Preferred — links by ID. Get from Supplier master."],
        ["supplier_name", "Fallback", "If supplier_id is empty, name must match an existing supplier."],
        ["owner_name", "Optional", "Any free text."],
        ["owner_phone", "Optional", "For renewal reminders."],
        ["make_model", "Optional", "e.g. Tata LPT 3118"],
        ["capacity_tons", "Optional", "Numeric."],
        ["remarks", "Optional", "Any notes."],
        ["is_active", "Optional", "true / false. Defaults to true if empty."],
    ]
    for r_idx, row in enumerate(inst, start=1):
        for c_idx, val in enumerate(row, start=1):
            cell = ws2.cell(row=r_idx, column=c_idx, value=val)
            if r_idx == 1:
                cell.font = header_font; cell.fill = header_fill
    for w in (ws, ws2):
        for col in w.columns:
            max_len = max(len(str(c.value or "")) for c in col) + 2
            w.column_dimensions[col[0].column_letter].width = min(max_len, 40)
    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="vehicles_sample_import.xlsx"'},
    )


# ==================== Fuel Log ====================






@router.get("/fuel")
async def list_fuel(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    docs = await db.fuel.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)
    return docs

@router.post("/fuel")
async def create_fuel(payload: Fuel, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.vehicle_number = payload.vehicle_number.upper().strip()
    payload.amount = round(payload.litres * payload.rate_per_litre, 2) if payload.amount == 0 else round(payload.amount, 2)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.fuel.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.put("/fuel/{fid}")
async def update_fuel(fid: str, payload: Fuel, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.id = fid
    payload.vehicle_number = payload.vehicle_number.upper().strip()
    payload.amount = round(payload.litres * payload.rate_per_litre, 2) if payload.amount == 0 else round(payload.amount, 2)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.fuel.update_one({"id": fid, "user_id": user["user_id"], "company_id": cid}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.delete("/fuel/{fid}")
async def delete_fuel(fid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.fuel.delete_one({"id": fid, "user_id": user["user_id"], "company_id": cid})
    return {"ok": True}

@router.get("/fuel/summary")
async def fuel_summary(request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    fuels = await db.fuel.find({"user_id": uid, "company_id": cid}, {"_id": 0}).sort("date", 1).to_list(5000)
    by_vehicle: dict = {}
    for f in fuels:
        vno = (f.get("vehicle_number") or "").upper()
        s = by_vehicle.setdefault(vno, {
            "vehicle_number": vno, "entries": 0, "litres": 0.0, "amount": 0.0,
            "first_odo": None, "last_odo": None, "km_run": 0.0, "km_per_litre": 0.0,
        })
        s["entries"] += 1
        s["litres"] += float(f.get("litres", 0))
        s["amount"] += float(f.get("amount", 0))
        odo = float(f.get("odometer", 0) or 0)
        if odo > 0:
            if s["first_odo"] is None:
                s["first_odo"] = odo
            s["last_odo"] = odo
    for s in by_vehicle.values():
        if s["first_odo"] and s["last_odo"] and s["last_odo"] > s["first_odo"]:
            s["km_run"] = round(s["last_odo"] - s["first_odo"], 2)
            # exclude the litres from the first fill because odometer at that fill is starting point
            usable_litres = max(s["litres"], 0.001)
            s["km_per_litre"] = round(s["km_run"] / usable_litres, 2)
        s["litres"] = round(s["litres"], 2)
        s["amount"] = round(s["amount"], 2)
    return {"by_vehicle": sorted(by_vehicle.values(), key=lambda x: -x["amount"])}

# ==================== GSTR-1 Report ====================

# Indian state → GST state code (2-digit)
STATE_CODES = {
    "andhra pradesh": "37", "andaman and nicobar islands": "35", "arunachal pradesh": "12",
    "assam": "18", "bihar": "10", "chandigarh": "04", "chhattisgarh": "22",
    "dadra and nagar haveli and daman and diu": "26", "delhi": "07", "goa": "30",
    "gujarat": "24", "haryana": "06", "himachal pradesh": "02", "jammu and kashmir": "01",
    "jharkhand": "20", "karnataka": "29", "kerala": "32", "ladakh": "38",
    "lakshadweep": "31", "madhya pradesh": "23", "maharashtra": "27", "manipur": "14",
    "meghalaya": "17", "mizoram": "15", "nagaland": "13", "odisha": "21",
    "puducherry": "34", "punjab": "03", "rajasthan": "08", "sikkim": "11",
    "tamil nadu": "33", "telangana": "36", "tripura": "16", "uttar pradesh": "09",
    "uttarakhand": "05", "west bengal": "19",
}
