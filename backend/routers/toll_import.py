"""Iter148 P0 · FASTag Toll Import endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Request, Body

from db import db
from auth import get_current_user
from company import _active_company_id
from services_toll_import import (
    parse_fastag, build_preview, commit_rows, MAX_ROWS_P0,
)

router = APIRouter(prefix="/api")
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@router.post("/toll-import/preview")
async def toll_import_preview(request: Request,
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
    vendor, rows = parse_fastag(blob)
    if vendor is None:
        raise HTTPException(status_code=400,
            detail="Unrecognised file. Expected an IDFC or LIVQ FASTag statement "
                   "(sheet 'Account_Summary' with the standard header row).")
    if not rows:
        return {"vendor": vendor, "total_rows": 0,
                "counts": {"ready": 0, "vehicle_mapping_required": 0,
                           "possible_duplicate": 0, "exact_duplicate": 0, "error": 0},
                "rows": [],
                "notice": "No eligible Toll (Debit) rows found in this statement."}
    if len(rows) > MAX_ROWS_P0:
        raise HTTPException(status_code=413,
            detail=f"File contains {len(rows)} rows (> P0 limit of {MAX_ROWS_P0}). Please split.")
    return await build_preview(uid, cid, vendor, rows)


@router.post("/toll-import/commit")
async def toll_import_commit(request: Request, body: dict = Body(...),
                             user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    vendor = str(body.get("vendor") or "").strip().lower()
    if vendor not in ("idfc", "livq"):
        raise HTTPException(status_code=400, detail="vendor must be 'idfc' or 'livq'")
    rows = body.get("rows") or []
    return await commit_rows(uid, cid, vendor, rows)


# ── Iter148 UAT diagnostics — read-only reconciliation helpers ─────────
@router.get("/toll-import/lookup")
async def toll_import_lookup(request: Request,
                             txn_ref: str = "", vendor: str = "",
                             user=Depends(get_current_user)):
    """Look up a canonical Toll Expense by its original source Transaction
    ID. Returns 200+row when found, 404 when the txn was never committed.
    Used for UAT reconciliation ("does the ₹570 row exist in DB?")."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    if not txn_ref:
        raise HTTPException(status_code=400, detail="txn_ref query param is required")
    q = {"user_id": uid, "company_id": cid,
         "source_type": "fastag_import", "source_txn_ref": txn_ref}
    if vendor:
        q["source"] = vendor.lower()
    doc = await db.expenses.find_one(q, {"_id": 0, "user_id": 0})
    if not doc:
        # Search by source_key too in case caller sent the full key
        doc = await db.expenses.find_one(
            {"user_id": uid, "company_id": cid, "source_key": txn_ref},
            {"_id": 0, "user_id": 0},
        )
    if not doc:
        raise HTTPException(status_code=404,
            detail=f"No canonical Expense with source_txn_ref={txn_ref!r}. "
                   f"The row was never committed — check the source file and re-import.")
    return doc


@router.post("/toll-import/reconcile")
async def toll_import_reconcile(request: Request,
                                file: UploadFile = File(...),
                                user=Depends(get_current_user)):
    """Upload a FASTag statement and get a per-row reconciliation report:
    for every eligible Debit row, show whether it is present in the
    canonical Expense table or missing (and why). Read-only; no writes."""
    from services_toll_import import parse_fastag, make_source_key
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty upload")
    vendor, rows = parse_fastag(blob)
    if vendor is None:
        raise HTTPException(status_code=400, detail="Unrecognised FASTag file")
    out = []
    matched = missing = errored = 0
    for r in rows:
        row_report = {"row_index": r["row_index"], "date": r["date"],
                      "amount": r["amount"],
                      "truck": r["source_vehicle_raw"],
                      "source_txn_ref": r["source_txn_ref"],
                      "plaza": r["plaza"]}
        if r.get("error"):
            row_report.update({"status": "error", "reason": r["error"]})
            out.append(row_report); errored += 1; continue
        skey = make_source_key(vendor, cid, r["source_txn_ref"])
        doc = await db.expenses.find_one(
            {"user_id": uid, "company_id": cid, "source_key": skey},
            {"_id": 0, "id": 1, "amount": 1, "is_deleted": 1, "is_reversed": 1,
             "vehicle_number": 1},
        )
        if doc:
            state = ("cancelled" if doc.get("is_deleted")
                     else "reversed" if doc.get("is_reversed") else "active")
            row_report.update({"status": "found", "expense_id": doc["id"],
                               "expense_state": state,
                               "expense_amount": float(doc.get("amount") or 0),
                               "expense_vehicle_number": doc.get("vehicle_number", "")})
            matched += 1
        else:
            row_report.update({"status": "missing",
                "reason": "No canonical Expense with this source_key. Row was likely "
                          "skipped in the preview (Vehicle Mapping Required, "
                          "Possible Duplicate not overridden, or the operator "
                          "did not click Confirm & Import for this bucket)."})
            missing += 1
        out.append(row_report)
    src_total = sum(r["amount"] for r in rows if not r.get("error"))
    imported_total = sum(x.get("expense_amount", 0) for x in out if x["status"] == "found")
    return {
        "vendor": vendor, "source_row_count": len(rows),
        "matched": matched, "missing": missing, "errored": errored,
        "source_debit_total": round(src_total, 2),
        "imported_total": round(imported_total, 2),
        "delta": round(src_total - imported_total, 2),
        "rows": out,
    }
