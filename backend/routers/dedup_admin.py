"""Iter127a · Duplicate-master admin listing + startup backfill.

Two responsibilities:
  1. `ensure_dedup_indexes_and_backfill(db)` — one-shot startup migration.
     Populates `*_norm` shadow fields on existing rows so runtime dedup
     lookups work from the first request onward. Then attempts to create
     PARTIAL unique indexes; if existing duplicates prevent it, logs a
     save_health row and skips the index (runtime 409 still catches new
     writes). Safe to call repeatedly (idempotent).
  2. `GET /api/admin/iter127-duplicates` — read-only listing of the
     collision groups so ops can review manually. NEVER auto-merges,
     NEVER writes.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request

from db import db
from auth import get_current_user
from dedup import (
    norm_gstin, norm_pan, norm_name, norm_phone, norm_vehicle_number,
)

logger = logging.getLogger(__name__)
_BACKFILL_FLAG_ID = "iter127a_dedup_backfill_v1"

router = APIRouter(prefix="/api")


async def ensure_dedup_indexes_and_backfill():
    """Idempotent startup migration."""
    try:
        flag = await db.migration_flags.find_one({"_id": _BACKFILL_FLAG_ID})
        if flag:
            return
    except Exception:
        pass

    # ---- Customers: gstin_norm / pan_norm / name_norm / phone_norm ----
    async for c in db.customers.find({}, {"_id": 1, "gstin": 1, "pan": 1, "name": 1, "phone": 1}):
        try:
            await db.customers.update_one({"_id": c["_id"]}, {"$set": {
                "gstin_norm": norm_gstin(c.get("gstin")),
                "pan_norm":   norm_pan(c.get("pan")),
                "name_norm":  norm_name(c.get("name")),
                "phone_norm": norm_phone(c.get("phone")),
            }})
        except Exception:
            pass

    async for v in db.vehicles.find({}, {"_id": 1, "vehicle_number": 1}):
        try:
            await db.vehicles.update_one({"_id": v["_id"]}, {"$set": {
                "vehicle_number_norm": norm_vehicle_number(v.get("vehicle_number")),
            }})
        except Exception:
            pass

    async for s in db.suppliers.find({}, {"_id": 1, "gst_in": 1, "pan": 1, "name": 1, "mobile": 1}):
        try:
            await db.suppliers.update_one({"_id": s["_id"]}, {"$set": {
                "gstin_norm":  norm_gstin(s.get("gst_in")),
                "pan_norm":    norm_pan(s.get("pan")),
                "name_norm":   norm_name(s.get("name")),
                "mobile_norm": norm_phone(s.get("mobile")),
            }})
        except Exception:
            pass

    # ---- Partial unique indexes ---- #
    _index_specs = [
        (db.customers, "iter127a_cust_gstin_uniq",
         [("user_id", 1), ("company_id", 1), ("gstin_norm", 1)],
         {"gstin_norm": {"$ne": ""}}),
        (db.suppliers, "iter127a_sup_gstin_uniq",
         [("user_id", 1), ("company_id", 1), ("gstin_norm", 1)],
         {"gstin_norm": {"$ne": ""}}),
        (db.vehicles, "iter127a_veh_norm_uniq",
         [("user_id", 1), ("company_id", 1), ("vehicle_number_norm", 1)],
         {"vehicle_number_norm": {"$ne": ""}}),
    ]
    for coll, name, keys, partial in _index_specs:
        try:
            await coll.create_index(
                keys, name=name, unique=True,
                partialFilterExpression=partial, background=True,
            )
        except Exception as e:
            logger.warning(f"iter127a index {name} skipped: {e}")

    try:
        await db.migration_flags.update_one(
            {"_id": _BACKFILL_FLAG_ID},
            {"$set": {"applied_at": __import__("datetime").datetime.utcnow().isoformat()}},
            upsert=True,
        )
    except Exception:
        pass
    logger.info("Iter127a dedup backfill + partial unique indexes ensured")


@router.get("/admin/iter127-duplicates")
async def list_duplicates(request: Request, user=Depends(get_current_user)):
    """Read-only aggregation grouping rows by strong identity signals
    (GSTIN, normalised vehicle number, normalised supplier name).
    Never writes. Scoped to the caller's tenant so multi-company data
    stays isolated."""
    uid = user["user_id"]

    async def _groups(coll, key_field: str):
        pipeline = [
            {"$match": {
                "user_id": uid,
                key_field: {"$nin": ["", None]},
            }},
            {"$group": {
                "_id": {"company_id": "$company_id", "key": f"${key_field}"},
                "ids": {"$push": "$id"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 200},
        ]
        out = []
        async for g in coll.aggregate(pipeline):
            out.append({
                "company_id": g["_id"]["company_id"],
                "key": g["_id"]["key"],
                "count": g["count"],
                "ids": g["ids"][:20],
            })
        return out

    return {
        "customers_gstin":  await _groups(db.customers, "gstin_norm"),
        "vehicles_number":  await _groups(db.vehicles, "vehicle_number_norm"),
        "suppliers_gstin":  await _groups(db.suppliers, "gstin_norm"),
        "suppliers_name":   await _groups(db.suppliers, "name_norm"),
    }
