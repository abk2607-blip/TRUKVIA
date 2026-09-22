"""Drive backend/services_fin_txn_hooks.py through a scenario list.

Used by scripts/fin-hook-parity.ts as the Python REFERENCE side. It calls the
real functions — no reimplementation — and prints one JSON object with each
step's return value plus the resulting fin_hook_failures documents, so the
TypeScript port can be compared against them.

    python fin_hook_driver.py <db_name> <uid> <cid> <vendor_payment_id>

Read the module from backend/ (cwd), so `from db import db` resolves.
"""
import asyncio
import json
import os
import sys

DB_NAME = sys.argv[1]
UID = sys.argv[2]
CID = sys.argv[3]
VP_ID = sys.argv[4]
os.environ["DB_NAME"] = DB_NAME

from db import db  # noqa: E402
import services_fin_txn_hooks as H  # noqa: E402


async def dump():
    # Sort by the BUSINESS key, not by `id`: ids are random, so sorting on them
    # puts the two databases' rows in different orders for no reason.
    rows = await db.fin_hook_failures.find({}, {"_id": 0}).to_list(100)
    return sorted(rows, key=lambda r: (r["source_type"], r["source_id"]))


async def main():
    steps = []

    async def step(name, value):
        steps.append({"step": name, "value": value, "rows": await dump()})

    # 1. A source type with no projection mapping: reported, never enqueued.
    await step("hook_unsupported",
               await H.hook_after_source_write(UID, CID, "banana", "x1"))

    # 2. A brand-new failure row.
    await step("record_new",
               await H._record_failure(UID, CID, "vendor_payment", VP_ID,
                                       error="boom one", action="upsert"))

    # 3. Same source again while pending: error refreshed, schedule untouched.
    await step("record_refresh",
               await H._record_failure(UID, CID, "vendor_payment", VP_ID,
                                       error="boom two", action="upsert"))

    # 4. Resolve it.
    await step("resolve", await H._resolve_failure(UID, CID, "vendor_payment", VP_ID))

    # 5. Resolving again finds nothing.
    await step("resolve_again", await H._resolve_failure(UID, CID, "vendor_payment", VP_ID))

    # 6. A failure after resolution REOPENS the same row (id + created_at kept).
    await step("record_reopen",
               await H._record_failure(UID, CID, "vendor_payment", VP_ID,
                                       error="boom three", action="delete_cascade"))

    # 7. Reopening from permanently_failed behaves the same way.
    await db.fin_hook_failures.update_one(
        {"user_id": UID, "company_id": CID, "source_type": "vendor_payment",
         "source_id": VP_ID},
        {"$set": {"status": H.FAILURE_STATUS_PERMANENTLY_FAILED, "retry_count": 8}},
    )
    await step("record_reopen_from_permanent",
               await H._record_failure(UID, CID, "vendor_payment", VP_ID,
                                       error="boom four", action="upsert"))

    # 8. A successful projection auto-resolves the lingering failure.
    await step("hook_success",
               await H.hook_after_source_write(UID, CID, "vendor_payment", VP_ID))

    # 9. Error longer than the 2000-char store limit.
    await step("record_long_error",
               await H._record_failure(UID, CID, "vendor_bill", "vbl_long",
                                       error="E" * 2500, action="upsert"))

    # 10. Backoff schedule for each retry_count.
    await step("backoff", [
        int((H._compute_next_attempt(n) - H._utc_now()).total_seconds() + 0.5)
        for n in range(0, 12)
    ])

    print(json.dumps({"steps": steps}, default=str))


asyncio.run(main())
