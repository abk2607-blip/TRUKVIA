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

@router.get("/drivers")
async def list_drivers(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])
    drivers = await db.drivers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "user_id": 0}).to_list(1000)
    # Attach stats (trips scoped to same company)
    trips = await db.trips.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0}).to_list(5000)
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

@router.post("/drivers")
async def create_driver(payload: Driver, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.drivers.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.put("/drivers/{did}")
async def update_driver(did: str, payload: Driver, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    payload.id = did
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.drivers.update_one({"id": did, "user_id": user["user_id"], "company_id": cid}, {"$set": doc})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc

@router.delete("/drivers/{did}")
async def delete_driver(did: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.drivers.delete_one({"id": did, "user_id": user["user_id"], "company_id": cid})
    return {"ok": True}


@router.get("/drivers/{did}/trips")
async def driver_trip_history(
    did: str, request: Request, user=Depends(get_current_user),
    date_from: str = "", date_to: str = "",
    limit: int = 200, offset: int = 0,
):
    """Iter60 · Phase B — Driver Trip History.

    Trip is the SOURCE OF TRUTH: this endpoint reads directly from the
    `trips` collection filtered by `driver_id`. No duplicate storage.

    Company-scoped. Historical shortage-policy snapshot on each trip
    (`driver_recovery`) is passed through as-is — Trip edits update the
    derived system values but never re-resolve the policy.
    """
    cid = await _active_company_id(request, user)
    # Verify driver exists in this company (privacy + 404 clarity)
    drv = await db.drivers.find_one(
        {"id": did, "user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    )
    if not drv:
        raise HTTPException(status_code=404, detail="Driver not found")
    q = {"user_id": user["user_id"], "company_id": cid, "driver_id": did}
    if date_from or date_to:
        rng = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to
        q["date"] = rng
    total = await db.trips.count_documents(q)
    trips = await (db.trips.find(q, {"_id": 0, "user_id": 0})
                   .sort([("date", -1), ("created_at", -1)])
                   .skip(max(0, offset)).limit(min(max(1, limit), 500))
                   .to_list(min(max(1, limit), 500)))
    # Denormalise customer names + roll up totals for the header stat strip
    cust_ids = list({t.get("customer_id") for t in trips if t.get("customer_id")})
    cust_map = {}
    if cust_ids:
        c_docs = await db.customers.find(
            {"id": {"$in": cust_ids}, "user_id": user["user_id"]},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(cust_ids))
        cust_map = {c["id"]: c["name"] for c in c_docs}
    # Build the requested trip-history columns per row
    rows = []
    tot_shortage_kg = tot_excess_kg = tot_recovery = 0.0
    for t in trips:
        dr = t.get("driver_recovery") or {}
        recovery = float(dr.get("final_recovery_amount") or 0)
        tot_recovery += recovery
        shortage_kg = float(dr.get("actual_shortage_kg") or (t.get("shortage_qty") or 0) * 1000)
        excess_kg = round(float(t.get("excess_qty") or 0) * 1000, 3)
        tot_shortage_kg += shortage_kg
        tot_excess_kg += excess_kg
        rows.append({
            "trip_id": t["id"],
            "date": t.get("date"),
            "trip_number": t.get("trip_number") or "",
            "lr_number": t.get("lr_number") or "",
            "vehicle_number": t.get("vehicle_number") or "",
            "customer_id": t.get("customer_id"),
            "customer_name": cust_map.get(t.get("customer_id"), ""),
            "loading_point": t.get("from_location") or t.get("supplier_loading_point") or "",
            "unloading_point": t.get("to_location") or t.get("supplier_unloading_point") or "",
            "product": t.get("load_details") or "",
            "loaded_qty_mt": t.get("tons") or 0,
            "unloaded_qty_mt": t.get("unloaded_qty") or 0,
            "shortage_qty_kg": shortage_kg,
            "excess_qty_kg": excess_kg,
            "product_rate_per_mt": t.get("product_rate_per_mt") or 0,
            "freight_amount": t.get("freight_amount") or 0,
            "status": t.get("status") or "pending",
            # Historical policy snapshot — MUST be shown as-is (never re-resolved)
            "driver_recovery": {
                "policy_id": dr.get("policy_id"),
                "policy_version": dr.get("policy_version"),
                "policy_name": dr.get("policy_name"),
                "allowed_limit_kg": dr.get("allowed_limit_kg"),
                "actual_shortage_kg": dr.get("actual_shortage_kg"),
                "system_recoverable_shortage_kg": dr.get("system_recoverable_shortage_kg"),
                "system_recovery_amount": dr.get("system_recovery_amount"),
                "final_recovery_amount": dr.get("final_recovery_amount"),
                "override": dr.get("override"),
                "policy_missing": dr.get("policy_missing", False),
            } if dr else None,
        })
    return {
        "driver": {"id": drv["id"], "name": drv["name"], "phone": drv.get("phone")},
        "total": total,
        "limit": min(max(1, limit), 500),
        "offset": max(0, offset),
        "totals": {
            "shortage_kg": round(tot_shortage_kg, 3),
            "excess_kg": round(tot_excess_kg, 3),
            "recovery_amount": round(tot_recovery, 2),
            "trip_count": len(rows),
        },
        "trips": rows,
    }


@router.get("/drivers/{did}/trips/export")
async def driver_trip_history_export(
    did: str, request: Request, user=Depends(get_current_user),
    format: str = "csv", date_from: str = "", date_to: str = "",
):
    """Iter62 · Priority 3 — Export Driver Trip History as CSV or PDF.

    Returns the same rows shown in the UI table. Range-filtered by the
    same date_from/date_to arguments.
    """
    fmt = (format or "csv").lower()
    if fmt not in ("csv", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'pdf'")
    # Reuse the same aggregation path — pull up to 5000 trips for export
    inner = await driver_trip_history(did, request, user, date_from, date_to, 5000, 0)
    drv = inner["driver"]
    trips = inner["trips"]
    totals = inner["totals"]
    company = await db.companies.find_one(
        {"id": (await _active_company_id(request, user)), "user_id": user["user_id"]},
        {"_id": 0}) or {}
    fname = f"driver-trips-{drv['name'].replace(' ', '_')}-{(date_from or 'all')}_to_{(date_to or 'now')}"
    if fmt == "csv":
        import csv as _csv
        buf = io.StringIO()
        w = _csv.writer(buf)
        w.writerow([f"Driver Trip History — {drv['name']}"])
        w.writerow([f"Company: {company.get('name','')}",
                    f"Period: {date_from or '—'} to {date_to or '—'}"])
        w.writerow([f"Total Trips: {totals['trip_count']}",
                    f"Shortage: {totals['shortage_kg']:.1f} KG",
                    f"Excess: {totals['excess_kg']:.1f} KG",
                    f"Recovery: {totals['recovery_amount']:.2f}"])
        w.writerow([])
        w.writerow([
            "Date", "LR", "Trip #", "Vehicle", "Customer",
            "Loading Point", "Unloading Point", "Product",
            "Loaded MT", "Unloaded MT", "Shortage KG", "Excess KG",
            "Product Rate", "Freight Amount", "Driver Recovery", "Policy",
        ])
        for r in trips:
            dr = r.get("driver_recovery") or {}
            w.writerow([
                r.get("date", ""), r.get("lr_number", ""), r.get("trip_number", ""),
                r.get("vehicle_number", ""), r.get("customer_name", ""),
                r.get("loading_point", ""), r.get("unloading_point", ""),
                r.get("product", ""),
                f"{r.get('loaded_qty_mt', 0)}", f"{r.get('unloaded_qty_mt', 0)}",
                f"{r.get('shortage_qty_kg', 0):.2f}", f"{r.get('excess_qty_kg', 0):.2f}",
                f"{r.get('product_rate_per_mt', 0)}", f"{r.get('freight_amount', 0):.2f}",
                f"{dr.get('final_recovery_amount', 0):.2f}" if dr else "0.00",
                (dr.get("policy_name") or "—") if dr else "—",
            ])
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
        )
    # PDF
    pdf_bytes = _build_trip_history_pdf(company, drv, trips, totals, date_from, date_to)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}.pdf"'},
    )


def _build_trip_history_pdf(company, driver, trips, totals, date_from, date_to):
    from io import BytesIO
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm,
        title=f"Driver Trip History — {driver.get('name','')}",
    )
    styles = getSampleStyleSheet()
    story = []
    C_INK = colors.HexColor("#0F172A")
    C_MUTED = colors.HexColor("#64748B")
    C_LINE = colors.HexColor("#E2E8F0")
    C_HEAD = colors.HexColor("#1E293B")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14, textColor=C_INK, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=C_MUTED)
    story.append(Paragraph(f"<b>{company.get('name','—')}</b>", h1))
    story.append(Paragraph(
        f"Driver Trip History — <b>{driver.get('name','')}</b> ({driver.get('phone','—')}) · "
        f"Period: {date_from or '—'} to {date_to or '—'}", small))
    story.append(Spacer(1, 4))
    # Summary strip
    summary = [["Trips", "Shortage KG", "Excess KG", "Recovery"],
               [str(totals["trip_count"]),
                f"{totals['shortage_kg']:.1f}", f"{totals['excess_kg']:.1f}",
                f"₹ {totals['recovery_amount']:,.2f}"]]
    ts = Table(summary, colWidths=[30*mm, 30*mm, 30*mm, 40*mm])
    ts.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("TEXTCOLOR", (0,0), (-1,0), C_MUTED),
        ("FONTNAME", (0,1), (-1,1), "Helvetica-Bold"),
        ("LINEBELOW", (0,0), (-1,0), 0.25, C_LINE),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(ts)
    story.append(Spacer(1, 6))
    # Trip rows
    header = ["Date", "LR", "Vehicle", "Customer",
              "Loading → Unloading", "Product",
              "Ld MT", "Ul MT", "Short KG", "Exc KG",
              "Rate", "Freight", "Recovery"]
    rows = [header]
    for r in trips:
        dr = r.get("driver_recovery") or {}
        rows.append([
            r.get("date", ""), r.get("lr_number", "") or "—",
            r.get("vehicle_number", ""),
            (r.get("customer_name", "") or "")[:22],
            f"{(r.get('loading_point','') or '—')[:12]} → {(r.get('unloading_point','') or '—')[:12]}",
            (r.get("product", "") or "")[:14],
            f"{r.get('loaded_qty_mt', 0)}", f"{r.get('unloaded_qty_mt', 0)}",
            f"{r.get('shortage_qty_kg', 0):.1f}", f"{r.get('excess_qty_kg', 0):.1f}",
            f"{r.get('product_rate_per_mt', 0)}",
            f"{r.get('freight_amount', 0):,.0f}",
            f"{dr.get('final_recovery_amount', 0):,.0f}" if dr else "0",
        ])
    if len(rows) == 1:
        rows.append(["—"] * 13)
    col_w = [20*mm, 20*mm, 22*mm, 30*mm, 45*mm, 22*mm, 12*mm, 12*mm, 15*mm, 15*mm, 15*mm, 18*mm, 20*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("BACKGROUND", (0,0), (-1,0), C_HEAD),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("LINEBELOW", (0,0), (-1,0), 0.4, C_LINE),
        ("LINEBELOW", (0,1), (-1,-1), 0.15, C_LINE),
        ("ALIGN", (6,1), (12,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(tbl)
    doc.build(story)
    return buf.getvalue()


# ==================== Trip Bulk Import ====================
