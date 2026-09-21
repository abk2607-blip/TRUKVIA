/**
 * TRUKVIA · Phase 6 · slice 1 — Drizzle schema for the vendors module.
 *
 * Column set and nullability are taken from the REAL production data
 * (2026-09-21: 2,177 vendors / 5,736 bills / 2,040 payments / 794 corrections),
 * not from the Pydantic models, so a migrated row is byte-for-byte explainable.
 *
 * Decisions (see docs/migration/PHASE6-SLICE1-VENDORS-NESTJS-POSTGRES.md):
 *   • money is numeric(14,2), never float;
 *   • point-in-time snapshots (before/after/diff, bank snapshots) stay jsonb;
 *   • business ids stay text so both stacks reference the same rows during the
 *     strangler period;
 *   • no FK to entities that still live in MongoDB (trips, vehicles, files).
 */
import {
  boolean,
  date,
  integer,
  jsonb,
  numeric,
  pgSchema,
  text,
  timestamp,
  uniqueIndex,
  index,
} from 'drizzle-orm/pg-core';

export const trukvia = pgSchema('trukvia');

export const vendor = trukvia.table(
  'vendor',
  {
    id: text('id').primaryKey(),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    name: text('name').notNull(),
    contactPerson: text('contact_person').notNull().default(''),
    mobile: text('mobile').notNull().default(''),
    altMobile: text('alt_mobile').notNull().default(''),
    address: text('address').notNull().default(''),
    state: text('state').notNull().default(''),
    city: text('city').notNull().default(''),
    gstIn: text('gst_in').notNull().default(''),
    pan: text('pan').notNull().default(''),
    msmeNumber: text('msme_number').notNull().default(''),
    bankName: text('bank_name').notNull().default(''),
    accountNumber: text('account_number').notNull().default(''),
    ifsc: text('ifsc').notNull().default(''),
    branch: text('branch').notNull().default(''),
    paymentTerms: text('payment_terms').notNull().default(''),
    openingBalance: numeric('opening_balance', { precision: 14, scale: 2 }).notNull().default('0'),
    openingBalanceType: text('opening_balance_type').notNull().default('payable'),
    remarks: text('remarks').notNull().default(''),
    isActive: boolean('is_active').notNull().default(true),
    isHistorical: boolean('is_historical').notNull().default(false),
    importedFrom: text('imported_from').notNull().default(''),
    importedRef: text('imported_ref').notNull().default(''),
    importedBatch: text('imported_batch').notNull().default(''),
    createdBy: text('created_by').notNull().default(''),
    createdAt: timestamp('created_at', { withTimezone: true, mode: 'string' }),
    modifiedBy: text('modified_by').notNull().default(''),
    modifiedAt: timestamp('modified_at', { withTimezone: true, mode: 'string' }),
    deactivatedBy: text('deactivated_by').notNull().default(''),
    deactivatedAt: timestamp('deactivated_at', { withTimezone: true, mode: 'string' }),
    deactivationReason: text('deactivation_reason').notNull().default(''),
  },
  (t) => ({
    scopeName: index('vendor_scope_name').on(t.userId, t.companyId, t.name),
  }),
);

export const vendorBill = trukvia.table(
  'vendor_bill',
  {
    id: text('id').primaryKey(),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    vendorId: text('vendor_id').notNull(),
    vendorName: text('vendor_name').notNull().default(''),
    billNumber: text('bill_number').notNull().default(''),
    billDate: date('bill_date'),
    billAmount: numeric('bill_amount', { precision: 14, scale: 2 }).notNull().default('0'),
    vehicleId: text('vehicle_id').notNull().default(''),
    vehicleNumber: text('vehicle_number').notNull().default(''),
    tripId: text('trip_id').notNull().default(''),
    repairEventId: text('repair_event_id').notNull().default(''),
    narration: text('narration').notNull().default(''),
    remarks: text('remarks').notNull().default(''),
    fileIds: jsonb('file_ids').notNull().default([]),
    isDeleted: boolean('is_deleted').notNull().default(false),
    deletedBy: text('deleted_by').notNull().default(''),
    deletedAt: timestamp('deleted_at', { withTimezone: true, mode: 'string' }),
    deletionReason: text('deletion_reason').notNull().default(''),
    createdBy: text('created_by').notNull().default(''),
    createdAt: timestamp('created_at', { withTimezone: true, mode: 'string' }),
    modifiedBy: text('modified_by').notNull().default(''),
    modifiedAt: timestamp('modified_at', { withTimezone: true, mode: 'string' }),
  },
  (t) => ({
    scopeDate: index('vendor_bill_scope_date').on(t.userId, t.companyId, t.billDate),
    byVendor: index('vendor_bill_vendor').on(t.vendorId),
    byVehicle: index('vendor_bill_vehicle').on(t.vehicleId),
    byRepair: index('vendor_bill_repair').on(t.repairEventId),
  }),
);

