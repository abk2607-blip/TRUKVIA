"""Iter150D · Day Closing — financial-control checkpoint (not entry lock).

Six endpoints (all `/api` prefix, tenant-scoped):

  POST /api/fin/day-closures                     (owner) — close a day
  POST /api/fin/day-closures/{close_date}/reopen (owner) — reopen a closed day
  GET  /api/fin/day-closures                             — list closures
  GET  /api/fin/day-closures/{close_date}                — one closure
  GET  /api/fin/day-closures/{close_date}/late-entries   — legs projected after close
  GET  /api/fin/day-status                               — quick date probe

Read-only against `fin_txn`. Zero touch on locked services/routers.
"""
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from db import db
from auth import get_current_user
from company import _active_company_id
from audit import _log_audit
from models_iter150d import FinDayClosure
from models import now_utc

router = APIRouter(prefix="/api")


# ── Guards ──────────────────────────────────────────────────────────────

def _require_owner(user: dict) -> None:
    role = (user.get("effective_role") or user.get("role") or "").lower()
    if role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner-only endpoint. Only the tenant owner may close or "
                   "reopen a day.",
        )


def _parse_iso_date(value: str, field: str = "close_date") -> _date:
    try:
        return _date.fromisoformat(value)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be ISO YYYY-MM-DD",
        )


# ── Snapshot helper ─────────────────────────────────────────────────────

async def _capture_snapshot(uid: str, cid: str, close_date: str):
    """Return (snapshot_dict, source_count) computed live from fin_txn."""
    cur = db.fin_txn.find(
        {
            "user_id": uid, "company_id": cid, "status": "active",
            "txn_date": {"$lte": close_date},
        },
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1},
    )
    snap: dict = {}
    count = 0
    async for r in cur:
        count += 1
        code = r.get("account_code") or ""
        t = snap.setdefault(code, {"in": 0.0, "out": 0.0, "net": 0.0})
        amt = float(r.get("amount") or 0)
        if r.get("direction") == "in":
            t["in"] += amt
        else:
            t["out"] += amt
    for _, t in snap.items():
        t["in"] = round(t["in"], 2)
        t["out"] = round(t["out"], 2)
        t["net"] = round(t["in"] - t["out"], 2)
    return snap, count


# ── Writer endpoints (owner-only) ───────────────────────────────────────

