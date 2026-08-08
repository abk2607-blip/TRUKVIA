from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64

import logging
from db import db
logger = logging.getLogger(__name__)
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

from storage_client import put_object, get_object, mime_for, APP_NAME


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: str = "general",
    linked_type: str = "",
    linked_id: str = "",
    user=Depends(get_current_user),
):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    ext = (file.filename or "bin").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    path = f"{APP_NAME}/uploads/{user['user_id']}/{uuid.uuid4().hex}.{ext}"
    ctype = file.content_type or mime_for(file.filename or "")
    try:
        result = put_object(path, data, ctype)
    except Exception as e:
        logger.exception("storage upload failed")
        raise HTTPException(status_code=502, detail=f"Storage upload failed: {e}")
    ref = FileRef(
        storage_path=result["path"],
        original_filename=file.filename or "unknown",
        content_type=ctype,
        size=result.get("size", len(data)),
        category=category,
        linked_type=linked_type,
        linked_id=linked_id,
    )
    doc = ref.model_dump()
    doc["user_id"] = user["user_id"]
    await db.files.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.get("/files/usage")
async def file_usage(user=Depends(get_current_user)):
    docs = await db.files.find({"user_id": user["user_id"], "is_deleted": False}, {"_id": 0, "size": 1, "category": 1}).to_list(5000)
    total = sum(int(d.get("size", 0) or 0) for d in docs)
    by_cat = {}
    for d in docs:
        c = d.get("category", "general")
        by_cat[c] = by_cat.get(c, 0) + int(d.get("size", 0) or 0)
    limit = 500 * 1024 * 1024  # 500MB soft cap
    return {
        "total_bytes": total,
        "limit_bytes": limit,
        "pct": round(min(100, total / limit * 100), 2) if limit else 0,
        "file_count": len(docs),
        "by_category": by_cat,
    }

@router.post("/files/bulk-upload")
async def bulk_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    category: str = "general",
    user=Depends(get_current_user),
):
    """Upload multiple files. Auto-tag vehicle_number and date from filename pattern
    like 'AP16TA1234_2026-02-05_anything.jpg' or 'AP16TA1234-2026-02-05.png'."""
    cid = await _active_company_id(request, user)
    results = []
    veh_re = re.compile(r"([A-Z]{2}[-\s]?\d{1,2}[-\s]?[A-Z]{1,3}[-\s]?\d{1,4})", re.IGNORECASE)
    date_re = re.compile(r"(20\d{2}[-_/.](?:0[1-9]|1[0-2])[-_/.](?:0[1-9]|[12]\d|3[01]))")

    for f in files:
        try:
            data = await f.read()
            if len(data) > 10 * 1024 * 1024:
                results.append({"filename": f.filename, "ok": False, "error": "> 10MB"})
                continue
            fname = f.filename or ""
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "bin"
            path = f"{APP_NAME}/uploads/{user['user_id']}/{uuid.uuid4().hex}.{ext}"
            ctype = f.content_type or mime_for(fname)
            result = put_object(path, data, ctype)

            # Auto-tag
            veh_match = veh_re.search(fname.upper())
            dt_match = date_re.search(fname)
            linked_id = ""
            linked_type = ""
            tags = {}
            if veh_match:
                vno = re.sub(r"[-\s]", "", veh_match.group(1)).upper()
                v = await db.vehicles.find_one({"vehicle_number": vno, "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
                if v:
                    linked_type = "vehicle"; linked_id = v["id"]
                tags["vehicle_number"] = vno
            if dt_match:
                tags["date"] = dt_match.group(1).replace("_", "-").replace(".", "-").replace("/", "-")

            ref_doc = FileRef(
                storage_path=result["path"],
                original_filename=fname,
                content_type=ctype,
                size=result.get("size", len(data)),
                category=category,
                linked_type=linked_type,
                linked_id=linked_id,
            ).model_dump()
            ref_doc["user_id"] = user["user_id"]
            ref_doc["tags"] = tags
            await db.files.insert_one(ref_doc)
            results.append({"filename": fname, "ok": True, "id": ref_doc["id"], "tags": tags, "linked_id": linked_id})
        except Exception as e:
            results.append({"filename": f.filename, "ok": False, "error": str(e)})
    return {"results": results, "uploaded": sum(1 for r in results if r["ok"]), "total": len(results)}

@router.get("/files")
async def list_files(
    category: Optional[str] = None,
    linked_type: Optional[str] = None,
    linked_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    q = {"user_id": user["user_id"], "is_deleted": False}
    if category: q["category"] = category
    if linked_type: q["linked_type"] = linked_type
    if linked_id: q["linked_id"] = linked_id
    docs = await db.files.find(q, {"_id": 0, "user_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@router.get("/files/{fid}/download")
async def download_file(fid: str, user=Depends(get_current_user)):
    ref = await db.files.find_one({"id": fid, "user_id": user["user_id"], "is_deleted": False}, {"_id": 0})
    if not ref:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        data, ctype = get_object(ref["storage_path"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Storage fetch failed: {e}")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=ref.get("content_type") or ctype,
        headers={"Content-Disposition": f'inline; filename="{ref["original_filename"]}"'},
    )

@router.delete("/files/{fid}")
async def delete_file(fid: str, user=Depends(get_current_user)):
    # Soft delete (storage has no delete API)
    r = await db.files.update_one(
        {"id": fid, "user_id": user["user_id"]},
        {"$set": {"is_deleted": True}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# Public retrieval — used by WhatsApp share links so recipients (without a login) can download the LR/Invoice PDF.
# Only exposes objects under the "lr_shares/" or "public/" prefix; any other path is 404.
@router.get("/files/public/{obj_path:path}")
async def public_file(obj_path: str):
    if not (obj_path.startswith("lr_shares/") or obj_path.startswith("public/")):
        raise HTTPException(status_code=404, detail="Not found")
    try:
        data, ctype = get_object(obj_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    fname = obj_path.rsplit("/", 1)[-1]
    return StreamingResponse(
        io.BytesIO(data), media_type=ctype or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{fname}"', "Cache-Control": "public, max-age=600"},
    )

