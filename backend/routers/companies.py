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

# ==================== Company Settings ====================

@router.get("/companies")
async def list_companies(user=Depends(get_current_user)):
    default = await _get_or_create_default_company(user["user_id"])  # ensures at least one
    docs = await db.companies.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).to_list(50)
    # Backfill legacy transactions to the default company
    await _backfill_company_id(user["user_id"], default["id"])
    return docs

@router.post("/companies")
async def create_company(payload: Company, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    # If first-ever, mark default
    existing = await db.companies.count_documents({"user_id": user["user_id"]})
    if existing == 0:
        doc["is_default"] = True
    await db.companies.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.put("/companies/{cid}")
async def update_company_by_id(cid: str, payload: Company, user=Depends(get_current_user)):
    upd = payload.model_dump()
    upd.pop("id", None)
    r = await db.companies.update_one({"id": cid, "user_id": user["user_id"]}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})

@router.post("/companies/{cid}/set-default")
async def set_default_company(cid: str, user=Depends(get_current_user)):
    r = await db.companies.update_one({"id": cid, "user_id": user["user_id"]}, {"$set": {"is_default": True}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    await db.companies.update_many({"user_id": user["user_id"], "id": {"$ne": cid}}, {"$set": {"is_default": False}})
    return {"ok": True}

@router.delete("/companies/{cid}")
async def delete_company_by_id(cid: str, user=Depends(get_current_user)):
    count = await db.companies.count_documents({"user_id": user["user_id"]})
    if count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only company")
    r = await db.companies.delete_one({"id": cid, "user_id": user["user_id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"ok": True}

# ==================== Legacy single-company aliases (active company) ====================

@router.get("/company")
async def get_company(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not doc:
        return Company().model_dump()
    return doc

@router.put("/company")
async def save_company(payload: Company, request: Request, user=Depends(get_current_user)):
    """Save changes to the ACTIVE company (backward-compatible with single-company clients)."""
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["id"] = cid
    doc["user_id"] = user["user_id"]
    await db.companies.update_one(
        {"id": cid, "user_id": user["user_id"]},
        {"$set": doc},
        upsert=True,
    )
    return doc


@router.post("/company/logo")
async def upload_logo(request: Request, file: UploadFile = File(...), user=Depends(get_current_user)):
    import base64
    cid = await _active_company_id(request, user)
    content = await file.read()
    if len(content) > 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo too large (max 1MB)")
    mime = file.content_type or "image/png"
    if not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="Not an image")
    data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
    await db.companies.update_one(
        {"id": cid, "user_id": user["user_id"]},
        {"$set": {"logo": data_url}},
    )
    return {"logo": data_url}

@router.delete("/company/logo")
async def delete_logo(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.companies.update_one(
        {"id": cid, "user_id": user["user_id"]},
        {"$set": {"logo": ""}},
    )
    return {"ok": True}

# ==================== Reports ====================
