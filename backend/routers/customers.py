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

# ==================== Customers ====================

@router.get("/customers")
async def list_customers(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    docs = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(1000)
    return docs

@router.post("/customers")
async def create_customer(payload: Customer, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.customers.insert_one(doc)
    doc.pop("user_id", None)
    doc.pop("_id", None)
    return doc

@router.put("/customers/{cid}")
async def update_customer(cid: str, payload: Customer, request: Request, user=Depends(get_current_user)):
    company_id = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["id"] = cid
    doc["user_id"] = user["user_id"]
    doc["company_id"] = company_id
    await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"], "company_id": company_id},
        {"$set": doc},
    )
    doc.pop("user_id", None)
    return doc

@router.delete("/customers/{cid}")
async def delete_customer(cid: str, request: Request, user=Depends(get_current_user)):
    company_id = await _active_company_id(request, user)
    await db.customers.delete_one({"id": cid, "user_id": user["user_id"], "company_id": company_id})
    return {"ok": True}

