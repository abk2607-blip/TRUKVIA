"""Iter139 P0 · Quick Operational Expense — bulk canonical Expense writer.

ONE INPUT → N canonical Expense rows.  Every row goes through the
existing Iter133 `_validate_and_normalise` gate — no accounting logic
is duplicated.  Standalone-Mongo-safe: row-level independent writes
with row-level idempotency via `expenses_source_key_uniq` partial-unique
index.  See Iter139 discovery §6-§9 for the atomicity rationale.
"""
from __future__ import annotations

import re
from typing import Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db import db
from models import Expense, now_utc, new_id


# Server-authoritative whitelist. Frontend hiding is not sufficient.
QUICK_OP_CATEGORIES: set[str] = {
    "Toll", "Diesel", "Parking", "Batta", "Driver Batta",
    "Loading Charges", "Unloading Charges", "Weighment",
    "Detention", "Cleaning", "Driver Food", "AdBlue",
}
# Normalised on write — operator vocabulary → canonical DB value.
_CATEGORY_ALIAS: dict[str, str] = {"Driver Batta": "Batta"}
_MAX_ENTRIES = 200


def _slug(s: str) -> str:
    """Category → source_key slug (lowercase, non-alnum → _)."""
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _q2(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _iso_date_ok(s: str) -> bool:
    try:
        datetime.strptime((s or "").strip(), "%Y-%m-%d")
        return True
    except Exception:
        return False


async def bulk_create_operational_expenses(uid: str, cid: str, user: dict,
                                           body: dict) -> dict:
    """Iter139 P0 batch endpoint.  Row-level idempotency + partial-success
    contract (§30-§31).  Never raises for a per-row problem — those flow
    through the `results[]` list as `status='failed'` / `'duplicate'`."""
    # Import inside function to avoid a router↔service import cycle.
    from routers.expenses import _validate_and_normalise

    # ── Batch-level validation ──────────────────────────────────────
    date = (body or {}).get("date") or ""
    if not _iso_date_ok(date):
        raise HTTPException(status_code=400, detail="date is required (YYYY-MM-DD)")
    category_in = ((body or {}).get("category") or "").strip()
    if category_in not in QUICK_OP_CATEGORIES:
        raise HTTPException(status_code=400,
            detail=f"Category '{category_in}' is not eligible for Quick Operational Expense; use the Expense Register.")
    category = _CATEGORY_ALIAS.get(category_in, category_in)

    entries = (body or {}).get("entries") or []
    if not isinstance(entries, list) or len(entries) < 1:
        raise HTTPException(status_code=400, detail="entries must be a non-empty list")
    if len(entries) > _MAX_ENTRIES:
        raise HTTPException(status_code=400,
            detail=f"Too many entries: {len(entries)} > {_MAX_ENTRIES}")

    trip_id = ((body or {}).get("trip_id") or "").strip()
    if trip_id:
        trip = await db.trips.find_one({"id": trip_id, "user_id": uid,
                                        "company_id": cid}, {"_id": 0, "id": 1})
        if not trip:
            raise HTTPException(status_code=400, detail="Trip not found in tenant")

    batch_id = new_id("qob_")
    cat_slug = _slug(category)
    results: list[dict] = []
    created = duplicate = failed = 0

    for e in entries:
        row_id = (e or {}).get("client_row_id") or ""
        base = {"client_row_id": row_id, "status": "failed"}
        vid = (e or {}).get("vehicle_id") or ""
        supplier_mode = (e or {}).get("supplier_settlement_mode") or ""
        remarks = (e or {}).get("remarks") or ""
        try:
            amt_raw = float((e or {}).get("amount") or 0)
        except Exception:
            amt_raw = 0.0

        # Row-level guards (per §32 error contract, never raise — record in results).
        if not row_id:
            base["error"] = {"code": "INVALID_ROW", "detail": "client_row_id is required"}
            results.append(base); failed += 1; continue
        # Diesel derives amount from qty × rate — skip the pre-check here
        # and enforce via INVALID_DIESEL_QTY_RATE inside the Diesel branch.
        if amt_raw <= 0 and category != "Diesel":
            base["error"] = {"code": "INVALID_AMOUNT", "detail": "amount must be > 0"}
            results.append(base); failed += 1; continue
        if not vid:
            base["error"] = {"code": "VEHICLE_NOT_FOUND", "detail": "vehicle_id is required"}
            results.append(base); failed += 1; continue

        veh = await db.vehicles.find_one(
            {"id": vid, "user_id": uid, "company_id": cid},
            {"_id": 0, "vehicle_number": 1, "vehicle_type": 1, "is_active": 1},
        )
        if not veh:
            base["error"] = {"code": "VEHICLE_NOT_FOUND", "detail": "Vehicle not found in tenant"}
            results.append(base); failed += 1; continue
        if veh.get("is_active") is False:
            base["error"] = {"code": "VEHICLE_INACTIVE", "detail": "Vehicle is inactive"}
            results.append(base); failed += 1; continue

        is_supplier = (veh.get("vehicle_type") or "").lower() == "supplier"
        if is_supplier:
            if not supplier_mode:
                base["error"] = {"code": "MISSING_SUPPLIER_MODE",
                                 "detail": "supplier_settlement_mode is required for supplier-owned vehicles"}
                results.append(base); failed += 1; continue
            if supplier_mode not in ("supplier_settlement_adjustment", "company_borne"):
                base["error"] = {"code": "INVALID_SUPPLIER_MODE",
                                 "detail": f"Invalid supplier_settlement_mode '{supplier_mode}'"}
                results.append(base); failed += 1; continue
            derived_owned, derived_mode = True, supplier_mode
        else:
            derived_owned, derived_mode = False, "n/a"

        # ── Iter139 UAT #2 · Diesel — server-authoritative amount + Vendor link ──
        #  • Amount is computed strictly from qty × rate; a client-supplied
        #    `amount` that disagrees is rejected (AMOUNT_TAMPERED). Non-Diesel
        #    rows are untouched.
        #  • Optional `vendor_id` is resolved against the existing Vendor
        #    master. When present, the row is persisted with
        #    party_type='vendor', party_id=<vid>, party_name=<name>.
        #    This reuses the field set already validated by
        #    `_validate_and_normalise` (routers/expenses.py) — NO schema
        #    change, NO VendorBill / VendorPayment side-effect, Vendor
        #    Ledger (Bills+Payments) unaffected.
        narration_override = None
        party_link = {"party_type": "cash", "party_id": "", "party_name": ""}
        if category == "Diesel":
            try:
                qty = float((e or {}).get("qty") or 0)
            except Exception:
                qty = 0.0
            try:
                rate = float((e or {}).get("rate") or 0)
            except Exception:
                rate = 0.0
            if qty <= 0 or rate <= 0:
                base["error"] = {"code": "INVALID_DIESEL_QTY_RATE",
                                 "detail": "qty and rate must both be > 0 for Diesel"}
                results.append(base); failed += 1; continue
            server_amount = _q2(qty * rate)
            if amt_raw and abs(amt_raw - server_amount) > 0.01:
                base["error"] = {"code": "AMOUNT_TAMPERED",
                                 "detail": f"amount ({amt_raw}) does not match qty × rate ({server_amount})"}
                results.append(base); failed += 1; continue
            amt_raw = server_amount

            vid_link = ((e or {}).get("vendor_id") or "").strip()
            vendor_name = ""
            if vid_link:
                ven = await db.vendors.find_one(
                    {"id": vid_link, "user_id": uid, "company_id": cid},
                    {"_id": 0, "name": 1, "is_active": 1},
                )
                if not ven:
                    base["error"] = {"code": "VENDOR_NOT_FOUND",
                                     "detail": "Selected Vendor not found in tenant"}
                    results.append(base); failed += 1; continue
                if ven.get("is_active") is False:
                    base["error"] = {"code": "VENDOR_INACTIVE",
                                     "detail": "Selected Vendor is inactive"}
                    results.append(base); failed += 1; continue
                vendor_name = ven.get("name", "")
                party_link = {"party_type": "vendor", "party_id": vid_link,
                              "party_name": vendor_name}

            filled_at = str((e or {}).get("filled_at") or "").strip()
            parts = [f"{qty}L @ ₹{rate:.2f}"]
            if filled_at:
                parts.append(filled_at)
            if vendor_name:
                parts.append(vendor_name)
            narration_override = " · ".join(parts)[:400]

        source_key = f"quickop:{date}:{cat_slug}:{vid}:{row_id}"
        # Fast-path duplicate check — avoid IX write-attempt when we already know.
        existing = await db.expenses.find_one(
            {"user_id": uid, "company_id": cid, "source_key": source_key},
            {"_id": 0, "user_id": 0},
        )
        if existing:
            results.append({"client_row_id": row_id, "status": "duplicate",
                            "expense": existing}); duplicate += 1; continue

        try:
            payload = Expense(
                date=date, category=category, amount=_q2(amt_raw),
                narration=(narration_override if narration_override is not None
                           else str((e or {}).get("narration") or "")[:400]),
                remarks=str(remarks or ""),
                vehicle_id=vid, vehicle_number=veh.get("vehicle_number", ""),
                trip_id=trip_id or "", repair_event_id="",
                party_type=party_link["party_type"],
                party_id=party_link["party_id"],
                party_name=party_link["party_name"],
                vendor_bill_id="", mechanic_work_order_id="",
                supplier_owned_vehicle=derived_owned,
                supplier_settlement_mode=derived_mode,
                settlement_mode="cash_now",
                source_type="quick_op", source_key=source_key,
                source_trip_id=trip_id or "",
                file_ids=[],
            )
            payload = await _validate_and_normalise(uid, cid, payload)
        except HTTPException as ex:
            base["error"] = {"code": "VALIDATION", "detail": str(ex.detail)}
            results.append(base); failed += 1; continue
        except Exception as ex:
            base["error"] = {"code": "VALIDATION", "detail": str(ex)[:200]}
            results.append(base); failed += 1; continue

        doc = payload.model_dump()
        doc["user_id"] = uid
        doc["company_id"] = cid
        doc["created_by"] = uid
        doc["created_at"] = now_utc().isoformat()
        doc["is_deleted"] = False
        try:
            await db.expenses.insert_one(doc)
        except DuplicateKeyError:
            existing = await db.expenses.find_one(
                {"user_id": uid, "company_id": cid, "source_key": source_key},
                {"_id": 0, "user_id": 0},
            )
            results.append({"client_row_id": row_id, "status": "duplicate",
                            "expense": existing or {}}); duplicate += 1; continue
        doc.pop("_id", None); doc.pop("user_id", None)
        results.append({"client_row_id": row_id, "status": "created",
                        "expense": doc}); created += 1

    return {"batch_id": batch_id, "date": date, "category": category,
            "created": created, "duplicate": duplicate, "failed": failed,
            "results": results}
