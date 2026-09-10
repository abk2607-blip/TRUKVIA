"""Iter150A-1 · Read-only Day Book + Accounts + owner-only reproject.

Endpoints:
  GET  /api/fin/accounts               — list tenant accounts.
  GET  /api/fin/day-book               — grouped movements (date, account).
  GET  /api/fin/fin-txn/{id}           — single row with source back-reference.
  POST /api/fin/reproject              — owner-only temporary UAT rebuild.
                                          NOT a permanent substitute for the
                                          Iter150A-2 write-path hooks.

All endpoints are strictly tenant-scoped via `_active_company_id`.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Body

from db import db
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit
from services_fin_txn import (
    reproject_source,
    backfill_tenant,
    ensure_system_accounts,
    SUPPORTED_SOURCE_TYPES,
)

router = APIRouter(prefix="/api")


def _require_owner(user: dict) -> None:
    role = (user.get("effective_role") or "").lower()
    if role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner-only endpoint. Iter150A-1 reproject is a temporary "
                   "admin bridge — write-path hooks in Iter150A-2 will replace it.",
        )


@router.get("/fin/accounts")
async def list_accounts(request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    # Idempotent seed on first hit — Day Book is empty for a fresh tenant
    # until backfill runs, but /accounts should always list the system set.
    await ensure_system_accounts(uid, cid)
    rows = await db.fin_accounts.find(
        {"user_id": uid, "company_id": cid, "is_active": True},
        {"_id": 0, "user_id": 0},
    ).sort("code", 1).to_list(500)
    return rows


@router.get("/fin/day-book")
async def day_book(
    request: Request,
    date_from: str,
    date_to: str,
    account_code: Optional[str] = None,
    account_id: Optional[str] = None,
    source_type: Optional[str] = None,
    party_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    trip_id: Optional[str] = None,
    limit: int = 5000,
    user=Depends(get_current_user),
):
    """Grouped movements between `date_from` and `date_to` (inclusive).

    Returns:
      {
        "date_from": "…",
        "date_to":   "…",
        "rows":      [FinTxn, …],       # every leg in the window
        "totals":    {                  # per-account aggregates
          "AR":         {"in": …, "out": …, "net": …},
          "EXPENSE_DEFAULT": {…}, …
        }
      }
    """
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    if not date_from or not date_to:
        raise HTTPException(status_code=400,
                            detail="date_from and date_to are required (YYYY-MM-DD)")
    q: dict = {
        "user_id": uid, "company_id": cid,
        "txn_date": {"$gte": date_from, "$lte": date_to},
        "status": "active",
    }
    if account_code: q["account_code"] = account_code
    if account_id:   q["account_id"] = account_id
    if source_type:  q["source_type"] = source_type
    if party_id:     q["party_id"] = party_id
    if vehicle_id:   q["vehicle_id"] = vehicle_id
    if trip_id:      q["trip_id"] = trip_id
    rows = await db.fin_txn.find(q, {"_id": 0, "user_id": 0}) \
        .sort([("txn_date", -1), ("created_at", -1)]) \
        .to_list(int(max(1, min(limit, 20000))))

    totals: dict = {}
    for r in rows:
        code = r.get("account_code") or ""
        t = totals.setdefault(code, {"in": 0.0, "out": 0.0, "net": 0.0})
        amt = float(r.get("amount") or 0)
        if r.get("direction") == "in":
            t["in"] += amt
        else:
            t["out"] += amt
    for code, t in totals.items():
        t["in"] = round(t["in"], 2)
        t["out"] = round(t["out"], 2)
        t["net"] = round(t["in"] - t["out"], 2)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "rows": rows,
        "totals": totals,
        "count": len(rows),
    }


@router.get("/fin/fin-txn/{txid}")
async def get_fin_txn(txid: str, request: Request, user=Depends(get_current_user)):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    row = await db.fin_txn.find_one(
        {"id": txid, "user_id": uid, "company_id": cid},
        {"_id": 0, "user_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail="FinTxn not found")
    # Best-effort source back-reference — for drill-through UX later.
    src_ref: dict = {}
    try:
        stype = row.get("source_type") or ""
        sid = row.get("source_id") or ""
        coll_map = {
            "invoice": "invoices", "credit_debit_note": "credit_debit_notes",
            "supplier_payment": "supplier_payments",
            "vendor_payment": "vendor_payments",
            "mechanic_payment": "mechanic_payments",
            "expense": "expenses",
            "vendor_bill": "vendor_bills",
            "mechanic_work_order": "mechanic_work_orders",
        }
        if stype in coll_map:
            src = await db[coll_map[stype]].find_one(
                {"user_id": uid, "company_id": cid, "id": sid},
                {"_id": 0, "user_id": 0},
            )
            if src:
                src_ref = {"collection": coll_map[stype], "doc": src}
    except Exception:
        pass
    return {"txn": row, "source": src_ref}


@router.post("/fin/reproject")
async def reproject(
    request: Request,
    body: dict = Body(...),
    user=Depends(get_current_user),
):
    """Owner-only rebuild bridge.

    Body variants:
      A. `{ "source_type": "...", "source_id": "..." }` — reproject one doc.
      B. `{ "full": true, "dry_run": false }` — full-tenant rebuild.

    Returns detailed counts. Marked with `temporary_iter150a1_bridge=True`
    so callers know this is not a permanent primitive.
    """
    _require_owner(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    full = bool(body.get("full"))
    dry_run = bool(body.get("dry_run"))

    if not full:
        source_type = (body.get("source_type") or "").strip()
        source_id = (body.get("source_id") or "").strip()
        if not source_type or not source_id:
            raise HTTPException(status_code=400,
                detail="source_type and source_id are required (or set full=true)")
        if source_type not in SUPPORTED_SOURCE_TYPES:
            raise HTTPException(status_code=400,
                detail=f"unsupported source_type. Allowed: {SUPPORTED_SOURCE_TYPES}")
        if dry_run:
            # Reproject writes nothing in dry-run mode.
            return {
                "temporary_iter150a1_bridge": True,
                "dry_run": True,
                "source_type": source_type, "source_id": source_id,
                "message": "dry_run=true — no rows deleted or written.",
            }
        deleted, written = await reproject_source(uid, cid, source_type, source_id)
        try:
            await _log_audit(
                {"user_id": uid, "company_id": cid,
                 "email": user.get("email", ""), "name": user.get("name", "")},
                "fin", "reproject_source",
                f"{source_type}:{source_id}",
                f"deleted={deleted} written={written}",
                "iter150a1_admin_bridge", {"deleted": deleted, "written": written},
            )
        except Exception:
            pass
        return {
            "temporary_iter150a1_bridge": True,
            "dry_run": False,
            "source_type": source_type, "source_id": source_id,
            "deleted": deleted, "written": written,
        }

    # Full-tenant rebuild.
    report = await backfill_tenant(uid, cid, dry_run=dry_run, verbose=False)
    report["temporary_iter150a1_bridge"] = True
    try:
        await _log_audit(
            {"user_id": uid, "company_id": cid,
             "email": user.get("email", ""), "name": user.get("name", "")},
            "fin", "reproject_full", cid,
            f"dry_run={dry_run} total_written={report.get('total_projected_legs')}",
            "iter150a1_admin_bridge",
            {"dry_run": dry_run,
             "per_source": report.get("per_source"),
             "invariants": report.get("invariants")},
        )
    except Exception:
        pass
    return report
