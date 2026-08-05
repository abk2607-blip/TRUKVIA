"""Bitumen Transport Accounting - Backend API
Emergent Google OAuth + Trip/Invoice management + Server-side PDF.
"""
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import uuid
import logging
import requests
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta

from pdf_generator import build_invoice_pdf

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
    bank_name: str = ""
    account_number: str = ""
    ifsc: str = ""
    branch: str = ""
    hsn_sac: str = "996791"
    invoice_prefix: str = "INV"
    next_invoice_number: int = 1

class Customer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cust_"))
    name: str
    address: str = ""
    phone: str = ""
    gstin: str = ""
    pan: str = ""
    state: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Expenses(BaseModel):
    diesel: float = 0.0
    toll: float = 0.0
    batta: float = 0.0
    repair: float = 0.0
    other: float = 0.0

class Trip(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trip_"))
    customer_id: str
    date: str  # ISO date
    vehicle_number: str
    driver_name: str = ""
    load_details: str = "Bitumen VG 40"
    tons: float
    from_location: str = ""
    to_location: str = ""
    freight_mode: Literal["per_ton", "fixed"]
    rate_per_ton: float = 0.0
    fixed_amount: float = 0.0
    freight_amount: float = 0.0
    expenses: Expenses = Field(default_factory=Expenses)
    total_expense: float = 0.0
    profit: float = 0.0
    invoice_id: Optional[str] = None
    status: Literal["pending", "invoiced"] = "pending"
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

    # Customer-wise receivables
    cust_map = {c["id"]: c for c in customers}
    receivables = {}
    for i in invoices:
        cid = i["customer_id"]
        bal = i.get("balance_due", 0.0)
        if bal <= 0:
            continue
        rec = receivables.setdefault(cid, {"customer_id": cid, "customer_name": cust_map.get(cid, {}).get("name", "Unknown"), "balance": 0.0, "invoices": 0})
        rec["balance"] = round(rec["balance"] + bal, 2)
        rec["invoices"] += 1

    receivables_list = sorted(receivables.values(), key=lambda x: -x["balance"])

    recent_trips = sorted(trips, key=lambda t: t.get("date", ""), reverse=True)[:8]
    for rt in recent_trips:
        rt["customer_name"] = cust_map.get(rt.get("customer_id"), {}).get("name", "")

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
    }

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

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
