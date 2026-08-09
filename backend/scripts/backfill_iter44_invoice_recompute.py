"""Iter44 one-shot: recompute every existing invoice so halting/shortage/
customer_receipts entered on trips AFTER invoice creation are pulled into
the invoice's totals.

Safe to re-run. Only recomputes; doesn't delete or reorder anything.
"""
import asyncio
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from db import db
from services import _recompute_invoice


async def main():
    total = await db.invoices.count_documents({})
    print(f"[backfill] scanning {total} invoices …")
    fixed = 0
    errored = 0
    async for inv in db.invoices.find({}, {"_id": 0, "id": 1, "user_id": 1}):
        user = {"user_id": inv["user_id"]}
        try:
            await _recompute_invoice(inv["id"], user)
            fixed += 1
        except Exception as e:
            errored += 1
            print(f"  skip {inv.get('id','?')}: {e}")
    print(f"[backfill] recomputed={fixed} errored={errored}")


if __name__ == "__main__":
    asyncio.run(main())
