from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64

from db import db
from pydantic import BaseModel
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
async def list_customers(request: Request, user=Depends(get_current_user), with_balance: bool = False):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    docs = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(1000)
    if with_balance:
        invs = await db.invoices.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "customer_id": 1, "balance_due": 1, "total_amount": 1, "gross_total": 1, "amount_paid": 1}).to_list(5000)
        bal_map: dict = {}
        for i in invs:
            k = i.get("customer_id")
            if not k:
                continue
            bal_map[k] = bal_map.get(k, 0.0) + float(i.get("balance_due", 0))
        for c in docs:
            c["outstanding_balance"] = round(bal_map.get(c["id"], 0.0), 2)
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
    total_billed = sum(float(inv.get("total_amount", inv.get("gross_total", 0))) for inv in invoices)
    total_received = sum(float(inv.get("amount_paid", 0)) for inv in invoices)
    outstanding = sum(float(inv.get("balance_due", 0)) for inv in invoices)
    # Uninvoiced billable freight (pending trips)
    total_pending_freight = sum(_trip_billable(t) for t in trips if t.get("status") != "invoiced")

    # Aging buckets (based on invoice date vs today)
    today = datetime.now(timezone.utc).date()
    aging = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    for inv in invoices:
        bal = float(inv.get("balance_due", 0))
        if bal <= 0:
            continue
        try:
            dt = datetime.fromisoformat(inv.get("date", ""))
        except Exception:
            try:
                dt = datetime.strptime(inv.get("date", ""), "%Y-%m-%d")
            except Exception:
                continue
        days = (today - dt.date()).days
        if days <= 30:
            aging["0_30"] += bal
        elif days <= 60:
            aging["31_60"] += bal
        elif days <= 90:
            aging["61_90"] += bal
        else:
            aging["90_plus"] += bal
    aging = {k: round(v, 2) for k, v in aging.items()}

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
        "aging": aging,
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
                "amount": inv.get("total_amount") or inv.get("gross_total"),
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
    total_billed = sum(float(inv.get("total_amount", inv.get("gross_total", 0))) for inv in invoices)
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
            f"₹{float(i.get('total_amount') or i.get('gross_total', 0)):,.2f}", f"₹{float(i.get('amount_paid', 0)):,.2f}",
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


# ============================================================================
# Iter37 — Bulk WhatsApp Payment Reminders + Monthly Balances + Add Payment
# ============================================================================

@router.get("/customers/bulk-reminder")
async def bulk_reminder_previews(request: Request, user=Depends(get_current_user)):
    """Return one WhatsApp deeplink per customer with an outstanding balance."""
    import urllib.parse
    cid = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}

    # Build a customer_id -> {balance, oldest_days} map from unpaid invoices
    invs = await db.invoices.find(
        {"user_id": user["user_id"], "company_id": cid, "balance_due": {"$gt": 0}},
        {"_id": 0}
    ).to_list(5000)
    today = datetime.now(timezone.utc).date()
    per_cust: dict = {}
    for i in invs:
        k = i.get("customer_id")
        if not k:
            continue
        b = per_cust.setdefault(k, {"balance": 0.0, "invoices": [], "oldest_days": 0})
        b["balance"] += float(i.get("balance_due", 0))
        try:
            dt = datetime.fromisoformat(i["date"]).date()
        except Exception:
            try:
                dt = datetime.strptime(i["date"], "%Y-%m-%d").date()
            except Exception:
                dt = today
        days = (today - dt).days
        b["oldest_days"] = max(b["oldest_days"], days)
        b["invoices"].append({"number": i.get("invoice_number"), "amount": float(i.get("balance_due", 0)), "date": i.get("date"), "days": days})

    customers = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0}).to_list(2000)
    cust_map = {c["id"]: c for c in customers}

    out = []
    for kid, info in per_cust.items():
        cust = cust_map.get(kid) or {}
        top = sorted(info["invoices"], key=lambda x: -x["days"])[:3]
        msg_lines = [
            f"*Payment Reminder — {company.get('name', 'Our Company')}*",
            f"Dear {cust.get('name', 'Customer')},",
            "",
            f"You have an outstanding balance of *₹{info['balance']:,.2f}*.",
            f"Oldest bill is {info['oldest_days']} days old.",
            "",
            "Pending invoices:",
        ]
        for t in top:
            msg_lines.append(f"  · {t['number']} — ₹{t['amount']:,.2f} ({t['days']}d old)")
        msg_lines.append("")
        msg_lines.append("Please arrange payment at your earliest convenience.")
        msg = "\n".join(msg_lines)
        phone = (cust.get("phone") or "").strip().replace(" ", "").replace("-", "")
        # wa.me format: 91xxxxxxxxxx or empty (opens chat picker)
        wa_target = phone if phone else ""
        # Strip leading + / 0 / country prefix duplicates
        if wa_target.startswith("+"):
            wa_target = wa_target[1:]
        if len(wa_target) == 10:
            wa_target = "91" + wa_target
        out.append({
            "customer_id": kid,
            "customer_name": cust.get("name", ""),
            "phone": cust.get("phone", ""),
            "balance": round(info["balance"], 2),
            "oldest_days": info["oldest_days"],
            "invoice_count": len(info["invoices"]),
            "message": msg,
            "whatsapp_url": f"https://wa.me/{wa_target}?text={urllib.parse.quote(msg)}",
        })
    out.sort(key=lambda x: -x["balance"])
    return {"reminders": out, "total_customers": len(out), "total_outstanding": round(sum(r["balance"] for r in out), 2)}


