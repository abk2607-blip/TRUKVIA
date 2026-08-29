"""Iter132a · Credit Note router.

Endpoints (all under /api, gated by ENABLE_CDN=1):
  POST   /api/credit-notes                     create draft
  POST   /api/credit-notes/{nid}/issue         draft → issued (assigns note_number)
  POST   /api/credit-notes/{nid}/cancel        issued → cancelled (Owner only)
  GET    /api/credit-notes                     list, filterable
  GET    /api/credit-notes/{nid}               single
  PUT    /api/credit-notes/{nid}               edit ONLY while status=draft
  GET    /api/invoices/{iid}/notes             all notes linked to invoice

Debit Note endpoints are reserved for Iter132b.
"""
from __future__ import annotations
import os
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from db import db
from auth import get_current_user, _has_perm
from audit import _log_audit
from models import (
    CreditDebitNote, CDNCreateRequest, CDNCancelRequest, CDNLine,
    new_id,
)
from services import (
    now_utc,
    _next_credit_note_number_for_company,
    _derive_fy_from_iso,
    _effective_invoice_totals,
)

router = APIRouter(prefix="/api", tags=["credit-notes"])


def _is_cdn_enabled() -> bool:
    """Feature flag. When unset, endpoints return 404 so the surface is
    invisible in production until UAT approves the flip. Matches the
    Iter130 fail-secure pattern."""
    return os.environ.get("ENABLE_CDN") == "1"


def _require_flag():
    if not _is_cdn_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


def _round2(x: float) -> float:
    return round(float(x or 0), 2)


async def _compute_note_totals(payload_lines: list, invoice: dict) -> dict:
    """Inherit GST from invoice; sum lines; produce totals. No auto-derivation
    of gst_type — CN must carry the same tax character as the invoice."""
    subtotal = 0.0
    lines_out = []
    for l in payload_lines:
        tv = _round2(float(l.quantity) * float(l.rate))
        subtotal += tv
        lines_out.append(CDNLine(
            description=(l.description or "").strip(),
            hsn_sac=(l.hsn_sac or invoice.get("hsn_sac") or "996791"),
            trip_id=l.trip_id,
            quantity=_round2(l.quantity),
            rate=_round2(l.rate),
            taxable_value=tv,
        ).model_dump())
    subtotal = _round2(subtotal)
    gst_type = invoice.get("gst_type") or "cgst_sgst"
    cgst_rate = float(invoice.get("cgst_rate") or 2.5)
    sgst_rate = float(invoice.get("sgst_rate") or 2.5)
    igst_rate = float(invoice.get("igst_rate") or 5.0)
    cgst = sgst = igst = 0.0
    if gst_type == "cgst_sgst":
        cgst = _round2(subtotal * cgst_rate / 100)
        sgst = _round2(subtotal * sgst_rate / 100)
    else:
        igst = _round2(subtotal * igst_rate / 100)
    total_tax = _round2(cgst + sgst + igst)
    # RCM parity — if invoice is RCM, tax not added to gross
    rcm = bool(invoice.get("rcm", True))
    gross = _round2(subtotal if rcm else subtotal + total_tax)
    final_amount = float(int(gross + 0.5)) if gross >= 0 else -float(int(-gross + 0.5))
    round_off = _round2(final_amount - gross)
    return {
        "lines": lines_out,
        "subtotal": subtotal,
        "gst_type": gst_type,
        "cgst_rate": cgst_rate, "sgst_rate": sgst_rate, "igst_rate": igst_rate,
        "cgst_amount": cgst, "sgst_amount": sgst, "igst_amount": igst,
        "total_tax": total_tax,
        "round_off": round_off,
        "total_amount": _round2(final_amount),
        "rcm": rcm,
    }


def _statutory_deadline_for_invoice_fy(inv_date_iso: str) -> date:
    """CGST §34 · CN/DN allowed up to 30-Nov of the FY following the
    invoice's FY. Invoice FY is the FY the invoice_date falls in."""
    d = date.fromisoformat(inv_date_iso)
    # FY end is 31-Mar of year Y+1 if month>=4, else 31-Mar of year Y.
    if d.month >= 4:
        deadline_year = d.year + 1
    else:
        deadline_year = d.year
    # Deadline is 30-Nov of the year that FOLLOWS the FY-end year.
    return date(deadline_year, 11, 30)


