"""Drive backend/services_fin_txn_hooks.replay_pending_failures through a
scenario list, as the Python REFERENCE side for scripts/fin-replay-parity.ts.

    python fin_replay_driver.py <db_name> <spec_json_path>

The spec is a list of steps, each {"op": ..., ...}:

    {"op": "hook",    "uid","cid","source_type","source_id"}   run the hook
    {"op": "replay",  ...options}                              drain the queue
    {"op": "age",     "source_id", "seconds"}                  move next_attempt_at
    {"op": "setcount","source_id", "retry_count"}              force a retry count

`age` and `setcount` exist because the real schedule is minutes to hours away;
rewinding `next_attempt_at` is how a due row is produced without waiting, and
forcing `retry_count` is how the MAX_RETRIES boundary is reached in one step
rather than eight.

Prints one JSON object with each step's return value and the queue afterwards.
"""
import asyncio
import json
import os
import sys
from datetime import timedelta

DB_NAME = sys.argv[1]
SPEC_PATH = sys.argv[2]
os.environ["DB_NAME"] = DB_NAME

from db import db  # noqa: E402
import services_fin_txn_hooks as H  # noqa: E402


async def queue():
    rows = await db.fin_hook_failures.find({}, {"_id": 0}).to_list(200)
    return sorted(rows, key=lambda r: (r["source_type"], r["source_id"]))


async def main():
    with open(SPEC_PATH, encoding="utf-8") as fh:
        steps = json.load(fh)

    out = []
    for st in steps:
        op = st["op"]
        if op == "hook":
            value = await H.hook_after_source_write(
                st["uid"], st["cid"], st["source_type"], st["source_id"])
        elif op == "replay":
            value = await H.replay_pending_failures(
                user_id=st.get("user_id"),
                company_id=st.get("company_id"),
                limit=st.get("limit", 100),
                dry_run=st.get("dry_run", False),
                ignore_schedule=st.get("ignore_schedule", False),
                verbose=st.get("verbose", False),
            )
        elif op == "age":
            # Rewind next_attempt_at so the row becomes due right now.
            when = H._utc_now() - timedelta(seconds=int(st["seconds"]))
            await db.fin_hook_failures.update_one(
                {"source_id": st["source_id"]},
                {"$set": {"next_attempt_at": H._iso(when)}})
            value = "aged"
        elif op == "setcount":
            await db.fin_hook_failures.update_one(
                {"source_id": st["source_id"]},
                {"$set": {"retry_count": int(st["retry_count"])}})
            value = "set"
        else:
            raise ValueError(f"unknown op {op}")
        out.append({"op": op, "value": value, "queue": await queue()})

    print(json.dumps({"steps": out}, default=str))


asyncio.run(main())
