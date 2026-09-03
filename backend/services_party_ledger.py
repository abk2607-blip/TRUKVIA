"""Iter135 · Vendor / Mechanic Ledger — Authoritative Builder.

ONE dataset serves the JSON endpoint AND the PDF renderer:

    VendorBill / MechanicWorkOrder  (debit)
    VendorPayment / MechanicPayment (credit)
    Party.opening_balance
                       │
                       ▼
       build_party_ledger(party_type, id, from, to, include_reversed, vehicle_id)
                       │                                      │
                       ▼                                      ▼
             GET /api/{...}/ledger                  GET /api/{...}/ledger.pdf

The builder is pure and Decimal-safe.  Neither the router nor the PDF
renderer re-computes any totals.  This guarantees:

    UI totals ≡ PDF totals   (opening, debit, credit, closing, row count)

Source-of-truth invariants (HARD-LOCKED):
- Vendor Ledger reads `vendor_bills` + `vendor_payments` + `vendor.opening_balance`.
- Mechanic Ledger reads `mechanic_work_orders` + `mechanic_payments` + `mechanic.opening_balance`.
- The `expenses` collection is NEVER read.
- Vehicle context is a projection — bill/WO rows carry the snapshot at
  write-time; payment rows derive via `vendor_bill_id` /
  `mechanic_work_order_id` in a single batched lookup (no N+1, no
  silent truncation, no vehicle_id field on payment models).

Deterministic ordering:
    date (str, ISO)  →  kind priority (opening=0, bill/WO=1, payment=2)
                     →  created_at
                     →  stable id
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional

from fastapi import HTTPException

from db import db
from models import now_utc


# ── Hard guardrail — refuse to render a mathematically inconsistent PDF ──
# Applies ONLY to the PDF path (the JSON path streams all rows).  When
# breached, the endpoint MUST fail loudly rather than silently truncate.
MAX_PDF_ENTRIES = 5000


_KIND_ORDER = {"opening": 0, "bill": 1, "work_order": 1, "payment": 2}
_TYPE_LABELS = {
    "opening": "Opening",
    "bill": "Bill",
    "work_order": "Work Order",
    "payment": "Payment",
}


def _q2(x) -> Decimal:
    """Money rounding — 2 dp, banker's-safe."""
    return Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _f2(x: Decimal) -> float:
    return float(x)


