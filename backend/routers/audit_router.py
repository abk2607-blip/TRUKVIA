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

@router.get("/audit-logs")
async def list_audit_logs(
    module: Optional[str] = None,
    action: Optional[str] = None,
    entity_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 200,
    user=Depends(get_current_user),
):
    q: dict = {"user_id": user["user_id"]}
    if module: q["module"] = module
    if action: q["action"] = action
    if entity_id: q["entity_id"] = entity_id
    if start or end:
        rng: dict = {}
        if start: rng["$gte"] = start
        if end: rng["$lte"] = end + "T23:59:59"
        q["timestamp"] = rng
    docs = await db.audit_logs.find(q, {"_id": 0, "user_id": 0}).sort("timestamp", -1).to_list(min(int(limit), 500))
    return docs

# ==================== Team Members ====================

