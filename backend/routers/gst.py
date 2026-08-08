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
    _GSTIN_RE, _GSTIN_CHECK_ALPHABET, STATE_CODES, STATE_CODE_TO_NAME,
    _compute_trip, _trip_billable, _recompute_invoice,
    _next_invoice_number, _next_invoice_number_for_company,
    _next_lr_number, _in_range, _vehicle_expiry_stats,
    _state_code, _gstin_checksum,
)

router = APIRouter(prefix="/api")

@router.get("/gstin/lookup")
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



@router.get("/reports/gstr1")
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
    customers = await db.customers.find({"user_id": uid, "company_id": cid}, {"_id": 0}).to_list(2000)
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

