#!/bin/bash
# ============================================================================
# QORVENA — Historical Data Migration Backup & Rollback Toolkit (Iter86)
# ----------------------------------------------------------------------------
# Purpose: Before importing any Transport Book historical data, take a full
# MongoDB backup. If anything goes wrong, restore from that backup OR delete
# only the imported batch.
#
# Usage:
#   ./backup_before_migration.sh <batch_tag>
#     e.g.  ./backup_before_migration.sh tb_20260220_1400
# ============================================================================

set -e

BATCH_TAG="${1:-tb_$(date +%Y%m%d_%H%M%S)}"
BACKUP_ROOT="/app/backups/pre-migration"
BACKUP_DIR="${BACKUP_ROOT}/${BATCH_TAG}"

# Load Mongo credentials from backend .env
if [ -f /app/backend/.env ]; then
    export MONGO_URL="$(grep -E '^MONGO_URL=' /app/backend/.env | cut -d= -f2- | sed 's/^"//;s/"$//')"
    export DB_NAME="$(grep -E '^DB_NAME=' /app/backend/.env | cut -d= -f2- | sed 's/^"//;s/"$//')"
fi

if [ -z "${MONGO_URL:-}" ] || [ -z "${DB_NAME:-}" ]; then
    echo "ERROR: MONGO_URL or DB_NAME not set in /app/backend/.env" >&2
    exit 1
fi

echo "🔒 QORVENA Pre-Migration Backup — batch: ${BATCH_TAG}"
echo "   MongoDB: ${MONGO_URL}"
echo "   Database: ${DB_NAME}"
echo "   Backup dir: ${BACKUP_DIR}"
echo ""

mkdir -p "${BACKUP_DIR}"

# Full mongodump (all collections)
mongodump \
    --uri="${MONGO_URL}" \
    --db="${DB_NAME}" \
    --out="${BACKUP_DIR}" \
    --gzip \
    --quiet

if [ $? -ne 0 ]; then
    echo "❌ Backup FAILED — do NOT proceed with migration." >&2
    exit 1
fi

# Write a manifest
cat > "${BACKUP_DIR}/MANIFEST.txt" <<EOF
QORVENA Backup Manifest
=======================
Batch Tag:      ${BATCH_TAG}
Created At:     $(date -u +"%Y-%m-%dT%H:%M:%SZ")
MONGO_URL:      ${MONGO_URL}
DB_NAME:        ${DB_NAME}
Backup Method:  mongodump --gzip
Collections:    $(ls "${BACKUP_DIR}/${DB_NAME}" 2>/dev/null | wc -l) files

Restore command (full DB):
  mongorestore --uri="${MONGO_URL}" --db="${DB_NAME}" --drop --gzip "${BACKUP_DIR}/${DB_NAME}"

Rollback command (delete ONLY this migration batch — safer):
  mongo "${MONGO_URL}" --eval '
    db.trips.deleteMany({"imported_batch": "${BATCH_TAG}"});
    db.customers.deleteMany({"imported_batch": "${BATCH_TAG}"});
    db.suppliers.deleteMany({"imported_batch": "${BATCH_TAG}"});
    db.vehicles.deleteMany({"imported_batch": "${BATCH_TAG}"});
    db.drivers.deleteMany({"imported_batch": "${BATCH_TAG}"});
    db.invoices.deleteMany({"imported_batch": "${BATCH_TAG}"});
    db.supplier_payments.deleteMany({"imported_batch": "${BATCH_TAG}"});
  '
EOF

echo "✅ Backup complete."
echo "   ${BACKUP_DIR}"
echo ""
echo "📋 Manifest written to ${BACKUP_DIR}/MANIFEST.txt"
echo ""
echo "Next: Run the migration dry-run only. Do NOT execute the actual insert"
echo "until user has approved the dry-run report."