@router.post("/credit-notes")
async def create_credit_note(payload: CDNCreateRequest, user=Depends(get_current_user)):
    _require_flag()
    if not _has_perm(user, "create_note"):
        raise HTTPException(status_code=403, detail="Missing permission: create_note")
    if not (payload.reason_text or "").strip() or len(payload.reason_text.strip()) < 8:
        raise HTTPException(status_code=400, detail="reason_text must be at least 8 characters")
    if not payload.lines:
        raise HTTPException(status_code=400, detail="At least one line item is required")

    inv = await db.invoices.find_one({"id": payload.invoice_id, "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Linked invoice not found")
    if inv.get("is_historical") or inv.get("imported_from"):
        raise HTTPException(status_code=422, detail="Historical/imported invoices cannot receive Credit Notes")

    note_date_iso = (payload.note_date or now_utc().date().isoformat())
    try:
        n_date = date.fromisoformat(note_date_iso)
    except Exception:
        raise HTTPException(status_code=400, detail="note_date must be ISO YYYY-MM-DD")
    inv_date_iso = inv.get("invoice_date") or now_utc().date().isoformat()
    if n_date < date.fromisoformat(inv_date_iso):
        raise HTTPException(status_code=400, detail="note_date cannot be earlier than invoice_date")
    if n_date > now_utc().date():
        raise HTTPException(status_code=400, detail="note_date cannot be in the future")

    # Statutory deadline (30-Nov of FY following the invoice's FY)
    deadline = _statutory_deadline_for_invoice_fy(inv_date_iso)
    deadline_override = False
    if n_date > deadline:
        if user.get("effective_role") != "owner":
            raise HTTPException(
                status_code=403,
                detail=f"Post-statutory-deadline note (past {deadline.isoformat()}) requires Owner override",
            )
        if not (payload.deadline_override_reason or "").strip():
            raise HTTPException(
                status_code=400,
                detail="deadline_override_reason is required for notes past the statutory deadline",
            )
        deadline_override = True

    totals = await _compute_note_totals(payload.lines, inv)

    # Over-credit guard — reject if this CN would drive effective total < 0.
    existing = await db.credit_debit_notes.find(
        {"user_id": user["user_id"], "invoice_id": inv["id"], "status": "issued"},
        {"_id": 0, "kind": 1, "total_amount": 1},
    ).to_list(5000)
    prospective = existing + [{"kind": "credit", "total_amount": totals["total_amount"]}]
    eff = await _effective_invoice_totals(inv, prospective)
    if eff["effective_total_amount"] < -0.01:
        raise HTTPException(
            status_code=422,
            detail=(f"Credit Note would make invoice effective total negative "
                    f"(₹{eff['effective_total_amount']:.2f}). Reduce amount or split."),
        )

    note = CreditDebitNote(
        kind="credit",
        company_id=inv.get("company_id") or "",
        note_date=note_date_iso,
        invoice_id=inv["id"],
        invoice_number_snapshot=inv.get("invoice_number", ""),
        customer_id=inv.get("customer_id", ""),
        reason_code=payload.reason_code,
        reason_text=payload.reason_text.strip(),
        lines=[CDNLine(**l) for l in totals["lines"]],
        subtotal=totals["subtotal"],
        gst_type=totals["gst_type"],
        cgst_rate=totals["cgst_rate"], sgst_rate=totals["sgst_rate"], igst_rate=totals["igst_rate"],
        cgst_amount=totals["cgst_amount"], sgst_amount=totals["sgst_amount"], igst_amount=totals["igst_amount"],
        total_tax=totals["total_tax"],
        total_amount=totals["total_amount"],
        round_off=totals["round_off"],
        rcm=totals["rcm"],
        status="draft",
        created_by=user["user_id"],
        deadline_override=deadline_override,
        is_historical=bool(inv.get("is_historical")),
    )
    doc = note.model_dump()
    doc["user_id"] = user["user_id"]
    # If require_cdn_approval is OFF, auto-issue in the same request so the
    # accountant flow is single-step. If ON, remain in draft.
    company = await db.companies.find_one({"id": note.company_id, "user_id": user["user_id"]},
                                          {"_id": 0, "require_cdn_approval": 1})
    if not (company or {}).get("require_cdn_approval", False):
        note_number = await _next_credit_note_number_for_company(
            note.company_id, user["user_id"], note_date_iso
        )
        doc["status"] = "issued"
        doc["note_number"] = note_number
        doc["approved_by"] = user["user_id"]
        doc["approved_at"] = now_utc().isoformat()

    await db.credit_debit_notes.insert_one(doc)
    await _log_audit(
        user, "credit_note", "create" if doc["status"] == "draft" else "issue",
        entity_id=doc["id"], entity_ref=doc.get("note_number", ""),
        reason=payload.reason_text.strip(),
        changes={"snapshot": {k: doc.get(k) for k in
                              ("kind", "invoice_id", "invoice_number_snapshot",
                               "note_date", "total_amount", "reason_code")}},
    )
    doc.pop("user_id", None)
    doc.pop("_id", None)  # insert_one mutates doc to include ObjectId; strip it for JSON serialisation
    return doc


@router.post("/credit-notes/{nid}/issue")
async def issue_credit_note(nid: str, user=Depends(get_current_user)):
    _require_flag()
    if not _has_perm(user, "issue_note"):
        raise HTTPException(status_code=403, detail="Missing permission: issue_note")
    note = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0})
    if not note:
        raise HTTPException(status_code=404, detail="Not found")
    if note["status"] == "issued":
        return {**{k: v for k, v in note.items() if k != "user_id"}}
    if note["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled notes cannot be issued")
    # Concurrent-issue race: use atomic filter on status=draft so exactly one
    # request wins the number assignment.
    note_number = await _next_credit_note_number_for_company(
        note["company_id"], user["user_id"], note["note_date"]
    )
    res = await db.credit_debit_notes.update_one(
        {"id": nid, "user_id": user["user_id"], "status": "draft"},
        {"$set": {
            "status": "issued",
            "note_number": note_number,
            "approved_by": user["user_id"],
            "approved_at": now_utc().isoformat(),
        }},
    )
    if res.matched_count == 0:
        # Another concurrent issue already won — return the winning row.
        winner = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
        return winner
    await _log_audit(user, "credit_note", "issue", entity_id=nid, entity_ref=note_number)
    updated = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    return updated