async def _resolve_party(party_type: str, uid: str, cid: str, pid: str) -> dict:
    coll = "vendors" if party_type == "vendor" else "mechanics"
    row = await db[coll].find_one(
        {"id": pid, "user_id": uid, "company_id": cid},
        {"_id": 0, "user_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404,
                            detail=f"{'Vendor' if party_type == 'vendor' else 'Mechanic'} not found")
    return row


async def _resolve_company(uid: str, cid: str) -> dict:
    return (await db.companies.find_one(
        {"id": cid, "user_id": uid},
        {"_id": 0, "user_id": 0},
    )) or {}


async def _load_bill_rows(party_type, uid, cid, pid, include_reversed) -> list[dict]:
    """Return ALL bill / work-order rows for the party (no date filter here —
    the date filter is applied to entries, opening is anything strictly
    before `date_from`)."""
    if party_type == "vendor":
        q = {"user_id": uid, "company_id": cid, "vendor_id": pid,
             "is_deleted": {"$ne": True}}
        rows = await db.vendor_bills.find(q, {"_id": 0, "user_id": 0}).to_list(None)
        for r in rows:
            r["_date"] = r.get("bill_date") or ""
            r["_kind"] = "bill"
            r["_debit"] = _q2(r.get("bill_amount") or 0)
            r["_credit"] = _q2(0)
            r["_ref"] = r.get("bill_number") or r.get("id") or ""
            r["_id"] = r.get("id") or ""
            r["_vehicle_id"] = r.get("vehicle_id") or ""
            r["_vehicle_number"] = r.get("vehicle_number") or ""
            r["_narration"] = r.get("narration") or ""
        return rows

    q = {"user_id": uid, "company_id": cid, "mechanic_id": pid,
         "is_deleted": {"$ne": True}}
    rows = await db.mechanic_work_orders.find(q, {"_id": 0, "user_id": 0}).to_list(None)
    for r in rows:
        r["_date"] = r.get("work_date") or ""
        r["_kind"] = "work_order"
        r["_debit"] = _q2(r.get("amount") or 0)
        r["_credit"] = _q2(0)
        r["_ref"] = r.get("id") or ""
        r["_id"] = r.get("id") or ""
        r["_vehicle_id"] = r.get("vehicle_id") or ""
        r["_vehicle_number"] = r.get("vehicle_number") or ""
        r["_narration"] = r.get("narration") or ""
    return rows


async def _load_payment_rows(party_type, uid, cid, pid, include_reversed) -> list[dict]:
    if party_type == "vendor":
        coll = db.vendor_payments
        link_field = "vendor_bill_id"
    else:
        coll = db.mechanic_payments
        link_field = "mechanic_work_order_id"

    q = {"user_id": uid, "company_id": cid,
         ("vendor_id" if party_type == "vendor" else "mechanic_id"): pid,
         "is_deleted": {"$ne": True}}
    if not include_reversed:
        q["is_reversed"] = {"$ne": True}

    rows = await coll.find(q, {"_id": 0, "user_id": 0}).to_list(None)
    for r in rows:
        r["_date"] = r.get("date") or ""
        r["_kind"] = "payment"
        # payment_out → credit; receipt_in → negative credit (i.e. debit-side)
        direction = 1 if r.get("type") == "payment_out" else -1
        amt = _q2(r.get("amount") or 0) * Decimal(direction)
        r["_debit"] = _q2(0)
        r["_credit"] = amt
        r["_ref"] = r.get("ref_no") or r.get("id") or ""
        r["_id"] = r.get("id") or ""
        r["_narration"] = r.get("remarks") or ""
        r["_link_field"] = link_field
        r["_link_id"] = r.get(link_field) or ""
        r["_vehicle_id"] = ""
        r["_vehicle_number"] = ""
        # Type label variants for the presentation layer.
        if r.get("is_reversed"):
            r["_kind_label_hint"] = "reversal"
        elif int(r.get("correction_count") or 0) > 0:
            r["_kind_label_hint"] = "correction"
        elif direction < 0:
            r["_kind_label_hint"] = "receipt"
        else:
            r["_kind_label_hint"] = "payment"
    return rows


async def _batched_vehicle_lookup(party_type, uid, cid, payment_rows) -> None:
    """Batched, single-query resolution of `vehicle_id` + `vehicle_number`
    for every payment linked to a bill / work order.  N+1 free."""
    ids = list({r["_link_id"] for r in payment_rows if r.get("_link_id")})
    if not ids:
        return
    coll = db.vendor_bills if party_type == "vendor" else db.mechanic_work_orders
    proj = {"_id": 0, "id": 1, "vehicle_id": 1, "vehicle_number": 1}
    rows = await coll.find(
        {"id": {"$in": ids}, "user_id": uid, "company_id": cid},
        proj,
    ).to_list(len(ids))
    veh = {r["id"]: r for r in rows}
    for p in payment_rows:
        src = veh.get(p.get("_link_id") or "")
        if src:
            p["_vehicle_id"] = src.get("vehicle_id") or ""
            p["_vehicle_number"] = src.get("vehicle_number") or ""


def _sort_key(r: dict) -> tuple:
    return (
        r.get("_date") or "",
        _KIND_ORDER.get(r.get("_kind") or "", 9),
        r.get("created_at") or "",
        r.get("_id") or "",
    )


def _type_label(entry: dict) -> str:
    if entry["kind"] == "payment":
        hint = entry.get("_kind_label_hint") or "payment"
        return {"payment": "Payment", "receipt": "Receipt / Refund",
                "reversal": "Reversal", "correction": "Correction"}[hint]
    return _TYPE_LABELS.get(entry["kind"], entry["kind"].title())


def _project_entry(r: dict, balance: Decimal) -> dict:
    """Presentation shape emitted by the builder — identical for JSON and PDF."""
    return {
        "date": r.get("_date") or "",
        "kind": r.get("_kind") or "",           # wire enum (unchanged)
        "type_label": _type_label({
            "kind": r.get("_kind") or "",
            "_kind_label_hint": r.get("_kind_label_hint"),
        }),
        "ref": r.get("_ref") or "",
        "id": r.get("_id") or "",
        "vehicle_id": r.get("_vehicle_id") or "",
        "vehicle_number": r.get("_vehicle_number") or "",
        "narration": r.get("_narration") or "",
        "debit": _f2(r["_debit"]),
        "credit": _f2(r["_credit"]),
        "balance": _f2(balance),
        # Correction / reversal presentation cues (preserved from Iter133 shape).
        "is_reversed": bool(r.get("is_reversed", False)) if r.get("_kind") == "payment" else False,
        "correction_count": int(r.get("correction_count") or 0) if r.get("_kind") == "payment" else 0,
        "mode": r.get("mode", "") if r.get("_kind") == "payment" else "",
        "against": r.get("against", "") if r.get("_kind") == "payment" else "",
        # Payment→bill/WO linkage (kept for the correction modal).
        "vendor_bill_id": r.get("vendor_bill_id", "") if r.get("_kind") == "payment" else "",
        "mechanic_work_order_id": r.get("mechanic_work_order_id", "") if r.get("_kind") == "payment" else "",
    }


async def build_party_ledger(
    party_type: Literal["vendor", "mechanic"],
    uid: str,
    cid: str,
    pid: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_reversed: bool = False,
    vehicle_id: Optional[str] = None,
) -> dict:
    """Authoritative party ledger.  See module docstring for invariants.

    Parameters
    ----------
    party_type   : "vendor" | "mechanic"
    date_from    : ISO YYYY-MM-DD (inclusive)   — entries strictly before are folded into opening.
    date_to      : ISO YYYY-MM-DD (inclusive).
    include_reversed : if False, reversed payments are excluded EVERYWHERE
                       (opening + entries) — same rule Iter133 already used
                       for the JSON endpoint.
    vehicle_id   : optional filter applied POST vehicle-derivation.  Opening
                   is intentionally computed BEFORE the filter so the ledger
                   remains balance-accurate.
    """
    party = await _resolve_party(party_type, uid, cid, pid)
    company = await _resolve_company(uid, cid)

    # 1. Load ALL bill/WO + payment rows for the party (no date filter yet).
    bill_rows = await _load_bill_rows(party_type, uid, cid, pid, include_reversed)
    pay_rows = await _load_payment_rows(party_type, uid, cid, pid, include_reversed)

    # 2. Batched vehicle derivation for payments — single query.
    await _batched_vehicle_lookup(party_type, uid, cid, pay_rows)

    # 3. Split into pre-window (folded into opening) and in-window (rendered).
    def _in_window(r: dict) -> bool:
        d = r.get("_date") or ""
        if date_from and d < date_from:
            return False
        if date_to and d > date_to:
            return False
        return True

    def _pre_window(r: dict) -> bool:
        d = r.get("_date") or ""
        return bool(date_from) and d < date_from

    # 4. Opening balance = party master opening ± pre-window movements.
    opening_type = (party.get("opening_balance_type") or "payable").lower()
    party_opening = _q2(party.get("opening_balance") or 0)
    # Convention: `payable` opening → adds to debit-side (positive balance
    # means "we owe them"). `advance` opening → subtracts (credit side).
    opening = party_opening if opening_type == "payable" else -party_opening

    for r in bill_rows:
        if _pre_window(r):
            opening += r["_debit"]
    for r in pay_rows:
        if _pre_window(r):
            opening += r["_debit"] - r["_credit"]

    # 5. In-window entries — deterministic sort.
    in_window = [r for r in (bill_rows + pay_rows) if _in_window(r)]
    in_window.sort(key=_sort_key)

    # 6. Optional vehicle filter (applied AFTER derivation; opening
    #    already accounts for pre-window movements → still balance-correct
    #    for the filtered vehicle only when derived vehicle exists on rows).
    if vehicle_id:
        in_window = [r for r in in_window
                     if (r.get("_vehicle_id") or "") == vehicle_id]

    # 7. Assemble entries with running balance.
    entries: list[dict] = []
    running = opening

    # Opening row (rendered only when meaningful).
    if opening != Decimal("0.00") or party_opening != Decimal("0.00"):
        entries.append({
            "date": (party.get("created_at") or "")[:10] or (date_from or ""),
            "kind": "opening",
            "type_label": "Opening",
            "ref": "Opening Balance" if opening >= Decimal("0.00") else "Opening Advance",
            "id": "",
            "vehicle_id": "",
            "vehicle_number": "",
            "narration": "opening payable" if opening_type == "payable" else "opening advance",
            "debit": _f2(opening if opening > 0 else Decimal("0.00")),
            "credit": _f2(-opening if opening < 0 else Decimal("0.00")),
            "balance": _f2(opening),
            "is_reversed": False, "correction_count": 0, "mode": "", "against": "",
            "vendor_bill_id": "", "mechanic_work_order_id": "",
        })

    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for r in in_window:
        running += r["_debit"] - r["_credit"]
        total_debit += r["_debit"]
        total_credit += r["_credit"]
        entries.append(_project_entry(r, running))

    closing = opening + total_debit - total_credit

    party_name = party.get("name", "")
    return {
        "party_type": party_type,
        "party_id": pid,
        "party_name": party_name,
        f"{party_type}_id": pid,          # backwards-compatible
        f"{party_type}_name": party_name, # backwards-compatible
        "party_gstin": party.get("gst_in") or "",
        "company": {
            "name": company.get("name") or company.get("company_name") or "",
            "gstin": company.get("gstin") or company.get("gst_number") or "",
            "address": company.get("address") or "",
        },
        "from": date_from or "",
        "to": date_to or "",
        "include_reversed": bool(include_reversed),
        "vehicle_id_filter": vehicle_id or "",
        "opening_balance": _f2(opening),
        "opening_balance_type": opening_type,
        "total_debit": _f2(total_debit),
        "total_credit": _f2(total_credit),
        "closing_balance": _f2(closing),
        "outstanding": _f2(closing if closing > 0 else Decimal("0.00")),
        "advance": _f2(-closing if closing < 0 else Decimal("0.00")),
        "entries": entries,
        "generated_at": now_utc().isoformat(),
    }


def guard_pdf_size(dataset: dict) -> None:
    """PDF-only guardrail — no silent truncation.  Raises HTTP 413 with a
    clear operator message when the entry count would exceed
    `MAX_PDF_ENTRIES`."""
    n = len(dataset.get("entries") or [])
    if n > MAX_PDF_ENTRIES:
        raise HTTPException(
            status_code=413,
            detail=(f"Ledger contains too many transactions ({n:,}) for this PDF range. "
                    f"Narrow the date range (limit: {MAX_PDF_ENTRIES:,})."),
        )
