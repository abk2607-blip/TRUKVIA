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

class Driver(BaseModel):
    id: str = Field(default_factory=lambda: new_id("drv_"))
    name: str
    phone: str = ""
    license_number: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Trip(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trip_"))
    customer_id: str
    date: str  # ISO date
    vehicle_number: str
    driver_id: Optional[str] = None
    driver_name: str = ""
    driver_mobile: str = ""
    product_id: Optional[str] = None
    load_details: str = "Bitumen VG 40"
    hsn_sac: str = ""
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
    invoice_id: Optional[str] = None
    status: Literal["pending", "invoiced"] = "pending"
    notes: str = ""
    # LR (Lorry Receipt / Consignment Note) fields
    lr_number: str = ""
    lr_time: str = ""
    consignor_name: str = ""
    consignor_address: str = ""
    consignee_site_location: str = ""
    consignee_site_contact: str = ""
    external_invoice_no: str = ""
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

class Vehicle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("veh_"))
    vehicle_number: str
    owner_name: str = ""
    owner_phone: str = ""
    make_model: str = ""
    capacity_tons: float = 0.0
    rc_expiry: str = ""            # ISO date
    fc_expiry: str = ""            # Fitness Certificate
    insurance_expiry: str = ""
    permit_expiry: str = ""
    puc_expiry: str = ""            # Pollution Under Control
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
    invoice_number: str
    customer_id: str
    invoice_date: str
    trip_ids: List[str]
    subtotal: float
    gst_type: Literal["cgst_sgst", "igst"] = "cgst_sgst"
    cgst_rate: float = 2.5
    sgst_rate: float = 2.5
    igst_rate: float = 5.0
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    total_tax: float = 0.0
    total_amount: float = 0.0
    rcm: bool = True  # Reverse charge — tax not collected
    payments: List[Payment] = []
    amount_paid: float = 0.0
    balance_due: float = 0.0
    share_token: Optional[str] = None
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

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

# ==================== Company Settings ====================

