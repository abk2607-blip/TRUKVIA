"""Bitumen Transport Accounting — Backend API.

Modular FastAPI service. Domain logic lives in dedicated modules
(models / auth / company / services) and endpoints under `routers/`.
This file only wires the application together.
"""
import logging
import os
from pathlib import Path

from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from db import client, db
from storage_client import init_storage, APP_NAME

# Router modules
from routers import (
    auth_router as auth_r,
    companies as companies_r,
    customers as customers_r,
    drivers as drivers_r,
    products as products_r,
    vehicles as vehicles_r,
    parties as parties_r,
    trips as trips_r,
    invoices as invoices_r,
    dashboard as dashboard_r,
    reports as reports_r,
    gst as gst_r,
    files as files_r,
    team as team_r,
    audit_router as audit_r,
    templates as templates_r,
    ai as ai_r,
    expenditure_types as expenditure_types_r,
    suppliers as suppliers_r,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bitumen Transport Accounting")

# Root ping (unprefixed) — sometimes probed by health-checks
@app.get("/api/")
async def root():
    return {"message": "Bitumen Transport Accounting API"}

# CORS — the frontend authenticates via Bearer token (Authorization header),
# so we never rely on cookies. Setting allow_credentials=False lets us use
# a plain `*` origin and keeps the API reachable from every preview URL
# (dynamic + static) as well as any user-supplied embed / mobile client.
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Mount all sub-routers. Each router has prefix="/api" so paths are already fully qualified.
for r in (
    auth_r, companies_r, customers_r, drivers_r, products_r,
    vehicles_r, parties_r, trips_r, invoices_r, dashboard_r,
    reports_r, gst_r, files_r, team_r, audit_r,
    templates_r, ai_r, expenditure_types_r, suppliers_r,
):
    app.include_router(r.router)


@app.on_event("startup")
async def startup_event():
    try:
        await init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Object storage init failed: {e}")
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler init failed: {e}")
    # Iter48 — Auth stability hardening (root-cause fixes for repeated login/session issues)
    # Iter49 — Also backfill legacy trips/vehicles with null-valued str/float fields
    # so the Pydantic v2 contract never rejects a legacy row on PUT.
    try:
        # Trip-level supplier_id
        r1 = await db.trips.update_many({"supplier_id": None}, {"$set": {"supplier_id": ""}})
        r2 = await db.vehicles.update_many({"supplier_id": None}, {"$set": {"supplier_id": ""}})
        # Trip.expenses.other_remarks & other_desc were `None` in legacy rows
        r3 = await db.trips.update_many({"expenses.other_remarks": None}, {"$set": {"expenses.other_remarks": ""}})
        r4 = await db.trips.update_many({"expenses.other_desc": None}, {"$set": {"expenses.other_desc": ""}})
        # Common null-str Trip fields — coerce to "" everywhere
        str_fields_to_normalise = [
            "supplier_name", "supplier_loading_point", "supplier_unloading_point",
            "supplier_material", "supplier_settlement_remarks",
            "driver_name", "driver_mobile", "lr_driver_name", "lr_driver_mobile",
            "consignor_name", "consignee_name", "consignor_address",
            "consignee_site_location", "consignee_site_contact",
            "hsn_sac", "load_details", "from_location", "to_location",
            "from_pincode", "to_pincode", "loading_date", "unloading_date",
            "halting_remarks", "shortage_remarks", "excess_remarks",
            "other_income_remarks", "notes", "lr_number", "lr_time",
            "external_invoice_no", "customer_invoice_no", "customer_purchased_at",
            "waybill_no", "seal_numbers",
        ]
        fixed_str = 0
        for f in str_fields_to_normalise:
            rr = await db.trips.update_many({f: None}, {"$set": {f: ""}})
            fixed_str += rr.modified_count
        if r1.modified_count or r2.modified_count or r3.modified_count or r4.modified_count or fixed_str:
            logger.info(
                f"Iter49 null-coerce backfill: trips.supplier_id={r1.modified_count}, "
                f"vehicles.supplier_id={r2.modified_count}, expenses.other_remarks={r3.modified_count}, "
                f"expenses.other_desc={r4.modified_count}, other-str-fields={fixed_str}"
            )
    except Exception as e:
        logger.warning(f"Iter49 null-coerce backfill failed: {e}")
    # 1. Unique index on session_token → guarantees no duplicate session docs
    # 2. TTL index on expires_at    → MongoDB auto-purges expired sessions
    # 3. Unique index on users.email → prevents dup user rows on OAuth replay
    try:
        # De-dupe existing session rows before applying unique index (keep the newest)
        seen = {}
        async for s in db.user_sessions.find({}, {"_id": 1, "session_token": 1, "created_at": 1}):
            tok = s.get("session_token")
            if not tok:
                await db.user_sessions.delete_one({"_id": s["_id"]})
                continue
            key = tok
            prev = seen.get(key)
            if prev is None or (s.get("created_at") or "") > (prev.get("created_at") or ""):
                if prev is not None:
                    await db.user_sessions.delete_one({"_id": prev["_id"]})
                seen[key] = s
            else:
                await db.user_sessions.delete_one({"_id": s["_id"]})
        # Now create the indexes (idempotent — will no-op if already there)
        await db.user_sessions.create_index("session_token", unique=True, name="uniq_session_token")
        await db.user_sessions.create_index("expires_at_ttl", expireAfterSeconds=0,
                                            partialFilterExpression={"expires_at_ttl": {"$exists": True}},
                                            name="auto_purge_expired") if False else None
        # Simpler approach: index expires_at as string (ISO) is not TTL-eligible; skip TTL for now
        # (rolling refresh + login-time cleanup keeps rows in check)
        await db.users.create_index("email", unique=True, name="uniq_user_email", sparse=True)
        await db.users.create_index("user_id", unique=True, name="uniq_user_id")
        logger.info("Auth stability indexes ensured (user_sessions.session_token unique + users.email unique)")
    except Exception as e:
        logger.warning(f"Auth index ensure failed: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    try:
        from scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