@router.get("/customers/{cid}/monthly-balances")
async def monthly_balances(cid: str, request: Request, user=Depends(get_current_user)):
    """Aggregate customer transactions by YYYY-MM for the Monthly Balances tab."""
    company_id = await _active_company_id(request, user)
    trips = await db.trips.find({"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}, {"_id": 0, "date": 1, "freight_amount": 1, "tons": 1, "status": 1}).to_list(5000)
    invoices = await db.invoices.find({"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}, {"_id": 0, "date": 1, "total_amount": 1, "gross_total": 1, "amount_paid": 1, "balance_due": 1, "payments": 1}).to_list(5000)

    months: dict = {}

    def _key(dstr):
        return (dstr or "")[:7] or "unknown"

    for t in trips:
        k = _key(t.get("date"))
        m = months.setdefault(k, {"month": k, "trip_count": 0, "quantity": 0.0, "freight": 0.0, "billed": 0.0, "received": 0.0, "balance": 0.0})
        m["trip_count"] += 1
        m["quantity"] += float(t.get("tons", 0))
        m["freight"] += float(t.get("freight_amount", 0))
    for inv in invoices:
        k = _key(inv.get("date"))
        m = months.setdefault(k, {"month": k, "trip_count": 0, "quantity": 0.0, "freight": 0.0, "billed": 0.0, "received": 0.0, "balance": 0.0})
        m["billed"] += float(inv.get("total_amount", inv.get("gross_total", 0)))
        m["received"] += float(inv.get("amount_paid", 0))
        m["balance"] += float(inv.get("balance_due", 0))
        # count payments in the same month based on payment date
        for p in (inv.get("payments") or []):
            pk = _key(p.get("date"))
            if pk != k:
                pm = months.setdefault(pk, {"month": pk, "trip_count": 0, "quantity": 0.0, "freight": 0.0, "billed": 0.0, "received": 0.0, "balance": 0.0})
                # Don't double count; keep received in invoice-month
                pm.setdefault("_", 0)

    rows = list(months.values())
    for m in rows:
        for k in ("quantity", "freight", "billed", "received", "balance"):
            m[k] = round(m[k], 2)
    rows.sort(key=lambda x: x["month"], reverse=True)
    return {"months": rows}


class AddPaymentRequest(BaseModel):
    amount: float
    date: str = ""
    mode: str = "Cash"                        # Cash | Cheque | UPI | Bank Transfer | Fuel | Others
    note: str = ""
    received_by_driver: bool = False
    driver_id: Optional[str] = None
    allocations: Optional[list] = None        # [{invoice_id, amount}] — optional targeted allocation


@router.post("/customers/{cid}/add-payment")
async def add_customer_payment(cid: str, payload: AddPaymentRequest, request: Request, user=Depends(get_current_user)):
    """Add a payment against a customer. Allocates to invoices oldest-first (or per user allocations)."""
    company_id = await _active_company_id(request, user)
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    remaining = float(payload.amount)
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    pay_date = payload.date or datetime.now(timezone.utc).date().isoformat()

    # Get all invoices with balance, oldest first
    invs = await db.invoices.find(
        {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid, "balance_due": {"$gt": 0}},
        {"_id": 0}
    ).sort("date", 1).to_list(2000)

    # Build allocation map
    alloc_map: dict = {}
    if payload.allocations:
        for a in payload.allocations:
            if a.get("invoice_id"):
                alloc_map[a["invoice_id"]] = float(a.get("amount", 0))

    applied = []
    for inv in invs:
        if remaining <= 0:
            break
        # Use explicit allocation if provided; else oldest-first fill
        if payload.allocations:
            ask = alloc_map.get(inv["id"], 0)
            if ask <= 0:
                continue
            pay = min(ask, remaining, float(inv["balance_due"]))
        else:
            pay = min(remaining, float(inv["balance_due"]))
        if pay <= 0:
            continue
        note_bits = [payload.note] if payload.note else []
        if payload.received_by_driver and payload.driver_id:
            note_bits.append(f"received-by-driver:{payload.driver_id}")
        elif payload.received_by_driver:
            note_bits.append("received-by-driver")
        new_pay = {"amount": pay, "date": pay_date, "mode": payload.mode, "note": " · ".join(note_bits)}
        inv_payments = inv.get("payments") or []
        inv_payments.append(new_pay)
        new_paid = float(inv.get("amount_paid", 0)) + pay
        inv_total = float(inv.get("total_amount") or inv.get("gross_total") or inv.get("total") or 0)
        new_balance = inv_total - new_paid
        new_status = "paid" if new_balance <= 0.01 else ("partial" if new_paid > 0 else "unpaid")
        await db.invoices.update_one(
            {"id": inv["id"], "user_id": user["user_id"]},
            {"$set": {"payments": inv_payments, "amount_paid": round(new_paid, 2), "balance_due": round(max(new_balance, 0), 2), "payment_status": new_status}},
        )
        applied.append({"invoice_id": inv["id"], "invoice_number": inv.get("invoice_number"), "amount": pay})
        remaining -= pay

    await _log_audit(user, "customer_payment", "create", entity_id=cid, entity_ref=f"₹{payload.amount} via {payload.mode}")

    return {
        "applied": applied,
        "amount_total": payload.amount,
        "amount_unallocated": round(remaining, 2),   # will appear as advance if > 0 (owner can allocate later)
        "date": pay_date,
        "mode": payload.mode,
    }