@router.post("/fin/day-closures")
async def close_day(
    request: Request,
    body: dict = Body(...),
    user=Depends(get_current_user),
):
    _require_owner(user)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    close_date = (body.get("close_date") or "").strip()
    if not close_date:
        raise HTTPException(status_code=400, detail="close_date is required")
    d = _parse_iso_date(close_date)
    today = now_utc().date()
    if d > today:
        raise HTTPException(
            status_code=422,
            detail="close_date cannot be in the future (v1 accepts today or past)",
        )
    close_notes = (body.get("close_notes") or "").strip()

    # Duplicate open closure guard (409). A `reopened` closure for the same
    # date may be re-closed — see re-close branch below.
    existing = await db.fin_day_closures.find_one(
        {"user_id": uid, "company_id": cid, "close_date": close_date},
        {"_id": 0},
    )
    now = now_utc().isoformat()
    snap, count = await _capture_snapshot(uid, cid, close_date)

    if existing and existing.get("status") == "closed":
        raise HTTPException(
            status_code=409,
            detail=f"Day {close_date} is already closed",
        )

    if existing and existing.get("status") == "reopened":
        # Re-close: refresh snapshot + append history event; preserve prior.
        hist = list(existing.get("history") or [])
        hist.append({
            "event": "closed", "at": now, "by": uid,
            "notes": close_notes, "snapshot": snap,
            "snapshot_source_count": count,
        })
        await db.fin_day_closures.update_one(
            {"user_id": uid, "company_id": cid, "close_date": close_date},
            {"$set": {
                "status": "closed", "closed_at": now, "closed_by": uid,
                "close_notes": close_notes,
                "snapshot": snap, "snapshot_source_count": count,
                "reopened_at": "", "reopened_by": "", "reopen_reason": "",
                "history": hist, "modified_at": now,
            }},
        )
        doc = await db.fin_day_closures.find_one(
            {"user_id": uid, "company_id": cid, "close_date": close_date},
            {"_id": 0, "user_id": 0},
        )
        await _log_audit(user, "fin_day_closure", "reclose",
                         entity_id=doc.get("id", ""), entity_ref=close_date,
                         changes={"count": count, "accounts": len(snap)})
        return doc

    # Fresh close.
    payload = FinDayClosure(
        close_date=close_date, closed_by=uid, close_notes=close_notes,
        snapshot=snap, snapshot_source_count=count,
    )
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["company_id"] = cid
    doc["history"] = [{
        "event": "closed", "at": doc["closed_at"], "by": uid,
        "notes": close_notes, "snapshot": snap,
        "snapshot_source_count": count,
    }]
    try:
        await db.fin_day_closures.insert_one(doc)
    except Exception as e:
        # UNIQUE index race (concurrent close for same date).
        raise HTTPException(
            status_code=409,
            detail=f"Day {close_date} already closed (concurrent write)",
        ) from e
    await _log_audit(user, "fin_day_closure", "close",
                     entity_id=doc["id"], entity_ref=close_date,
                     changes={"count": count, "accounts": len(snap),
                              "notes": close_notes})
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.post("/fin/day-closures/{close_date}/reopen")
async def reopen_day(
    close_date: str, request: Request,
    body: dict = Body(...),
    user=Depends(get_current_user),
):
    _require_owner(user)
    _parse_iso_date(close_date)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)

    reason = (body.get("reopen_reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="reopen_reason is required")

    existing = await db.fin_day_closures.find_one(
        {"user_id": uid, "company_id": cid, "close_date": close_date},
        {"_id": 0},
    )
    if not existing:
        raise HTTPException(status_code=404,
                            detail=f"No closure exists for {close_date}")
    if existing.get("status") == "reopened":
        raise HTTPException(status_code=409,
                            detail=f"Day {close_date} is already reopened")

    now = now_utc().isoformat()
    hist = list(existing.get("history") or [])
    hist.append({"event": "reopened", "at": now, "by": uid, "reason": reason})
    await db.fin_day_closures.update_one(
        {"user_id": uid, "company_id": cid, "close_date": close_date},
        {"$set": {
            "status": "reopened",
            "reopened_at": now, "reopened_by": uid, "reopen_reason": reason,
            "history": hist, "modified_at": now,
        }},
    )
    doc = await db.fin_day_closures.find_one(
        {"user_id": uid, "company_id": cid, "close_date": close_date},
        {"_id": 0, "user_id": 0},
    )
    await _log_audit(user, "fin_day_closure", "reopen",
                     entity_id=doc.get("id", ""), entity_ref=close_date,
                     changes={"reason": reason})
    return doc


# ── Reader endpoints ────────────────────────────────────────────────────

@router.get("/fin/day-closures")
async def list_closures(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    q: dict = {"user_id": uid, "company_id": cid}
    if date_from or date_to:
        rng: dict = {}
        if date_from: rng["$gte"] = date_from
        if date_to:   rng["$lte"] = date_to
        q["close_date"] = rng
    if status:
        q["status"] = status
    rows = await db.fin_day_closures.find(
        q, {"_id": 0, "user_id": 0},
    ).sort("close_date", -1).to_list(int(max(1, min(limit, 5000))))
    return {"rows": rows, "count": len(rows)}


@router.get("/fin/day-closures/{close_date}")
async def get_closure(
    close_date: str, request: Request,
    user=Depends(get_current_user),
):
    _parse_iso_date(close_date)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.fin_day_closures.find_one(
        {"user_id": uid, "company_id": cid, "close_date": close_date},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404,
                            detail=f"No closure exists for {close_date}")
    return doc


def _bucket(days: int) -> str:
    if days <= 7:   return "0-7"
    if days <= 30:  return "8-30"
    if days <= 90:  return "31-90"
    return "90+"


@router.get("/fin/day-closures/{close_date}/late-entries")
async def late_entries(
    close_date: str, request: Request,
    user=Depends(get_current_user),
):
    _parse_iso_date(close_date)
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    closure = await db.fin_day_closures.find_one(
        {"user_id": uid, "company_id": cid, "close_date": close_date},
        {"_id": 0, "closed_at": 1},
    )
    if not closure:
        raise HTTPException(status_code=404,
                            detail=f"No closure exists for {close_date}")
    closed_at = closure.get("closed_at") or ""
    cur = db.fin_txn.find({
        "user_id": uid, "company_id": cid, "status": "active",
        "txn_date": {"$lte": close_date},
        "created_at": {"$gt": closed_at},
    }, {"_id": 0, "user_id": 0}).sort("txn_date", -1)
    rows = await cur.to_list(5000)
    by_source: dict = {}
    by_bucket = {"0-7": 0, "8-30": 0, "31-90": 0, "90+": 0}
    totals = {"in": 0.0, "out": 0.0, "net": 0.0}
    close_d = _date.fromisoformat(close_date)
    for r in rows:
        stype = r.get("source_type") or ""
        by_source[stype] = by_source.get(stype, 0) + 1
        try:
            td = _date.fromisoformat((r.get("txn_date") or "")[:10])
            days_late = (close_d - td).days
        except Exception:
            days_late = 0
        r["days_late"] = max(0, days_late)
        by_bucket[_bucket(r["days_late"])] += 1
        amt = float(r.get("amount") or 0)
        if r.get("direction") == "in": totals["in"] += amt
        else: totals["out"] += amt
    totals["in"]  = round(totals["in"], 2)
    totals["out"] = round(totals["out"], 2)
    totals["net"] = round(totals["in"] - totals["out"], 2)
    return {
        "close_date": close_date,
        "count": len(rows),
        "totals": totals,
        "by_source_type": by_source,
        "by_days_late_bucket": by_bucket,
        "rows": rows,
    }


@router.get("/fin/day-status")
async def day_status(
    request: Request,
    date: str,
    user=Depends(get_current_user),
):
    if not date:
        raise HTTPException(status_code=400, detail="date is required (YYYY-MM-DD)")
    _parse_iso_date(date, field="date")
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    doc = await db.fin_day_closures.find_one(
        {"user_id": uid, "company_id": cid, "close_date": date},
        {"_id": 0, "status": 1, "closed_at": 1, "closed_by": 1,
         "reopened_at": 1, "reopened_by": 1},
    )
    if not doc:
        return {"date": date, "is_closed": False}
    is_closed = doc.get("status") == "closed"
    # Cheap late-entry flag: only compute when currently closed.
    has_late = False
    if is_closed and doc.get("closed_at"):
        has_late = bool(await db.fin_txn.find_one({
            "user_id": uid, "company_id": cid, "status": "active",
            "txn_date": {"$lte": date},
            "created_at": {"$gt": doc["closed_at"]},
        }, {"_id": 0, "id": 1}))
    return {
        "date": date,
        "is_closed": is_closed,
        "status": doc.get("status"),
        "closed_at": doc.get("closed_at", ""),
        "closed_by": doc.get("closed_by", ""),
        "reopened_at": doc.get("reopened_at", ""),
        "reopened_by": doc.get("reopened_by", ""),
        "has_late_entries": has_late,
    }
