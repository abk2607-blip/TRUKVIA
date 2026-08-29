from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64

import logging
from db import db
logger = logging.getLogger(__name__)
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

from pdf import build_invoice_pdf
from storage_client import put_object, APP_NAME

@router.get("/invoices")
async def list_invoices(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    docs = await db.invoices.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).sort("created_at", -1).to_list(1000)
    return docs

@router.get("/invoices/overdue")
async def list_overdue_invoices(request: Request, days: int = 30, user=Depends(get_current_user)):
    """List invoices with outstanding balance older than `days` days."""
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    cutoff = (now_utc().date() - timedelta(days=days)).isoformat()
    docs = await db.invoices.find({
        "user_id": uid,
        "company_id": cid,
        "balance_due": {"$gt": 0.01},
        "invoice_date": {"$lte": cutoff},
    }, {"_id": 0, "user_id": 0}).sort("invoice_date", 1).to_list(500)
    customers = await db.customers.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(2000)
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

@router.get("/invoices/{iid}")
async def get_invoice(iid: str, user=Depends(get_current_user)):
    # Iter44: silently re-derive from linked trips so stale invoices auto-heal
    # (fixes case where trip halting/shortage were added AFTER invoice creation).
    try:
        await _recompute_invoice(iid, user)
    except Exception:
        pass
    doc = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return doc


@router.get("/invoices/{iid}/ship-to")
async def get_invoice_ship_to(iid: str, user=Depends(get_current_user)):
    """Iter127c-invoice-shipto v3 (Feb 2026 · KOLVEKAR LOGISTICS UAT).

    Returns the SAME resolved Ship-To that the invoice PDF uses, so the
    Invoice Preview can render an identical header. See
    `ship_to_resolver.resolve_invoice_ship_to` for the guarded rules.

    Read-only: never writes an inferred ship_site_id back to the trip.
    """
    from ship_to_resolver import resolve_invoice_ship_to
    inv = await db.invoices.find_one(
        {"id": iid, "user_id": user["user_id"]},
        {"_id": 0, "user_id": 0},
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    customer = await db.customers.find_one(
        {"id": inv.get("customer_id"), "user_id": user["user_id"]},
        {"_id": 0, "user_id": 0},
    ) or {}
    trip_ids = inv.get("trip_ids") or []
    trips = await db.trips.find(
        {"id": {"$in": trip_ids}, "user_id": user["user_id"]},
        {"_id": 0, "user_id": 0},
    ).to_list(1000) if trip_ids else []
    trip_by_id = {t.get("id"): t for t in trips}
    ordered_trips = [trip_by_id[t] for t in trip_ids if t in trip_by_id]
    result = resolve_invoice_ship_to(customer, ordered_trips)
    # Identity is a tuple — JSON-serialize as a list.
    for p in result["per_trip"]:
        p["identity"] = list(p["identity"])
    return result

@router.post("/invoices")
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
        # Iter86 — Historical trips can never be selected for a new live invoice.
        if t.get("is_historical") or t.get("status") == "archived_historical":
            raise HTTPException(
                status_code=400,
                detail=f"Trip {t['id']} is a historical import and cannot be added to a live invoice",
            )

    subtotal = round(sum(_trip_billable(t) for t in trips), 2)
    freight_total = round(sum(t.get("freight_amount", 0.0) for t in trips), 2)
    halting_total = round(sum(t.get("halting_amount", 0.0) for t in trips), 2)
    excess_total = round(sum(t.get("excess_amount", 0.0) for t in trips), 2)
    shortage_total = round(
        sum(t.get("shortage_amount", 0.0) + (t.get("expenses") or {}).get("shortage_amount", 0.0) for t in trips), 2,
    )
    diesel_deduction_total = round(sum(
        (
            sum(float(r.get("amount") or 0) for r in (t.get("customer_receipts") or []) if (r.get("type") or "").lower() == "diesel")
            if (t.get("customer_receipts") or []) else float((t.get("expenses") or {}).get("diesel_from_customer_amount", 0.0))
        )
        for t in trips
    ), 2)
    advance_deduction_total = round(sum(
        (
            sum(float(r.get("amount") or 0) for r in (t.get("customer_receipts") or []) if (r.get("type") or "").lower() == "advance")
            if (t.get("customer_receipts") or []) else float((t.get("expenses") or {}).get("cash_advance_received", 0.0))
        )
        for t in trips
    ), 2)
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
        diesel_deduction_total=diesel_deduction_total,
        advance_deduction_total=advance_deduction_total,
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


@router.put("/invoices/{iid}")
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
        inv_company_id = updated.get("company_id", "")
        company = await db.companies.find_one({"id": inv_company_id, "user_id": user["user_id"]}, {"_id": 0}) if inv_company_id else None
        company = company or await db.companies.find_one({"user_id": user["user_id"], "is_default": True}, {"_id": 0}) or {}
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

@router.delete("/invoices/{iid}")
async def delete_invoice(iid: str, reason: str = "", user=Depends(get_current_user)):
    if not _has_perm(user, "delete_invoice"):
        raise HTTPException(status_code=403, detail="Missing permission: delete_invoice")
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="Reason for deletion is required")
    doc = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    # Iter132a · Block deletion while any non-cancelled CN/DN references this invoice.
    linked = await db.credit_debit_notes.count_documents({
        "user_id": user["user_id"], "invoice_id": iid,
        "status": {"$in": ["draft", "issued"]},
    })
    if linked:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete — {linked} active Credit/Debit Note(s) reference this invoice. Cancel the notes first.",
        )
    await db.trips.update_many(
        {"user_id": user["user_id"], "id": {"$in": doc.get("trip_ids", [])}},
        {"$set": {"status": "pending", "invoice_id": None}},
    )
    await db.invoices.delete_one({"id": iid, "user_id": user["user_id"]})
    await _log_audit(user, "invoice", "delete", entity_id=iid, entity_ref=doc.get("invoice_number", ""),
                     reason=reason, changes={"snapshot": {k: doc.get(k) for k in ("invoice_number", "customer_id", "total_amount", "amount_paid", "trip_ids")}})
    return {"ok": True}


@router.post("/invoices/{iid}/payments")
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

@router.get("/invoices/{iid}/pdf")
async def invoice_pdf(iid: str, user=Depends(get_current_user)):
    # Iter44: auto-recompute so stale halting/shortage/receipts pull latest trip data
    try:
        await _recompute_invoice(iid, user)
    except Exception:
        pass
    inv = await db.invoices.find_one({"id": iid, "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    customer = await db.customers.find_one({"id": inv["customer_id"], "user_id": user["user_id"]}, {"_id": 0}) or {}
    inv_company_id = inv.get("company_id", "")
    company = await db.companies.find_one({"id": inv_company_id, "user_id": user["user_id"]}, {"_id": 0}) if inv_company_id else None
    company = company or await db.companies.find_one({"user_id": user["user_id"], "is_default": True}, {"_id": 0}) or {}
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

