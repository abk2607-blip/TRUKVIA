import { Inject, Injectable } from '@nestjs/common';
import type { Request } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { and, asc, eq, getTableColumns, ne, sql } from 'drizzle-orm';
import { db as pg } from '../db/pg';
import { paymentCorrection, vendorPayment } from '../db/schema';
import { activeCompanyId, authenticate } from '../common/identity';
import { pyFloat, pyIsoTimestamp, raw } from '../common/py-json';
import { MONGO } from './vendors.service';

/**
 * GET /api/vendors/{vid}/payments   — routers/vendors.py::list_vendor_payments
 * GET /api/vendor-payments/{pid}/corrections
 *                                   — routers/vendor_ledger.py + services_payment_corrections.list_corrections
 *
 * Preserved semantics:
 *   • payments: scope (user_id, company_id, vendor_id) plus is_deleted != true,
 *     projection without _id/user_id, sort `date` DESC, cap 5,000. An unknown
 *     vendor id is NOT a 404 — Python returns an empty list;
 *   • corrections: scope (user_id, company_id, payment_type='vendor',
 *     payment_id), sort correction_index ASC, cap 1,000.
 *
 * Shape handling: vendor_payments has SIX key orders in production. Each row
 * carries `source_shape`, the ordered key list of the source document, so the
 * response reproduces both which fields exist and the order they appear in.
 * Fields absent from the shape are omitted entirely, which is what Python does.
 */
const absent = (v: string | null): string => v ?? '';

/** Canonical order for a row whose shape was not recorded. */
const DEFAULT_PAYMENT_SHAPE = [
  'id', 'vendor_id', 'date', 'amount', 'type', 'mode', 'account_id', 'ref_no', 'against',
  'vendor_bill_id', 'remarks', 'file_ids', 'created_by', 'created_at', 'modified_by',
  'modified_at', 'is_deleted', 'deleted_by', 'deleted_at', 'deletion_reason', 'company_id',
];

/**
 * Snapshot columns are selected as TEXT and emitted verbatim. Letting the pg
 * driver parse them and re-encoding would reorder object keys and turn 7500.0
 * into 7500 — both real differences found against live Python on 2026-09-21.
 */
type PaymentRow = typeof vendorPayment.$inferSelect & {
  bankSnapshotText: string | null;
  sourceBankSnapshotText: string | null;
};

function paymentField(r: PaymentRow, key: string): unknown {
  switch (key) {
    case 'id': return r.id;
    case 'vendor_id': return r.vendorId;
    case 'date': return absent(r.paymentDate);
    case 'amount': return pyFloat(r.amount);
    case 'type': return r.type;
    case 'mode': return r.mode;
    case 'account_id': return r.accountId;
    case 'ref_no': return r.refNo;
    case 'against': return r.against;
    case 'vendor_bill_id': return r.vendorBillId;
    case 'remarks': return r.remarks;
    case 'file_ids': return r.fileIds;
    case 'bank_account_id': return absent(r.bankAccountId);
    case 'bank_snapshot': return r.bankSnapshotText === null ? null : raw(r.bankSnapshotText);
    case 'company_bank_account_id': return absent(r.companyBankAccountId);
    case 'source_bank_snapshot': return r.sourceBankSnapshotText === null ? null : raw(r.sourceBankSnapshotText);
    case 'corrected_at': return absent(pyIsoTimestamp(r.correctedAt));
    case 'corrected_by': return absent(r.correctedBy);
    case 'correction_count': return r.correctionCount;
    case 'latest_correction_id': return absent(r.latestCorrectionId);
    case 'is_reversed': return r.isReversed;
    case 'reversed_by': return absent(r.reversedBy);
    case 'reversed_at': return absent(pyIsoTimestamp(r.reversedAt));
    case 'reversal_reason': return absent(r.reversalReason);
    case 'reversal_of': return absent(r.reversalOf);
    case 'reconciled_at': return absent(r.reconciledAt);
    case 'reconciled_ref': return absent(r.reconciledRef);
    case 'created_by': return r.createdBy;
    case 'created_at': return absent(pyIsoTimestamp(r.createdAt));
    case 'modified_by': return r.modifiedBy;
    case 'modified_at': return absent(pyIsoTimestamp(r.modifiedAt));
    case 'is_deleted': return r.isDeleted;
    case 'deleted_by': return r.deletedBy;
    case 'deleted_at': return absent(pyIsoTimestamp(r.deletedAt));
    case 'deletion_reason': return r.deletionReason;
    case 'company_id': return r.companyId;
    default: return undefined; // unknown key: omitted, never guessed
  }
}

