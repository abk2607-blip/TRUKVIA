from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64, logging

logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# Iter91 — Supplier Diesel / Advance transaction-log helpers
# ---------------------------------------------------------------------------

def _sup_entry_active(entries):
    return [e for e in (entries or []) if not e.get("deleted")]

def _sup_entries_total(entries) -> float:
    return round(sum(float(e.get("amount", 0) or 0) for e in _sup_entry_active(entries)), 2)

def _lazy_migrate_supplier_entries(doc: dict, uid: str) -> tuple[dict, bool]:
    """One-time migration: if a legacy trip has a flat supplier_diesel or
    supplier_advance value but no entry list, convert each to a single
    "Migrated" entry so the transaction log becomes the source of truth.

    Returns (doc, changed). Only supplier trips are migrated.
    """
    if doc.get("vehicle_type") != "supplier":
        return doc, False
    changed = False
    d_amt = float(doc.get("supplier_diesel") or 0)
    if d_amt > 0 and not (doc.get("supplier_diesel_entries") or []):
        doc["supplier_diesel_entries"] = [{
            "id": new_id("sde_"),
            "date": doc.get("date") or "",
            "quantity": 0.0, "rate": 0.0, "amount": d_amt,
            "mode": "", "reference": "",
            "remarks": "Migrated from single field",
            "created_at": now_utc().isoformat(), "created_by": uid,
            "modified_at": "", "modified_by": "",
            "deleted": False, "deleted_reason": "", "deleted_at": "", "deleted_by": "",
        }]
        changed = True
    a_amt = float(doc.get("supplier_advance") or 0)
    if a_amt > 0 and not (doc.get("supplier_advance_entries") or []):
        doc["supplier_advance_entries"] = [{
            "id": new_id("sae_"),
            "date": doc.get("date") or "",
            "amount": a_amt,
            "mode": "", "reference": "",
            "remarks": "Migrated from single field",
            "created_at": now_utc().isoformat(), "created_by": uid,
            "modified_at": "", "modified_by": "",
            "deleted": False, "deleted_reason": "", "deleted_at": "", "deleted_by": "",
        }]
        changed = True
    return doc, changed


