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
  json,
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
    /**
     * The source document's _id. MongoDB resolves sort ties in _id order
     * (verified stable on real data, 2026-09-21), so list endpoints order by
     * their sort key and then by this to reproduce Python's row order exactly.
     */
    sourceId: text('source_id'),
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
    /**
     * The source document's _id. MongoDB resolves sort ties in _id order
     * (verified stable on real data, 2026-09-21), so list endpoints order by
     * their sort key and then by this to reproduce Python's row order exactly.
     */
    sourceId: text('source_id'),
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
    /**
     * The source document's _id. MongoDB resolves sort ties in _id order
     * (verified stable on real data, 2026-09-21), so list endpoints order by
     * their sort key and then by this to reproduce Python's row order exactly.
     */
    sourceId: text('source_id'),
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
    /**
     * `json`, not `jsonb`: jsonb normalises object key order and re-renders
     * numbers, so a snapshot would come back reordered and with 7500.0 as
     * 7500. These payloads are opaque audit records that are never queried by
     * key, so preserving the exact source text matters more than indexing.
     */
    bankSnapshot: json('bank_snapshot'),
    companyBankAccountId: text('company_bank_account_id'),
    sourceBankSnapshot: json('source_bank_snapshot'),
    isDeleted: boolean('is_deleted').notNull().default(false),
    deletedBy: text('deleted_by').notNull().default(''),
    deletedAt: timestamp('deleted_at', { withTimezone: true, mode: 'string' }),
    deletionReason: text('deletion_reason').notNull().default(''),
    createdBy: text('created_by').notNull().default(''),
    createdAt: timestamp('created_at', { withTimezone: true, mode: 'string' }),
    modifiedBy: text('modified_by').notNull().default(''),
    modifiedAt: timestamp('modified_at', { withTimezone: true, mode: 'string' }),
    /**
     * Ordered list of the keys the source document actually had (minus _id and
     * user_id). vendor_payments has SIX distinct shapes in production: 23 rows
     * carry no correction block at all, 148 carry bank fields, and the key
     * order differs between them. Python returns each document's own shape, so
     * reproducing it byte-for-byte needs the shape recorded per row.
     * Vestigial once writes move to Postgres and rows gain a canonical shape.
     */
    sourceShape: jsonb('source_shape').$type<string[]>(),
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
    /**
     * The source document's _id. MongoDB resolves sort ties in _id order
     * (verified stable on real data, 2026-09-21), so list endpoints order by
     * their sort key and then by this to reproduce Python's row order exactly.
     */
    sourceId: text('source_id'),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    paymentType: text('payment_type').notNull(),
    paymentId: text('payment_id').notNull(),
    correctionIndex: integer('correction_index').notNull(),
    kind: text('kind').notNull().default(''),
    correctionReason: text('correction_reason').notNull().default(''),
    before: json('before'),
    after: json('after'),
    diff: json('diff'),
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

// ── Phase 6 · slice 2a — Finance read models ────────────────────────────────
//
// READ-ONLY copies of the three Finance-owned collections. Python remains the
// only writer; these tables are a derived read model, rebuilt by the migration
// script. Nothing here writes back to MongoDB.
//
// Two deliberate choices:
//   • Timestamps and dates are TEXT, not timestamptz/date. fin_txn stores
//     txn_date as "YYYY-MM-DD" and created_at as an ISO string, the day-book
//     sorts on those strings, and the response returns them verbatim. Keeping
//     TEXT preserves both the exact bytes and Mongo's lexicographic ordering,
//     and sidesteps the session-timezone rendering trap entirely.
//   • Money is numeric(14,2), as everywhere else.

export const finTxn = trukvia.table(
  'fin_txn',
  {
    id: text('id').primaryKey(),
    /**
     * The source document's _id. Named mongo_id here (not source_id) because
     * fin_txn already has a business field called source_id. Used only as the
     * sort tie-breaker, matching Mongo's tie order.
     */
    mongoId: text('mongo_id'),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    refSourceKey: text('ref_source_key'),
    accountCode: text('account_code'),
    accountId: text('account_id'),
    adjustmentGroupId: text('adjustment_group_id'),
    amount: numeric('amount', { precision: 14, scale: 2 }),
    category: text('category'),
    counterAccountCode: text('counter_account_code'),
    counterAccountId: text('counter_account_id'),
    createdAt: text('created_at'),
    direction: text('direction'),
    isReversal: boolean('is_reversal'),
    isSupplierSettlementRecovery: boolean('is_supplier_settlement_recovery'),
    narration: text('narration'),
    partyId: text('party_id'),
    partyName: text('party_name'),
    partyType: text('party_type'),
    projectedAt: text('projected_at'),
    reconciledAt: text('reconciled_at'),
    reconciledRef: text('reconciled_ref'),
    reversalOf: text('reversal_of'),
    sourceId: text('source_id'),
    sourceKey: text('source_key'),
    sourceType: text('source_type'),
    status: text('status'),
    transferGroupId: text('transfer_group_id'),
    tripId: text('trip_id'),
    txnDate: text('txn_date'),
    txnType: text('txn_type'),
    vehicleId: text('vehicle_id'),
    /**
     * fin_txn has TWO key orders in production (18,980 / 9,184): the upsert
     * filter is serialised differently by the two drivers, so company_id and
     * ref_source_key swap positions. The response returns documents in their
     * own order, so the shape is recorded per row.
     */
    sourceShape: jsonb('source_shape').$type<string[]>(),
  },
  (t) => ({
    scopeDate: index('fin_txn_scope_date').on(t.userId, t.companyId, t.txnDate),
    byAccountCode: index('fin_txn_account_code').on(t.accountCode),
    bySource: index('fin_txn_source').on(t.sourceType, t.sourceId),
    byRefSourceKey: index('fin_txn_ref_source_key').on(t.refSourceKey),
  }),
);

export const finAccount = trukvia.table(
  'fin_account',
  {
    id: text('id').primaryKey(),
    mongoId: text('mongo_id'),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    code: text('code').notNull(),
    name: text('name'),
    type: text('type'),
    isSystem: boolean('is_system'),
    isActive: boolean('is_active'),
    remarks: text('remarks'),
    createdAt: text('created_at'),
  },
  (t) => ({
    // A scope legitimately has 13 or 14 accounts (the DRIVER_OUTFLOW
    // generation split). Uniqueness is per (scope, code) — never a fixed count.
    uniqScopeCode: uniqueIndex('fin_account_scope_code').on(t.userId, t.companyId, t.code),
  }),
);

export const finDayClosure = trukvia.table(
  'fin_day_closure',
  {
    id: text('id').primaryKey(),
    mongoId: text('mongo_id'),
    userId: text('user_id').notNull(),
    companyId: text('company_id').notNull(),
    closeDate: text('close_date').notNull(),
    status: text('status'),
    closedAt: text('closed_at'),
    closedBy: text('closed_by'),
    closeNotes: text('close_notes'),
    /** Point-in-time balances; `json` preserves key order and number text. */
    snapshot: json('snapshot'),
    snapshotSourceCount: integer('snapshot_source_count'),
    reopenedAt: text('reopened_at'),
    reopenedBy: text('reopened_by'),
    reopenReason: text('reopen_reason'),
    history: json('history'),
    createdAt: text('created_at'),
    modifiedAt: text('modified_at'),
  },
  (t) => ({
    scopeDate: index('fin_day_closure_scope_date').on(t.userId, t.companyId, t.closeDate),
  }),
);