export function paymentToJson(r: PaymentRow): Record<string, unknown> {
  const shape =
    Array.isArray(r.sourceShape) && r.sourceShape.length ? r.sourceShape : DEFAULT_PAYMENT_SHAPE;
  const out: Record<string, unknown> = {};
  for (const key of shape) {
    if (key === '_id' || key === 'user_id') continue; // stripped by the projection
    const value = paymentField(r, key);
    if (value !== undefined) out[key] = value;
  }
  return out;
}

export function correctionToJson(
  r: typeof paymentCorrection.$inferSelect & {
    beforeText: string | null;
    afterText: string | null;
    diffText: string | null;
  },
): Record<string, unknown> {
  // All 794 corrections share one key order.
  return {
    id: r.id,
    company_id: r.companyId,
    payment_type: r.paymentType,
    payment_id: r.paymentId,
    correction_index: r.correctionIndex,
    kind: r.kind,
    correction_reason: r.correctionReason,
    before: r.beforeText === null ? null : raw(r.beforeText),
    after: r.afterText === null ? null : raw(r.afterText),
    diff: r.diffText === null ? null : raw(r.diffText),
    linked_reversal_id: absent(r.linkedReversalId),
    linked_new_id: absent(r.linkedNewId),
    force_reconciled_override: r.forceReconciledOverride,
    corrected_by: r.correctedBy,
    corrected_at: absent(pyIsoTimestamp(r.correctedAt)),
  };
}

@Injectable()
export class VendorPaymentsService {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  async listForVendor(req: Request, vid: string): Promise<Array<Record<string, unknown>>> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    const rows = await pg
      .select({
        ...getTableColumns(vendorPayment),
        bankSnapshotText: sql<string | null>`${vendorPayment.bankSnapshot}::text`,
        sourceBankSnapshotText: sql<string | null>`${vendorPayment.sourceBankSnapshot}::text`,
      })
      .from(vendorPayment)
      .where(
        and(
          eq(vendorPayment.userId, user.user_id),
          eq(vendorPayment.companyId, cid),
          eq(vendorPayment.vendorId, vid),
          ne(vendorPayment.isDeleted, true),
        ),
      )
      .orderBy(sql`${vendorPayment.paymentDate} DESC NULLS FIRST`, asc(vendorPayment.sourceId))
      .limit(5000);
    return rows.map(paymentToJson);
  }

  async corrections(req: Request, pid: string): Promise<Array<Record<string, unknown>>> {
    const user = await authenticate(req, this.mongo);
    const cid = await activeCompanyId(req, user.user_id, this.mongo);
    const rows = await pg
      .select({
        ...getTableColumns(paymentCorrection),
        beforeText: sql<string | null>`${paymentCorrection.before}::text`,
        afterText: sql<string | null>`${paymentCorrection.after}::text`,
        diffText: sql<string | null>`${paymentCorrection.diff}::text`,
      })
      .from(paymentCorrection)
      .where(
        and(
          eq(paymentCorrection.userId, user.user_id),
          eq(paymentCorrection.companyId, cid),
          eq(paymentCorrection.paymentType, 'vendor'),
          eq(paymentCorrection.paymentId, pid),
        ),
      )
      .orderBy(asc(paymentCorrection.correctionIndex), asc(paymentCorrection.sourceId))
      .limit(1000);
    return rows.map(correctionToJson);
  }
}