export const vendorPayment = trukvia.table(
  'vendor_payment',
  {
    id: text('id').primaryKey(),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    vendorId: text('vendor_id').notNull(),
    vendorBillId: text('vendor_bill_id').notNull().default(''),
    paymentDate: date('payment_date'),
    amount: numeric('amount', { precision: 14, scale: 2 }).notNull().default('0'),
    type: text('type').notNull().default(''),
    mode: text('mode').notNull().default(''),
    accountId: text('account_id').notNull().default(''),
    refNo: text('ref_no').notNull().default(''),
    against: text('against').notNull().default(''),
    remarks: text('remarks').notNull().default(''),
    fileIds: jsonb('file_ids').notNull().default([]),
    correctedBy: text('corrected_by'),
    correctedAt: timestamp('corrected_at', { withTimezone: true, mode: 'string' }),
    correctionCount: integer('correction_count'),
    latestCorrectionId: text('latest_correction_id'),
    isReversed: boolean('is_reversed'),
    reversedBy: text('reversed_by'),
    reversedAt: timestamp('reversed_at', { withTimezone: true, mode: 'string' }),
    reversalReason: text('reversal_reason'),
    reversalOf: text('reversal_of'),
    // Source data stores this as a plain date (49 rows, all date-only), not a timestamp.
    reconciledAt: date('reconciled_at'),
    reconciledRef: text('reconciled_ref'),
    bankAccountId: text('bank_account_id'),
    bankSnapshot: jsonb('bank_snapshot'),
    companyBankAccountId: text('company_bank_account_id'),
    sourceBankSnapshot: jsonb('source_bank_snapshot'),
    isDeleted: boolean('is_deleted').notNull().default(false),
    deletedBy: text('deleted_by').notNull().default(''),
    deletedAt: timestamp('deleted_at', { withTimezone: true, mode: 'string' }),
    deletionReason: text('deletion_reason').notNull().default(''),
    createdBy: text('created_by').notNull().default(''),
    createdAt: timestamp('created_at', { withTimezone: true, mode: 'string' }),
    modifiedBy: text('modified_by').notNull().default(''),
    modifiedAt: timestamp('modified_at', { withTimezone: true, mode: 'string' }),
  },
  (t) => ({
    scopeDate: index('vendor_payment_scope_date').on(t.userId, t.companyId, t.paymentDate),
    byVendor: index('vendor_payment_vendor').on(t.vendorId),
    byBill: index('vendor_payment_bill').on(t.vendorBillId),
    byReversalOf: index('vendor_payment_reversal_of').on(t.reversalOf),
  }),
);

export const paymentCorrection = trukvia.table(
  'payment_correction',
  {
    id: text('id').primaryKey(),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    paymentType: text('payment_type').notNull(),
    paymentId: text('payment_id').notNull(),
    correctionIndex: integer('correction_index').notNull(),
    kind: text('kind').notNull().default(''),
    correctionReason: text('correction_reason').notNull().default(''),
    before: jsonb('before'),
    after: jsonb('after'),
    diff: jsonb('diff'),
    linkedReversalId: text('linked_reversal_id'),
    linkedNewId: text('linked_new_id'),
    forceReconciledOverride: boolean('force_reconciled_override'),
    correctedBy: text('corrected_by').notNull().default(''),
    correctedAt: timestamp('corrected_at', { withTimezone: true, mode: 'string' }),
  },
  (t) => ({
    uniqScopePayment: uniqueIndex('pcr_scope_payment_index').on(
      t.userId,
      t.companyId,
      t.paymentType,
      t.paymentId,
      t.correctionIndex,
    ),
  }),
);
