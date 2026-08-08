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

# ==================== Customers ====================

@router.get("/customers")
async def list_customers(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    docs = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(1000)
    return docs

@router.post("/customers")
async def create_customer(payload: Customer, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.customers.insert_one(doc)
    doc.pop("user_id", None)
    doc.pop("_id", None)
    return doc

@router.put("/customers/{cid}")
async def update_customer(cid: str, payload: Customer, request: Request, user=Depends(get_current_user)):
    company_id = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["id"] = cid
    doc["user_id"] = user["user_id"]
    doc["company_id"] = company_id
    await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"], "company_id": company_id},
        {"$set": doc},
    )
    doc.pop("user_id", None)
    return doc

@router.delete("/customers/{cid}")
async def delete_customer(cid: str, request: Request, user=Depends(get_current_user)):
    company_id = await _active_company_id(request, user)
    await db.customers.delete_one({"id": cid, "user_id": user["user_id"], "company_id": company_id})
    return {"ok": True}



# ============================================================================
# Customer Transaction History (Iter36) — myBillBook-style single-screen ledger
# ============================================================================

@router.get("/customers/{cid}/transactions")
async def customer_transactions(
    cid: str,
    request: Request,
    user=Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    invoice_status: Optional[str] = None,        # all | pending | invoiced
    payment_status: Optional[str] = None,        # all | unpaid | partial | paid
    vehicle_number: Optional[str] = None,
    product_id: Optional[str] = None,
    from_location: Optional[str] = None,
    to_location: Optional[str] = None,
    txn_type: Optional[str] = None,              # all | trip | invoice | payment
):
    company_id = await _active_company_id(request, user)
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Base trip filter
    trip_q: dict = {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}
    if date_from:
        trip_q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        trip_q.setdefault("date", {})["$lte"] = date_to
    if invoice_status and invoice_status != "all":
        trip_q["status"] = invoice_status
    if vehicle_number:
        trip_q["vehicle_number"] = vehicle_number.upper()
    if product_id:
        trip_q["product_id"] = product_id
    if from_location:
        trip_q["from_location"] = {"$regex": f"^{from_location}", "$options": "i"}
    if to_location:
        trip_q["to_location"] = {"$regex": f"^{to_location}", "$options": "i"}

    trips = await db.trips.find(trip_q, {"_id": 0, "user_id": 0}).sort([("date", -1), ("created_at", -1)]).to_list(2000)

    # Invoices for this customer
    inv_q: dict = {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}
    if date_from:
        inv_q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        inv_q.setdefault("date", {})["$lte"] = date_to
    if payment_status and payment_status != "all":
        inv_q["payment_status"] = payment_status
    invoices = await db.invoices.find(inv_q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)

    # Payments from invoices
    payments = []
    for inv in invoices:
        for p in (inv.get("payments") or []):
            payments.append({
                **p,
                "invoice_id": inv["id"],
                "invoice_number": inv.get("invoice_number", ""),
            })
    payments.sort(key=lambda p: p.get("date", ""), reverse=True)

    # Summary aggregates
    total_qty = sum(float(t.get("tons", 0)) for t in trips)
    total_freight = sum(float(t.get("freight_amount", 0)) for t in trips)
    total_diesel_received = sum(float(t.get("customer_diesel_received", 0)) for t in trips)
    total_advances = sum(float(t.get("customer_advance_received", 0)) for t in trips)
    total_shortage = sum(float(t.get("shortage_amount", 0)) for t in trips)
    total_excess = sum(float(t.get("excess_amount", 0)) for t in trips)
    total_halting = sum(float(t.get("halting_amount", 0)) for t in trips)
    total_billed = sum(float(inv.get("total", 0)) for inv in invoices)
    total_received = sum(float(inv.get("amount_paid", 0)) for inv in invoices)
    outstanding = sum(float(inv.get("balance_due", 0)) for inv in invoices)
    # Uninvoiced billable freight (pending trips)
    total_pending_freight = sum(_trip_billable(t) for t in trips if t.get("status") != "invoiced")

    summary = {
        "trip_count": len(trips),
        "total_qty": round(total_qty, 3),
        "total_freight": round(total_freight, 2),
        "total_diesel_received": round(total_diesel_received, 2),
        "total_advances": round(total_advances, 2),
        "total_shortage": round(total_shortage, 2),
        "total_excess": round(total_excess, 2),
        "total_halting": round(total_halting, 2),
        "total_billed": round(total_billed, 2),
        "total_received": round(total_received, 2),
        "outstanding": round(outstanding, 2),
        "total_pending_uninvoiced": round(total_pending_freight, 2),
        "invoice_count": len(invoices),
        "payment_count": len(payments),
    }

    # Unified transaction list (sorted DESC by date)
    txns: list = []
    if not txn_type or txn_type in ("all", "trip"):
        for t in trips:
            txns.append({
                "type": "trip",
                "date": t.get("date"),
                "id": t.get("id"),
                "ref": t.get("lr_number") or "—",
                "vehicle_number": t.get("vehicle_number"),
                "driver_name": t.get("driver_name"),
                "from_location": t.get("from_location"),
                "to_location": t.get("to_location"),
                "load_details": t.get("load_details"),
                "tons": t.get("tons"),
                "amount": t.get("freight_amount"),
                "customer_diesel_received": t.get("customer_diesel_received", 0),
                "customer_advance_received": t.get("customer_advance_received", 0),
                "shortage_amount": t.get("shortage_amount", 0),
                "excess_amount": t.get("excess_amount", 0),
                "halting_amount": t.get("halting_amount", 0),
                "status": t.get("status"),   # pending | invoiced
                "invoice_id": t.get("invoice_id"),
                "created_at": t.get("created_at"),
            })
    if not txn_type or txn_type in ("all", "invoice"):
        for inv in invoices:
            txns.append({
                "type": "invoice",
                "date": inv.get("date"),
                "id": inv.get("id"),
                "ref": inv.get("invoice_number"),
                "amount": inv.get("total"),
                "amount_paid": inv.get("amount_paid", 0),
                "balance_due": inv.get("balance_due", 0),
                "status": inv.get("payment_status"),   # unpaid | partial | paid
                "due_date": inv.get("due_date"),
                "created_at": inv.get("created_at"),
            })
    if not txn_type or txn_type in ("all", "payment"):
        for p in payments:
            txns.append({
                "type": "payment",
                "date": p.get("date"),
                "id": f"{p.get('invoice_id')}_{p.get('date')}_{p.get('amount')}",
                "ref": p.get("invoice_number"),
                "amount": p.get("amount"),
                "mode": p.get("mode"),
                "note": p.get("note"),
                "invoice_id": p.get("invoice_id"),
                "status": "received",
            })
    txns.sort(key=lambda t: (t.get("date") or "", t.get("created_at") or ""), reverse=True)

    return {
        "customer": customer,
        "summary": summary,
        "transactions": txns,
        "trips": trips,
        "invoices": invoices,
        "payments": payments,
    }


@router.get("/customers/{cid}/statement.pdf")
async def customer_statement_pdf(
    cid: str,
    request: Request,
    user=Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    company_id = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": company_id, "user_id": user["user_id"]}, {"_id": 0}) or {}
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Reuse the aggregation
    trip_q: dict = {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}
    if date_from:
        trip_q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        trip_q.setdefault("date", {})["$lte"] = date_to
    trips = await db.trips.find(trip_q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)
    invoices = await db.invoices.find({"user_id": user["user_id"], "company_id": company_id, "customer_id": cid, **({"date": trip_q["date"]} if "date" in trip_q else {})}, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)

    total_qty = sum(float(t.get("tons", 0)) for t in trips)
    total_freight = sum(float(t.get("freight_amount", 0)) for t in trips)
    total_billed = sum(float(inv.get("total", 0)) for inv in invoices)
    total_received = sum(float(inv.get("amount_paid", 0)) for inv in invoices)
    outstanding = sum(float(inv.get("balance_due", 0)) for inv in invoices)

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story: list = []
    title_st = ParagraphStyle("t", parent=styles["Title"], fontSize=15, leading=18)
    hdr_st = ParagraphStyle("h", parent=styles["Normal"], fontSize=10, textColor=colors.grey)

    story.append(Paragraph(f"<b>{company.get('name', '')}</b>", title_st))
    story.append(Paragraph(f"Customer Statement — {customer.get('name', '')}", hdr_st))
    if date_from or date_to:
        story.append(Paragraph(f"Period: {date_from or 'all'} to {date_to or 'today'}", hdr_st))
    story.append(Spacer(1, 6))

    # Summary block
    smy = [
        ["Trips", str(len(trips)), "Qty (MT)", f"{total_qty:,.3f}"],
        ["Freight Booked", f"₹{total_freight:,.2f}", "Amount Billed", f"₹{total_billed:,.2f}"],
        ["Amount Received", f"₹{total_received:,.2f}", "Outstanding", f"₹{outstanding:,.2f}"],
    ]
    st = Table(smy, hAlign="LEFT", colWidths=[35 * mm, 45 * mm, 35 * mm, 45 * mm])
    st.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
    ]))
    story.append(st)
    story.append(Spacer(1, 12))

    # Trip table
    story.append(Paragraph("<b>Trip Sheets</b>", styles["Heading3"]))
    trip_rows = [["Date", "LR No.", "Vehicle", "Route", "MT", "Freight", "Status"]]
    for t in trips:
        trip_rows.append([
            t.get("date", ""), t.get("lr_number", "") or "—", t.get("vehicle_number", ""),
            f"{t.get('from_location', '') or '?'} → {t.get('to_location', '') or '?'}",
            f"{float(t.get('tons', 0)):.2f}",
            f"₹{float(t.get('freight_amount', 0)):,.2f}",
            t.get("status", "").upper(),
        ])
    tt = Table(trip_rows, hAlign="LEFT", repeatRows=1, colWidths=[22 * mm, 26 * mm, 24 * mm, 44 * mm, 14 * mm, 26 * mm, 18 * mm])
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ALIGN", (4, 0), (5, -1), "RIGHT"),
    ]))
    story.append(tt)
    story.append(Spacer(1, 10))

    # Invoice table
    story.append(Paragraph("<b>Invoices</b>", styles["Heading3"]))
    inv_rows = [["Date", "Invoice #", "Total", "Paid", "Balance", "Status"]]
    for i in invoices:
        inv_rows.append([
            i.get("date", ""), i.get("invoice_number", ""),
            f"₹{float(i.get('total', 0)):,.2f}", f"₹{float(i.get('amount_paid', 0)):,.2f}",
            f"₹{float(i.get('balance_due', 0)):,.2f}", str(i.get("payment_status", "")).upper(),
        ])
    it = Table(inv_rows, hAlign="LEFT", repeatRows=1, colWidths=[22 * mm, 30 * mm, 28 * mm, 28 * mm, 28 * mm, 22 * mm])
    it.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ALIGN", (2, 0), (4, -1), "RIGHT"),
    ]))
    story.append(it)

    doc.build(story)
    buf.seek(0)
    fname = f"statement_{(customer.get('name', 'customer')).replace(' ', '_')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{fname}"'})