async def _load_supplier_trip(tid: str, uid: str, cid: str) -> dict:
    doc = await db.trips.find_one(
        {"id": tid, "user_id": uid, "company_id": cid}, {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Trip not found")
    if doc.get("vehicle_type") != "supplier":
        raise HTTPException(status_code=400, detail="Trip is not a supplier vehicle trip")
    return doc


async def _persist_supplier_entries(tid: str, uid: str, cid: str, doc: dict) -> dict:
    """Recompute supplier_diesel / supplier_advance from entries, run
    _compute_trip to keep net_payable / profit consistent, then write back
    the mutated document."""
    if doc.get("supplier_diesel_entries") is not None:
        doc["supplier_diesel"] = _sup_entries_total(doc["supplier_diesel_entries"])
    if doc.get("supplier_advance_entries") is not None:
        doc["supplier_advance"] = _sup_entries_total(doc["supplier_advance_entries"])
    try:
        trip = Trip(**{k: v for k, v in doc.items() if k in Trip.model_fields})
        trip = _compute_trip(trip)
        computed = trip.model_dump()
        # keep the entry lists exactly as passed (Trip → model_dump may reserialise
        # nested BaseModel; ensure we don't lose per-row audit metadata that
        # already lives on `doc`).
        computed["supplier_diesel_entries"] = doc.get("supplier_diesel_entries") or []
        computed["supplier_advance_entries"] = doc.get("supplier_advance_entries") or []
        doc = computed
    except Exception as _e:  # never block the entry CRUD on compute glitches
        logger.warning(f"_persist_supplier_entries compute failed: {_e}")
    await db.trips.update_one(
        {"id": tid, "user_id": uid, "company_id": cid},
        {"$set": doc},
    )
    if doc.get("invoice_id"):
        try:
            await _recompute_invoice(doc["invoice_id"], {"user_id": uid})
        except Exception as _e:
            logger.warning(f"invoice recompute after entry change failed: {_e}")
    return doc



TRIP_IMPORT_COLUMNS = [
    "date", "customer_name", "vehicle_number", "driver_name",
    "load_details", "tons", "from_location", "to_location",
    "freight_mode", "rate_per_ton", "fixed_amount",
    "diesel", "toll", "batta", "repair", "other", "notes",
]


import pandas as pd
from pdf import build_lr_pdf, build_invoice_pdf


# ---------------------------------------------------------------------------
# Iter47 Phase 3 — Supplier link enforcement
# ---------------------------------------------------------------------------
async def _enforce_supplier_link(payload: Trip, uid: str, cid: str):
    """When a trip's vehicle is 'supplier' type, mandate a valid Supplier master link.
    Auto-resolves supplier_id from supplier_name when the FK isn't set yet.
    If a name is provided but no Supplier master record exists, auto-creates one
    (backward-compat for legacy trip data + strict FK-integrity going forward).
    Raises 400 when neither supplier_id nor supplier_name is present."""
    from models import Supplier as _SupModel  # local to avoid cycles

    if not (payload.supplier_id or "").strip() and (payload.supplier_name or "").strip():
        # Try to resolve by name (case-insensitive)
        sup = await db.suppliers.find_one(
            {"user_id": uid, "company_id": cid,
             "name": {"$regex": f"^{payload.supplier_name.strip()}$", "$options": "i"}},
            {"_id": 0, "id": 1, "name": 1},
        )
        if sup:
            payload.supplier_id = sup["id"]
            payload.supplier_name = sup["name"]  # normalise casing
        else:
            # Auto-create a Supplier master record so the FK is always valid
            new_sup = _SupModel(name=payload.supplier_name.strip())
            doc = new_sup.model_dump()
            doc["user_id"] = uid
            doc["company_id"] = cid
            doc["created_by"] = uid
            await db.suppliers.insert_one(doc)
            payload.supplier_id = doc["id"]
            payload.supplier_name = doc["name"]

    if not (payload.supplier_id or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Supplier vehicle requires a linked Supplier. Please select a supplier or create one under Suppliers → Add.",
        )
    # Validate the supplier_id belongs to this company
    sup = await db.suppliers.find_one({"id": payload.supplier_id, "user_id": uid, "company_id": cid}, {"_id": 0, "name": 1})
    if not sup:
        raise HTTPException(status_code=400, detail="Selected supplier does not exist for this company")
    payload.supplier_name = sup["name"]


async def _build_trip_filter_query(
    user, cid: str,
    customer_id=None, vehicle_id=None, supplier_id=None, status=None,
    date=None, date_from=None, date_to=None, q=None, halting_only=False,
    missing_cust_ref=False,
) -> dict:
    """Iter57 — Shared filter-builder used by GET /trips and GET /trips/export
    so both endpoints apply *exactly* the same AND-filter semantics.

    Iter84 — `missing_cust_ref=True` narrows the result to trips that don't yet
    have a Customer Reference / Customer Invoice Number stored (all three
    aliases blank/missing). No new field is created — we reuse the existing
    per-trip `customer_reference_number` (with legacy fallbacks).
    """
    mongo_q: dict = {"user_id": user["user_id"], "company_id": cid}
    if customer_id:
        mongo_q["customer_id"] = customer_id
    if vehicle_id:
        mongo_q["vehicle_id"] = vehicle_id
    if supplier_id:
        mongo_q["supplier_id"] = supplier_id
    if status:
        mongo_q["status"] = status
    if halting_only:
        mongo_q["halting_amount"] = {"$gt": 0}
    if missing_cust_ref:
        # A ref is "missing" when every alias is blank/absent.
        blank = {"$in": [None, ""]}
        mongo_q["$and"] = mongo_q.get("$and", []) + [
            {"$or": [{"customer_reference_number": blank}, {"customer_reference_number": {"$exists": False}}]},
            {"$or": [{"customer_invoice_no": blank}, {"customer_invoice_no": {"$exists": False}}]},
            {"$or": [{"waybill_no": blank}, {"waybill_no": {"$exists": False}}]},
        ]
    if date:
        mongo_q["date"] = date
    else:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        if rng:
            mongo_q["date"] = rng
    if q and q.strip():
        import re as _re
        pattern = _re.compile(_re.escape(q.strip()), _re.IGNORECASE)
        cust_ids: list = []
        try:
            cust_docs = await db.customers.find(
                {"user_id": user["user_id"], "company_id": cid, "name": pattern},
                {"id": 1, "_id": 0},
            ).to_list(50)
            cust_ids = [c["id"] for c in cust_docs]
        except Exception:
            cust_ids = []
        or_clauses = [
            {"lr_number": pattern},
            {"vehicle_number": pattern},
            {"from_location": pattern},
            {"to_location": pattern},
            {"external_invoice_no": pattern},
            {"customer_invoice_no": pattern},
            {"waybill_no": pattern},
            {"driver_name": pattern},
            {"supplier_name": pattern},
        ]
        if cust_ids:
            or_clauses.append({"customer_id": {"$in": cust_ids}})
        mongo_q["$or"] = or_clauses
    return mongo_q


@router.get("/trips")
async def list_trips(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    customer_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    supplier_id: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    halting_only: bool = False,
    missing_cust_ref: bool = False,
    ids: Optional[str] = None,
    limit: int = Query(2000, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    """Iter56 — server-side search/filter + pagination.

    All filters are combined with AND. Company-scoped by the active company.
    Default behaviour (no query params) is preserved: returns up to 2000 trips
    sorted by (date desc, created_at desc). Total match count is exposed via
    the `X-Total-Count` header so the client can render pagination controls
    without a second round-trip.

    Iter79 — `ids` (comma-separated) fetches specific trips directly; used by
    InvoiceView which knows the trip_ids on the invoice and must not depend on
    the 2000-row cap.
    """
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    if ids:
        id_list = [s.strip() for s in ids.split(",") if s.strip()]
        if not id_list:
            return []
        docs = await db.trips.find(
            {"user_id": user["user_id"], "company_id": cid, "id": {"$in": id_list}},
            {"_id": 0, "user_id": 0},
        ).to_list(len(id_list))
        return docs

    mongo_q = await _build_trip_filter_query(
        user, cid,
        customer_id=customer_id, vehicle_id=vehicle_id, supplier_id=supplier_id,
        status=status, date=date, date_from=date_from, date_to=date_to,
        q=q, halting_only=halting_only, missing_cust_ref=missing_cust_ref,
    )

    total = await db.trips.count_documents(mongo_q)
    cursor = (db.trips
              .find(mongo_q, {"_id": 0, "user_id": 0})
              .sort([("date", -1), ("created_at", -1)])
              .skip(offset).limit(limit))
    docs = await cursor.to_list(limit)
    # Expose pagination metadata via headers (backward-compatible with array body).
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Has-More"] = "true" if (offset + len(docs)) < total else "false"
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count, X-Has-More"
    return docs


@router.get("/trips/export")
async def export_trips(
    request: Request,
    user=Depends(get_current_user),
    format: str = "csv",
    customer_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    supplier_id: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    halting_only: bool = False,
    missing_cust_ref: bool = False,
    trip_ids: Optional[str] = None,   # Iter58 — comma-separated IDs for bulk "Export Selected"
):
    """Iter57 P1 — Export currently-filtered trips as CSV or XLSX.

    Accepts the exact same filter query params as GET /trips, so the export
    contains ONLY the trips that would appear in the filtered log. Multi-
    company isolation is preserved (results are scoped to the active company).

    Iter58 — When `trip_ids` (comma-separated) is provided, the export is
    narrowed to exactly those IDs on top of any other filters. This backs the
    "Export Selected" bulk action.
    """
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    mongo_q = await _build_trip_filter_query(
        user, cid,
        customer_id=customer_id, vehicle_id=vehicle_id, supplier_id=supplier_id,
        status=status, date=date, date_from=date_from, date_to=date_to,
        q=q, halting_only=halting_only, missing_cust_ref=missing_cust_ref,
    )
    if trip_ids:
        ids = [tid.strip() for tid in trip_ids.split(",") if tid.strip()]
        if ids:
            mongo_q["id"] = {"$in": ids[:5000]}
    # Cap at 10k rows to keep memory sane while still supporting a full year of trips.
    trips = await (db.trips
                   .find(mongo_q, {"_id": 0, "user_id": 0})
                   .sort([("date", -1), ("created_at", -1)])
                   .limit(10000)
                   .to_list(10000))
    # Denormalise customer name for readability.
    cust_ids = list({t.get("customer_id") for t in trips if t.get("customer_id")})
    cust_map = {}
    if cust_ids:
        c_docs = await db.customers.find(
            {"user_id": user["user_id"], "id": {"$in": cust_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(cust_ids))
        cust_map = {c["id"]: c["name"] for c in c_docs}
    # Build rows (flat, human-readable columns).
    columns = [
        "date", "trip_number", "lr_number", "customer", "vehicle_number",
        "vehicle_type", "supplier_name", "driver_name",
        "load_details", "tons", "from_location", "to_location",
        "freight_mode", "rate_per_ton", "round_trip_kms", "rate_per_km_per_ton",
        "fixed_amount", "freight_amount",
        "loaded_qty", "unloaded_qty", "shortage_qty", "excess_qty",
        "shortage_amount", "excess_amount",
        "total_halting_days", "grace_days", "chargeable_halting_days",
        "halting_rate_per_day", "halting_amount",
        "exp_diesel", "exp_toll", "exp_batta", "exp_repair", "exp_other",
        "total_expense", "other_income", "profit", "status", "invoice_id",
    ]
    rows = []
    for t in trips:
        e = t.get("expenses") or {}
        rows.append({
            "date": t.get("date"),
            "trip_number": t.get("trip_number") or "",
            "lr_number": t.get("lr_number") or "",
            "customer": cust_map.get(t.get("customer_id"), ""),
            "vehicle_number": t.get("vehicle_number") or "",
            "vehicle_type": t.get("vehicle_type") or "own",
            "supplier_name": t.get("supplier_name") or "",
            "driver_name": t.get("driver_name") or "",
            "load_details": t.get("load_details") or "",
            "tons": t.get("tons") or 0,
            "from_location": t.get("from_location") or "",
            "to_location": t.get("to_location") or "",
            "freight_mode": t.get("freight_mode") or "per_ton",
            "rate_per_ton": t.get("rate_per_ton") or 0,
            "round_trip_kms": t.get("round_trip_kms") or 0,
            "rate_per_km_per_ton": t.get("rate_per_km_per_ton") or 0,
            "fixed_amount": t.get("fixed_amount") or 0,
            "freight_amount": t.get("freight_amount") or 0,
            "loaded_qty": t.get("loaded_qty") or t.get("tons") or 0,
            "unloaded_qty": t.get("unloaded_qty") or 0,
            "shortage_qty": t.get("shortage_qty") or 0,
            "excess_qty": t.get("excess_qty") or 0,
            "shortage_amount": t.get("shortage_amount") or 0,
            "excess_amount": t.get("excess_amount") or 0,
            "total_halting_days": t.get("total_halting_days") or 0,
            "grace_days": t.get("grace_days") or 0,
            "chargeable_halting_days": t.get("chargeable_halting_days") or 0,
            "halting_rate_per_day": t.get("halting_rate_per_day") or 0,
            "halting_amount": t.get("halting_amount") or 0,
            "exp_diesel": e.get("diesel") or 0,
            "exp_toll": e.get("toll") or 0,
            "exp_batta": e.get("batta") or 0,
            "exp_repair": e.get("repair") or 0,
            "exp_other": e.get("other") or 0,
            "total_expense": t.get("total_expense") or 0,
            "other_income": t.get("other_income") or 0,
            "profit": t.get("profit") or 0,
            "status": t.get("status") or "pending",
            "invoice_id": t.get("invoice_id") or "",
        })
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fmt = (format or "csv").lower()
    if fmt == "xlsx":
        df = pd.DataFrame(rows, columns=columns)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Trips")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="trips_export_{stamp}.xlsx"'},
        )
    # Default: CSV
    df = pd.DataFrame(rows, columns=columns)
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")  # BOM for Excel compat
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="trips_export_{stamp}.csv"'},
    )



@router.post("/trips")
async def create_trip(payload: Trip, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.company_id = cid
    if not payload.vehicle_id and payload.vehicle_number:
        v = await db.vehicles.find_one({"vehicle_number": payload.vehicle_number.upper(), "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
        if v:
            payload.vehicle_id = v["id"]
            payload.vehicle_type = v.get("vehicle_type", "own")
            if payload.vehicle_type == "supplier":
                payload.supplier_name = payload.supplier_name or v.get("supplier_name", "")
                payload.supplier_id = payload.supplier_id or v.get("supplier_id", "")
    # Iter47 Phase 3: Strict enforcement — supplier vehicle MUST link to a Supplier master record
    if payload.vehicle_type == "supplier":
        await _enforce_supplier_link(payload, user["user_id"], cid)
    # Auto-assign LR number if not provided (per-company sequential)
    if not (payload.lr_number or "").strip():
        payload.lr_number = await _next_lr_number(user["user_id"], cid)
    payload = _compute_trip(payload)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    # Iter89 · Phase 1 — POLICY SNAPSHOT.
    # Freeze Customer freight method + shortage config + Product default shortage
    # + Supplier KG limit onto the trip at create time. Later master edits will
    # NEVER change these values on this trip.
    if not doc.get("policy_snapshot_at"):
        try:
            snap_now = now_utc().isoformat()
            cust = await db.customers.find_one(
                {"id": doc.get("customer_id"), "user_id": user["user_id"], "company_id": cid},
                {"_id": 0, "default_freight_method": 1, "shortage_config": 1},
            ) or {}
            doc["applied_freight_method"] = doc.get("applied_freight_method") or cust.get("default_freight_method") or "per_ton_loading"
            sc = cust.get("shortage_config") or {}
            # Iter103 fix — snapshot the customer's DEDUCTION METHOD unconditionally
            # (it's the primary customer decision and applies even when the
            # allowance comes from the Product Master via the engine fallback).
            # Only snapshot the LIMIT/LIMIT_TYPE when the customer has actually
            # configured a custom allowance (limit > 0) — Customer Master
            # defaults (`{limit:0, limit_type:"pct", method:"net_shortage"}`)
            # must not be mistaken for a real policy.
            _sc_limit = float(sc.get("limit", 0) or 0)
            _sc_method = (sc.get("method") or "").strip()
            if _sc_limit > 0:
                doc["applied_customer_shortage_limit"] = _sc_limit
                doc["applied_customer_shortage_limit_type"] = sc.get("limit_type") or "pct"
            else:
                doc["applied_customer_shortage_limit"] = 0.0
                doc["applied_customer_shortage_limit_type"] = ""
            # Method: always snapshot when the customer picked one (even without
            # a custom limit — the Product fallback still needs to know it).
            doc["applied_customer_shortage_method"] = _sc_method
            if doc.get("product_id"):
                prod = await db.products.find_one(
                    {"id": doc["product_id"], "user_id": user["user_id"], "company_id": cid},
                    {"_id": 0, "default_shortage_allowance_pct": 1},
                ) or {}
                doc["applied_product_shortage_pct"] = float(prod.get("default_shortage_allowance_pct", 0) or 0)
            if doc.get("vehicle_type") == "supplier" and doc.get("supplier_id"):
                sup = await db.suppliers.find_one(
                    {"id": doc["supplier_id"], "user_id": user["user_id"], "company_id": cid},
                    {"_id": 0, "shortage_limit_kg": 1, "product_shortage_limits": 1},
                ) or {}
                # Iter90 — Prefer per-product KG limit; fall back to legacy flat
                # `shortage_limit_kg` when the trip's product isn't listed.
                psl_kg = None
                pid = doc.get("product_id")
                for row in (sup.get("product_shortage_limits") or []):
                    if row.get("product_id") == pid:
                        try:
                            psl_kg = float(row.get("limit_kg", 0) or 0)
                        except (TypeError, ValueError):
                            psl_kg = 0.0
                        break
                if psl_kg is None:
                    psl_kg = float(sup.get("shortage_limit_kg", 0) or 0)
                doc["applied_supplier_shortage_limit_kg"] = psl_kg
            doc["policy_snapshot_at"] = snap_now
            # Iter97 · Phase 2 — Now that the freight method snapshot is set,
            # recompute freight_amount so the correct method (unloading /
            # higher-of / fixed) is applied. Compute originally ran with an
            # empty applied_freight_method (default per_ton_loading).
            try:
                _t = Trip(**{k: v for k, v in doc.items() if k in Trip.model_fields})
                _t = _compute_trip(_t)
                _c = _t.model_dump()
                for k in ("freight_amount", "freight_qty_used", "shortage_qty",
                          "excess_qty", "shortage_amount", "excess_amount",
                          "supplier_freight", "supplier_net_payable",
                          "supplier_shortage_deduction"):
                    if k in _c:
                        doc[k] = _c[k]
            except Exception as _e:
                import logging; logging.getLogger(__name__).warning(f"phase2 recompute failed: {_e}")
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"policy snapshot failed: {_e}")
    # Iter59 · Phase A — Snapshot the applicable Driver Shortage Policy onto
    # the Trip at CREATE time. Future policy edits will NEVER change this
    # snapshot.
    try:
        from routers.driver_shortage_policies import build_trip_driver_recovery_snapshot
        snap = await build_trip_driver_recovery_snapshot(user["user_id"], cid, doc)
        if snap is not None:
            doc["driver_recovery"] = snap
    except Exception as _e:
        # Never block trip create because of policy issues; log for ops.
        import logging; logging.getLogger(__name__).warning(f"driver_recovery snapshot failed: {_e}")
    await db.trips.insert_one(doc)
    # Iter61 · Phase C — Mirror driver_recovery to Driver Ledger (Trip = SSoT)
    try:
        from routers.driver_ledger import sync_trip_recovery_to_ledger
        await sync_trip_recovery_to_ledger(user["user_id"], cid, doc)
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning(f"ledger sync (create) failed: {_e}")
    doc.pop("user_id", None)
    doc.pop("_id", None)
    await _log_audit(user, "trip", "create", entity_id=doc["id"], entity_ref=doc.get("vehicle_number", ""))
    return doc

@router.patch("/trips/{tid}/customer-ref")
async def update_trip_customer_ref(
    tid: str,
    payload: dict = Body(...),
    request: Request = None,
    user=Depends(get_current_user),
):
    """Iter85 — Inline "One-Click Cust Ref Fill" from the Missing Cust Ref view.

    Only updates the per-trip `customer_reference_number` field. Never touches
    any other trip data (freight, halting, expenses, invoice link, etc.).
    Blank input clears the ref (moves the trip BACK into the missing list),
    matching the user's expectation that saving a real value pulls it out of
    the filtered list.
    """
    cid = await _active_company_id(request, user)
    ref = str(payload.get("customer_reference_number") or "").strip()
    existing = await db.trips.find_one(
        {"id": tid, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0, "id": 1, "customer_reference_number": 1},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Trip not found")
    await db.trips.update_one(
        {"id": tid, "user_id": user["user_id"], "company_id": cid},
        {"$set": {"customer_reference_number": ref}},
    )
    await _log_audit(
        user, "trip", "customer_ref_inline_update",
        entity_id=tid,
        entity_ref=f"{existing.get('customer_reference_number', '') or '∅'} → {ref or '∅'}",
    )
    return {"id": tid, "customer_reference_number": ref}


@router.put("/trips/{tid}")
async def update_trip(tid: str, payload: Trip, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    existing = await db.trips.find_one({"id": tid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Trip not found")
    payload.id = tid
    payload.company_id = cid
    if payload.vehicle_number:
        v = await db.vehicles.find_one({"vehicle_number": payload.vehicle_number.upper(), "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
        if v:
            payload.vehicle_id = v["id"]
            payload.vehicle_type = v.get("vehicle_type", "own")
            if payload.vehicle_type == "supplier" and not payload.supplier_name:
                payload.supplier_name = v.get("supplier_name", "")
            if payload.vehicle_type == "supplier" and not payload.supplier_id:
                payload.supplier_id = v.get("supplier_id", "")
    # Iter47 Phase 3: Strict enforcement — supplier vehicle MUST link to a Supplier master record
    if payload.vehicle_type == "supplier":
        await _enforce_supplier_link(payload, user["user_id"], cid)
    payload = _compute_trip(payload)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["invoice_id"] = existing.get("invoice_id")
    doc["status"] = existing.get("status", "pending")
    # Iter59 · Phase A — CRITICAL: preserve the historical policy snapshot.
    # We NEVER re-resolve the policy on update. Instead we recompute the
    # system_* values using the ORIGINAL allowed_limit_kg from the snapshot,
    # preserving override + audit history. If the existing trip pre-dated
    # Iter59 (no snapshot), we take one now using the current trip_date so
    # the trip finally has a policy attached — but subsequent edits still
    # won't re-resolve.
    try:
        from routers.driver_shortage_policies import (
            refresh_trip_driver_recovery_from_snapshot,
            build_trip_driver_recovery_snapshot,
        )
        prev_snap = existing.get("driver_recovery")
        doc["driver_recovery_history"] = existing.get("driver_recovery_history") or []
        if prev_snap:
            # Preserve original policy identity; only recompute derived values.
            doc["driver_recovery"] = {
                **prev_snap,
                **(await refresh_trip_driver_recovery_from_snapshot({**doc, "driver_recovery": prev_snap}) or {}),
            }
        elif doc.get("driver_id"):
            # Legacy trip → capture initial snapshot now
            snap = await build_trip_driver_recovery_snapshot(user["user_id"], cid, doc)
            if snap is not None:
                doc["driver_recovery"] = snap
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning(f"driver_recovery preserve failed: {_e}")
    await db.trips.update_one({"id": tid, "user_id": user["user_id"], "company_id": cid}, {"$set": doc})
    # Iter61 · Phase C — Keep Driver Ledger mirror in sync on Trip edit.
    # If driver was reassigned, sync will remove the old-driver row and
    # (re)create under new driver.  If recovery went to 0, the row is
    # deleted entirely.
    try:
        from routers.driver_ledger import sync_trip_recovery_to_ledger
        await sync_trip_recovery_to_ledger(user["user_id"], cid, {**doc, "id": tid})
        # Old-driver cleanup if driver_id changed
        if existing.get("driver_id") and existing["driver_id"] != doc.get("driver_id"):
            await db.driver_ledger_entries.delete_many({
                "user_id": user["user_id"], "company_id": cid,
                "driver_id": existing["driver_id"],
                "entry_type": "trip_recovery", "source": "system",
                "reference.kind": "trip", "reference.id": tid,
            })
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning(f"ledger sync (update) failed: {_e}")
    if existing.get("invoice_id"):
        await _recompute_invoice(existing["invoice_id"], user)
    changes = _diff_dict(existing, doc, ["freight_amount", "tons", "rate_per_ton", "supplier_freight", "total_expense", "profit", "vehicle_number", "vehicle_type"])
    await _log_audit(user, "trip", "update", entity_id=tid, entity_ref=doc.get("vehicle_number", ""), changes=changes)
    doc.pop("user_id", None)
    return doc

@router.post("/trips/bulk-invoice-preflight")
async def bulk_invoice_preflight(
    request: Request,
    payload: dict,
    user=Depends(get_current_user),
):
    """Iter58 P1 — Pre-flight validation for the Bulk Invoice action.

    Returns whether the selected trips are eligible to be invoiced together:
      * All belong to the SAME customer
      * NONE is already invoiced
      * All have freight_amount > 0
    The frontend calls this before POST /invoices so the operator sees the
    exact reason a bulk invoice can't be created (matching the user's UX ask).
    """
    trip_ids = list(payload.get("trip_ids") or [])
    if not trip_ids:
        raise HTTPException(status_code=400, detail="trip_ids required")
    if len(trip_ids) > 200:
        raise HTTPException(status_code=400, detail="Cannot bulk-invoice more than 200 trips at a time")
    cid = await _active_company_id(request, user)
    trips = await db.trips.find(
        {"id": {"$in": trip_ids}, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    ).to_list(len(trip_ids))
    found = {t["id"]: t for t in trips}
    missing = [tid for tid in trip_ids if tid not in found]
    if missing:
        return {
            "ok": False,
            "reason": "not_found",
            "detail": f"{len(missing)} selected trip(s) were not found in the active company",
            "missing_ids": missing,
        }
    customers = sorted({t.get("customer_id") for t in trips if t.get("customer_id")})
    if len(customers) == 0:
        return {"ok": False, "reason": "no_customer",
                "detail": "Selected trips do not have a customer assigned"}
    if len(customers) > 1:
        # Load customer names for the error message so operators can see which are the outliers.
        cust_docs = await db.customers.find(
            {"id": {"$in": customers}, "user_id": user["user_id"]},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(customers))
        names = ", ".join(sorted(c.get("name", c["id"][:8]) for c in cust_docs))
        return {
            "ok": False,
            "reason": "mixed_customers",
            "detail": "Bulk invoice can only be created for trips belonging to the same customer.",
            "customer_ids": customers,
            "customer_names": names,
        }
    already_invoiced = [t["id"] for t in trips if t.get("status") == "invoiced"]
    if already_invoiced:
        return {
            "ok": False,
            "reason": "already_invoiced",
            "detail": f"{len(already_invoiced)} selected trip(s) are already invoiced. Only unbilled trips can be bulk-invoiced.",
            "invoiced_ids": already_invoiced,
        }
    zero_freight = [t["id"] for t in trips if not (t.get("freight_amount") or 0) > 0]
    if zero_freight:
        return {
            "ok": False,
            "reason": "zero_freight",
            "detail": f"{len(zero_freight)} selected trip(s) have zero freight and cannot be invoiced.",
            "trip_ids": zero_freight,
        }
    return {
        "ok": True,
        "customer_id": customers[0],
        "trip_count": len(trips),
        "freight_total": round(sum(t.get("freight_amount", 0.0) for t in trips), 2),
        "halting_total": round(sum(t.get("halting_amount", 0.0) for t in trips), 2),
    }


@router.post("/trips/bulk-delete")
async def bulk_delete_trips(
    request: Request,
    payload: dict,
    user=Depends(get_current_user),
):
    """Iter58 P1 — Bulk delete selected trips.

    Required body: {trip_ids: [str], reason: str, force_invoiced: bool}
      * `reason` is MANDATORY (matches single-delete policy).
      * `force_invoiced=true` is required to delete any trip whose status is
        already 'invoiced' — this is the extra confirmation the user asked for.
      * Any invoice linked to a deleted trip is auto-recomputed.
    Returns per-trip results so the UI can report partial failures cleanly.
    """
    if not _has_perm(user, "delete_trip"):
        raise HTTPException(status_code=403, detail="Missing permission: delete_trip")
    trip_ids = list(payload.get("trip_ids") or [])
    reason = (payload.get("reason") or "").strip()
    force_invoiced = bool(payload.get("force_invoiced") or False)
    if not trip_ids:
        raise HTTPException(status_code=400, detail="trip_ids required")
    if len(trip_ids) > 500:
        raise HTTPException(status_code=400, detail="Cannot bulk-delete more than 500 trips at a time")
    if not reason:
        raise HTTPException(status_code=400, detail="Reason for deletion is required")
    cid = await _active_company_id(request, user)
    trips = await db.trips.find(
        {"id": {"$in": trip_ids}, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    ).to_list(len(trip_ids))
    found_ids = {t["id"] for t in trips}
    # Check invoiced protection
    invoiced_trips = [t for t in trips if t.get("status") == "invoiced"]
    if invoiced_trips and not force_invoiced:
        return {
            "ok": False,
            "requires_force": True,
            "invoiced_count": len(invoiced_trips),
            "detail": (
                f"{len(invoiced_trips)} of the selected trips are linked to an invoice. "
                "Pass force_invoiced=true to delete them (invoices will be recomputed)."
            ),
            "invoiced_ids": [t["id"] for t in invoiced_trips],
        }
    deleted, skipped, invoice_ids = [], [], set()
    for t in trips:
        try:
            await db.trips.delete_one({"id": t["id"], "user_id": user["user_id"], "company_id": cid})
            if t.get("invoice_id"):
                invoice_ids.add(t["invoice_id"])
            deleted.append(t["id"])
            await _log_audit(
                user, "trip", "delete", entity_id=t["id"],
                entity_ref=t.get("vehicle_number", ""), reason=reason,
                changes={"snapshot": {k: t.get(k) for k in ("date", "customer_id", "vehicle_number", "freight_amount", "invoice_id")},
                         "bulk": True},
            )
        except Exception as e:
            skipped.append({"trip_id": t["id"], "error": str(e)})
    # Recompute affected invoices once each
    for iid in invoice_ids:
        try:
            await _recompute_invoice(iid, user)
        except Exception:
            pass
    not_found = [tid for tid in trip_ids if tid not in found_ids]
    return {
        "ok": True,
        "deleted_count": len(deleted),
        "deleted_ids": deleted,
        "recomputed_invoices": list(invoice_ids),
        "skipped": skipped,
        "not_found": not_found,
    }


@router.delete("/trips/{tid}")
async def delete_trip(tid: str, request: Request, reason: str = "", user=Depends(get_current_user)):
    if not _has_perm(user, "delete_trip"):
        raise HTTPException(status_code=403, detail="Missing permission: delete_trip")
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="Reason for deletion is required")
    cid = await _active_company_id(request, user)
    existing = await db.trips.find_one({"id": tid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Trip not found")
    linked_invoice_id = existing.get("invoice_id")
    await db.trips.delete_one({"id": tid, "user_id": user["user_id"], "company_id": cid})
    # Iter61 · Phase C — Remove mirrored ledger entry (Trip = SSoT)
    try:
        from routers.driver_ledger import delete_trip_recovery_from_ledger
        await delete_trip_recovery_from_ledger(user["user_id"], cid, tid)
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning(f"ledger sync (delete) failed: {_e}")
    if linked_invoice_id:
        await _recompute_invoice(linked_invoice_id, user)
    await _log_audit(user, "trip", "delete", entity_id=tid, entity_ref=existing.get("vehicle_number", ""), reason=reason,
                     changes={"snapshot": {k: existing.get(k) for k in ("date", "customer_id", "vehicle_number", "freight_amount", "invoice_id")}})
    return {"ok": True, "linked_invoice_id": linked_invoice_id}


@router.post("/trips/{tid}/duplicate")
async def duplicate_trip(tid: str, request: Request, user=Depends(get_current_user)):
    """Clone an existing trip. Variable fields (date, tons, invoice link, status,
    supplier/customer advances, halting days, LR number) are reset so the user
    only needs to fill in vehicle/driver/date/tons for the new trip."""
    cid = await _active_company_id(request, user)
    src = await db.trips.find_one({"id": tid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
    if not src:
        raise HTTPException(status_code=404, detail="Trip not found")
    src.pop("id", None)
    src.pop("invoice_id", None)
    src["status"] = "pending"
    src["lr_number"] = ""
    src["date"] = now_utc().date().isoformat()
    # Reset one-off numeric fields but keep rate/route/product info
    for f in ("tons", "total_halting_days", "chargeable_halting_days", "halting_amount",
              "shortage_qty", "excess_qty", "shortage_amount", "excess_amount",
              "supplier_advance", "supplier_other_recoveries"):
        if f in src:
            src[f] = 0
    if isinstance(src.get("expenses"), dict):
        exp = src["expenses"]
        for f in ("cash_advance_received", "diesel_from_customer_qty",
                  "diesel_from_customer_rate", "diesel_from_customer_amount",
                  "diesel", "toll", "batta", "repair", "other", "firewood", "shortage_amount"):
            if f in exp:
                exp[f] = 0
    trip = Trip(**{k: v for k, v in src.items() if k in Trip.model_fields})
    trip = _compute_trip(trip)
    doc = trip.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.trips.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("user_id", None)
    await _log_audit(user, "trip", "create", entity_id=doc["id"], entity_ref=doc.get("vehicle_number", ""), reason=f"Duplicated from {tid}")
    return doc


@router.post("/trips/from-template/{tid}")
async def trip_from_template(tid: str, request: Request, user=Depends(get_current_user)):
    """Return a pre-populated Trip payload from a saved template. Client saves via POST /trips."""
    cid = await _active_company_id(request, user)
    tpl = await db.templates.find_one({"id": tid, "company_id": cid}, {"_id": 0, "user_id": 0})
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "customer_id": tpl.get("customer_id", ""),
        "from_location": tpl.get("from_location", ""),
        "to_location": tpl.get("to_location", ""),
        "load_details": tpl.get("load_details", ""),
        "product_type": tpl.get("product_type", ""),
        "round_trip_kms": tpl.get("round_trip_kms", 0),
        "freight_mode": tpl.get("freight_mode", "per_ton"),
        "rate_per_ton": tpl.get("rate_per_ton", 0),
        "rate_per_km_per_ton": tpl.get("rate_per_km_per_ton", 0),
        "fixed_amount": tpl.get("fixed_amount", 0),
        "hsn_sac": tpl.get("hsn_sac", "996791"),
        "halting_rate_per_day": tpl.get("halting_rate_per_day", 0),
        "notes": tpl.get("remarks", ""),
        "date": now_utc().date().isoformat(),
    }




@router.get("/trips/import/template")
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

@router.post("/trips/import")
async def trip_import(request: Request, file: UploadFile = File(...), user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
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
    customers = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0}).to_list(2000)
    cust_by_name = {c["name"].strip().lower(): c["id"] for c in customers}
    drivers = await db.drivers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0}).to_list(1000)
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
            cust_id = cust_by_name.get(cname.lower())
            if not cust_id:
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
                customer_id=cust_id,
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
            d["company_id"] = cid
            docs.append(d)
        except Exception as e:
            errors.append({"row": int(idx) + 2, "error": str(e)})

    if docs:
        await db.trips.insert_many(docs)
        inserted = len(docs)
    return {"inserted": inserted, "errors": errors, "total_rows": len(df)}

# ==================== Invoice Share (Public PDF) ====================

@router.post("/invoices/{iid}/share")
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

@router.get("/public/invoice/{token}/pdf")
async def public_invoice_pdf(token: str):
    inv = await db.invoices.find_one({"share_token": token}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    customer = await db.customers.find_one({"id": inv["customer_id"], "user_id": inv["user_id"]}, {"_id": 0}) or {}
    inv_company_id = inv.get("company_id", "")
    company = await db.companies.find_one({"id": inv_company_id, "user_id": inv["user_id"]}, {"_id": 0}) if inv_company_id else None
    company = company or await db.companies.find_one({"user_id": inv["user_id"], "is_default": True}, {"_id": 0}) or {}
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


@router.get("/trips/{tid}/ewaybill")
async def eway_bill(tid: str, user=Depends(get_current_user)):
    trip = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    customer = await db.customers.find_one({"id": trip["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
    trip_company_id = trip.get("company_id", "")
    company = await db.companies.find_one({"id": trip_company_id, "user_id": user["user_id"]}, {"_id": 0}) if trip_company_id else None
    company = company or await db.companies.find_one({"user_id": user["user_id"], "is_default": True}, {"_id": 0}) or {}

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


@router.post("/trips/lr/preview")
async def trip_lr_preview(payload: dict, user=Depends(get_current_user)):
    """Iter101 — Render an LR / Goods Consignment Note PDF from a DRAFT trip payload
    WITHOUT persisting anything. Used by the Trip Form to preview the LR before Save.

    The payload is the same shape the Trip Form POSTs to /api/trips. Missing
    `lr_number` renders as the placeholder "DRAFT" so users can verify layout
    even before a real LR series number is auto-assigned on the real save."""
    trip = dict(payload or {})
    if not trip.get("lr_number"):
        trip["lr_number"] = "DRAFT"
    # Resolve customer (best-effort — LR preview works even without a customer link)
    customer = {}
    cust_id = (trip.get("customer_id") or "").strip()
    if cust_id:
        customer = await db.customers.find_one(
            {"id": cust_id, "user_id": user["user_id"]}, {"_id": 0}
        ) or {}
    # Resolve company: explicit → active header → user default
    trip_company_id = (trip.get("company_id") or "").strip()
    company = None
    if trip_company_id:
        company = await db.companies.find_one(
            {"id": trip_company_id, "user_id": user["user_id"]}, {"_id": 0}
        )
    company = company or await db.companies.find_one(
        {"user_id": user["user_id"], "is_default": True}, {"_id": 0}
    ) or {}
    pdf_bytes = build_lr_pdf(company, customer, trip)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="LR_Preview.pdf"'},
    )


@router.get("/trips/{tid}/lr")
async def trip_lr_pdf(tid: str, user=Depends(get_current_user)):
    trip = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    # Auto-assign lr_number if missing (per-company LR series)
    if not trip.get("lr_number"):
        lr_num = await _next_lr_number(user["user_id"], trip.get("company_id", ""))
        await db.trips.update_one({"id": tid, "user_id": user["user_id"]}, {"$set": {"lr_number": lr_num}})
        trip["lr_number"] = lr_num
    customer = await db.customers.find_one({"id": trip["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
    trip_company_id = trip.get("company_id", "")
    company = await db.companies.find_one({"id": trip_company_id, "user_id": user["user_id"]}, {"_id": 0}) if trip_company_id else None
    company = company or await db.companies.find_one({"user_id": user["user_id"], "is_default": True}, {"_id": 0}) or {}
    pdf_bytes = build_lr_pdf(company, customer, trip)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{trip["lr_number"].replace("/", "_")}.pdf"'},
    )


@router.post("/trips/{tid}/share-lr")
async def share_lr_whatsapp(tid: str, request: Request, user=Depends(get_current_user)):
    """Generate the LR PDF, upload to object storage, return a public URL + WhatsApp-ready text.
    The trip list opens https://wa.me/?text=<encoded text with the pdf link>."""
    trip = await db.trips.find_one({"id": tid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not trip.get("lr_number"):
        lr_num = await _next_lr_number(user["user_id"], trip.get("company_id", ""))
        await db.trips.update_one({"id": tid, "user_id": user["user_id"]}, {"$set": {"lr_number": lr_num}})
        trip["lr_number"] = lr_num
    customer = await db.customers.find_one({"id": trip["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
    trip_company_id = trip.get("company_id", "")
    company = await db.companies.find_one({"id": trip_company_id, "user_id": user["user_id"]}, {"_id": 0}) if trip_company_id else None
    company = company or await db.companies.find_one({"user_id": user["user_id"], "is_default": True}, {"_id": 0}) or {}
    pdf_bytes = build_lr_pdf(company, customer, trip)

    # Upload to public storage bucket
    lr_safe = str(trip["lr_number"]).replace("/", "_")
    obj_path = f"lr_shares/{user['user_id']}/{tid}_{lr_safe}.pdf"
    try:
        from storage_client import put_object
        put_object(obj_path, pdf_bytes, "application/pdf")
    except Exception as e:
        logger.exception("LR upload failed")
        raise HTTPException(status_code=502, detail=f"LR upload failed: {e}")

    # Public retrieval goes through our GET /api/files/public/{path}
    frontend_base = os.environ.get("REACT_APP_BACKEND_URL")
    if not frontend_base:
        try:
            with open("/app/frontend/.env", "r") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        frontend_base = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
    if not frontend_base:
        frontend_base = str(request.base_url).rstrip("/")
    if not frontend_base.startswith("http"):
        frontend_base = f"https://{frontend_base}"
    public_url = f"{frontend_base.rstrip('/')}/api/files/public/{obj_path}"

    msg = (
        f"*LR from {company.get('name', 'Our Company')}*\n"
        f"LR No: {trip['lr_number']}\n"
        f"Date: {trip.get('date', '')}\n"
        f"Vehicle: {trip.get('vehicle_number', '')}\n"
        f"Load: {trip.get('load_details', '')} · {trip.get('tons', 0)} MT\n"
        f"From: {trip.get('from_location', '')}  →  To: {trip.get('to_location', '')}\n\n"
        f"Download LR PDF: {public_url}"
    )
    import urllib.parse
    return {
        "public_url": public_url,
        "whatsapp_text": msg,
        "whatsapp_url": f"https://wa.me/?text={urllib.parse.quote(msg)}",
        "lr_number": trip["lr_number"],
    }

# ==================== Audit Logs ====================



# ============================================================================
# Recurring Trip Suggestions (Iter34) — One-tap repeat
# ============================================================================

@router.get("/trips/recurring-suggestions")
async def recurring_suggestions(request: Request, user=Depends(get_current_user)):
    """Detect (customer × from × to) combos with ≥2 occurrences in the last 60 days.
    Return the top 5 suggestions with the most recent trip snapshot so the UI can offer 1-tap repeat."""
    cid = await _active_company_id(request, user)
    sixty_ago = (datetime.now(timezone.utc).date() - timedelta(days=60)).isoformat()
    trips = await db.trips.find(
        {"user_id": user["user_id"], "company_id": cid, "date": {"$gte": sixty_ago}},
        {"_id": 0}
    ).sort("date", -1).to_list(1000)
    buckets: dict = {}
    for t in trips:
        key = (t.get("customer_id") or "", (t.get("from_location") or "").strip().lower(), (t.get("to_location") or "").strip().lower())
        if not key[0] or not key[1] or not key[2]:
            continue
        b = buckets.setdefault(key, {"count": 0, "last": None, "avg_freight": 0.0, "sum_freight": 0.0})
        b["count"] += 1
        b["sum_freight"] += float(t.get("freight_amount", 0))
        if b["last"] is None or (t.get("date") or "") > (b["last"].get("date") or ""):
            b["last"] = t

    customers = {c["id"]: c["name"] for c in await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)}
    out = []
    for (cid_key, from_l, to_l), b in buckets.items():
        if b["count"] < 2:
            continue
        last = b["last"] or {}
        out.append({
            "customer_id": cid_key,
            "customer_name": customers.get(cid_key, "—"),
            "from_location": last.get("from_location") or from_l.title(),
            "to_location": last.get("to_location") or to_l.title(),
            "count_60d": b["count"],
            "avg_freight": round(b["sum_freight"] / b["count"], 2),
            "last_date": last.get("date"),
            "last_trip_id": last.get("id"),
            "vehicle_number": last.get("vehicle_number"),
            "load_details": last.get("load_details"),
            "tons": last.get("tons"),
            "rate_per_ton": last.get("rate_per_ton"),
            "freight_mode": last.get("freight_mode"),
        })
    out.sort(key=lambda x: (-x["count_60d"], x["last_date"] or ""), reverse=False)
    out.sort(key=lambda x: -x["count_60d"])
    return out[:5]


@router.post("/trips/quick-repeat/{last_trip_id}")
async def quick_repeat_trip(last_trip_id: str, request: Request, user=Depends(get_current_user)):
    """One-tap: clone the given (last) trip for today with a fresh id and blank lr_number."""
    src = await db.trips.find_one({"id": last_trip_id, "user_id": user["user_id"]}, {"_id": 0})
    if not src:
        raise HTTPException(status_code=404, detail="Source trip not found")
    cid = await _active_company_id(request, user)
    src.pop("id", None)
    src.pop("user_id", None)
    src["id"] = "trip_" + secrets.token_hex(8)
    src["date"] = datetime.now(timezone.utc).date().isoformat()
    src["lr_number"] = ""
    src["invoice_id"] = None
    src["status"] = "pending"
    src["amount_received"] = 0
    src["company_id"] = cid
    src["created_at"] = datetime.now(timezone.utc).isoformat()
    src["updated_at"] = src["created_at"]
    # Recompute using services
    try:
        model = Trip(**{k: v for k, v in src.items() if k in Trip.model_fields})
        model = _compute_trip(model)
        merged = model.model_dump()
        for k in ("id", "date", "lr_number", "invoice_id", "status", "amount_received", "company_id", "created_at", "updated_at"):
            merged[k] = src[k]
        src = merged
    except Exception:
        pass
    doc = {**src, "user_id": user["user_id"]}
    await db.trips.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("user_id", None)
    await _log_audit(user, "trip", "create", entity_id=doc["id"], entity_ref=f"quick-repeat from {last_trip_id}")
    return doc



# ============================================================================
# Iter53 — Single trip lookup (must be LAST to avoid shadowing literal routes)
# ============================================================================
@router.get("/trips/{tid}")
async def get_trip(tid: str, request: Request, user=Depends(get_current_user)):
    """Single trip GET by id — avoids the 2000-row cap on /trips for edit/view
    flows. Multi-company isolation enforced."""
    cid = await _active_company_id(request, user)
    doc = await db.trips.find_one(
        {"id": tid, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Trip not found")
    # Iter91 — lazy migration of legacy flat supplier_diesel / supplier_advance
    # into transaction-log entries on first view. Idempotent; only touches
    # supplier trips.
    doc, changed = _lazy_migrate_supplier_entries(doc, user["user_id"])
    if changed:
        try:
            await db.trips.update_one(
                {"id": tid, "user_id": user["user_id"], "company_id": cid},
                {"$set": {
                    "supplier_diesel_entries": doc.get("supplier_diesel_entries") or [],
                    "supplier_advance_entries": doc.get("supplier_advance_entries") or [],
                }},
            )
        except Exception as _e:
            logger.warning(f"lazy migrate persist failed: {_e}")
    return doc




# ---------------------------------------------------------------------------
# Iter91 — Supplier Diesel entries (multi-row)
# ---------------------------------------------------------------------------

@router.post("/trips/{tid}/supplier-diesel")
async def add_supplier_diesel_entry(tid: str, payload: dict, request: Request,
                                    user=Depends(get_current_user)):
    """Append a new Supplier Diesel entry to a supplier trip. Payload accepts
    `date, quantity, rate, amount, mode, reference, remarks`. If `amount` is
    0 but quantity & rate > 0, it auto-computes `qty × rate`."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await _load_supplier_trip(tid, uid, cid)
    doc, _ = _lazy_migrate_supplier_entries(doc, uid)
    qty = float(payload.get("quantity", 0) or 0)
    rate = float(payload.get("rate", 0) or 0)
    amt = float(payload.get("amount", 0) or 0)
    if amt <= 0 and qty > 0 and rate > 0:
        amt = round(qty * rate, 2)
    entry = {
        "id": new_id("sde_"),
        "date": (payload.get("date") or doc.get("date") or "")[:10],
        "quantity": qty, "rate": rate, "amount": round(amt, 2),
        "mode": str(payload.get("mode") or "").strip(),
        "reference": str(payload.get("reference") or "").strip(),
        "remarks": str(payload.get("remarks") or "").strip(),
        "created_at": now_utc().isoformat(), "created_by": uid,
        "modified_at": "", "modified_by": "",
        "deleted": False, "deleted_reason": "", "deleted_at": "", "deleted_by": "",
    }
    entries = list(doc.get("supplier_diesel_entries") or [])
    entries.append(entry)
    doc["supplier_diesel_entries"] = entries
    doc = await _persist_supplier_entries(tid, uid, cid, doc)
    await _log_audit(user, "trip", "supplier_diesel_add",
                     entity_id=tid, entity_ref=doc.get("vehicle_number", ""),
                     changes={"entry_id": entry["id"], "amount": entry["amount"]})
    return doc


@router.put("/trips/{tid}/supplier-diesel/{eid}")
async def edit_supplier_diesel_entry(tid: str, eid: str, payload: dict,
                                     request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await _load_supplier_trip(tid, uid, cid)
    doc, _ = _lazy_migrate_supplier_entries(doc, uid)
    entries = list(doc.get("supplier_diesel_entries") or [])
    idx = next((i for i, e in enumerate(entries) if e.get("id") == eid), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Diesel entry not found")
    old = entries[idx]
    if old.get("deleted"):
        raise HTTPException(status_code=400, detail="Cannot edit a deleted entry")
    qty = float(payload.get("quantity", old.get("quantity", 0)) or 0)
    rate = float(payload.get("rate", old.get("rate", 0)) or 0)
    if "amount" in payload:
        amt = float(payload.get("amount") or 0)
    else:
        amt = round(qty * rate, 2) if (qty > 0 and rate > 0) else float(old.get("amount", 0) or 0)
    entries[idx] = {
        **old,
        "date": (payload.get("date") or old.get("date") or "")[:10],
        "quantity": qty, "rate": rate, "amount": round(amt, 2),
        "mode": str(payload.get("mode") if payload.get("mode") is not None else old.get("mode") or "").strip(),
        "reference": str(payload.get("reference") if payload.get("reference") is not None else old.get("reference") or "").strip(),
        "remarks": str(payload.get("remarks") if payload.get("remarks") is not None else old.get("remarks") or "").strip(),
        "modified_at": now_utc().isoformat(), "modified_by": uid,
    }
    doc["supplier_diesel_entries"] = entries
    doc = await _persist_supplier_entries(tid, uid, cid, doc)
    await _log_audit(user, "trip", "supplier_diesel_edit",
                     entity_id=tid, entity_ref=doc.get("vehicle_number", ""),
                     changes={"entry_id": eid, "before": {k: old.get(k) for k in ("amount","quantity","rate","mode","reference")},
                              "after": {k: entries[idx].get(k) for k in ("amount","quantity","rate","mode","reference")}})
    return doc


@router.delete("/trips/{tid}/supplier-diesel/{eid}")
async def delete_supplier_diesel_entry(tid: str, eid: str, request: Request,
                                       reason: str = Query(""),
                                       user=Depends(get_current_user)):
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="Reason for deletion is required")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await _load_supplier_trip(tid, uid, cid)
    doc, _ = _lazy_migrate_supplier_entries(doc, uid)
    entries = list(doc.get("supplier_diesel_entries") or [])
    idx = next((i for i, e in enumerate(entries) if e.get("id") == eid), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Diesel entry not found")
    if entries[idx].get("deleted"):
        raise HTTPException(status_code=400, detail="Entry already deleted")
    entries[idx] = {
        **entries[idx],
        "deleted": True,
        "deleted_reason": reason.strip(),
        "deleted_at": now_utc().isoformat(),
        "deleted_by": uid,
    }
    doc["supplier_diesel_entries"] = entries
    doc = await _persist_supplier_entries(tid, uid, cid, doc)
    await _log_audit(user, "trip", "supplier_diesel_delete",
                     entity_id=tid, entity_ref=doc.get("vehicle_number", ""),
                     reason=reason.strip(),
                     changes={"entry_id": eid, "amount": entries[idx].get("amount")})
    return doc


# ---------------------------------------------------------------------------
# Iter91 — Supplier Advance entries (multi-row)
# ---------------------------------------------------------------------------

@router.post("/trips/{tid}/supplier-advance")
async def add_supplier_advance_entry(tid: str, payload: dict, request: Request,
                                     user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await _load_supplier_trip(tid, uid, cid)
    doc, _ = _lazy_migrate_supplier_entries(doc, uid)
    entry = {
        "id": new_id("sae_"),
        "date": (payload.get("date") or doc.get("date") or "")[:10],
        "amount": round(float(payload.get("amount", 0) or 0), 2),
        "mode": str(payload.get("mode") or "").strip(),
        "reference": str(payload.get("reference") or "").strip(),
        "remarks": str(payload.get("remarks") or "").strip(),
        "created_at": now_utc().isoformat(), "created_by": uid,
        "modified_at": "", "modified_by": "",
        "deleted": False, "deleted_reason": "", "deleted_at": "", "deleted_by": "",
    }
    entries = list(doc.get("supplier_advance_entries") or [])
    entries.append(entry)
    doc["supplier_advance_entries"] = entries
    doc = await _persist_supplier_entries(tid, uid, cid, doc)
    await _log_audit(user, "trip", "supplier_advance_add",
                     entity_id=tid, entity_ref=doc.get("vehicle_number", ""),
                     changes={"entry_id": entry["id"], "amount": entry["amount"]})
    return doc


@router.put("/trips/{tid}/supplier-advance/{eid}")
async def edit_supplier_advance_entry(tid: str, eid: str, payload: dict,
                                      request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await _load_supplier_trip(tid, uid, cid)
    doc, _ = _lazy_migrate_supplier_entries(doc, uid)
    entries = list(doc.get("supplier_advance_entries") or [])
    idx = next((i for i, e in enumerate(entries) if e.get("id") == eid), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Advance entry not found")
    old = entries[idx]
    if old.get("deleted"):
        raise HTTPException(status_code=400, detail="Cannot edit a deleted entry")
    entries[idx] = {
        **old,
        "date": (payload.get("date") or old.get("date") or "")[:10],
        "amount": round(float(payload.get("amount", old.get("amount", 0)) or 0), 2),
        "mode": str(payload.get("mode") if payload.get("mode") is not None else old.get("mode") or "").strip(),
        "reference": str(payload.get("reference") if payload.get("reference") is not None else old.get("reference") or "").strip(),
        "remarks": str(payload.get("remarks") if payload.get("remarks") is not None else old.get("remarks") or "").strip(),
        "modified_at": now_utc().isoformat(), "modified_by": uid,
    }
    doc["supplier_advance_entries"] = entries
    doc = await _persist_supplier_entries(tid, uid, cid, doc)
    await _log_audit(user, "trip", "supplier_advance_edit",
                     entity_id=tid, entity_ref=doc.get("vehicle_number", ""),
                     changes={"entry_id": eid,
                              "before": {k: old.get(k) for k in ("amount","mode","reference")},
                              "after": {k: entries[idx].get(k) for k in ("amount","mode","reference")}})
    return doc


@router.delete("/trips/{tid}/supplier-advance/{eid}")
async def delete_supplier_advance_entry(tid: str, eid: str, request: Request,
                                        reason: str = Query(""),
                                        user=Depends(get_current_user)):
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="Reason for deletion is required")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await _load_supplier_trip(tid, uid, cid)
    doc, _ = _lazy_migrate_supplier_entries(doc, uid)
    entries = list(doc.get("supplier_advance_entries") or [])
    idx = next((i for i, e in enumerate(entries) if e.get("id") == eid), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Advance entry not found")
    if entries[idx].get("deleted"):
        raise HTTPException(status_code=400, detail="Entry already deleted")
    entries[idx] = {
        **entries[idx],
        "deleted": True,
        "deleted_reason": reason.strip(),
        "deleted_at": now_utc().isoformat(),
        "deleted_by": uid,
    }
    doc["supplier_advance_entries"] = entries
    doc = await _persist_supplier_entries(tid, uid, cid, doc)
    await _log_audit(user, "trip", "supplier_advance_delete",
                     entity_id=tid, entity_ref=doc.get("vehicle_number", ""),
                     reason=reason.strip(),
                     changes={"entry_id": eid, "amount": entries[idx].get("amount")})
    return doc



# ---------------------------------------------------------------------------
# Iter99 · Phase 4 — Per-Field Override Audit Trail
# ---------------------------------------------------------------------------

_OVERRIDE_LABELS = {
    "freight_amount": "Freight",
    "freight_qty_used": "Freight Basis Qty",
    "shortage_amount": "Customer Shortage",
    "excess_amount": "Customer Excess",
    "supplier_shortage_deduction": "Supplier Shortage",
    "supplier_halting_amount": "Supplier Halting",
    "halting_amount": "Customer Halting",
    "supplier_freight": "Supplier Freight",
    "supplier_advance": "Supplier Advance",
    "supplier_diesel": "Supplier Diesel",
}


@router.post("/trips/{tid}/field-override")
async def log_field_override(tid: str, payload: dict, request: Request,
                             user=Depends(get_current_user)):
    """Record one per-field override event on a Trip.

    Body: { field, system_value, final_value, reason }
    Never mutates the underlying value — only appends to `field_overrides` so
    Accounts / Audit can reconcile.
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    field = str(payload.get("field") or "").strip()
    if not field:
        raise HTTPException(status_code=400, detail="field is required")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="reason is required")
    try:
        sys_v = float(payload.get("system_value") or 0)
        fin_v = float(payload.get("final_value") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="system_value / final_value must be numbers")

    doc = await db.trips.find_one({"id": tid, "user_id": uid, "company_id": cid},
                                  {"_id": 0, "user_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Trip not found")

    entry = {
        "id": new_id("fov_"),
        "field": field,
        "label": _OVERRIDE_LABELS.get(field, field.replace("_", " ").title()),
        "system_value": round(sys_v, 2),
        "final_value": round(fin_v, 2),
        "reason": reason,
        "modified_by": uid,
        "modified_at": now_utc().isoformat(),
        "trip_id": tid,
    }
    entries = list(doc.get("field_overrides") or [])
    entries.append(entry)
    await db.trips.update_one(
        {"id": tid, "user_id": uid, "company_id": cid},
        {"$set": {"field_overrides": entries}},
    )
    await _log_audit(user, "trip", "field_override_logged",
                     entity_id=tid, entity_ref=doc.get("vehicle_number", ""),
                     reason=reason, changes={"field": field, "system": sys_v, "final": fin_v})
    doc["field_overrides"] = entries
    return doc
