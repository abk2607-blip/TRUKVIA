"""Iter45 — Backfill Supplier master from existing vehicle/trip supplier_name.

For every (company, supplier_name) combination found in Vehicles master (or Trips),
create a Supplier record if none exists and link supplier_id on all vehicles + trips.
"""
import asyncio
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from db import db
from models import now_utc, new_id


async def main():
    print("[backfill] scanning vehicles + trips …")
    # Gather all (user_id, company_id, supplier_name) tuples
    pipeline = [
        {"$match": {"vehicle_type": "supplier", "supplier_name": {"$nin": ["", None]}}},
        {"$group": {"_id": {"u": "$user_id", "c": "$company_id", "n": "$supplier_name"}}},
    ]
    v_groups = await db.vehicles.aggregate(pipeline).to_list(10000)
    t_groups = await db.trips.aggregate(pipeline).to_list(10000)
    seen = set()
    for g in (v_groups + t_groups):
        k = (g["_id"]["u"], g["_id"]["c"], g["_id"]["n"].strip().lower())
        seen.add(k)
    print(f"[backfill] found {len(seen)} unique (company, supplier) pairs")

    created = 0
    linked_v = 0
    linked_t = 0
    for uid, cid, name_lc in seen:
        # Original casing lookup
        v = await db.vehicles.find_one({"user_id": uid, "company_id": cid, "vehicle_type": "supplier",
                                         "supplier_name": {"$regex": f"^{name_lc}$", "$options": "i"}},
                                         {"_id": 0, "supplier_name": 1, "supplier_mobile": 1, "owner_phone": 1, "owner_name": 1})
        original_name = (v.get("supplier_name") if v else name_lc.title()) or name_lc.title()
        mobile = (v.get("supplier_mobile") or v.get("owner_phone") or "") if v else ""
        contact = (v.get("owner_name") or "") if v else ""

        existing = await db.suppliers.find_one({
            "user_id": uid, "company_id": cid,
            "name": {"$regex": f"^{original_name}$", "$options": "i"},
        }, {"_id": 0, "id": 1})
        if existing:
            sid = existing["id"]
        else:
            sid = new_id("sup_")
            await db.suppliers.insert_one({
                "id": sid,
                "name": original_name,
                "contact_person": contact,
                "mobile": mobile,
                "alt_mobile": "", "address": "", "state": "", "city": "",
                "gst_in": "", "pan": "", "msme_number": "",
                "bank_name": "", "account_number": "", "ifsc": "", "branch": "",
                "payment_terms": "", "opening_balance": 0.0, "opening_balance_type": "payable",
                "remarks": "Auto-imported from Vehicles master (Iter45 backfill)",
                "is_active": True,
                "created_by": uid,
                "created_at": now_utc().isoformat(),
                "modified_by": "", "modified_at": "",
                "user_id": uid, "company_id": cid,
            })
            created += 1
        # Link vehicles + trips
        rv = await db.vehicles.update_many({
            "user_id": uid, "company_id": cid, "vehicle_type": "supplier",
            "supplier_name": {"$regex": f"^{original_name}$", "$options": "i"},
        }, {"$set": {"supplier_id": sid}})
        rt = await db.trips.update_many({
            "user_id": uid, "company_id": cid, "vehicle_type": "supplier",
            "supplier_name": {"$regex": f"^{original_name}$", "$options": "i"},
        }, {"$set": {"supplier_id": sid}})
        linked_v += rv.modified_count
        linked_t += rt.modified_count

    print(f"[backfill] suppliers created={created} · vehicles linked={linked_v} · trips linked={linked_t}")


if __name__ == "__main__":
    asyncio.run(main())
