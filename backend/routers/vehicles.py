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
async def list_vehicles(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    docs = await db.vehicles.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(1000)
    return [_vehicle_expiry_stats(v) for v in docs]

@router.post("/vehicles")
async def create_vehicle(payload: Vehicle, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.vehicle_number = payload.vehicle_number.upper().strip()
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

@router.delete("/vehicles/{vid}")
async def delete_vehicle(vid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.vehicles.delete_one({"id": vid, "user_id": user["user_id"], "company_id": cid})
    return {"ok": True}

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
