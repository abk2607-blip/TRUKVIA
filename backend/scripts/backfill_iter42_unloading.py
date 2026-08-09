"""Iter42 one-shot backfill: recompute Loading/Unloading diff on legacy trips.

Rules:
  - For every trip where tons > 0 AND (loaded_qty == 0 OR loaded_qty is missing),
    set loaded_qty = tons and recompute shortage_qty / excess_qty /
    shortage_amount / excess_amount (unless override flag is set).
  - Additionally, if loaded_qty != tons AND tons > 0, sync loaded_qty <- tons
    so `tons` remains the single source of truth going forward.
  - Existing shortage_amount_override / excess_amount_override trips are left
    with their manual amounts intact (only qty fields are recomputed).

Usage:
  python -m scripts.backfill_iter42_unloading
"""
import asyncio
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from db import db
from models import Trip
from services import _compute_trip


async def main():
    q = {"$or": [{"loaded_qty": {"$in": [0, 0.0, None]}}, {"loaded_qty": {"$exists": False}}]}
    total = await db.trips.count_documents({})
    candidates = await db.trips.find(q, {"_id": 0}).to_list(100000)
    # Filter for tons > 0
    to_fix = [t for t in candidates if float(t.get("tons") or 0) > 0]
    print(f"[backfill] scanned {total} trips; {len(to_fix)} candidates for loaded_qty <- tons")

    fixed = 0
    skipped_manual = 0
    for doc in to_fix:
        # Preserve overrides (leave shortage_amount / excess_amount user-set values)
        try:
            trip = Trip(**{k: v for k, v in doc.items() if k in Trip.model_fields})
        except Exception as e:
            print(f"  skip {doc.get('id','?')}: parse error {e}")
            continue
        # Recompute
        _compute_trip(trip)
        patch = {
            "loaded_qty": trip.loaded_qty,
            "shortage_qty": trip.shortage_qty,
            "excess_qty": trip.excess_qty,
        }
        if not trip.shortage_amount_override:
            patch["shortage_amount"] = trip.shortage_amount
        else:
            skipped_manual += 1
        if not trip.excess_amount_override:
            patch["excess_amount"] = trip.excess_amount
        await db.trips.update_one({"id": doc["id"]}, {"$set": patch})
        fixed += 1

    # Second pass: sync loaded_qty <- tons for docs where they mismatch and no override
    q2 = {"tons": {"$gt": 0}}
    more = await db.trips.find(q2, {"_id": 0, "id": 1, "tons": 1, "loaded_qty": 1}).to_list(100000)
    resynced = 0
    for d in more:
        if float(d.get("loaded_qty") or 0) != float(d.get("tons") or 0):
            await db.trips.update_one({"id": d["id"]}, {"$set": {"loaded_qty": float(d["tons"])}})
            resynced += 1
    print(f"[backfill] loaded_qty synced from tons on {resynced} additional trips")
    print(f"[backfill] fixed={fixed} skipped_manual={skipped_manual}")


if __name__ == "__main__":
    asyncio.run(main())
