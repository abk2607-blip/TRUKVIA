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
    _GSTR1_9B_REASON_MAP,
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



# ============================================================================
# Iter132c C3.5 · GSTR-1 §9A Export Parity — canonical payload builder.
#
# Endpoint (existing, byte-identical shape):
#     GET /api/reports/gstr1?month=YYYY-MM
# Export projections (additive · C3.5):
#     GET /api/reports/gstr1.json    (canonical projection · same body + additive fields)
#     GET /api/reports/gstr1.xlsx    (4-sheet accountant workbook)
#     GET /api/reports/gstr1.pdf     (A4 landscape working report)
#
# STATUTORY CONTRACT (locked in C3.5 research):
#   * Source of truth = db.invoices scoped by {user_id, company_id, invoice_date in [start,end]}.
#     Tax character (cgst_amount/sgst_amount/igst_amount) is PERSISTED at invoice save
#     via services._recompute_invoice (LOCKED · Iter127a). This endpoint never
#     recomputes tax.
#   * POS = customer.state (IGST §12(9) registered-recipient rule). Ship-to state
#     is deliberately NOT used because tax character is persisted at invoice save
#     time on customer.state basis. Any B2C-unregistered POS correction is
#     out of scope — see backlog C6.
#   * Bill-To (customer) is the authoritative reporting identity/state source
#     for GSTR-1. Ship-To is operational and never overrides POS silently.
#   * B2B / B2C split = presence of customer.gstin (non-blank ⇒ B2B).
#   * NOT emitted by this endpoint (out of scope for C3.5):
#       - B2CL (inter-state B2C > ₹2.5 L) split — historical scope
#       - HSN Summary (Table 12) — historical scope
#       - Docs Summary (Table 13) — historical scope
#       - Amendments (Tables 9A / 9B / 9C) — §9B is separate (C3.1/C3.2 LOCKED);
#         §9C is future C5.
#   * The generated PDF/XLSX are a WORKING REPORT, not a portal upload file.
#
# HIGH-VOLUME CONTRACT (C3.5 mandatory):
#   * Invoice iteration uses a streaming Motor cursor with an in-Mongo
#     invoice_date range filter — NO to_list(5000).
#   * Customer preload is bounded by the unique customer_ids referenced by the
#     month's invoices, fetched via $in — NO to_list(2000).
#   * 10 000 invoices in a single month must render without silent truncation
#     (guardrail test: test_streaming_10k_invoices).
#
# RECONCILIATION (fail-loud):
#   * additive `reconciliation` dict compares endpoint totals to a Mongo $group
#     ground truth over the identical filter — any delta ⇒ reconciled=False +
#     a warning row. Never silently disappears.
# ============================================================================


