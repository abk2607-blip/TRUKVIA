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
