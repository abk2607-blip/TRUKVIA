"""Iter150C · Source Ledgers / Financial Traceability — READ/UI-only.

Two endpoints (strictly read-only, tenant-scoped, no `fin_txn` writes):

  GET  /api/fin/source/{source_type}/{source_id}
       → authoritative source doc for a FinTxn leg (drill: leg → source).

  GET  /api/fin/source-legs/{source_type}/{source_id}
       → all `fin_txn` legs for a given source (drill: source → ledger).

Supports the 12 canonical source_types frozen by Iter150A-1 + Iter150B:
  invoice · credit_debit_note · supplier_payment · vendor_payment ·
  mechanic_payment · expense · vendor_bill · mechanic_work_order ·
  trip_customer_receipt · wallet_recharge · wallet_transfer ·
  wallet_adjustment.

Zero writes. Zero mutation of any locked service or router.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends

from db import db
from auth import get_current_user
from company import _active_company_id
from services_fin_txn import SUPPORTED_SOURCE_TYPES

router = APIRouter(prefix="/api")


# source_type → authoritative Mongo collection (Iter150C · frozen).
_COLL_MAP: dict[str, str] = {
    "invoice": "invoices",
    "credit_debit_note": "credit_debit_notes",
    "supplier_payment": "supplier_payments",
    "vendor_payment": "vendor_payments",
    "mechanic_payment": "mechanic_payments",
    "expense": "expenses",
    "vendor_bill": "vendor_bills",
    "mechanic_work_order": "mechanic_work_orders",
    "trip_customer_receipt": "trips",
    "wallet_recharge": "wallet_recharges",
    "wallet_transfer": "wallet_transfers",
    "wallet_adjustment": "wallet_adjustments",
}


def _split_trip_receipt(source_id: str) -> tuple[str, Optional[str]]:
    """Split `trip_customer_receipt` compound source_id.

    source_id is either `{trip_id}` (whole-trip drill) or
    `{trip_id}:{receipt_id_or_idxN}` (per-receipt drill).
    Returns (trip_id, receipt_id_or_None).
    """
    if ":" in source_id:
        tid, rid = source_id.split(":", 1)
        return tid.strip(), rid.strip() or None
    return source_id.strip(), None


@router.get("/fin/source/{source_type}/{source_id}")
async def get_source_doc(
    source_type: str,
    source_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    """Return the authoritative source document for a FinTxn leg.

    Response shape:
      {
        "source_type": "...",
        "source_id":   "...",
        "collection":  "...",
        "doc":         { … authoritative doc … },
        # trip_customer_receipt with compound source_id only:
        "receipt":     { … embedded receipt row … } | null
      }
    """
    if source_type not in _COLL_MAP or source_type not in SUPPORTED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported source_type. Allowed: {SUPPORTED_SOURCE_TYPES}",
        )
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    coll = _COLL_MAP[source_type]

    if source_type == "trip_customer_receipt":
        tid, rid = _split_trip_receipt(source_id)
        trip = await db[coll].find_one(
            {"id": tid, "user_id": uid, "company_id": cid},
            {"_id": 0, "user_id": 0},
        )
        if not trip:
            raise HTTPException(status_code=404, detail="Source doc not found")
        receipt = None
        if rid:
            for i, r in enumerate(trip.get("customer_receipts") or []):
                r_id = str(r.get("id") or "").strip() or f"idx{i}"
                if r_id == rid:
                    receipt = r
                    break
        return {
            "source_type": source_type,
            "source_id": source_id,
            "collection": coll,
            "doc": trip,
            "receipt": receipt,
        }

    doc = await db[coll].find_one(
        {"id": source_id, "user_id": uid, "company_id": cid},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Source doc not found")
    return {
        "source_type": source_type,
        "source_id": source_id,
        "collection": coll,
        "doc": doc,
    }


@router.get("/fin/source-legs/{source_type}/{source_id}")
async def get_source_legs(
    source_type: str,
    source_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    """Return every FinTxn leg projected from a given source.

    Compound-key handling (mirrors Iter150A-1/A-2 cascade semantics):
      * `invoice` + inv_id  → include embedded `invoice_payment:{inv_id}:*`.
      * `trip_customer_receipt` + `{trip_id}` (no rid) → prefix all receipts.
      * `trip_customer_receipt` + `{trip_id}:{rid}`   → exact match.
      * All other 10 types → exact `source_id` match.
    """
    if source_type not in _COLL_MAP or source_type not in SUPPORTED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported source_type. Allowed: {SUPPORTED_SOURCE_TYPES}",
        )
    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    base = {"user_id": uid, "company_id": cid, "status": "active"}
    ors: list[dict] = []

    if source_type == "invoice":
        ors.append({"source_type": "invoice", "source_id": source_id})
        # Embedded invoice_payment legs cascade under `{inv_id}:*`.
        ors.append({
            "source_type": "invoice_payment",
            "source_id": {"$regex": f"^{source_id}:"},
        })
    elif source_type == "trip_customer_receipt":
        if ":" in source_id:
            ors.append({"source_type": source_type, "source_id": source_id})
        else:
            # Whole-trip drill — prefix all `{trip_id}:*` legs.
            ors.append({
                "source_type": source_type,
                "source_id": {"$regex": f"^{source_id}:"},
            })
    else:
        ors.append({"source_type": source_type, "source_id": source_id})

    q = {**base, "$or": ors}
    rows = await db.fin_txn.find(
        q, {"_id": 0, "user_id": 0}
    ).sort([("txn_date", 1), ("created_at", 1)]).to_list(5000)

    totals = {"in": 0.0, "out": 0.0, "net": 0.0}
    for r in rows:
        amt = float(r.get("amount") or 0)
        if r.get("direction") == "in":
            totals["in"] += amt
        else:
            totals["out"] += amt
    totals["in"] = round(totals["in"], 2)
    totals["out"] = round(totals["out"], 2)
    totals["net"] = round(totals["in"] - totals["out"], 2)

    return {
        "source_type": source_type,
        "source_id": source_id,
        "count": len(rows),
        "legs": rows,
        "totals": totals,
    }
