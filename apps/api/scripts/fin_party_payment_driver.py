"""Reproject party-payment documents through the REAL Python implementation.

Used by scripts/fin-mechanic-parity.ts as the reference side.

    python fin_party_payment_driver.py <db_name> <source_type> <spec_json_path>

The spec is [[source_id, uid, cid], ...]. Each entry is reprojected twice, so
the comparison also covers reprojection idempotency — delete-then-insert must
leave exactly the same rows the first run produced.

With TRUKVIA_FIN_NODE_URL / TRUKVIA_FIN_NODE_SOURCE_TYPES set in the
environment, this exercises the reverse bridge instead: the hook delegates to
NestJS and Python writes nothing itself.
"""
import asyncio
import json
import os
import sys

DB_NAME = sys.argv[1]
SOURCE_TYPE = sys.argv[2]
SPEC_PATH = sys.argv[3]
os.environ["DB_NAME"] = DB_NAME

from services_fin_txn_hooks import hook_after_source_write  # noqa: E402


async def main():
    with open(SPEC_PATH, encoding="utf-8") as fh:
        spec = json.load(fh)

    reports = []
    for _ in range(2):  # twice: reprojection must be idempotent
        for source_id, uid, cid in spec:
            reports.append(
                await hook_after_source_write(uid, cid, SOURCE_TYPE, source_id)
            )
    print(json.dumps({"reports": reports}, default=str))


asyncio.run(main())
