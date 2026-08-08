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

@router.get("/team")
async def list_team(user=Depends(get_current_user)):
    if user.get("is_staff"):
        raise HTTPException(status_code=403, detail="Only owner can view team")
    docs = await db.team_members.find({"owner_user_id": user["user_id"]}, {"_id": 0}).to_list(200)
    return docs

@router.post("/team")
async def add_team_member(payload: TeamMember, user=Depends(get_current_user)):
    if user.get("is_staff"):
        raise HTTPException(status_code=403, detail="Only owner can add team")
    payload.owner_user_id = user["user_id"]
    payload.email = payload.email.strip().lower()
    if payload.role == "owner":
        payload.role = "accountant"  # never elevate to owner via API
    existing = await db.team_members.find_one({"owner_user_id": user["user_id"], "email": payload.email})
    if existing:
        raise HTTPException(status_code=400, detail="Member already exists")
    doc = payload.model_dump()
    await db.team_members.insert_one(doc)
    doc.pop("_id", None)
    await _log_audit(user, "team", "create", entity_id=doc["id"], entity_ref=doc["email"])
    return doc

@router.put("/team/{tid}")
async def update_team_member(tid: str, payload: TeamMember, user=Depends(get_current_user)):
    if user.get("is_staff"):
        raise HTTPException(status_code=403, detail="Only owner")
    existing = await db.team_members.find_one({"id": tid, "owner_user_id": user["user_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    payload.id = tid
    payload.owner_user_id = user["user_id"]
    if payload.role == "owner":
        payload.role = "accountant"
    doc = payload.model_dump()
    await db.team_members.update_one({"id": tid, "owner_user_id": user["user_id"]}, {"$set": doc})
    await _log_audit(user, "team", "update", entity_id=tid, entity_ref=doc["email"])
    return doc

@router.delete("/team/{tid}")
async def delete_team_member(tid: str, user=Depends(get_current_user)):
    if user.get("is_staff"):
        raise HTTPException(status_code=403, detail="Only owner")
    doc = await db.team_members.find_one({"id": tid, "owner_user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.team_members.delete_one({"id": tid, "owner_user_id": user["user_id"]})
    await _log_audit(user, "team", "delete", entity_id=tid, entity_ref=doc.get("email", ""), reason="removed")
    return {"ok": True}

@router.get("/team/me")
async def team_me(user=Depends(get_current_user)):
    return {
        "email": user.get("email"),
        "name": user.get("name"),
        "role": user.get("effective_role"),
        "is_staff": user.get("is_staff", False),
        "permissions": sorted(list(ROLE_PERMISSIONS.get(user.get("effective_role", "owner"), set()))),
    }

# ==================== Supplier P&L Report ====================