@router.post("/credit-notes/{nid}/cancel")
async def cancel_credit_note(nid: str, payload: CDNCancelRequest, user=Depends(get_current_user)):
    _require_flag()
    if not _has_perm(user, "cancel_note"):
        raise HTTPException(status_code=403, detail="Missing permission: cancel_note")
    if not (payload.reason or "").strip() or len(payload.reason.strip()) < 8:
        raise HTTPException(status_code=400, detail="Cancellation reason must be at least 8 characters")
    note = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0})
    if not note:
        raise HTTPException(status_code=404, detail="Not found")
    if note["status"] == "cancelled":
        return {**{k: v for k, v in note.items() if k != "user_id"}}
    await db.credit_debit_notes.update_one(
        {"id": nid, "user_id": user["user_id"]},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": now_utc().isoformat(),
            "cancelled_by": user["user_id"],
            "cancelled_reason": payload.reason.strip(),
        }},
    )
    await _log_audit(user, "credit_note", "cancel", entity_id=nid,
                     entity_ref=note.get("note_number", ""), reason=payload.reason.strip())
    updated = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    return updated


@router.put("/credit-notes/{nid}")
async def update_credit_note(nid: str, payload: CDNCreateRequest, user=Depends(get_current_user)):
    _require_flag()
    if not _has_perm(user, "create_note"):
        raise HTTPException(status_code=403, detail="Missing permission: create_note")
    note = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0})
    if not note:
        raise HTTPException(status_code=404, detail="Not found")
    if note["status"] != "draft":
        raise HTTPException(status_code=409, detail="Only draft notes can be edited")
    inv = await db.invoices.find_one({"id": note["invoice_id"], "user_id": user["user_id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Linked invoice missing")
    totals = await _compute_note_totals(payload.lines, inv)
    await db.credit_debit_notes.update_one(
        {"id": nid, "user_id": user["user_id"], "status": "draft"},
        {"$set": {
            "reason_code": payload.reason_code,
            "reason_text": payload.reason_text.strip(),
            **totals,
            "lines": totals["lines"],
        }},
    )
    await _log_audit(user, "credit_note", "update", entity_id=nid,
                     entity_ref=note.get("note_number", ""), reason=payload.reason_text.strip())
    updated = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    return updated


@router.get("/credit-notes")
async def list_credit_notes(
    request: Request,
    customer_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    user=Depends(get_current_user),
):
    _require_flag()
    q: dict = {"user_id": user["user_id"], "kind": "credit"}
    if customer_id:
        q["customer_id"] = customer_id
    if invoice_id:
        q["invoice_id"] = invoice_id
    if status:
        q["status"] = status
    docs = await db.credit_debit_notes.find(q, {"_id": 0, "user_id": 0}).sort("note_date", -1).to_list(limit)
    return docs


@router.get("/credit-notes/{nid}")
async def get_credit_note(nid: str, user=Depends(get_current_user)):
    _require_flag()
    d = await db.credit_debit_notes.find_one({"id": nid, "user_id": user["user_id"]}, {"_id": 0, "user_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return d


@router.get("/invoices/{iid}/notes")
async def list_notes_for_invoice(iid: str, user=Depends(get_current_user)):
    """List CN/DN linked to a specific invoice. Always returns 200 even
    when the feature flag is off — callers use this to render the
    'Related Notes' section, which is empty when no notes exist."""
    docs = await db.credit_debit_notes.find(
        {"user_id": user["user_id"], "invoice_id": iid},
        {"_id": 0, "user_id": 0},
    ).sort("note_date", 1).to_list(500)
    return docs