async def _gstr1_payload(month: str, request: Request, user: dict) -> dict:
    """C3.5.1 · Internal canonical builder — SINGLE SOURCE OF TRUTH for the
    /reports/gstr1 · .json · .xlsx · .pdf endpoints.

    Streaming cursor. Bounded customer preload. Deliberately additive
    (issuer_gstin / reconciliation / warnings) on top of the Iter127a shape,
    which is preserved byte-identically.
    """
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

    # ── (A) Streaming invoice iteration (Mongo-side date filter, no cap) ──
    inv_filter = {
        "user_id": uid,
        "company_id": cid,
        "invoice_date": {"$gte": start, "$lte": end},
    }
    invoice_docs: list = []
    seen_customer_ids: set = set()
    async for inv in db.invoices.find(inv_filter, {"_id": 0, "user_id": 0}):
        invoice_docs.append(inv)
        cust_id = inv.get("customer_id")
        if cust_id:
            seen_customer_ids.add(cust_id)

    # ── (B) Bounded customer preload — only referenced ids, no cap ────────
    cmap: dict = {}
    if seen_customer_ids:
        async for c in db.customers.find(
            {"user_id": uid, "company_id": cid, "id": {"$in": list(seen_customer_ids)}},
            {"_id": 0},
        ):
            cmap[c["id"]] = c

    company = await db.companies.find_one({"id": cid, "user_id": uid}, {"_id": 0}) or {}
    home_state_code = _state_code(company.get("state", ""))

    warnings: list = []

    b2b_rows: list = []
    b2c_rows: list = []
    totals = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total": 0.0}
    for inv in invoice_docs:
        cust_id = inv.get("customer_id")
        c = cmap.get(cust_id)
        if c is None:
            warnings.append(
                f"invoice {inv.get('invoice_number','?')} references missing customer_id={cust_id or '(blank)'}"
            )
            c = {}
        gstin = (c.get("gstin") or "").strip()
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

    # ── By State (POS) grouping ───────────────────────────────────────────
    by_state: dict = {}
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

    invoice_count = len(invoice_docs)

    # ── Additive: issuer GSTIN (from company doc; may be blank on legacy tenants) ──
    issuer_gstin = (company.get("gstin") or "").strip().upper()

    # ── Additive: fail-loud reconciliation against Mongo $group ground truth ──
    gt_agg_cursor = db.invoices.aggregate([
        {"$match": inv_filter},
        {"$group": {
            "_id": None,
            "gt_count":   {"$sum": 1},
            "gt_taxable": {"$sum": {"$ifNull": ["$subtotal", 0]}},
            "gt_cgst":    {"$sum": {"$ifNull": ["$cgst_amount", 0]}},
            "gt_sgst":    {"$sum": {"$ifNull": ["$sgst_amount", 0]}},
            "gt_igst":    {"$sum": {"$ifNull": ["$igst_amount", 0]}},
            "gt_total":   {"$sum": {"$ifNull": ["$total_amount", 0]}},
        }},
    ])
    gt_docs = await gt_agg_cursor.to_list(1)
    gt = gt_docs[0] if gt_docs else {
        "gt_count": 0, "gt_taxable": 0.0, "gt_cgst": 0.0, "gt_sgst": 0.0,
        "gt_igst": 0.0, "gt_total": 0.0,
    }
    gt_count = int(gt.get("gt_count", 0))
    gt_total = round(float(gt.get("gt_total", 0.0)), 2)
    gt_taxable = round(float(gt.get("gt_taxable", 0.0)), 2)

    reconciled = (
        gt_count == invoice_count
        and abs(gt_total - totals["total"]) < 0.01
        and abs(gt_taxable - totals["taxable"]) < 0.01
    )
    if not reconciled:
        warnings.append(
            f"reconciliation mismatch: endpoint(count={invoice_count},total={totals['total']},"
            f"taxable={totals['taxable']}) vs ground_truth(count={gt_count},"
            f"total={gt_total},taxable={gt_taxable})"
        )

    return {
        # ── Iter127a-shape (byte-identical) ──
        "month": month,
        "period": {"start": start, "end": end},
        "company_state": company.get("state", ""),
        "company_state_code": home_state_code,
        "b2b": b2b_rows,
        "b2c": b2c_rows,
        "by_state": sorted(by_state.values(), key=lambda x: -x["total"]),
        "totals": totals,
        "invoice_count": invoice_count,
        # ── C3.5 additive fields ──
        "company_id": cid,
        "company_name": company.get("name", ""),
        "issuer_gstin": issuer_gstin,
        "reconciliation": {
            "endpoint_invoice_count": invoice_count,
            "ground_truth_invoice_count": gt_count,
            "endpoint_total": totals["total"],
            "ground_truth_total": gt_total,
            "endpoint_taxable": totals["taxable"],
            "ground_truth_taxable": gt_taxable,
            "reconciled": reconciled,
        },
        "warnings": warnings,
    }


@router.get("/reports/gstr1")
async def report_gstr1(month: str, request: Request, user=Depends(get_current_user)):
    """Iter127a GSTR-1 report · byte-identical to pre-C3.5 for existing keys.

    Delegates to _gstr1_payload(). The additive keys (company_id, company_name,
    issuer_gstin, reconciliation, warnings) are appended without disturbing
    any pre-existing key or value.
    """
    return await _gstr1_payload(month, request, user)


