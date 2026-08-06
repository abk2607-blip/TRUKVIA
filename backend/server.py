"""Bitumen Transport Accounting - Backend API
Emergent Google OAuth + Trip/Invoice management + Server-side PDF.
"""
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import uuid
import logging
import re
import requests
import secrets
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta

import pandas as pd

from pdf_generator import build_invoice_pdf, build_ledger_pdf
from storage_client import init_storage, put_object, get_object, mime_for, APP_NAME

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Bitumen Transport Accounting")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== Utility ====================

def now_utc():
    return datetime.now(timezone.utc)

def new_id(prefix: str = ""):
    return f"{prefix}{uuid.uuid4().hex[:16]}"

# ==================== Models ====================

class Company(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: new_id("co_"))
    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    gstin: str = ""
    pan: str = ""
    state: str = ""
    pincode: str = ""
    bank_name: str = ""
    account_number: str = ""
    ifsc: str = ""
    branch: str = ""
    hsn_sac: str = "996791"
    invoice_prefix: str = "INV"
    next_invoice_number: int = 1
    lr_prefix: str = "LR"
    next_lr_number: int = 1
    logo: str = ""  # data URL (base64)
    is_default: bool = False

class Customer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cust_"))
    name: str
    address: str = ""
    phone: str = ""
    gstin: str = ""
    pan: str = ""
    state: str = ""
    pincode: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Expenses(BaseModel):
    diesel: float = 0.0
    toll: float = 0.0
    batta: float = 0.0
    repair: float = 0.0
    other: float = 0.0
    # Additional expenses / recoveries
    firewood: float = 0.0
    other_desc: str = ""
    diesel_from_customer_qty: float = 0.0
    diesel_from_customer_rate: float = 0.0
    diesel_from_customer_amount: float = 0.0   # recovery (reduces our cost)
    shortage_qty: float = 0.0
    shortage_amount: float = 0.0               # deduction from freight
    cash_advance_received: float = 0.0         # settlement only

class Driver(BaseModel):
    id: str = Field(default_factory=lambda: new_id("drv_"))
    name: str
    phone: str = ""
    license_number: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Trip(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trip_"))
    company_id: str = ""
    customer_id: str
    date: str  # ISO date
    vehicle_number: str
    vehicle_id: Optional[str] = None
    vehicle_type: Literal["own", "supplier"] = "own"
    # ---- Loading / Unloading (Feb 2026) ----
    loading_date: str = ""       # ISO date; if empty, `date` is used
    unloading_date: str = ""     # ISO date
    loaded_qty: float = 0.0      # MT loaded at origin
    unloaded_qty: float = 0.0    # MT received at destination
    excess_qty: float = 0.0      # auto: max(unloaded - loaded, 0)
    shortage_qty: float = 0.0    # auto: max(loaded - unloaded, 0)
    product_rate_per_mt: float = 0.0   # optional per-MT rate for excess/shortage valuation
    shortage_amount: float = 0.0       # auto: rate * shortage_qty (editable via override)
    excess_amount: float = 0.0         # auto: rate * excess_qty (editable via override)
    shortage_amount_override: bool = False   # true = user manually set shortage_amount
    excess_amount_override: bool = False
    # ---- Halting / Waiting charges (Feb 2026) ----
    total_halting_days: int = 0        # auto: (unloading_date - loading_date) days
    grace_days: int = 4                # user-editable (contractual)
    chargeable_halting_days: int = 0   # auto: max(total_halting_days - grace_days, 0), user-editable
    halting_rate_per_day: float = 0.0  # user-editable
    halting_amount: float = 0.0        # auto: chargeable * rate, user-editable
    halting_amount_override: bool = False
    # ---- Supplier fields ----
    supplier_name: str = ""
    supplier_freight: float = 0.0
    # Supplier freight detailed calculation (mirrors customer billing)
    supplier_freight_mode: Literal["per_ton", "fixed"] = "per_ton"
    supplier_rate_per_ton: float = 0.0
    supplier_fixed_amount: float = 0.0
    supplier_round_trip_kms: float = 0.0
    supplier_rate_per_km_per_ton: float = 0.0
    supplier_loading_point: str = ""
    supplier_unloading_point: str = ""
    supplier_material: str = ""
    supplier_quantity: float = 0.0
    supplier_advance: float = 0.0
    supplier_other_recoveries: float = 0.0
    supplier_net_payable: float = 0.0
    driver_id: Optional[str] = None
    driver_name: str = ""
    driver_mobile: str = ""
    product_id: Optional[str] = None
    load_details: str = "Bitumen VG 40"
    hsn_sac: str = ""
    consignor_id: Optional[str] = None
    consignor_name: str = ""
    consignee_id: Optional[str] = None
    consignee_name: str = ""
    tons: float
    from_location: str = ""
    to_location: str = ""
    from_pincode: str = ""
    to_pincode: str = ""
    freight_mode: Literal["per_ton", "fixed"]
    rate_per_ton: float = 0.0
    fixed_amount: float = 0.0
    round_trip_kms: float = 0.0
    rate_per_km_per_ton: float = 0.0
    freight_amount: float = 0.0
    expenses: Expenses = Field(default_factory=Expenses)
    total_expense: float = 0.0
    profit: float = 0.0
    net_settlement: float = 0.0
    invoice_id: Optional[str] = None
    status: Literal["pending", "invoiced"] = "pending"
    notes: str = ""
    # LR / invoice reference fields
    lr_number: str = ""
    lr_time: str = ""
    consignor_name: str = ""
    consignor_address: str = ""
    consignee_site_location: str = ""
    consignee_site_contact: str = ""
    external_invoice_no: str = ""
    customer_invoice_no: str = ""
    customer_purchased_at: str = ""
    invoice_value: float = 0.0
    waybill_no: str = ""
    gross_weight: float = 0.0
    tare_weight: float = 0.0
    seal_numbers: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Product(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prd_"))
    name: str
    hsn_sac: str = "996791"
    default_rate: float = 0.0
    unit: str = "MT"
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Party(BaseModel):
    """Consignor / Consignee address book (both types share one shape).
    Used to select loading (consignor) and unloading (consignee) parties on a trip
    when they differ from the billed customer."""
    id: str = Field(default_factory=lambda: new_id("party_"))
    party_type: Literal["consignor", "consignee", "both"] = "both"
    name: str
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    gstin: str = ""
    pan: str = ""
    address: str = ""
    state: str = ""
    pincode: str = ""
    linked_customer_id: Optional[str] = None  # optional linkage to a customer
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Vehicle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("veh_"))
    vehicle_number: str
    vehicle_type: Literal["own", "supplier"] = "own"
    owner_name: str = ""
    owner_phone: str = ""
    supplier_name: str = ""
    supplier_contact_person: str = ""
    supplier_mobile: str = ""
    supplier_state: str = ""
    supplier_gstin: str = ""
    make_model: str = ""
    capacity_tons: float = 0.0
    rc_expiry: str = ""
    fc_expiry: str = ""
    insurance_expiry: str = ""
    permit_expiry: str = ""
    puc_expiry: str = ""
    remarks: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class MaintenanceLog(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mnt_"))
    vehicle_id: Optional[str] = None
    vehicle_number: str
    date: str
    type: Literal["Tyre", "Service", "Repair", "Other"] = "Service"
    description: str = ""
    cost: float = 0.0
    odometer: float = 0.0
    next_due_date: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Fuel(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fuel_"))
    date: str  # ISO date
    vehicle_id: Optional[str] = None
    vehicle_number: str
    litres: float
    rate_per_litre: float
    amount: float = 0.0
    odometer: float = 0.0
    station_name: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Payment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pay_"))
    amount: float
    date: str
    mode: str = "Cash"
    note: str = ""

class Invoice(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inv_"))
    company_id: str = ""
    invoice_number: str
    customer_id: str
    invoice_date: str
    trip_ids: List[str]
    subtotal: float
    hsn_sac: str = "996791"  # 996511 or 996791 — chosen at invoice creation
    freight_total: float = 0.0
    halting_total: float = 0.0
    excess_total: float = 0.0
    shortage_total: float = 0.0
    gst_type: Literal["cgst_sgst", "igst"] = "cgst_sgst"
    cgst_rate: float = 2.5
    sgst_rate: float = 2.5
    igst_rate: float = 5.0
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    total_tax: float = 0.0
    gross_total: float = 0.0
    round_off: float = 0.0
    total_amount: float = 0.0
    rcm: bool = True  # Reverse charge — tax not collected
    payments: List[Payment] = []
    amount_paid: float = 0.0
    balance_due: float = 0.0
    share_token: Optional[str] = None
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

# Simple RBAC: role -> permissions
ROLE_PERMISSIONS = {
    "owner": {"edit_trip", "delete_trip", "edit_invoice", "delete_invoice", "edit_master", "delete_master", "manage_users"},
    "accountant": {"edit_trip", "edit_invoice", "edit_master"},
    "viewer": set(),
}

class TeamMember(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tm_"))
    owner_user_id: str          # the owner's user_id
    email: str
    name: str = ""
    role: Literal["owner", "accountant", "viewer"] = "accountant"
    active: bool = True
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

def _has_perm(user: dict, perm: str) -> bool:
    role = user.get("effective_role") or "owner"
    return perm in ROLE_PERMISSIONS.get(role, set())

def require_perm(perm: str):
    async def _check(user=Depends(get_current_user)):
        if not _has_perm(user, perm):
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
        return user
    return _check

# ==================== Auth ====================

async def get_current_user(request: Request):
    """Read session_token from cookie or Authorization header."""
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    exp = session.get("expires_at")
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")

    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # RBAC: if this user's email is registered as a team member of another owner, scope data to that owner
    tm = await db.team_members.find_one({"email": user["email"], "active": True}, {"_id": 0})
    if tm and tm.get("owner_user_id") and tm["owner_user_id"] != user["user_id"]:
        user = dict(user)
        user["user_id"] = tm["owner_user_id"]  # data scope = owner
        user["effective_role"] = tm.get("role", "accountant")
        user["is_staff"] = True
    else:
        user = dict(user)
        user["effective_role"] = "owner"
        user["is_staff"] = False
    return user

@api.post("/auth/session")
async def create_session(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    # Exchange session_id with Emergent Auth
    r = requests.get(
        "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
        headers={"X-Session-ID": session_id},
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = r.json()

    email = data["email"]
    # Find or create user
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": data.get("name", ""), "picture": data.get("picture", "")}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": data.get("name", ""),
            "picture": data.get("picture", ""),
            "created_at": now_utc().isoformat(),
        })

    session_token = data["session_token"]
    expires_at = now_utc() + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": now_utc().isoformat(),
    })

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    return {
        "user_id": user_id,
        "email": email,
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
        "session_token": session_token,  # fallback for browsers blocking third-party cookies
    }

@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
    }

@api.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

# ==================== Multi-Company Support ====================
# Users can maintain multiple company profiles under one login.
# Masters (customers, vehicles, drivers, products, parties) are shared.
# Transactions (trips, invoices, fuel logs) are scoped to the active company.

async def _get_or_create_default_company(user_id: str) -> dict:
    """Ensure at least one company exists for the user. Migrate legacy (no id) docs."""
    docs = await db.companies.find({"user_id": user_id}, {"_id": 0}).to_list(50)
    # Backfill missing id / is_default on legacy docs
    for d in docs:
        if not d.get("id"):
            new = new_id("co_")
            await db.companies.update_one({"user_id": user_id, "name": d.get("name", "")}, {"$set": {"id": new}})
            d["id"] = new
    if not docs:
        # Create an empty default
        c = Company(name="My Company", is_default=True).model_dump()
        c["user_id"] = user_id
        await db.companies.insert_one(c)
        return c
    # Ensure exactly one is_default
    if not any(d.get("is_default") for d in docs):
        first_id = docs[0]["id"]
        await db.companies.update_one({"user_id": user_id, "id": first_id}, {"$set": {"is_default": True}})
        docs[0]["is_default"] = True
    return next((d for d in docs if d.get("is_default")), docs[0])

async def _active_company_id(request: Request, user: dict) -> str:
    """Resolve which company the current request is scoped to.
    Priority: X-Company-Id header → user's default company → first company."""
    override = request.headers.get("x-company-id") or request.headers.get("X-Company-Id")
    if override:
        # Verify the company belongs to this user
        doc = await db.companies.find_one({"id": override, "user_id": user["user_id"]}, {"id": 1, "_id": 0})
        if doc:
            return override
    default = await _get_or_create_default_company(user["user_id"])
    return default["id"]

async def _backfill_company_id(user_id: str, company_id: str):
    """Assign the given company_id to any legacy trip/invoice/file lacking one for this user."""
    for coll in ("trips", "invoices", "files", "audit_logs"):
        await db[coll].update_many({"user_id": user_id, "$or": [{"company_id": {"$exists": False}}, {"company_id": ""}]}, {"$set": {"company_id": company_id}})

# ==================== Company Settings ====================

@api.get("/companies")
async def list_companies(user=Depends(get_current_user)):
    default = await _get_or_create_default_company(user["user_id"])  # ensures at least one
    docs = await db.companies.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).to_list(50)
    # Backfill legacy transactions to the default company
    await _backfill_company_id(user["user_id"], default["id"])
    return docs

@api.post("/companies")
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

@api.put("/companies/{cid}")
async def update_company_by_id(cid: str, payload: Company, user=Depends(get_current_user)):
    upd = payload.model_dump()
    upd.pop("id", None)
    r = await db.companies.update_one({"id": cid, "user_id": user["user_id"]}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})

@api.post("/companies/{cid}/set-default")
async def set_default_company(cid: str, user=Depends(get_current_user)):
    r = await db.companies.update_one({"id": cid, "user_id": user["user_id"]}, {"$set": {"is_default": True}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    await db.companies.update_many({"user_id": user["user_id"], "id": {"$ne": cid}}, {"$set": {"is_default": False}})
    return {"ok": True}

@api.delete("/companies/{cid}")
async def delete_company_by_id(cid: str, user=Depends(get_current_user)):
    count = await db.companies.count_documents({"user_id": user["user_id"]})
    if count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only company")
    r = await db.companies.delete_one({"id": cid, "user_id": user["user_id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"ok": True}

# ==================== Legacy single-company aliases (active company) ====================

@api.get("/company")
async def get_company(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not doc:
        return Company().model_dump()
    return doc

@api.put("/company")
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

# ==================== Customers ====================

@api.get("/customers")
async def list_customers(user=Depends(get_current_user)):
    docs = await db.customers.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).to_list(1000)
    return docs

@api.post("/customers")
async def create_customer(payload: Customer, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.customers.insert_one(doc)
    doc.pop("user_id", None)
    doc.pop("_id", None)
    return doc

@api.put("/customers/{cid}")
async def update_customer(cid: str, payload: Customer, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["id"] = cid
    doc["user_id"] = user["user_id"]
    await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"]},
        {"$set": doc},
    )
    doc.pop("user_id", None)
    return doc

@api.delete("/customers/{cid}")
async def delete_customer(cid: str, user=Depends(get_current_user)):
    await db.customers.delete_one({"id": cid, "user_id": user["user_id"]})
    return {"ok": True}

# ==================== Trips ====================

class AuditLog(BaseModel):
    id: str = Field(default_factory=lambda: new_id("audit_"))
    timestamp: str = Field(default_factory=lambda: now_utc().isoformat())
    module: str                  # trip | invoice | customer | vehicle | driver | product | company | payment
    action: str                  # create | update | delete
    entity_id: str = ""
    entity_ref: str = ""         # user-friendly name (invoice_number, vehicle_number, etc.)
    reason: str = ""
    changes: dict = Field(default_factory=dict)   # {field: {old, new}}
    user_email: str = ""
    user_name: str = ""

async def _log_audit(user: dict, module: str, action: str, entity_id: str = "", entity_ref: str = "", reason: str = "", changes: Optional[dict] = None):
    doc = AuditLog(
        module=module, action=action,
        entity_id=entity_id, entity_ref=entity_ref,
        reason=reason, changes=changes or {},
        user_email=user.get("email", ""), user_name=user.get("name", ""),
    ).model_dump()
    doc["user_id"] = user["user_id"]
    try:
        await db.audit_logs.insert_one(doc)
    except Exception as e:
        logger.warning(f"audit log failed: {e}")

def _diff_dict(old: dict, new: dict, keys: Optional[list] = None) -> dict:
    """Return {field: {old, new}} for keys where values differ."""
    diff = {}
    if keys is None:
        keys = set(list(old.keys()) + list(new.keys()))
    for k in keys:
        if old.get(k) != new.get(k):
            diff[k] = {"old": old.get(k), "new": new.get(k)}
    return diff

def _compute_trip(t: Trip) -> Trip:
    if t.freight_mode == "per_ton":
        t.freight_amount = round(t.tons * t.rate_per_ton, 2)
    else:
        if t.round_trip_kms > 0 and t.rate_per_km_per_ton > 0:
            t.freight_amount = round(t.tons * t.round_trip_kms * t.rate_per_km_per_ton, 2)
        else:
            t.freight_amount = round(t.fixed_amount, 2)
    # ---- Loading / Unloading auto-diff ----
    diff = round((t.loaded_qty or 0) - (t.unloaded_qty or 0), 3)
    if t.loaded_qty > 0 or t.unloaded_qty > 0:
        if diff > 0:
            t.shortage_qty = diff
            t.excess_qty = 0.0
        elif diff < 0:
            t.excess_qty = round(-diff, 3)
            t.shortage_qty = 0.0
        else:
            t.shortage_qty = 0.0
            t.excess_qty = 0.0
    # Product-rate valuation for shortage / excess (editable via override flags)
    rate = t.product_rate_per_mt or 0
    if not t.shortage_amount_override:
        t.shortage_amount = round(rate * t.shortage_qty, 2)
    if not t.excess_amount_override:
        t.excess_amount = round(rate * t.excess_qty, 2)
    # ---- Halting / Waiting Charges auto-calc ----
    if t.loading_date and t.unloading_date:
        try:
            _ld = datetime.fromisoformat(t.loading_date).date()
            _ud = datetime.fromisoformat(t.unloading_date).date()
            t.total_halting_days = max((_ud - _ld).days, 0)
        except Exception:
            t.total_halting_days = 0
    else:
        t.total_halting_days = 0
    _grace = max(int(t.grace_days or 0), 0)
    # Only auto-set chargeable days if not manually diverged from formula
    _auto_chargeable = max(t.total_halting_days - _grace, 0)
    # If user hasn't customised (override marker via halting_amount_override implies manual)
    if not t.halting_amount_override:
        t.chargeable_halting_days = _auto_chargeable
        t.halting_amount = round(t.chargeable_halting_days * (t.halting_rate_per_day or 0), 2)
    e = t.expenses
    # Auto-compute diesel from customer amount
    if e.diesel_from_customer_qty > 0 and e.diesel_from_customer_rate > 0 and e.diesel_from_customer_amount == 0:
        e.diesel_from_customer_amount = round(e.diesel_from_customer_qty * e.diesel_from_customer_rate, 2)
    # Own expense base
    own_expense = e.diesel + e.toll + e.batta + e.repair + e.other + e.firewood
    # Diesel recovery reduces our cost (but never below 0)
    own_expense_net = max(own_expense - e.diesel_from_customer_amount, 0)
    if t.vehicle_type == "supplier":
        # Auto-compute supplier freight from detailed inputs when available
        sup_qty = t.supplier_quantity if t.supplier_quantity > 0 else t.tons
        if t.supplier_freight_mode == "per_ton" and t.supplier_rate_per_ton > 0:
            t.supplier_freight = round(sup_qty * t.supplier_rate_per_ton, 2)
        elif t.supplier_freight_mode == "fixed":
            if t.supplier_round_trip_kms > 0 and t.supplier_rate_per_km_per_ton > 0:
                t.supplier_freight = round(sup_qty * t.supplier_round_trip_kms * t.supplier_rate_per_km_per_ton, 2)
            elif t.supplier_fixed_amount > 0:
                t.supplier_freight = round(t.supplier_fixed_amount, 2)
        # else keep manually entered supplier_freight
        # Net payable = freight − advance − other recoveries (for settlement)
        t.supplier_net_payable = round(t.supplier_freight - t.supplier_advance - t.supplier_other_recoveries, 2)
        # Profit formula (as per user spec): Customer Freight − (Supplier Freight − Supplier Advance)
        # total_expense reflects the supplier cost portion after advance
        t.total_expense = round(t.supplier_freight - t.supplier_advance, 2)
    else:
        t.total_expense = round(own_expense_net, 2)
        t.supplier_net_payable = 0.0
    # Billable freight to customer = freight + halting + excess − shortage
    # (shortage is a customer deduction from our freight; excess bonus optional add-on)
    billable = t.freight_amount + t.halting_amount + t.excess_amount - t.shortage_amount - e.shortage_amount
    t.profit = round(billable - t.total_expense, 2)
    t.net_settlement = round(billable - t.total_expense - e.cash_advance_received, 2)
    return t

def _trip_billable(t: dict) -> float:
    """Billable freight for invoice = freight + halting + excess − shortage."""
    return round(
        float(t.get("freight_amount", 0))
        + float(t.get("halting_amount", 0))
        + float(t.get("excess_amount", 0))
        - float(t.get("shortage_amount", 0))
        - float((t.get("expenses") or {}).get("shortage_amount", 0)),
        2,
    )

@api.get("/trips")
async def list_trips(request: Request, user=Depends(get_current_user), customer_id: Optional[str] = None, status: Optional[str] = None):
    cid = await _active_company_id(request, user)
    await _backfill_company_id(user["user_id"], cid)
    q = {"user_id": user["user_id"], "company_id": cid}
    if customer_id:
        q["customer_id"] = customer_id
    if status:
        q["status"] = status
    docs = await db.trips.find(q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)
    return docs

@api.post("/trips")
async def create_trip(payload: Trip, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.company_id = cid
    if not payload.vehicle_id and payload.vehicle_number:
        v = await db.vehicles.find_one({"vehicle_number": payload.vehicle_number.upper(), "user_id": user["user_id"]}, {"_id": 0})
        if v:
            payload.vehicle_id = v["id"]
            payload.vehicle_type = v.get("vehicle_type", "own")
            if payload.vehicle_type == "supplier":
                payload.supplier_name = payload.supplier_name or v.get("supplier_name", "")
    payload = _compute_trip(payload)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.trips.insert_one(doc)
    doc.pop("user_id", None)
    doc.pop("_id", None)
    await _log_audit(user, "trip", "create", entity_id=doc["id"], entity_ref=doc.get("vehicle_number", ""))
    return doc

@api.put("/trips/{tid}")
async def update_trip(tid: str, payload: Trip, user=Depends(get_current_user)):
    existing = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Trip not found")
    payload.id = tid
    if payload.vehicle_number:
        v = await db.vehicles.find_one({"vehicle_number": payload.vehicle_number.upper(), "user_id": user["user_id"]}, {"_id": 0})
        if v:
            payload.vehicle_id = v["id"]
            payload.vehicle_type = v.get("vehicle_type", "own")
            if payload.vehicle_type == "supplier" and not payload.supplier_name:
                payload.supplier_name = v.get("supplier_name", "")
    payload = _compute_trip(payload)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["invoice_id"] = existing.get("invoice_id")
    doc["status"] = existing.get("status", "pending")
    await db.trips.update_one({"id": tid, "user_id": user["user_id"]}, {"$set": doc})
    if existing.get("invoice_id"):
        await _recompute_invoice(existing["invoice_id"], user)
    changes = _diff_dict(existing, doc, ["freight_amount", "tons", "rate_per_ton", "supplier_freight", "total_expense", "profit", "vehicle_number", "vehicle_type"])
    await _log_audit(user, "trip", "update", entity_id=tid, entity_ref=doc.get("vehicle_number", ""), changes=changes)
    doc.pop("user_id", None)
    return doc

@api.delete("/trips/{tid}")
async def delete_trip(tid: str, reason: str = "", user=Depends(get_current_user)):
    if not _has_perm(user, "delete_trip"):
        raise HTTPException(status_code=403, detail="Missing permission: delete_trip")
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="Reason for deletion is required")
    existing = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Trip not found")
    linked_invoice_id = existing.get("invoice_id")
    await db.trips.delete_one({"id": tid, "user_id": user["user_id"]})
    if linked_invoice_id:
        await _recompute_invoice(linked_invoice_id, user)
    await _log_audit(user, "trip", "delete", entity_id=tid, entity_ref=existing.get("vehicle_number", ""), reason=reason,
                     changes={"snapshot": {k: existing.get(k) for k in ("date", "customer_id", "vehicle_number", "freight_amount", "invoice_id")}})
    return {"ok": True, "linked_invoice_id": linked_invoice_id}

async def _recompute_invoice(iid: str, user):
    inv = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        return
    trips = await db.trips.find({"user_id": user["user_id"], "id": {"$in": inv.get("trip_ids", [])}}, {"_id": 0}).to_list(500)
    freight_total = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    halting_total = round(sum(t.get("halting_amount", 0.0) for t in trips), 2)
    excess_total = round(sum(t.get("excess_amount", 0.0) for t in trips), 2)
    shortage_total = round(
        sum(t.get("shortage_amount", 0.0) + (t.get("expenses") or {}).get("shortage_amount", 0.0) for t in trips), 2,
    )
    subtotal = round(sum(_trip_billable(t) for t in trips), 2)
    # Auto GST re-evaluation on edit (customer/company state may have changed)
    customer_doc = await db.customers.find_one({"id": inv.get("customer_id"), "user_id": user["user_id"]}, {"_id": 0}) or {}
    company_doc = await db.companies.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    home_state = (company_doc.get("state") or "").strip().lower()
    cust_state = (customer_doc.get("state") or "").strip().lower()
    if home_state and cust_state:
        gst_type = "cgst_sgst" if home_state == cust_state else "igst"
    else:
        gst_type = inv.get("gst_type", "cgst_sgst")
    cgst = round(subtotal * 2.5 / 100, 2) if gst_type == "cgst_sgst" else 0.0
    sgst = round(subtotal * 2.5 / 100, 2) if gst_type == "cgst_sgst" else 0.0
    igst = round(subtotal * 5.0 / 100, 2) if gst_type == "igst" else 0.0
    total_tax = round(cgst + sgst + igst, 2)
    gross_total = round(subtotal if inv.get("rcm") else subtotal + total_tax, 2)
    final_amount = float(int(gross_total + 0.5)) if gross_total >= 0 else -float(int(-gross_total + 0.5))
    round_off = round(final_amount - gross_total, 2)
    total_amount = final_amount
    amount_paid = round(sum(p["amount"] for p in inv.get("payments", [])), 2)
    balance_due = round(total_amount - amount_paid, 2)
    await db.invoices.update_one(
        {"id": iid, "user_id": user["user_id"]},
        {"$set": {"subtotal": subtotal, "freight_total": freight_total, "halting_total": halting_total,
                  "excess_total": excess_total, "shortage_total": shortage_total,
                  "gst_type": gst_type,
                  "cgst_amount": cgst, "sgst_amount": sgst, "igst_amount": igst,
                  "total_tax": total_tax, "gross_total": gross_total, "round_off": round_off,
                  "total_amount": total_amount,
                  "amount_paid": amount_paid, "balance_due": balance_due}},
    )

# ==================== Invoices ====================

class InvoiceCreateRequest(BaseModel):
    customer_id: str
    trip_ids: List[str]
    invoice_date: Optional[str] = None
    hsn_sac: str = "996791"  # 996511 or 996791
    gst_type: Literal["cgst_sgst", "igst"] = "cgst_sgst"
    rcm: bool = True
    notes: str = ""

async def _next_invoice_number(user_id: str) -> str:
    company = await db.companies.find_one({"user_id": user_id}, {"_id": 0})
    prefix = "INV"
    seq = 1
    if company:
        prefix = company.get("invoice_prefix") or "INV"
        seq = int(company.get("next_invoice_number") or 1)
    fy = now_utc()
    yr = fy.year % 100
    yr_next = (fy.year + 1) % 100
    fy_str = f"{yr:02d}-{yr_next:02d}" if fy.month >= 4 else f"{yr-1:02d}-{yr:02d}"
    num = f"{prefix}/{fy_str}/{seq:04d}"
    await db.companies.update_one(
        {"user_id": user_id},
        {"$set": {"next_invoice_number": seq + 1}},
        upsert=True,
    )
    return num

async def _next_invoice_number_for_company(company_id: str, user_id: str) -> str:
    """Generate next invoice number scoped to a specific company (multi-company)."""
    company = await db.companies.find_one({"id": company_id, "user_id": user_id}, {"_id": 0})
    prefix = "INV"
    seq = 1
    if company:
        prefix = company.get("invoice_prefix") or "INV"
        seq = int(company.get("next_invoice_number") or 1)
    fy = now_utc()
    yr = fy.year % 100
    yr_next = (fy.year + 1) % 100
    fy_str = f"{yr:02d}-{yr_next:02d}" if fy.month >= 4 else f"{yr-1:02d}-{yr:02d}"
    num = f"{prefix}/{fy_str}/{seq:04d}"
    await db.companies.update_one(
        {"id": company_id, "user_id": user_id},
        {"$set": {"next_invoice_number": seq + 1}},
    )
    return num

@api.get("/invoices")
async def list_invoices(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_company_id(user["user_id"], cid)
    docs = await db.invoices.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).sort("created_at", -1).to_list(1000)
    return docs

@api.get("/invoices/overdue")
async def list_overdue_invoices(request: Request, days: int = 30, user=Depends(get_current_user)):
    """List invoices with outstanding balance older than `days` days."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    from datetime import timedelta
    cutoff = (now_utc().date() - timedelta(days=days)).isoformat()
    docs = await db.invoices.find({
        "user_id": uid,
        "company_id": cid,
        "balance_due": {"$gt": 0.01},
        "invoice_date": {"$lte": cutoff},
    }, {"_id": 0, "user_id": 0}).sort("invoice_date", 1).to_list(500)
    customers = await db.customers.find({"user_id": uid}, {"_id": 0}).to_list(2000)
    cmap = {c["id"]: c for c in customers}
    today = now_utc().date()
    out = []
    for d in docs:
        c = cmap.get(d.get("customer_id"), {})
        try:
            inv_dt = datetime.fromisoformat(d.get("invoice_date")).date()
            age_days = (today - inv_dt).days
        except Exception:
            age_days = 0
        d["customer_name"] = c.get("name", "")
        d["customer_phone"] = c.get("phone", "")
        d["customer_email"] = c.get("email", "")
        d["age_days"] = age_days
        out.append(d)
    return out

@api.get("/invoices/{iid}")
async def get_invoice(iid: str, user=Depends(get_current_user)):
    doc = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return doc

@api.post("/invoices")
async def create_invoice(payload: InvoiceCreateRequest, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    # Load trips scoped to this company
    trips = await db.trips.find(
        {"user_id": user["user_id"], "company_id": cid, "id": {"$in": payload.trip_ids}, "customer_id": payload.customer_id},
        {"_id": 0},
    ).to_list(1000)
    if len(trips) != len(payload.trip_ids):
        raise HTTPException(status_code=400, detail="Some trips not found or belong to different customer / company")
    for t in trips:
        if t.get("status") == "invoiced":
            raise HTTPException(status_code=400, detail=f"Trip {t['id']} already invoiced")

    subtotal = round(sum(_trip_billable(t) for t in trips), 2)
    freight_total = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    halting_total = round(sum(t.get("halting_amount", 0.0) for t in trips), 2)
    excess_total = round(sum(t.get("excess_amount", 0.0) for t in trips), 2)
    shortage_total = round(
        sum(t.get("shortage_amount", 0.0) + (t.get("expenses") or {}).get("shortage_amount", 0.0) for t in trips), 2,
    )
    # --- Auto GST type based on state match ---
    customer_doc = await db.customers.find_one({"id": payload.customer_id, "user_id": user["user_id"]}, {"_id": 0}) or {}
    company_doc = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}
    home_state = (company_doc.get("state") or "").strip().lower()
    cust_state = (customer_doc.get("state") or "").strip().lower()
    if home_state and cust_state:
        auto_gst = "cgst_sgst" if home_state == cust_state else "igst"
    else:
        auto_gst = payload.gst_type  # fallback to payload if state missing
    gst_type = auto_gst
    cgst = sgst = igst = 0.0
    if gst_type == "cgst_sgst":
        cgst = round(subtotal * 2.5 / 100, 2)
        sgst = round(subtotal * 2.5 / 100, 2)
    else:
        igst = round(subtotal * 5.0 / 100, 2)
    total_tax = round(cgst + sgst + igst, 2)
    # RCM: tax NOT added to total (recipient pays)
    gross_total = round(subtotal if payload.rcm else subtotal + total_tax, 2)
    # Round off to nearest rupee
    final_amount = float(int(gross_total + 0.5)) if gross_total >= 0 else -float(int(-gross_total + 0.5))
    round_off = round(final_amount - gross_total, 2)
    total_amount = final_amount

    invoice_number = await _next_invoice_number_for_company(cid, user["user_id"])
    inv = Invoice(
        company_id=cid,
        invoice_number=invoice_number,
        customer_id=payload.customer_id,
        invoice_date=payload.invoice_date or now_utc().date().isoformat(),
        trip_ids=payload.trip_ids,
        subtotal=subtotal,
        hsn_sac=payload.hsn_sac or (company_doc.get("hsn_sac") or "996791"),
        freight_total=freight_total,
        halting_total=halting_total,
        excess_total=excess_total,
        shortage_total=shortage_total,
        gst_type=gst_type,
        cgst_amount=cgst,
        sgst_amount=sgst,
        igst_amount=igst,
        total_tax=total_tax,
        gross_total=gross_total,
        round_off=round_off,
        total_amount=total_amount,
        rcm=payload.rcm,
        amount_paid=0.0,
        balance_due=total_amount,
        notes=payload.notes,
    )
    doc = inv.model_dump()
    doc["user_id"] = user["user_id"]
    await db.invoices.insert_one(doc)

    # Mark trips as invoiced
    await db.trips.update_many(
        {"user_id": user["user_id"], "id": {"$in": payload.trip_ids}},
        {"$set": {"status": "invoiced", "invoice_id": inv.id}},
    )
    doc.pop("user_id", None)
    doc.pop("_id", None)
    await _log_audit(user, "invoice", "create", entity_id=inv.id, entity_ref=invoice_number)
    return doc

class InvoiceUpdateRequest(BaseModel):
    invoice_date: Optional[str] = None
    gst_type: Optional[Literal["cgst_sgst", "igst"]] = None
    rcm: Optional[bool] = None
    notes: Optional[str] = None
    reason: str = ""

@api.put("/invoices/{iid}")
async def update_invoice(iid: str, payload: InvoiceUpdateRequest, user=Depends(get_current_user)):
    existing = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    if not (payload.reason or "").strip():
        raise HTTPException(status_code=400, detail="Reason for modification is required")
    updates = {}
    for k in ("invoice_date", "gst_type", "rcm", "notes"):
        v = getattr(payload, k)
        if v is not None and v != existing.get(k):
            updates[k] = v
    if updates:
        await db.invoices.update_one({"id": iid, "user_id": user["user_id"]}, {"$set": updates})
    # If gst_type/rcm changed, recompute totals
    if "gst_type" in updates or "rcm" in updates:
        await _recompute_invoice(iid, user)
    changes = _diff_dict(existing, {**existing, **updates}, list(updates.keys()))
    await _log_audit(user, "invoice", "update", entity_id=iid, entity_ref=existing.get("invoice_number", ""), reason=payload.reason, changes=changes)
    updated = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    # Auto-save PDF snapshot to storage (best-effort, non-blocking on failure)
    try:
        customer = await db.customers.find_one({"id": updated["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
        company = await db.companies.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
        trip_docs = await db.trips.find({"user_id": user["user_id"], "id": {"$in": updated["trip_ids"]}}, {"_id": 0}).to_list(500)
        trip_docs.sort(key=lambda t: t.get("date", ""))
        pdf_bytes = build_invoice_pdf(company, customer, updated, trip_docs)
        snap_path = f"{APP_NAME}/uploads/{user['user_id']}/{uuid.uuid4().hex}.pdf"
        put_object(snap_path, pdf_bytes, "application/pdf")
        ref = FileRef(
            storage_path=snap_path,
            original_filename=f"{updated['invoice_number'].replace('/', '_')}_snapshot_{now_utc().date().isoformat()}.pdf",
            content_type="application/pdf", size=len(pdf_bytes),
            category="invoice_snapshot", linked_type="invoice", linked_id=iid,
        ).model_dump()
        ref["user_id"] = user["user_id"]
        await db.files.insert_one(ref)
    except Exception as e:
        logger.warning(f"invoice snapshot failed: {e}")
    return updated

@api.delete("/invoices/{iid}")
async def delete_invoice(iid: str, reason: str = "", user=Depends(get_current_user)):
    if not _has_perm(user, "delete_invoice"):
        raise HTTPException(status_code=403, detail="Missing permission: delete_invoice")
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="Reason for deletion is required")
    doc = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.trips.update_many(
        {"user_id": user["user_id"], "id": {"$in": doc.get("trip_ids", [])}},
        {"$set": {"status": "pending", "invoice_id": None}},
    )
    await db.invoices.delete_one({"id": iid, "user_id": user["user_id"]})
    await _log_audit(user, "invoice", "delete", entity_id=iid, entity_ref=doc.get("invoice_number", ""),
                     reason=reason, changes={"snapshot": {k: doc.get(k) for k in ("invoice_number", "customer_id", "total_amount", "amount_paid", "trip_ids")}})
    return {"ok": True}

class PaymentAdd(BaseModel):
    amount: float
    date: Optional[str] = None
    mode: str = "Cash"
    note: str = ""

@api.post("/invoices/{iid}/payments")
async def add_payment(iid: str, payload: PaymentAdd, user=Depends(get_current_user)):
    inv = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    p = Payment(
        amount=round(payload.amount, 2),
        date=payload.date or now_utc().date().isoformat(),
        mode=payload.mode,
        note=payload.note,
    )
    payments = inv.get("payments", []) + [p.model_dump()]
    amount_paid = round(sum(x["amount"] for x in payments), 2)
    balance_due = round(inv["total_amount"] - amount_paid, 2)
    await db.invoices.update_one(
        {"id": iid, "user_id": user["user_id"]},
        {"$set": {"payments": payments, "amount_paid": amount_paid, "balance_due": balance_due}},
    )
    inv["payments"] = payments
    inv["amount_paid"] = amount_paid
    inv["balance_due"] = balance_due
    inv.pop("user_id", None)
    return inv

@api.get("/invoices/{iid}/pdf")
async def invoice_pdf(iid: str, user=Depends(get_current_user)):
    inv = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    customer = await db.customers.find_one({"id": inv["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
    company = await db.companies.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    trips = await db.trips.find(
        {"user_id": user["user_id"], "id": {"$in": inv["trip_ids"]}},
        {"_id": 0},
    ).to_list(1000)
    trips.sort(key=lambda t: t.get("date", ""))
    pdf_bytes = build_invoice_pdf(company, customer, inv, trips)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{inv["invoice_number"].replace("/", "_")}.pdf"'},
    )

# ==================== Dashboard ====================

@api.get("/dashboard")
async def dashboard(request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(5000)
    invoices = await db.invoices.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(2000)
    customers = await db.customers.find({"user_id": uid}, {"_id": 0, "user_id": 0}).to_list(2000)

    total_revenue = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    total_expense = round(sum(t.get("total_expense", 0.0) for t in trips), 2)
    total_profit = round(total_revenue - total_expense, 2)
    trip_count = len(trips)
    pending_trips = len([t for t in trips if t.get("status") == "pending"])
    invoiced_trips = trip_count - pending_trips

    total_billed = round(sum(i.get("total_amount", 0.0) for i in invoices), 2)
    total_received = round(sum(i.get("amount_paid", 0.0) for i in invoices), 2)
    total_receivable = round(total_billed - total_received, 2)

    # Customer-wise receivables (with phone + oldest invoice for overdue calc)
    cust_map = {c["id"]: c for c in customers}
    receivables = {}
    today = now_utc().date()
    for i in invoices:
        cid = i["customer_id"]
        bal = i.get("balance_due", 0.0)
        if bal <= 0:
            continue
        c = cust_map.get(cid, {})
        rec = receivables.setdefault(cid, {
            "customer_id": cid,
            "customer_name": c.get("name", "Unknown"),
            "customer_phone": c.get("phone", ""),
            "balance": 0.0,
            "invoices": 0,
            "oldest_days": 0,
        })
        rec["balance"] = round(rec["balance"] + bal, 2)
        rec["invoices"] += 1
        try:
            inv_date = datetime.fromisoformat(i["invoice_date"]).date()
            days = (today - inv_date).days
            if days > rec["oldest_days"]:
                rec["oldest_days"] = days
        except Exception:
            pass

    receivables_list = sorted(receivables.values(), key=lambda x: -x["balance"])

    recent_trips = sorted(trips, key=lambda t: t.get("date", ""), reverse=True)[:8]
    for rt in recent_trips:
        rt["customer_name"] = cust_map.get(rt.get("customer_id"), {}).get("name", "")

    # Vehicle expiry alerts (within 60 days or expired)
    vehicles = await db.vehicles.find({"user_id": uid}, {"_id": 0, "user_id": 0}).to_list(500)
    expiry_alerts = []
    for v in vehicles:
        v = _vehicle_expiry_stats(v)
        for field, info in (v.get("alerts") or {}).items():
            if info["status"] in ("expired", "expiring"):
                expiry_alerts.append({
                    "vehicle_number": v.get("vehicle_number"),
                    "document": field.replace("_expiry", "").upper(),
                    "date": info["date"],
                    "days": info["days"],
                    "status": info["status"],
                })
    expiry_alerts.sort(key=lambda x: x["days"])

    return {
        "total_revenue": total_revenue,
        "total_expense": total_expense,
        "total_profit": total_profit,
        "trip_count": trip_count,
        "pending_trips": pending_trips,
        "invoiced_trips": invoiced_trips,
        "total_billed": total_billed,
        "total_received": total_received,
        "total_receivable": total_receivable,
        "customer_count": len(customers),
        "invoice_count": len(invoices),
        "receivables": receivables_list,
        "recent_trips": recent_trips,
        "expiry_alerts": expiry_alerts,
    }

# ==================== Drivers ====================

@api.get("/drivers")
async def list_drivers(user=Depends(get_current_user)):
    drivers = await db.drivers.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).to_list(1000)
    # Attach stats
    trips = await db.trips.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(5000)
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

@api.post("/drivers")
async def create_driver(payload: Driver, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.drivers.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@api.put("/drivers/{did}")
async def update_driver(did: str, payload: Driver, user=Depends(get_current_user)):
    payload.id = did
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.drivers.update_one({"id": did, "user_id": user["user_id"]}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@api.delete("/drivers/{did}")
async def delete_driver(did: str, user=Depends(get_current_user)):
    await db.drivers.delete_one({"id": did, "user_id": user["user_id"]})
    return {"ok": True}

# ==================== Trip Bulk Import ====================

TRIP_IMPORT_COLUMNS = [
    "date", "customer_name", "vehicle_number", "driver_name",
    "load_details", "tons", "from_location", "to_location",
    "freight_mode", "rate_per_ton", "fixed_amount",
    "diesel", "toll", "batta", "repair", "other", "notes",
]

@api.get("/trips/import/template")
async def trip_import_template():
    df = pd.DataFrame([{c: "" for c in TRIP_IMPORT_COLUMNS}])
    df.loc[1] = ["2026-02-01", "Megha Engineering", "AP16TA1234", "Ramesh",
                 "Bitumen VG 40", 25.5, "Vijayawada", "Hyderabad",
                 "per_ton", 1200, 0, 8000, 500, 1000, 0, 0, "sample row"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Trips")
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="trip_import_template.xlsx"'},
    )

@api.post("/trips/import")
async def trip_import(file: UploadFile = File(...), user=Depends(get_current_user)):
    contents = await file.read()
    fname = (file.filename or "").lower()
    try:
        if fname.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}")

    # Normalize columns
    df.columns = [str(c).strip().lower() for c in df.columns]
    customers = await db.customers.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(2000)
    cust_by_name = {c["name"].strip().lower(): c["id"] for c in customers}
    drivers = await db.drivers.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(1000)
    driver_by_name = {d["name"].strip().lower(): d["id"] for d in drivers}

    inserted = 0
    errors = []
    docs = []
    for idx, row in df.iterrows():
        try:
            r = {k: (row.get(k) if k in df.columns else None) for k in TRIP_IMPORT_COLUMNS}
            cname = str(r.get("customer_name") or "").strip()
            if not cname:
                raise ValueError("customer_name empty")
            cid = cust_by_name.get(cname.lower())
            if not cid:
                raise ValueError(f"customer '{cname}' not found — please add it first")
            date_val = r.get("date")
            if pd.isna(date_val):
                raise ValueError("date empty")
            if hasattr(date_val, "isoformat"):
                date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)[:10]
            else:
                date_str = str(date_val)[:10]

            freight_mode = str(r.get("freight_mode") or "per_ton").strip().lower()
            if freight_mode not in ("per_ton", "fixed"):
                freight_mode = "per_ton"

            def numf(x):
                try:
                    if x is None or (isinstance(x, float) and pd.isna(x)):
                        return 0.0
                    return float(x)
                except Exception:
                    return 0.0

            trip = Trip(
                customer_id=cid,
                date=date_str,
                vehicle_number=str(r.get("vehicle_number") or "").strip().upper(),
                driver_id=driver_by_name.get(str(r.get("driver_name") or "").strip().lower()),
                driver_name=str(r.get("driver_name") or "").strip(),
                load_details=str(r.get("load_details") or "Bitumen VG 40").strip(),
                tons=numf(r.get("tons")),
                from_location=str(r.get("from_location") or "").strip(),
                to_location=str(r.get("to_location") or "").strip(),
                freight_mode=freight_mode,
                rate_per_ton=numf(r.get("rate_per_ton")),
                fixed_amount=numf(r.get("fixed_amount")),
                expenses=Expenses(
                    diesel=numf(r.get("diesel")),
                    toll=numf(r.get("toll")),
                    batta=numf(r.get("batta")),
                    repair=numf(r.get("repair")),
                    other=numf(r.get("other")),
                ),
                notes=str(r.get("notes") or "").strip(),
            )
            if not trip.vehicle_number:
                raise ValueError("vehicle_number empty")
            trip = _compute_trip(trip)
            d = trip.model_dump()
            d["user_id"] = user["user_id"]
            docs.append(d)
        except Exception as e:
            errors.append({"row": int(idx) + 2, "error": str(e)})

    if docs:
        await db.trips.insert_many(docs)
        inserted = len(docs)
    return {"inserted": inserted, "errors": errors, "total_rows": len(df)}

# ==================== Invoice Share (Public PDF) ====================

@api.post("/invoices/{iid}/share")
async def create_share_link(iid: str, user=Depends(get_current_user)):
    inv = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    token = inv.get("share_token")
    if not token:
        token = secrets.token_urlsafe(16)
        await db.invoices.update_one(
            {"id": iid, "user_id": user["user_id"]},
            {"$set": {"share_token": token}},
        )
    return {"share_token": token}

@api.get("/public/invoice/{token}/pdf")
async def public_invoice_pdf(token: str):
    inv = await db.invoices.find_one({"share_token": token}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    customer = await db.customers.find_one({"id": inv["customer_id"], "user_id": inv["user_id"]}, {"_id": 0}) or {}
    company = await db.companies.find_one({"user_id": inv["user_id"]}, {"_id": 0}) or {}
    trips = await db.trips.find(
        {"user_id": inv["user_id"], "id": {"$in": inv["trip_ids"]}},
        {"_id": 0},
    ).to_list(1000)
    trips.sort(key=lambda t: t.get("date", ""))
    pdf_bytes = build_invoice_pdf(company, customer, inv, trips)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{inv["invoice_number"].replace("/", "_")}.pdf"'},
    )

# ==================== Products (Load Master) ====================

@api.get("/products")
async def list_products(user=Depends(get_current_user)):
    docs = await db.products.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).to_list(1000)
    return docs

@api.post("/products")
async def create_product(payload: Product, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.products.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@api.put("/products/{pid}")
async def update_product(pid: str, payload: Product, user=Depends(get_current_user)):
    payload.id = pid
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.products.update_one({"id": pid, "user_id": user["user_id"]}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@api.delete("/products/{pid}")
async def delete_product(pid: str, user=Depends(get_current_user)):
    await db.products.delete_one({"id": pid, "user_id": user["user_id"]})
    return {"ok": True}

# ==================== Company Logo ====================

@api.post("/company/logo")
async def upload_logo(file: UploadFile = File(...), user=Depends(get_current_user)):
    import base64
    content = await file.read()
    if len(content) > 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo too large (max 1MB)")
    mime = file.content_type or "image/png"
    if not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="Not an image")
    data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
    await db.companies.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"logo": data_url}},
        upsert=True,
    )
    return {"logo": data_url}

@api.delete("/company/logo")
async def delete_logo(user=Depends(get_current_user)):
    await db.companies.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"logo": ""}},
    )
    return {"ok": True}

# ==================== Reports ====================

def _in_range(date_str: str, start: Optional[str], end: Optional[str]) -> bool:
    if not date_str:
        return False
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True

@api.get("/reports/ledger")
async def report_ledger(
    request: Request,
    customer_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    customer = await db.customers.find_one({"id": customer_id, "user_id": uid}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    invoices = await db.invoices.find({"user_id": uid, "company_id": cid, "customer_id": customer_id}, {"_id": 0, "user_id": 0}).to_list(2000)

    # Build entries: invoice (debit), payment (credit)
    entries = []
    for inv in invoices:
        idt = inv.get("invoice_date", "")
        if _in_range(idt, start, end):
            entries.append({
                "date": idt,
                "type": "invoice",
                "reference": inv["invoice_number"],
                "particulars": f"Sales - {len(inv['trip_ids'])} trip(s)",
                "debit": inv["total_amount"],
                "credit": 0.0,
                "invoice_id": inv["id"],
            })
        for p in inv.get("payments", []):
            pdt = p.get("date", "")
            if _in_range(pdt, start, end):
                entries.append({
                    "date": pdt,
                    "type": "payment",
                    "reference": inv["invoice_number"],
                    "particulars": f"Payment received ({p.get('mode','Cash')}) - {p.get('note','')}".strip(" -"),
                    "debit": 0.0,
                    "credit": p["amount"],
                    "invoice_id": inv["id"],
                })

    # Sort by date, then type (invoice before payment on same day)
    entries.sort(key=lambda x: (x["date"], 0 if x["type"] == "invoice" else 1))

    # Opening balance = balances before 'start'
    opening = 0.0
    if start:
        for inv in invoices:
            if inv.get("invoice_date", "") < start:
                opening += inv["total_amount"]
            for p in inv.get("payments", []):
                if p.get("date", "") < start:
                    opening -= p["amount"]

    running = opening
    for e in entries:
        running = round(running + e["debit"] - e["credit"], 2)
        e["balance"] = running

    total_debit = round(sum(e["debit"] for e in entries), 2)
    total_credit = round(sum(e["credit"] for e in entries), 2)
    closing = round(opening + total_debit - total_credit, 2)

    return {
        "customer": {k: customer.get(k, "") for k in ["id", "name", "gstin", "phone", "address", "state"]},
        "period": {"start": start, "end": end},
        "opening_balance": round(opening, 2),
        "entries": entries,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "closing_balance": closing,
    }

@api.get("/reports/ledger/pdf")
async def report_ledger_pdf(
    customer_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    ledger = await report_ledger(customer_id=customer_id, start=start, end=end, user=user)
    company = await db.companies.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    pdf_bytes = build_ledger_pdf(company, ledger)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="ledger_{ledger["customer"]["name"].replace(" ", "_")}.pdf"'},
    )

@api.get("/reports/pl")
async def report_profit_loss(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(5000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]

    freight_revenue = round(sum(t.get("freight_amount", 0) for t in trips), 2)
    halting_revenue = round(sum(t.get("halting_amount", 0) for t in trips), 2)
    excess_revenue = round(sum(t.get("excess_amount", 0) for t in trips), 2)
    shortage_deduction = round(
        sum(t.get("shortage_amount", 0) + (t.get("expenses") or {}).get("shortage_amount", 0) for t in trips), 2,
    )
    revenue = round(freight_revenue + halting_revenue + excess_revenue - shortage_deduction, 2)
    diesel = round(sum((t.get("expenses") or {}).get("diesel", 0) for t in trips), 2)
    toll = round(sum((t.get("expenses") or {}).get("toll", 0) for t in trips), 2)
    batta = round(sum((t.get("expenses") or {}).get("batta", 0) for t in trips), 2)
    repair = round(sum((t.get("expenses") or {}).get("repair", 0) for t in trips), 2)
    other = round(sum((t.get("expenses") or {}).get("other", 0) for t in trips), 2)
    supplier_cost = round(sum(t.get("total_expense", 0) if t.get("vehicle_type") == "supplier" else 0 for t in trips), 2)
    total_expense = round(sum(t.get("total_expense", 0) for t in trips), 2)
    net_profit = round(revenue - total_expense, 2)
    margin = round((net_profit / revenue * 100.0), 2) if revenue > 0 else 0.0

    # Per-customer breakdown
    customers = await db.customers.find({"user_id": uid}, {"_id": 0}).to_list(2000)
    cmap = {c["id"]: c.get("name", "Unknown") for c in customers}
    per_customer = {}
    for t in trips:
        cid = t.get("customer_id")
        b = per_customer.setdefault(cid, {"customer_id": cid, "customer_name": cmap.get(cid, "Unknown"), "trips": 0, "revenue": 0.0, "expense": 0.0, "profit": 0.0, "tons": 0.0})
        b["trips"] += 1
        billable = float(t.get("freight_amount", 0)) + float(t.get("halting_amount", 0)) + float(t.get("excess_amount", 0)) - float(t.get("shortage_amount", 0)) - float((t.get("expenses") or {}).get("shortage_amount", 0))
        b["revenue"] += billable
        b["expense"] += t.get("total_expense", 0)
        b["profit"] += t.get("profit", 0)
        b["tons"] += t.get("tons", 0)
    for b in per_customer.values():
        for k in ("revenue", "expense", "profit", "tons"):
            b[k] = round(b[k], 2)

    return {
        "period": {"start": start, "end": end},
        "trip_count": len(trips),
        "revenue": revenue,
        "freight_revenue": freight_revenue,
        "halting_revenue": halting_revenue,
        "excess_revenue": excess_revenue,
        "shortage_deduction": shortage_deduction,
        "expenses": {
            "diesel": diesel, "toll": toll, "batta": batta, "repair": repair, "other": other,
            "supplier_net_payable": supplier_cost,
            "total": total_expense,
        },
        "net_profit": net_profit,
        "margin_pct": margin,
        "per_customer": sorted(per_customer.values(), key=lambda x: -x["revenue"]),
    }

@api.get("/reports/balance-sheet")
async def report_balance_sheet(
    request: Request,
    as_of: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    as_of = as_of or now_utc().date().isoformat()
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(5000)
    invoices = await db.invoices.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(2000)

    # Cumulative net profit up to as_of (from trips dated <= as_of)
    trips_todate = [t for t in trips if t.get("date", "") <= as_of]
    revenue = sum(t.get("freight_amount", 0) for t in trips_todate)
    expenses = sum(t.get("total_expense", 0) for t in trips_todate)
    net_profit = round(revenue - expenses, 2)

    # Cash & Bank (approximate) = total payments received up to as_of
    cash_bank = 0.0
    receivables = 0.0
    payments_by_customer = {}
    for inv in invoices:
        if inv.get("invoice_date", "") <= as_of:
            billed = inv.get("total_amount", 0)
            paid_upto = sum(p["amount"] for p in inv.get("payments", []) if p.get("date", "") <= as_of)
            cash_bank += paid_upto
            receivables += max(billed - paid_upto, 0)

    total_assets = round(cash_bank + receivables, 2)

    # Simplified: Owner's equity balances the sheet
    owners_equity = total_assets  # balance-plug for zero liabilities

    return {
        "as_of": as_of,
        "assets": {
            "cash_and_bank": round(cash_bank, 2),
            "sundry_debtors": round(receivables, 2),
            "total": total_assets,
        },
        "liabilities": {
            "current_liabilities": 0.0,
            "total": 0.0,
        },
        "equity": {
            "retained_earnings": net_profit,
            "owners_capital": round(owners_equity - net_profit, 2),
            "total": round(owners_equity, 2),
        },
        "note": "Simplified statement. Balance-plug on Owner's Capital. Add loans / opening capital in future for full balance sheet.",
    }

# ==================== Vehicles ====================

def _vehicle_expiry_stats(v: dict) -> dict:
    today = now_utc().date()
    fields = ["rc_expiry", "fc_expiry", "insurance_expiry", "permit_expiry", "puc_expiry"]
    v["alerts"] = {}
    soonest = None
    for f in fields:
        val = v.get(f) or ""
        if not val:
            continue
        try:
            d = datetime.fromisoformat(val).date()
            days = (d - today).days
            status = "expired" if days < 0 else ("expiring" if days <= 30 else "ok")
            v["alerts"][f] = {"date": val, "days": days, "status": status}
            if soonest is None or days < soonest:
                soonest = days
        except Exception:
            continue
    v["soonest_days"] = soonest
    return v

@api.get("/vehicles")
async def list_vehicles(user=Depends(get_current_user)):
    docs = await db.vehicles.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).to_list(1000)
    return [_vehicle_expiry_stats(v) for v in docs]

@api.post("/vehicles")
async def create_vehicle(payload: Vehicle, user=Depends(get_current_user)):
    payload.vehicle_number = payload.vehicle_number.upper().strip()
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.vehicles.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return _vehicle_expiry_stats(doc)

@api.put("/vehicles/{vid}")
async def update_vehicle(vid: str, payload: Vehicle, user=Depends(get_current_user)):
    payload.id = vid
    payload.vehicle_number = payload.vehicle_number.upper().strip()
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.vehicles.update_one({"id": vid, "user_id": user["user_id"]}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return _vehicle_expiry_stats(doc)

@api.delete("/vehicles/{vid}")
async def delete_vehicle(vid: str, user=Depends(get_current_user)):
    await db.vehicles.delete_one({"id": vid, "user_id": user["user_id"]})
    return {"ok": True}

# ==================== Fuel Log ====================

@api.get("/fuel")
async def list_fuel(user=Depends(get_current_user)):
    docs = await db.fuel.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)
    return docs

@api.post("/fuel")
async def create_fuel(payload: Fuel, user=Depends(get_current_user)):
    payload.vehicle_number = payload.vehicle_number.upper().strip()
    payload.amount = round(payload.litres * payload.rate_per_litre, 2) if payload.amount == 0 else round(payload.amount, 2)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.fuel.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@api.put("/fuel/{fid}")
async def update_fuel(fid: str, payload: Fuel, user=Depends(get_current_user)):
    payload.id = fid
    payload.vehicle_number = payload.vehicle_number.upper().strip()
    payload.amount = round(payload.litres * payload.rate_per_litre, 2) if payload.amount == 0 else round(payload.amount, 2)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.fuel.update_one({"id": fid, "user_id": user["user_id"]}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@api.delete("/fuel/{fid}")
async def delete_fuel(fid: str, user=Depends(get_current_user)):
    await db.fuel.delete_one({"id": fid, "user_id": user["user_id"]})
    return {"ok": True}

@api.get("/fuel/summary")
async def fuel_summary(user=Depends(get_current_user)):
    uid = user["user_id"]
    fuels = await db.fuel.find({"user_id": uid}, {"_id": 0}).sort("date", 1).to_list(5000)
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

def _state_code(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    return STATE_CODES.get(key, "")

# Reverse map: 2-digit GST state code → canonical state name
STATE_CODE_TO_NAME = {v: k.title().replace("And ", "and ").replace("Of ", "of ") for k, v in STATE_CODES.items()}
# Manual title-case tweaks (union territories / compound names)
STATE_CODE_TO_NAME["07"] = "Delhi"
STATE_CODE_TO_NAME["35"] = "Andaman and Nicobar Islands"
STATE_CODE_TO_NAME["26"] = "Dadra and Nagar Haveli and Daman and Diu"
STATE_CODE_TO_NAME["01"] = "Jammu and Kashmir"
STATE_CODE_TO_NAME["37"] = "Andhra Pradesh"
STATE_CODE_TO_NAME["36"] = "Telangana"

# ==================== GSTIN Lookup (offline structure parse) ====================

# GSTIN format: 15 chars = <2-digit state><10-char PAN><1 entity><'Z'><1 checksum>
_GSTIN_RE = re.compile(r"^([0-9]{2})([A-Z]{5}[0-9]{4}[A-Z])([0-9A-Z])(Z)([0-9A-Z])$")
_GSTIN_CHECK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def _gstin_checksum(gstin14: str) -> str:
    """Compute the 15th checksum char of a GSTIN using the standard algorithm."""
    total = 0
    for idx, ch in enumerate(gstin14):
        v = _GSTIN_CHECK_ALPHABET.index(ch)
        factor = 2 if idx % 2 else 1
        prod = v * factor
        total += (prod // 36) + (prod % 36)
    remainder = total % 36
    return _GSTIN_CHECK_ALPHABET[(36 - remainder) % 36]

@api.get("/gstin/lookup")
async def gstin_lookup(gstin: str, user=Depends(get_current_user)):
    """Parse a GSTIN offline (free) and return state, PAN, entity code and format validity.

    A future paid GSTIN details API (Signzy / ClearTax / etc.) can be layered on
    top by populating GSTIN_LOOKUP_API_KEY in .env — this endpoint would then
    also return the taxpayer's legal name, trade name and registered address.
    For now it just returns the offline parse so customer forms can auto-fill
    state and PAN the moment the GSTIN is entered.
    """
    g = (gstin or "").strip().upper().replace(" ", "")
    if not g:
        raise HTTPException(status_code=400, detail="GSTIN is required")
    m = _GSTIN_RE.match(g)
    result = {
        "gstin": g,
        "valid_format": bool(m),
        "checksum_ok": False,
        "state_code": "",
        "state": "",
        "pan": "",
        "entity_code": "",
        "source": "offline_parse",
        "legal_name": None,
        "trade_name": None,
        "address": None,
        "note": None,
    }
    if m:
        state_code = m.group(1)
        pan = m.group(2)
        entity = m.group(3)
        expected_check = _gstin_checksum(g[:14])
        result["state_code"] = state_code
        result["state"] = STATE_CODE_TO_NAME.get(state_code, "")
        result["pan"] = pan
        result["entity_code"] = entity
        result["checksum_ok"] = (expected_check == g[14])
    # Placeholder for paid API integration — no key configured yet.
    if not os.environ.get("GSTIN_LOOKUP_API_KEY"):
        result["note"] = "Offline parse only. Full name/address needs a paid GSTIN API (Signzy/ClearTax). Configure GSTIN_LOOKUP_API_KEY to enable."
    return result

@api.get("/reports/gstr1")
async def report_gstr1(month: str, request: Request, user=Depends(get_current_user)):
    """month format: YYYY-MM"""
    try:
        year_str, mo_str = month.split("-")
        y = int(year_str); m = int(mo_str)
        assert 1 <= m <= 12
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month; use YYYY-MM")
    from calendar import monthrange
    start = f"{y:04d}-{m:02d}-01"
    end = f"{y:04d}-{m:02d}-{monthrange(y, m)[1]:02d}"

    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    invoices = await db.invoices.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(5000)
    invoices = [i for i in invoices if start <= i.get("invoice_date", "") <= end]
    customers = await db.customers.find({"user_id": uid}, {"_id": 0}).to_list(2000)
    cmap = {c["id"]: c for c in customers}
    company = await db.companies.find_one({"id": cid, "user_id": uid}, {"_id": 0}) or {}
    home_state_code = _state_code(company.get("state", ""))

    b2b_rows = []
    b2c_rows = []
    totals = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total": 0.0}
    for inv in invoices:
        c = cmap.get(inv["customer_id"], {})
        gstin = c.get("gstin", "").strip()
        st = c.get("state", "")
        sc = _state_code(st)
        row = {
            "invoice_number": inv["invoice_number"],
            "invoice_date": inv["invoice_date"],
            "customer_name": c.get("name", ""),
            "gstin": gstin,
            "state": st,
            "state_code": sc,
            "place_of_supply": f"{sc}-{st}" if sc else st,
            "reverse_charge": "Y" if inv.get("rcm") else "N",
            "taxable_value": inv.get("subtotal", 0.0),
            "cgst": inv.get("cgst_amount", 0.0),
            "sgst": inv.get("sgst_amount", 0.0),
            "igst": inv.get("igst_amount", 0.0),
            "total": inv.get("total_amount", 0.0),
            "gst_type": "IGST" if inv.get("gst_type") == "igst" else "CGST+SGST",
        }
        (b2b_rows if gstin else b2c_rows).append(row)
        totals["taxable"] += row["taxable_value"]
        totals["cgst"] += row["cgst"]
        totals["sgst"] += row["sgst"]
        totals["igst"] += row["igst"]
        totals["total"] += row["total"]

    for k in totals:
        totals[k] = round(totals[k], 2)

    # Group by state
    by_state = {}
    for r in b2b_rows + b2c_rows:
        key = r.get("state_code") or "N/A"
        s = by_state.setdefault(key, {"state_code": key, "state": r["state"], "invoices": 0, "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total": 0.0})
        s["invoices"] += 1
        s["taxable"] += r["taxable_value"]
        s["cgst"] += r["cgst"]
        s["sgst"] += r["sgst"]
        s["igst"] += r["igst"]
        s["total"] += r["total"]
    for s in by_state.values():
        for k in ("taxable", "cgst", "sgst", "igst", "total"):
            s[k] = round(s[k], 2)

    return {
        "month": month,
        "period": {"start": start, "end": end},
        "company_state": company.get("state", ""),
        "company_state_code": home_state_code,
        "b2b": b2b_rows,
        "b2c": b2c_rows,
        "by_state": sorted(by_state.values(), key=lambda x: -x["total"]),
        "totals": totals,
        "invoice_count": len(invoices),
    }

# ==================== E-Way Bill JSON ====================

@api.get("/trips/{tid}/ewaybill")
async def eway_bill(tid: str, user=Depends(get_current_user)):
    trip = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    customer = await db.customers.find_one({"id": trip["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
    company = await db.companies.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}

    invoice = None
    if trip.get("invoice_id"):
        invoice = await db.invoices.find_one({"id": trip["invoice_id"], "user_id": user["user_id"]}, {"_id": 0})

    from_state_code = _state_code(company.get("state", ""))
    to_state_code = _state_code(customer.get("state", ""))
    is_intrastate = from_state_code and to_state_code and from_state_code == to_state_code

    taxable = round(float(trip.get("freight_amount", 0)), 2)
    if is_intrastate:
        cgst_rate = 2.5; sgst_rate = 2.5; igst_rate = 0.0
    else:
        cgst_rate = 0.0; sgst_rate = 0.0; igst_rate = 5.0
    cgst_amt = round(taxable * cgst_rate / 100, 2)
    sgst_amt = round(taxable * sgst_rate / 100, 2)
    igst_amt = round(taxable * igst_rate / 100, 2)
    total_val = round(taxable + cgst_amt + sgst_amt + igst_amt, 2)

    payload = {
        "version": "1.0.0421",
        "billLists": [
            {
                "userGstin": company.get("gstin", ""),
                "supplyType": "O",
                "subSupplyType": "1",
                "subSupplyDesc": "",
                "docType": "TRA",  # Transport (LR/GR)
                "docNo": invoice["invoice_number"] if invoice else trip["id"].replace("trip_", "TRP-"),
                "docDate": (invoice["invoice_date"] if invoice else trip["date"]).replace("-", "/"),
                "fromGstin": company.get("gstin", "URP"),
                "fromTrdName": company.get("name", ""),
                "fromAddr1": company.get("address", "")[:120],
                "fromAddr2": "",
                "fromPlace": company.get("state", ""),
                "fromPincode": int(company.get("pincode", "0") or 0) if str(company.get("pincode", "")).isdigit() else 0,
                "fromStateCode": int(from_state_code) if from_state_code else 0,
                "actFromStateCode": int(from_state_code) if from_state_code else 0,
                "toGstin": customer.get("gstin", "URP"),
                "toTrdName": customer.get("name", ""),
                "toAddr1": customer.get("address", "")[:120],
                "toAddr2": "",
                "toPlace": customer.get("state", ""),
                "toPincode": int(customer.get("pincode", "0") or 0) if str(customer.get("pincode", "")).isdigit() else 0,
                "toStateCode": int(to_state_code) if to_state_code else 0,
                "actToStateCode": int(to_state_code) if to_state_code else 0,
                "transactionType": 1,
                "otherValue": 0,
                "totalValue": taxable,
                "cgstValue": cgst_amt,
                "sgstValue": sgst_amt,
                "igstValue": igst_amt,
                "cessValue": 0,
                "TotNonAdvolVal": 0,
                "OthValue": 0,
                "totInvValue": total_val,
                "transMode": "1",  # Road
                "transDistance": str(int(trip.get("round_trip_kms", 0) or 0) or 0),
                "transporterName": company.get("name", ""),
                "transporterId": company.get("gstin", ""),
                "transDocNo": "",
                "transDocDate": (invoice["invoice_date"] if invoice else trip["date"]).replace("-", "/"),
                "vehicleNo": trip.get("vehicle_number", ""),
                "vehicleType": "R",
                "itemList": [
                    {
                        "productName": trip.get("load_details", "Bitumen"),
                        "productDesc": trip.get("load_details", ""),
                        "hsnCode": int((trip.get("hsn_sac") or company.get("hsn_sac") or "996791").replace(" ", "")) if (trip.get("hsn_sac") or company.get("hsn_sac") or "996791").replace(" ", "").isdigit() else 996791,
                        "quantity": trip.get("tons", 0),
                        "qtyUnit": "MT",
                        "cgstRate": cgst_rate,
                        "sgstRate": sgst_rate,
                        "igstRate": igst_rate,
                        "cessRate": 0,
                        "cessNonAdvol": 0,
                        "taxableAmount": taxable,
                    }
                ],
            }
        ],
    }
    return payload

# ==================== File Uploads (Object Storage) ====================

class FileRef(BaseModel):
    id: str = Field(default_factory=lambda: new_id("file_"))
    storage_path: str
    original_filename: str
    content_type: str
    size: int
    category: str = "general"           # logo | vehicle_doc | fuel_bill | lr_proof | trip_attachment | general
    linked_type: str = ""               # vehicle | trip | fuel | invoice | ""
    linked_id: str = ""
    is_deleted: bool = False
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

@api.post("/files/upload")
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

@api.get("/files/usage")
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

@api.post("/files/bulk-upload")
async def bulk_upload(
    files: List[UploadFile] = File(...),
    category: str = "general",
    user=Depends(get_current_user),
):
    """Upload multiple files. Auto-tag vehicle_number and date from filename pattern
    like 'AP16TA1234_2026-02-05_anything.jpg' or 'AP16TA1234-2026-02-05.png'."""
    import re
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
                v = await db.vehicles.find_one({"vehicle_number": vno, "user_id": user["user_id"]}, {"_id": 0})
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

@api.get("/files")
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

@api.get("/files/{fid}/download")
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

@api.delete("/files/{fid}")
async def delete_file(fid: str, user=Depends(get_current_user)):
    # Soft delete (storage has no delete API)
    r = await db.files.update_one(
        {"id": fid, "user_id": user["user_id"]},
        {"$set": {"is_deleted": True}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}

async def _next_lr_number(user_id: str) -> str:
    company = await db.companies.find_one({"user_id": user_id}, {"_id": 0})
    prefix = "LR"
    seq = 1
    if company:
        prefix = company.get("lr_prefix") or "LR"
        seq = int(company.get("next_lr_number") or 1)
    fy = now_utc()
    yr = fy.year % 100
    yr_next = (fy.year + 1) % 100
    fy_str = f"{yr:02d}-{yr_next:02d}" if fy.month >= 4 else f"{yr-1:02d}-{yr:02d}"
    num = f"{prefix}/{fy_str}/{seq:05d}"
    await db.companies.update_one(
        {"user_id": user_id},
        {"$set": {"next_lr_number": seq + 1}},
        upsert=True,
    )
    return num

@api.get("/trips/{tid}/lr")
async def trip_lr_pdf(tid: str, user=Depends(get_current_user)):
    from pdf_generator import build_lr_pdf
    trip = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    # Auto-assign lr_number if missing
    if not trip.get("lr_number"):
        lr_num = await _next_lr_number(user["user_id"])
        await db.trips.update_one({"id": tid, "user_id": user["user_id"]}, {"$set": {"lr_number": lr_num}})
        trip["lr_number"] = lr_num
    customer = await db.customers.find_one({"id": trip["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
    company = await db.companies.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    pdf_bytes = build_lr_pdf(company, customer, trip)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{trip["lr_number"].replace("/", "_")}.pdf"'},
    )

# ==================== Audit Logs ====================

@api.get("/audit-logs")
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

@api.get("/team")
async def list_team(user=Depends(get_current_user)):
    if user.get("is_staff"):
        raise HTTPException(status_code=403, detail="Only owner can view team")
    docs = await db.team_members.find({"owner_user_id": user["user_id"]}, {"_id": 0}).to_list(200)
    return docs

@api.post("/team")
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

@api.put("/team/{tid}")
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

@api.delete("/team/{tid}")
async def delete_team_member(tid: str, user=Depends(get_current_user)):
    if user.get("is_staff"):
        raise HTTPException(status_code=403, detail="Only owner")
    doc = await db.team_members.find_one({"id": tid, "owner_user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.team_members.delete_one({"id": tid, "owner_user_id": user["user_id"]})
    await _log_audit(user, "team", "delete", entity_id=tid, entity_ref=doc.get("email", ""), reason="removed")
    return {"ok": True}

@api.get("/team/me")
async def team_me(user=Depends(get_current_user)):
    return {
        "email": user.get("email"),
        "name": user.get("name"),
        "role": user.get("effective_role"),
        "is_staff": user.get("is_staff", False),
        "permissions": sorted(list(ROLE_PERMISSIONS.get(user.get("effective_role", "owner"), set()))),
    }

# ==================== Supplier P&L Report ====================

@api.get("/reports/supplier-pl")
async def report_supplier_pl(request: Request, start: Optional[str] = None, end: Optional[str] = None, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid, "vehicle_type": "supplier"}, {"_id": 0, "user_id": 0}).to_list(5000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]
    by = {}
    for t in trips:
        name = (t.get("supplier_name") or "—").strip() or "—"
        s = by.setdefault(name, {"supplier_name": name, "trips": 0, "tons": 0.0, "customer_freight": 0.0,
                                  "supplier_freight": 0.0, "supplier_advance": 0.0, "supplier_other_recoveries": 0.0,
                                  "net_payable": 0.0, "profit": 0.0, "margin_pct": 0.0})
        s["trips"] += 1
        s["tons"] += float(t.get("tons", 0))
        s["customer_freight"] += float(t.get("freight_amount", 0))
        s["supplier_freight"] += float(t.get("supplier_freight", 0))
        s["supplier_advance"] += float(t.get("supplier_advance", 0))
        s["supplier_other_recoveries"] += float(t.get("supplier_other_recoveries", 0))
    total = {"trips": 0, "tons": 0.0, "customer_freight": 0.0, "supplier_freight": 0.0,
             "supplier_advance": 0.0, "supplier_other_recoveries": 0.0, "net_payable": 0.0, "profit": 0.0}
    for s in by.values():
        s["net_payable"] = round(s["supplier_freight"] - s["supplier_advance"] - s["supplier_other_recoveries"], 2)
        # Profit = Customer Freight - (Supplier Freight - Supplier Advance)
        s["profit"] = round(s["customer_freight"] - (s["supplier_freight"] - s["supplier_advance"]), 2)
        s["margin_pct"] = round((s["profit"] / s["customer_freight"] * 100.0), 2) if s["customer_freight"] > 0 else 0.0
        for k in ("tons", "customer_freight", "supplier_freight", "supplier_advance", "supplier_other_recoveries"):
            s[k] = round(s[k], 2)
        total["trips"] += s["trips"]; total["tons"] += s["tons"]
        total["customer_freight"] += s["customer_freight"]; total["supplier_freight"] += s["supplier_freight"]
        total["supplier_advance"] += s["supplier_advance"]; total["supplier_other_recoveries"] += s["supplier_other_recoveries"]
        total["net_payable"] += s["net_payable"]; total["profit"] += s["profit"]
    for k in ("tons", "customer_freight", "supplier_freight", "supplier_advance", "supplier_other_recoveries", "net_payable", "profit"):
        total[k] = round(total[k], 2)
    return {
        "period": {"start": start, "end": end},
        "suppliers": sorted(by.values(), key=lambda x: -x["profit"]),
        "totals": total,
    }

# ==================== Consignor / Consignee Master ====================

@api.get("/parties")
async def list_parties(party_type: Optional[str] = None, user=Depends(get_current_user)):
    q = {"user_id": user["user_id"]}
    if party_type:
        q["$or"] = [{"party_type": party_type}, {"party_type": "both"}]
    docs = await db.parties.find(q, {"_id": 0, "user_id": 0}).sort("name", 1).to_list(2000)
    return docs

@api.post("/parties")
async def create_party(payload: Party, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.parties.insert_one(doc)
    return payload.model_dump()

@api.put("/parties/{pid}")
async def update_party(pid: str, payload: Party, user=Depends(get_current_user)):
    upd = payload.model_dump()
    upd["id"] = pid
    upd.pop("created_at", None)
    r = await db.parties.update_one({"id": pid, "user_id": user["user_id"]}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Party not found")
    return await db.parties.find_one({"id": pid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})

@api.delete("/parties/{pid}")
async def delete_party(pid: str, user=Depends(get_current_user)):
    r = await db.parties.delete_one({"id": pid, "user_id": user["user_id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Party not found")
    return {"ok": True}

# ==================== Halting Report ====================

@api.get("/reports/halting")
async def report_halting(request: Request, start: Optional[str] = None, end: Optional[str] = None, user=Depends(get_current_user)):
    """Monthly / range summary of halting per customer.

    Response includes rows per customer with total trips, total halting days,
    chargeable halting days and halting revenue, plus overall totals.
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(10000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]
    customers = await db.customers.find({"user_id": uid}, {"_id": 0}).to_list(2000)
    cmap = {c["id"]: c.get("name", "Unknown") for c in customers}

    by = {}
    for t in trips:
        halt = float(t.get("halting_amount", 0) or 0)
        total_days = int(t.get("total_halting_days", 0) or 0)
        charge_days = int(t.get("chargeable_halting_days", 0) or 0)
        if halt <= 0 and charge_days == 0:
            continue
        cid = t.get("customer_id")
        b = by.setdefault(cid, {
            "customer_id": cid, "customer_name": cmap.get(cid, "Unknown"),
            "trips_with_halting": 0, "total_days": 0, "chargeable_days": 0,
            "halting_revenue": 0.0, "avg_rate": 0.0,
        })
        b["trips_with_halting"] += 1
        b["total_days"] += total_days
        b["chargeable_days"] += charge_days
        b["halting_revenue"] += halt
    total = {"trips_with_halting": 0, "total_days": 0, "chargeable_days": 0, "halting_revenue": 0.0}
    for b in by.values():
        b["halting_revenue"] = round(b["halting_revenue"], 2)
        b["avg_rate"] = round(b["halting_revenue"] / b["chargeable_days"], 2) if b["chargeable_days"] > 0 else 0.0
        for k in ("trips_with_halting", "total_days", "chargeable_days"):
            total[k] += b[k]
        total["halting_revenue"] += b["halting_revenue"]
    total["halting_revenue"] = round(total["halting_revenue"], 2)
    return {
        "period": {"start": start, "end": end},
        "customers": sorted(by.values(), key=lambda x: -x["halting_revenue"]),
        "totals": total,
    }

# ==================== GST Summary Widget ====================

@api.get("/reports/gst-summary")
async def report_gst_summary(request: Request, user=Depends(get_current_user)):
    """Compact GST breakup for the current month + current FY + next filing due date."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    today = now_utc().date()
    month_start = today.replace(day=1).isoformat()
    month_end = today.isoformat()
    # Financial year: Apr - Mar
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    fy_start = f"{fy_start_year:04d}-04-01"
    fy_end = f"{fy_start_year + 1:04d}-03-31"

    def _agg(rows):
        return {
            "invoices": len(rows),
            "taxable": round(sum(i.get("subtotal", 0) for i in rows), 2),
            "cgst": round(sum(i.get("cgst_amount", 0) for i in rows), 2),
            "sgst": round(sum(i.get("sgst_amount", 0) for i in rows), 2),
            "igst": round(sum(i.get("igst_amount", 0) for i in rows), 2),
            "total_tax": round(sum(i.get("total_tax", 0) for i in rows), 2),
            "total": round(sum(i.get("total_amount", 0) for i in rows), 2),
        }

    invoices = await db.invoices.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(10000)
    month_rows = [i for i in invoices if month_start <= i.get("invoice_date", "") <= month_end]
    fy_rows = [i for i in invoices if fy_start <= i.get("invoice_date", "") <= fy_end]

    # Next GSTR-1 filing date: 11th of following month
    y = today.year + (1 if today.month == 12 else 0)
    m = 1 if today.month == 12 else today.month + 1
    gstr1_due = f"{y:04d}-{m:02d}-11"
    # Next GSTR-3B: 20th of following month
    gstr3b_due = f"{y:04d}-{m:02d}-20"

    return {
        "current_month": {"start": month_start, "end": month_end, **_agg(month_rows)},
        "current_fy": {"start": fy_start, "end": fy_end, **_agg(fy_rows)},
        "next_gstr1_due": gstr1_due,
        "next_gstr3b_due": gstr3b_due,
    }

# ==================== Overdue Invoices — see /invoices/overdue defined above /invoices/{iid} ====================

# ==================== Health ====================

@api.get("/")
async def root():
    return {"service": "bitumen-transport-accounting", "ok": True}

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Storage init failed at startup: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