def _public_base_url(request):
    """Return the public HTTPS base URL for building share links. Reads frontend/.env if backend env is missing."""
    url = os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get("PUBLIC_BASE_URL")
    if not url:
        try:
            with open("/app/frontend/.env", "r") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
    if not url:
        url = str(request.base_url).rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"
    return url.rstrip("/")


@router.post("/customers/{cid}/share-statement")
async def share_customer_statement(
    cid: str,
    request: Request,
    user=Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Uploads the customer statement PDF to public storage and returns a WhatsApp deeplink."""
    # Build the PDF using the same route logic then persist to storage.
    resp = await customer_statement_pdf(cid, request, user, date_from, date_to)
    # Read bytes back from the StreamingResponse
    body_bytes = b""
    async for chunk in resp.body_iterator:
        body_bytes += chunk

    company_id = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": company_id, "user_id": user["user_id"]}, {"_id": 0}) or {}
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0}) or {}

    obj_path = f"lr_shares/{user['user_id']}/statement_{cid}_{secrets.token_hex(4)}.pdf"
    try:
        from storage_client import put_object
        put_object(obj_path, body_bytes, "application/pdf")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upload failed: {e}")

    frontend_base = _public_base_url(request)
    public_url = f"{frontend_base}/api/files/public/{obj_path}"

    msg = (
        f"*Customer Statement — {company.get('name', 'Our Company')}*\n"
        f"To: {customer.get('name', '')}\n"
        f"Period: {date_from or 'all'} → {date_to or 'today'}\n\n"
        f"Download statement PDF: {public_url}"
    )
    import urllib.parse
    return {
        "public_url": public_url,
        "whatsapp_url": f"https://wa.me/?text={urllib.parse.quote(msg)}",
        "whatsapp_text": msg,
    }
