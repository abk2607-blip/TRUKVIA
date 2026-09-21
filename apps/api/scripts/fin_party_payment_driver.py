"""Reproject party-payment documents through the REAL Python implementation.

Used by scripts/fin-mechanic-parity.ts as the reference side.

    python fin_party_payment_driver.py <db_name> <source_type> <spec_json_path> [mode]

mode is "hook" (default) or "reproject". The two are different ENTRY POINTS:
the hook gates delegation before it ever calls reproject_source, while
reproject_source is what the admin bridge and the retry driver call directly.
For driver_payment the latter is also the Iter150I monkey-patched wrapper, so
both have to be exercised.

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
MODE = sys.argv[4] if len(sys.argv) > 4 else "hook"
os.environ["DB_NAME"] = DB_NAME

import services_fin_txn as S  # noqa: E402
from services_fin_txn_hooks import hook_after_source_write  # noqa: E402


async def main():
    with open(SPEC_PATH, encoding="utf-8") as fh:
        spec = json.load(fh)

    reports = []
    for _ in range(2):  # twice: reprojection must be idempotent
        for source_id, uid, cid in spec:
            if MODE == "reproject":
                # Call the module attribute, NOT a name bound at import time,
                # so the bridge layer and the Iter150I wrapper are both live.
                deleted, written = await S.reproject_source(
                    uid, cid, SOURCE_TYPE, source_id)
                reports.append({"deleted": deleted, "written": written})
            else:
                reports.append(
                    await hook_after_source_write(uid, cid, SOURCE_TYPE, source_id)
                )
    print(json.dumps({"reports": reports}, default=str))


asyncio.run(main())
