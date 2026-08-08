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

@router.get("/parties")
async def list_parties(request: Request, party_type: Optional[str] = None, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    q = {"user_id": user["user_id"], "company_id": cid}
    if party_type:
        q["$or"] = [{"party_type": party_type}, {"party_type": "both"}]
    docs = await db.parties.find(q, {"_id": 0, "user_id": 0}).sort("name", 1).to_list(2000)
    return docs

@router.post("/parties")
async def create_party(payload: Party, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.parties.insert_one(doc)
    return payload.model_dump()

@router.put("/parties/{pid}")
async def update_party(pid: str, payload: Party, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    upd = payload.model_dump()
    upd["id"] = pid
    upd["company_id"] = cid
    upd.pop("created_at", None)
    r = await db.parties.update_one({"id": pid, "user_id": user["user_id"], "company_id": cid}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Party not found")
    return await db.parties.find_one({"id": pid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0})

@router.delete("/parties/{pid}")
async def delete_party(pid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    r = await db.parties.delete_one({"id": pid, "user_id": user["user_id"], "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Party not found")
    return {"ok": True}

# ==================== Halting Report ====================

