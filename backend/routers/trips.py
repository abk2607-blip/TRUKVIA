from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
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


@router.get("/trips")
async def list_trips(request: Request, user=Depends(get_current_user), customer_id: Optional[str] = None, status: Optional[str] = None):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    q = {"user_id": user["user_id"], "company_id": cid}
    if customer_id:
        q["customer_id"] = customer_id
    if status:
        q["status"] = status
    docs = await db.trips.find(q, {"_id": 0, "user_id": 0}).sort([("date", -1), ("created_at", -1)]).to_list(2000)
    return docs

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
    await db.trips.insert_one(doc)
    doc.pop("user_id", None)
    doc.pop("_id", None)
    await _log_audit(user, "trip", "create", entity_id=doc["id"], entity_ref=doc.get("vehicle_number", ""))
    return doc

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
    await db.trips.update_one({"id": tid, "user_id": user["user_id"], "company_id": cid}, {"$set": doc})
    if existing.get("invoice_id"):
        await _recompute_invoice(existing["invoice_id"], user)
    changes = _diff_dict(existing, doc, ["freight_amount", "tons", "rate_per_ton", "supplier_freight", "total_expense", "profit", "vehicle_number", "vehicle_type"])
    await _log_audit(user, "trip", "update", entity_id=tid, entity_ref=doc.get("vehicle_number", ""), changes=changes)
    doc.pop("user_id", None)
    return doc

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
    return doc

