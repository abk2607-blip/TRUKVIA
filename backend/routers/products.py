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

@router.get("/products")
async def list_products(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    docs = await db.products.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(None)
    return docs

@router.post("/products")
async def create_product(payload: Product, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.products.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.put("/products/{pid}")
async def update_product(pid: str, payload: Product, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.id = pid
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.products.update_one({"id": pid, "user_id": user["user_id"], "company_id": cid}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.delete("/products/{pid}")
async def delete_product(pid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.products.delete_one({"id": pid, "user_id": user["user_id"], "company_id": cid})
    return {"ok": True}

# ==================== Company Logo ====================