@api.get("/company")
async def get_company(user=Depends(get_current_user)):
    doc = await db.companies.find_one({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not doc:
        return Company().model_dump()
    return doc

@api.put("/company")
async def save_company(payload: Company, user=Depends(get_current_user)):
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.companies.update_one(
        {"user_id": user["user_id"]},
        {"$set": doc},
        upsert=True,
    )
    return payload.model_dump()

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

def _compute_trip(t: Trip) -> Trip:
    if t.freight_mode == "per_ton":
        t.freight_amount = round(t.tons * t.rate_per_ton, 2)
    else:
        # Round trip: tons × round_trip_kms × rate_per_km_per_ton
        # Backward-compat: fall back to fixed_amount if new fields are 0
        if t.round_trip_kms > 0 and t.rate_per_km_per_ton > 0:
            t.freight_amount = round(t.tons * t.round_trip_kms * t.rate_per_km_per_ton, 2)
        else:
            t.freight_amount = round(t.fixed_amount, 2)
    e = t.expenses
    t.total_expense = round(e.diesel + e.toll + e.batta + e.repair + e.other, 2)
    t.profit = round(t.freight_amount - t.total_expense, 2)
    return t

@api.get("/trips")
async def list_trips(user=Depends(get_current_user), customer_id: Optional[str] = None, status: Optional[str] = None):
    q = {"user_id": user["user_id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if status:
        q["status"] = status
    docs = await db.trips.find(q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)
    return docs

@api.post("/trips")
async def create_trip(payload: Trip, user=Depends(get_current_user)):
    payload = _compute_trip(payload)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.trips.insert_one(doc)
    doc.pop("user_id", None)
    doc.pop("_id", None)
    return doc

@api.put("/trips/{tid}")
async def update_trip(tid: str, payload: Trip, user=Depends(get_current_user)):
    existing = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Trip not found")
    if existing.get("status") == "invoiced":
        raise HTTPException(status_code=400, detail="Cannot edit invoiced trip")
    payload.id = tid
    payload = _compute_trip(payload)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    await db.trips.update_one({"id": tid, "user_id": user["user_id"]}, {"$set": doc})
    doc.pop("user_id", None)
    return doc

@api.delete("/trips/{tid}")
async def delete_trip(tid: str, user=Depends(get_current_user)):
    existing = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Trip not found")
    if existing.get("status") == "invoiced":
        raise HTTPException(status_code=400, detail="Cannot delete invoiced trip")
    await db.trips.delete_one({"id": tid, "user_id": user["user_id"]})
    return {"ok": True}

# ==================== Invoices ====================

class InvoiceCreateRequest(BaseModel):
    customer_id: str
    trip_ids: List[str]
    invoice_date: Optional[str] = None
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

@api.get("/invoices")
async def list_invoices(user=Depends(get_current_user)):
    docs = await db.invoices.find({"user_id": user["user_id"]}, {"_id": 0, "user_id": 0}).sort("created_at", -1).to_list(1000)
    return docs

@api.get("/invoices/{iid}")
async def get_invoice(iid: str, user=Depends(get_current_user)):
    doc = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return doc

@api.post("/invoices")
async def create_invoice(payload: InvoiceCreateRequest, user=Depends(get_current_user)):
    # Load trips
    trips = await db.trips.find(
        {"user_id": user["user_id"], "id": {"$in": payload.trip_ids}, "customer_id": payload.customer_id},
        {"_id": 0},
    ).to_list(1000)
    if len(trips) != len(payload.trip_ids):
        raise HTTPException(status_code=400, detail="Some trips not found or belong to different customer")
    for t in trips:
        if t.get("status") == "invoiced":
            raise HTTPException(status_code=400, detail=f"Trip {t['id']} already invoiced")

    subtotal = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    cgst = sgst = igst = 0.0
    if payload.gst_type == "cgst_sgst":
        cgst = round(subtotal * 2.5 / 100, 2)
        sgst = round(subtotal * 2.5 / 100, 2)
    else:
        igst = round(subtotal * 5.0 / 100, 2)
    total_tax = round(cgst + sgst + igst, 2)
    # RCM: tax NOT added to total (recipient pays)
    total_amount = round(subtotal if payload.rcm else subtotal + total_tax, 2)

    invoice_number = await _next_invoice_number(user["user_id"])
    inv = Invoice(
        invoice_number=invoice_number,
        customer_id=payload.customer_id,
        invoice_date=payload.invoice_date or now_utc().date().isoformat(),
        trip_ids=payload.trip_ids,
        subtotal=subtotal,
        gst_type=payload.gst_type,
        cgst_amount=cgst,
        sgst_amount=sgst,
        igst_amount=igst,
        total_tax=total_tax,
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
    return doc

@api.delete("/invoices/{iid}")
async def delete_invoice(iid: str, user=Depends(get_current_user)):
    doc = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.trips.update_many(
        {"user_id": user["user_id"], "id": {"$in": doc.get("trip_ids", [])}},
        {"$set": {"status": "pending", "invoice_id": None}},
    )
    await db.invoices.delete_one({"id": iid, "user_id": user["user_id"]})
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
async def dashboard(user=Depends(get_current_user)):
    uid = user["user_id"]
    trips = await db.trips.find({"user_id": uid}, {"_id": 0, "user_id": 0}).to_list(5000)
    invoices = await db.invoices.find({"user_id": uid}, {"_id": 0, "user_id": 0}).to_list(2000)
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
    customer_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    customer = await db.customers.find_one({"id": customer_id, "user_id": uid}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    invoices = await db.invoices.find({"user_id": uid, "customer_id": customer_id}, {"_id": 0, "user_id": 0}).to_list(2000)

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
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    trips = await db.trips.find({"user_id": uid}, {"_id": 0, "user_id": 0}).to_list(5000)
    trips = [t for t in trips if _in_range(t.get("date", ""), start, end)]

    revenue = round(sum(t.get("freight_amount", 0) for t in trips), 2)
    diesel = round(sum((t.get("expenses") or {}).get("diesel", 0) for t in trips), 2)
    toll = round(sum((t.get("expenses") or {}).get("toll", 0) for t in trips), 2)
    batta = round(sum((t.get("expenses") or {}).get("batta", 0) for t in trips), 2)
    repair = round(sum((t.get("expenses") or {}).get("repair", 0) for t in trips), 2)
    other = round(sum((t.get("expenses") or {}).get("other", 0) for t in trips), 2)
    total_expense = round(diesel + toll + batta + repair + other, 2)
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
        b["revenue"] += t.get("freight_amount", 0)
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
        "expenses": {
            "diesel": diesel, "toll": toll, "batta": batta, "repair": repair, "other": other,
            "total": total_expense,
        },
        "net_profit": net_profit,
        "margin_pct": margin,
        "per_customer": sorted(per_customer.values(), key=lambda x: -x["revenue"]),
    }

@api.get("/reports/balance-sheet")
async def report_balance_sheet(
    as_of: Optional[str] = None,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    as_of = as_of or now_utc().date().isoformat()
    trips = await db.trips.find({"user_id": uid}, {"_id": 0}).to_list(5000)
    invoices = await db.invoices.find({"user_id": uid}, {"_id": 0}).to_list(2000)

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

@api.get("/reports/gstr1")
async def report_gstr1(month: str, user=Depends(get_current_user)):
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
    invoices = await db.invoices.find({"user_id": uid}, {"_id": 0, "user_id": 0}).to_list(5000)
    invoices = [i for i in invoices if start <= i.get("invoice_date", "") <= end]
    customers = await db.customers.find({"user_id": uid}, {"_id": 0}).to_list(2000)
    cmap = {c["id"]: c for c in customers}
    company = await db.companies.find_one({"user_id": uid}, {"_id": 0}) or {}
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
