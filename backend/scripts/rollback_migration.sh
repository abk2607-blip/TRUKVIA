#!/bin/bash
# ============================================================================
# QORVENA — Historical Data Rollback (Iter86)
# ----------------------------------------------------------------------------
# Deletes ALL records with `imported_batch` == the provided tag, across every
# entity that supports historical import. Safer than a full DB restore because
# it leaves live data untouched.
#
# Usage:
#   ./rollback_migration.sh <batch_tag> [--dry-run]
#     e.g. ./rollback_migration.sh tb_20260220_1400 --dry-run
#          ./rollback_migration.sh tb_20260220_1400            # actual rollback
# ============================================================================

set -e

BATCH_TAG="${1:?Usage: $0 <batch_tag> [--dry-run]}"
DRY_RUN="${2:-}"

if [ -f /app/backend/.env ]; then
    export MONGO_URL="$(grep -E '^MONGO_URL=' /app/backend/.env | cut -d= -f2- | sed 's/^"//;s/"$//')"
    export DB_NAME="$(grep -E '^DB_NAME=' /app/backend/.env | cut -d= -f2- | sed 's/^"//;s/"$//')"
fi

if [ -z "${MONGO_URL:-}" ] || [ -z "${DB_NAME:-}" ]; then
    echo "ERROR: MONGO_URL or DB_NAME not set" >&2
    exit 1
fi

echo "🧹 QORVENA Historical Data Rollback"
echo "   Batch tag:  ${BATCH_TAG}"
echo "   DB:         ${DB_NAME}"
echo "   Mode:       ${DRY_RUN:-EXECUTE}"
echo ""

python3 <<PYEOF
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os

async def main():
    dry_run = "${DRY_RUN}" == "--dry-run"
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    tag = "${BATCH_TAG}"
    collections = ["trips", "customers", "suppliers", "vehicles",
                   "drivers", "invoices", "supplier_payments"]
    for coll_name in collections:
        coll = db[coll_name]
        count = await coll.count_documents({"imported_batch": tag})
        if dry_run:
            print(f"  [dry-run] would delete {count:>6} rows from {coll_name}")
        else:
            if count > 0:
                res = await coll.delete_many({"imported_batch": tag})
                print(f"  ✓ deleted {res.deleted_count:>6} rows from {coll_name}")
            else:
                print(f"  · no rows to delete in {coll_name}")

asyncio.run(main())
PYEOF

echo ""
if [ "${DRY_RUN}" = "--dry-run" ]; then
    echo "🔍 Dry run complete. Re-run without --dry-run to actually delete."
else
    echo "✅ Rollback complete for batch ${BATCH_TAG}."
fi