@router.get("/reports/gstr1.json")
async def report_gstr1_json(month: str, request: Request, user=Depends(get_current_user)):
    """C3.5 · Downloadable canonical GSTR-1 §9A JSON.

    Returns the same body as GET /reports/gstr1, wrapped in an attachment
    Content-Disposition so browsers save it as a file. Emits one
    audit_logs.gstr_export/download row.
    """
    payload = await _gstr1_payload(month, request, user)
    code = payload.get("company_name", "").strip() or "company"
    code = "".join(c if c.isalnum() else "_" for c in code)[:24] or "company"
    fname = f"GSTR1_{code}_{month}.json"
    recon = payload.get("reconciliation") or {}
    await _log_audit(
        user, "gstr_export", "download",
        entity_id="", entity_ref=fname,
        changes={
            "format": "json",
            "period": payload.get("period"),
            "row_count": payload.get("invoice_count", 0),
            "gst_total": payload.get("totals", {}).get("total"),
            "reconciled": recon.get("reconciled"),
        },
    )
    import json as _json
    return StreamingResponse(
        io.BytesIO(_json.dumps(payload).encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/reports/gstr1.xlsx")
async def report_gstr1_xlsx(month: str, request: Request, user=Depends(get_current_user)):
    """C3.5 · XLSX projection of the C3.5 canonical payload.

    Four accountant-friendly sheets: Summary / B2B / B2C / By_State.
    Never recomputes tax, totals, POS, or GST routing.
    """
    payload = await _gstr1_payload(month, request, user)
    company = await db.companies.find_one(
        {"id": payload["company_id"], "user_id": user["user_id"]}, {"_id": 0}
    ) or {}

    from xlsx.gstr1 import build_gstr1_xlsx
    data = build_gstr1_xlsx(company, payload)

    code = (company.get("company_code") or "company")
    fname = f"GSTR1_{code}_{month}.xlsx"
    recon = payload.get("reconciliation") or {}
    await _log_audit(
        user, "gstr_export", "download",
        entity_id="", entity_ref=fname,
        changes={
            "format": "xlsx",
            "period": payload.get("period"),
            "row_count": payload.get("invoice_count", 0),
            "gst_total": payload.get("totals", {}).get("total"),
            "reconciled": recon.get("reconciled"),
        },
    )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/reports/gstr1.pdf")
async def report_gstr1_pdf(month: str, request: Request, user=Depends(get_current_user)):
    """C3.5 · PDF projection of the C3.5 canonical payload (A4 landscape).

    Human-readable working report — NOT a portal upload file. Uses the
    L2d v3 fresh-flowable two-pass render pattern to survive unlimited
    row volume without HTTP 500 / LayoutError.
    """
    payload = await _gstr1_payload(month, request, user)
    company = await db.companies.find_one(
        {"id": payload["company_id"], "user_id": user["user_id"]}, {"_id": 0}
    ) or {}

    from pdf.gstr1 import build_gstr1_pdf
    data = build_gstr1_pdf(company, payload)

    code = (company.get("company_code") or "company")
    fname = f"GSTR1_{code}_{month}.pdf"
    recon = payload.get("reconciliation") or {}
    await _log_audit(
        user, "gstr_export", "download",
        entity_id="", entity_ref=fname,
        changes={
            "format": "pdf",
            "period": payload.get("period"),
            "row_count": payload.get("invoice_count", 0),
            "gst_total": payload.get("totals", {}).get("total"),
            "reconciled": recon.get("reconciled"),
        },
    )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )

# ==================== E-Way Bill JSON ====================


# ============================================================================
# Iter132c C3.1 · GSTR-1 §9B (CDNR / CDNUR) canonical statutory feed.
#
# Endpoint:  GET /api/reports/gstr1-9b?month=YYYY-MM
#
# Statutory contract (locked in C3 research):
#   * Filing period = note.note_date (issue date), NOT invoice_date.
#   * Source of truth = credit_debit_notes collection filtered by
#         {user_id, company_id, note_date in [start,end], status in [issued|cancelled]}
#     — NO recomputation of persisted note totals.
#   * apply_gst=False notes → commercial_notes[] (statutorily excluded from
#     §9B per CGST §34 / §15(3)(b); financial/commercial notes are NOT
#     reported in GSTR-1).
#   * Draft notes → excluded silently.
#   * Cancelled notes:
#       - never issued (no note_number) → excluded silently.
#       - issued, cancelled_at ≤ period_end → excluded silently
#         (cancelled within the same period, before any export).
#       - issued, cancelled_at > period_end → surfaced in
#         cancelled_after_export[] with an advisory that §9C amendment is
#         required (§9C emission itself deferred to future C5).
#   * Routing tree for issued+apply_gst=True notes:
#       recipient GSTIN valid (_GSTIN_RE)                       → CDNR   (inv_typ="R")
#       else inter-state (gst_type=igst) AND invoice > ₹2.5 L   → CDNUR  (typ="B2CL")
#       else                                                    → b2cs_adjustments[]
#         (statutorily reported net-of in Table 7 — surfaced here for
#         audit visibility, NOT part of §9B).
#   * Reason-code map is deterministic (locked, see services._GSTR1_9B_REASON_MAP).
#   * Streaming cursor (async for) — no to_list() truncation; scales to
#     10,000+ notes per period.
#   * Reconciliation is FAIL-LOUD: any delta between the emitted payload
#     and a Mongo $group ground truth over the same filter → HTTP 500 with
#     the offending IDs. Never silently disappears.
#   * Every call emits one gstr_export/download audit log row.
# ============================================================================

def _dd_mm_yyyy(iso: str) -> str:
    """Portal expects dd-mm-yyyy. Accept ISO yyyy-mm-dd, fall back to raw
    string on parse failure (defensive — an unparseable date is data-side
    corruption and should not blow up the endpoint)."""
    if not iso:
        return ""
    try:
        from datetime import date as _d
        return _d.fromisoformat(iso[:10]).strftime("%d-%m-%Y")
    except Exception:
        return iso


def _gstr1_reason_for(qorvena_code: str) -> tuple:
    """Return (statutory_rsn, remapped_to_others: bool). Unknown QORVENA
    codes fall through to '07 Others' with the boolean flag set True so
    the endpoint can surface a warning."""
    if not qorvena_code:
        return ("07", True)
    if qorvena_code in _GSTR1_9B_REASON_MAP:
        return (_GSTR1_9B_REASON_MAP[qorvena_code], False)
    return ("07", True)


async def _gstr1_9b_payload(month: str, request: Request, user: dict) -> dict:
    """C3.2.1 · Internal canonical statutory-feed builder.

    ONE SOURCE OF TRUTH for the JSON / XLSX / PDF endpoints. Feature-flag
    gated (ENABLE_CDN=1). Streaming-safe. Fail-loud reconciliation.
    Deliberately no audit-log emission here — each public endpoint
    (JSON / XLSX / PDF) logs its own `gstr_export/download` row with
    the format it served. Keeps the payload builder side-effect-free."""
    if os.environ.get("ENABLE_CDN") != "1":
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        y_s, m_s = month.split("-")
        y = int(y_s); mn = int(m_s)
        assert 1 <= mn <= 12
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month; use YYYY-MM")
    from calendar import monthrange
    start = f"{y:04d}-{mn:02d}-01"
    end = f"{y:04d}-{mn:02d}-{monthrange(y, mn)[1]:02d}"

    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    company = await db.companies.find_one({"id": cid, "user_id": uid}, {"_id": 0}) or {}
    home_state = company.get("state", "")
    home_sc = _state_code(home_state)
    issuer_gstin = (company.get("gstin", "") or "").strip().upper()

    warnings: list = []
    if not issuer_gstin:
        warnings.append("issuer_company_gstin_missing")

    # ── Streaming fetch of eligible notes (issued OR cancelled with note in-period) ──
    q = {
        "user_id": uid,
        "company_id": cid,
        "note_date": {"$gte": start, "$lte": end},
        "status": {"$in": ["issued", "cancelled"]},
    }
    notes: list = []
    invoice_ids_needed: set = set()
    customer_ids_needed: set = set()
    async for n in db.credit_debit_notes.find(q, {"_id": 0, "user_id": 0}).sort("note_date", 1):
        notes.append(n)
        if n.get("invoice_id"):
            invoice_ids_needed.add(n["invoice_id"])
        if n.get("customer_id"):
            customer_ids_needed.add(n["customer_id"])

    # Batch-fetch referenced invoices + customers (single query each, no N+1).
    inv_map: dict = {}
    if invoice_ids_needed:
        async for inv in db.invoices.find(
            {"user_id": uid, "id": {"$in": list(invoice_ids_needed)}},
            {"_id": 0, "user_id": 0},
        ):
            inv_map[inv["id"]] = inv
    cust_map: dict = {}
    if customer_ids_needed:
        async for cst in db.customers.find(
            {"user_id": uid, "id": {"$in": list(customer_ids_needed)}},
            {"_id": 0, "user_id": 0},
        ):
            cust_map[cst["id"]] = cst

    cdnr_map: dict = {}    # ctin → {ctin, customer_name, nt: [...]}
    cdnur_rows: list = []
    commercial_rows: list = []
    b2cs_rows: list = []
    cancelled_after_export_rows: list = []
    row_warnings_total: list = []
    reason_remap_count = 0

    for n in notes:
        inv = inv_map.get(n.get("invoice_id"), {}) or {}
        cust = cust_map.get(n.get("customer_id"), {}) or {}
        note_status = n.get("status")
        was_issued = bool(n.get("note_number"))

        # ── Cancelled branch ─────────────────────────────────────────
        if note_status == "cancelled":
            if not was_issued:
                continue  # never had a note_number → silent drop
            cancelled_at = (n.get("cancelled_at") or "")[:10]
            if cancelled_at and cancelled_at > end:
                # cancelled AFTER filing period → §9C amendment due
                cancelled_after_export_rows.append({
                    "note_id": n.get("id"),
                    "note_number": n.get("note_number"),
                    "note_date": n.get("note_date"),
                    "kind": n.get("kind"),
                    "ntty": "C" if n.get("kind") == "credit" else "D",
                    "invoice_number": n.get("invoice_number_snapshot"),
                    "customer_id": n.get("customer_id"),
                    "customer_name": cust.get("name", ""),
                    "customer_gstin": (cust.get("gstin", "") or "").upper(),
                    "total_amount": round(float(n.get("total_amount", 0) or 0), 2),
                    "cancelled_at": n.get("cancelled_at", ""),
                    "cancelled_reason": n.get("cancelled_reason", ""),
                    "_advisory": "Requires GSTR-1 §9C (CDNRA / CDNURA) amendment in a subsequent filing period",
                })
            # else: cancelled within period → silent drop (safe — never exported)
            continue

        if note_status != "issued":
            continue  # draft

        # ── Statutory reason-code map ────────────────────────────────
        qcode = n.get("reason_code") or ""
        rsn, remapped = _gstr1_reason_for(qcode)
        if remapped:
            reason_remap_count += 1
            row_warnings_total.append(f"reason_remapped_to_others:{n.get('note_number')}")

        # ── Amounts read verbatim (no recompute) ─────────────────────
        val = round(float(n.get("total_amount", 0) or 0), 2)
        txval = round(float(n.get("subtotal", 0) or 0), 2)
        cgst_amt = round(float(n.get("cgst_amount", 0) or 0), 2)
        sgst_amt = round(float(n.get("sgst_amount", 0) or 0), 2)
        igst_amt = round(float(n.get("igst_amount", 0) or 0), 2)
        rchrg = "Y" if n.get("rcm") else "N"
        apply_gst = bool(n.get("apply_gst", True))
        ntty = "C" if n.get("kind") == "credit" else "D"

        gst_type = n.get("gst_type") or inv.get("gst_type") or "cgst_sgst"
        if gst_type == "igst":
            rt = round(float(n.get("igst_rate", 0) or 0), 2)
        else:
            rt = round(float(n.get("cgst_rate", 0) or 0) + float(n.get("sgst_rate", 0) or 0), 2)

        # ── apply_gst=False → commercial (statutorily excluded from §9B) ──
        if not apply_gst:
            commercial_rows.append({
                "note_id": n.get("id"),
                "note_number": n.get("note_number"),
                "note_date": n.get("note_date"),
                "kind": n.get("kind"),
                "ntty": ntty,
                "invoice_number": n.get("invoice_number_snapshot"),
                "invoice_date": inv.get("invoice_date"),
                "customer_id": n.get("customer_id"),
                "customer_name": cust.get("name", ""),
                "customer_gstin": (cust.get("gstin", "") or "").upper(),
                "reason_code_qorvena": qcode,
                "reason_text": n.get("reason_text", ""),
                "subtotal": txval,
                "total_amount": val,
                "_info": "Financial/Commercial note — not reported in GSTR-1 per CGST §34/§15(3)(b)",
            })
            continue

        # ── GST-applied routing ──────────────────────────────────────
        cust_gstin = (cust.get("gstin", "") or "").strip().upper()
        gstin_valid = bool(cust_gstin and _GSTIN_RE.match(cust_gstin))

        cust_state = cust.get("state", "")
        cust_sc = _state_code(cust_state)
        pos = f"{cust_sc}-{cust_state}" if cust_sc else cust_state

        is_inter_state = (gst_type == "igst")
        inv_total = float(inv.get("total_amount", 0) or 0)
        b2cl_eligible = is_inter_state and inv_total > 250000.0

        itm_det = {
            "rt": rt,
            "txval": txval,
            "iamt": igst_amt,
            "camt": cgst_amt,
            "samt": sgst_amt,
            "csamt": 0.0,
        }
        base_row = {
            "note_id": n.get("id"),
            "note_number": n.get("note_number"),
            "note_date": n.get("note_date"),
            "nt_num": n.get("note_number"),
            "nt_dt": _dd_mm_yyyy(n.get("note_date", "")),
            "kind": n.get("kind"),
            "ntty": ntty,
            "val": val,
            "p_gst": "N",
            "rchrg": rchrg,
            "pos": pos,
            "reason_code_qorvena": qcode,
            "rsn": rsn,
            "reason_text": n.get("reason_text", ""),
            # Rule 53(1A) audit link (portal-optional since 14-Sep-2020)
            "inum": n.get("invoice_number_snapshot"),
            "idt": _dd_mm_yyyy(inv.get("invoice_date", "") or ""),
            "customer_id": n.get("customer_id"),
            "customer_name": cust.get("name", ""),
            "customer_gstin": cust_gstin,
            "itms": [{"num": 1, "itm_det": itm_det}],
        }
        _wrow: list = []
        if not cust_sc:
            _wrow.append("missing_state_code")
            row_warnings_total.append(f"missing_state_code:{n.get('note_number')}")
        if not n.get("invoice_number_snapshot"):
            _wrow.append("missing_invoice_ref")
            row_warnings_total.append(f"missing_invoice_ref:{n.get('note_number')}")

        if gstin_valid:
            base_row["inv_typ"] = "R"
            if _wrow:
                base_row["_warnings"] = _wrow
            grp = cdnr_map.setdefault(
                cust_gstin,
                {"ctin": cust_gstin, "customer_name": cust.get("name", ""), "nt": []},
            )
            grp["nt"].append(base_row)
        elif b2cl_eligible:
            base_row["typ"] = "B2CL"
            if _wrow:
                base_row["_warnings"] = _wrow
            cdnur_rows.append(base_row)
        else:
            base_row["_warnings"] = _wrow + ["report_net_of_in_table_7"]
            b2cs_rows.append(base_row)

    if reason_remap_count:
        warnings.append(f"reason_remapped_to_others_count:{reason_remap_count}")

    cdnr_list = list(cdnr_map.values())
    cdnr_all_nt = [nt for grp in cdnr_list for nt in grp["nt"]]

    def _sum(rows, key):
        return round(sum(float(r.get(key, 0) or 0) for r in rows), 2)

    def _split_cn_dn(rows, key):
        cn = round(sum(float(r.get(key, 0) or 0) for r in rows if r.get("kind") == "credit"), 2)
        dn = round(sum(float(r.get(key, 0) or 0) for r in rows if r.get("kind") == "debit"), 2)
        return cn, dn

    cdnr_val = _sum(cdnr_all_nt, "val")
    cdnur_val = _sum(cdnur_rows, "val")
    b2cs_val = _sum(b2cs_rows, "val")
    commercial_val = _sum(commercial_rows, "total_amount")

    cdnr_cn, cdnr_dn = _split_cn_dn(cdnr_all_nt, "val")
    cdnur_cn, cdnur_dn = _split_cn_dn(cdnur_rows, "val")
    b2cs_cn, b2cs_dn = _split_cn_dn(b2cs_rows, "val")
    comm_cn, comm_dn = _split_cn_dn(commercial_rows, "total_amount")

    # ── Fail-loud reconciliation invariant (Mongo $group ground truth) ──
    gt_true = 0.0; gt_false = 0.0
    gt_true_cn = 0.0; gt_true_dn = 0.0
    gt_false_cn = 0.0; gt_false_dn = 0.0
    gt_issued_count = 0
    async for x in db.credit_debit_notes.find(
        {"user_id": uid, "company_id": cid, "status": "issued",
         "note_date": {"$gte": start, "$lte": end}},
        {"_id": 0, "apply_gst": 1, "total_amount": 1, "kind": 1},
    ):
        v = float(x.get("total_amount", 0) or 0)
        k = x.get("kind")
        gt_issued_count += 1
        if x.get("apply_gst", True):
            gt_true += v
            if k == "credit": gt_true_cn += v
            elif k == "debit": gt_true_dn += v
        else:
            gt_false += v
            if k == "credit": gt_false_cn += v
            elif k == "debit": gt_false_dn += v
    gt_true = round(gt_true, 2);   gt_false = round(gt_false, 2)
    gt_true_cn = round(gt_true_cn, 2); gt_true_dn = round(gt_true_dn, 2)
    gt_false_cn = round(gt_false_cn, 2); gt_false_dn = round(gt_false_dn, 2)

    endpoint_gst_true = round(cdnr_val + cdnur_val + b2cs_val, 2)
    endpoint_gst_false = round(commercial_val, 2)
    endpoint_count = len(cdnr_all_nt) + len(cdnur_rows) + len(b2cs_rows) + len(commercial_rows)

    deltas: list = []
    if abs(endpoint_gst_true - gt_true) > 0.01:
        deltas.append({"invariant": "sum_gst_true_notes",
                       "endpoint": endpoint_gst_true, "ground_truth": gt_true,
                       "delta": round(endpoint_gst_true - gt_true, 2)})
    if abs(endpoint_gst_false - gt_false) > 0.01:
        deltas.append({"invariant": "sum_gst_false_notes",
                       "endpoint": endpoint_gst_false, "ground_truth": gt_false,
                       "delta": round(endpoint_gst_false - gt_false, 2)})
    if endpoint_count != gt_issued_count:
        deltas.append({"invariant": "issued_note_count",
                       "endpoint": endpoint_count, "ground_truth": gt_issued_count,
                       "delta": endpoint_count - gt_issued_count})
    if deltas:
        raise HTTPException(status_code=500, detail={
            "error": "gstr1_9b_reconciliation_mismatch",
            "period": month, "deltas": deltas,
        })

    totals = {
        "cdnr":                    {"note_count": len(cdnr_all_nt),  "val": cdnr_val,       "cn": cdnr_cn, "dn": cdnr_dn},
        "cdnur":                   {"note_count": len(cdnur_rows),   "val": cdnur_val,      "cn": cdnur_cn, "dn": cdnur_dn},
        "b2cs_adjustments":        {"note_count": len(b2cs_rows),    "val": b2cs_val,       "cn": b2cs_cn, "dn": b2cs_dn},
        "commercial_notes":        {"note_count": len(commercial_rows), "val": commercial_val, "cn": comm_cn, "dn": comm_dn},
        "cancelled_after_export":  {"note_count": len(cancelled_after_export_rows)},
    }
    reconciliation = {
        "reconciled": True,
        "endpoint_gst_true_total":   endpoint_gst_true,
        "ground_truth_gst_true":     gt_true,
        "endpoint_gst_false_total":  endpoint_gst_false,
        "ground_truth_gst_false":    gt_false,
        "endpoint_row_count":        endpoint_count,
        "ground_truth_issued_count": gt_issued_count,
        "cn_total": round(gt_true_cn + gt_false_cn, 2),
        "dn_total": round(gt_true_dn + gt_false_dn, 2),
        "cn_gst_true":  gt_true_cn,
        "dn_gst_true":  gt_true_dn,
        "cn_gst_false": gt_false_cn,
        "dn_gst_false": gt_false_dn,
    }

    return {
        "month": month,
        "period": {"start": start, "end": end},
        "company_id": cid,
        "company_state": home_state,
        "company_state_code": home_sc,
        "issuer_gstin": issuer_gstin,
        "cdnr": cdnr_list,
        "cdnur": cdnur_rows,
        "b2cs_adjustments": b2cs_rows,
        "commercial_notes": commercial_rows,
        "cancelled_after_export": cancelled_after_export_rows,
        "totals": totals,
        "reconciliation": reconciliation,
        "warnings": warnings + row_warnings_total,
        "note_count": endpoint_count,
    }


# ============================================================================
# C3.1 / C3.2 · Public endpoints wrapping the shared `_gstr1_9b_payload`
# helper. Each endpoint emits its own gstr_export/download audit row with
# the served format (json / xlsx / pdf). ONE SOURCE OF TRUTH — every
# endpoint returns a projection of the identical canonical payload.
# ============================================================================

@router.get("/reports/gstr1-9b")
async def report_gstr1_9b(month: str, request: Request, user=Depends(get_current_user)):
    """C3.1 · Canonical statutory JSON feed."""
    payload = await _gstr1_9b_payload(month, request, user)
    recon = payload.get("reconciliation") or {}
    await _log_audit(
        user, "gstr_export", "download",
        entity_id="", entity_ref=f"gstr1_9b_{month}",
        changes={
            "format": "json",
            "period": payload.get("period"),
            "row_count": payload.get("note_count", 0),
            "gst_true_total": recon.get("endpoint_gst_true_total"),
            "gst_false_total": recon.get("endpoint_gst_false_total"),
            "cancelled_after_export_count":
                (payload.get("totals", {}).get("cancelled_after_export", {}) or {}).get("note_count", 0),
        },
    )
    return payload


@router.get("/reports/gstr1-9b.xlsx")
async def report_gstr1_9b_xlsx(month: str, request: Request, user=Depends(get_current_user)):
    """C3.2 · XLSX projection of the C3.1 canonical payload.

    Six accountant-friendly sheets: Summary / CDNR / CDNUR /
    B2CS_Adjustments / Commercial_Notes / Cancelled_After_Export.
    Never recomputes tax, totals, routing or reconciliation."""
    payload = await _gstr1_9b_payload(month, request, user)
    company = await db.companies.find_one(
        {"id": payload["company_id"], "user_id": user["user_id"]}, {"_id": 0}
    ) or {}

    from xlsx.gstr1_9b import build_gstr1_9b_xlsx
    data = build_gstr1_9b_xlsx(company, payload)

    code = (company.get("company_code") or "company")
    fname = f"GSTR1_9B_{code}_{month}.xlsx"
    recon = payload.get("reconciliation") or {}
    await _log_audit(
        user, "gstr_export", "download",
        entity_id="", entity_ref=fname,
        changes={
            "format": "xlsx",
            "period": payload.get("period"),
            "row_count": payload.get("note_count", 0),
            "gst_true_total": recon.get("endpoint_gst_true_total"),
            "gst_false_total": recon.get("endpoint_gst_false_total"),
        },
    )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/reports/gstr1-9b.pdf")
async def report_gstr1_9b_pdf(month: str, request: Request, user=Depends(get_current_user)):
    """C3.2 · PDF projection of the C3.1 canonical payload (A4 landscape).

    Human-readable statutory working document — NOT a portal upload file.
    Uses the L2d v3 fresh-flowable two-pass render pattern to survive
    unlimited row volume without HTTP 500 / LayoutError."""
    payload = await _gstr1_9b_payload(month, request, user)
    company = await db.companies.find_one(
        {"id": payload["company_id"], "user_id": user["user_id"]}, {"_id": 0}
    ) or {}

    from pdf.gstr1_9b import build_gstr1_9b_pdf
    data = build_gstr1_9b_pdf(company, payload)

    code = (company.get("company_code") or "company")
    fname = f"GSTR1_9B_{code}_{month}.pdf"
    recon = payload.get("reconciliation") or {}
    await _log_audit(
        user, "gstr_export", "download",
        entity_id="", entity_ref=fname,
        changes={
            "format": "pdf",
            "period": payload.get("period"),
            "row_count": payload.get("note_count", 0),
            "gst_true_total": recon.get("endpoint_gst_true_total"),
            "gst_false_total": recon.get("endpoint_gst_false_total"),
        },
    )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )

