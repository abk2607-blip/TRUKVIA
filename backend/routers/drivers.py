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

@router.get("/drivers")
async def list_drivers(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    drivers = await db.drivers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(1000)
    # Attach stats (trips scoped to same company)
    trips = await db.trips.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0}).to_list(5000)
    stats = {}
    for t in trips:
        did = t.get("driver_id")
        if not did:
            continue
        s = stats.setdefault(did, {"trips": 0, "tons": 0.0, "batta": 0.0, "freight": 0.0})
        s["trips"] += 1
        s["tons"] += float(t.get("tons", 0))
        s["batta"] += float((t.get("expenses") or {}).get("batta", 0))
        s["freight"] += float(t.get("freight_amount", 0))
    for d in drivers:
        s = stats.get(d["id"], {"trips": 0, "tons": 0, "batta": 0, "freight": 0})
        d["stats"] = {k: round(v, 2) for k, v in s.items()}
    return drivers

@router.post("/drivers")
async def create_driver(payload: Driver, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.drivers.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.put("/drivers/{did}")
async def update_driver(did: str, payload: Driver, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.id = did
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.drivers.update_one({"id": did, "user_id": user["user_id"], "company_id": cid}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.delete("/drivers/{did}")
async def delete_driver(did: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.drivers.delete_one({"id": did, "user_id": user["user_id"], "company_id": cid})
    return {"ok": True}

# ==================== Trip Bulk Import ====================
