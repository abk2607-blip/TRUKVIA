/**
 * TRUKVIA · Phase 6 · slice 1b — fin_txn projection for the VENDOR source types.
 *
 * A faithful port of the vendor paths in backend/services_fin_txn.py:
 *   _q2, _mode_account, _leg, _party_payment_legs, project_vendor_payment,
 *   project_vendor_bill, _has_paired_expense, _delete_by_source, _persist_legs
 *   and the vendor branches of reproject_source.
 *
 * SCOPE: `vendor_payment` and `vendor_bill` ONLY. Every other source type still
 * belongs to Python; calling this with one throws rather than guessing.
 *
 * This is a SECOND implementation of ledger maths, which is a real risk: if the
 * Python version changes, these diverge silently. Two mitigations are in place.
 *   1. scripts/fin-projection-parity.ts writes the same document through both
 *      stacks and compares the resulting fin_txn rows field by field.
 *   2. Every function below names the Python function it mirrors, so a diff of
 *      services_fin_txn.py shows exactly what must be re-checked here.
 * The longer-term intent is still to move finance wholesale (option c), at
 * which point this file becomes the seed of that slice rather than a shadow.
 *
 * Legs are written to MongoDB, because fin_txn is still Python-owned data.
 */
import type { Db } from 'mongodb';

/** models.py FIN_SYSTEM_ACCOUNTS, including the appended DRIVER_OUTFLOW entry. */
export const FIN_SYSTEM_ACCOUNTS: Array<{ code: string; name: string; type: string }> = [
  { code: 'CASH', name: 'Cash on Hand', type: 'cash' },
  { code: 'BANK_DEFAULT', name: 'Bank — Default', type: 'bank' },
  { code: 'WALLET_FASTAG', name: 'FASTag Wallet', type: 'wallet' },
  { code: 'WALLET_FUEL', name: 'Fleet-card Fuel Wallet', type: 'wallet' },
  { code: 'AR', name: 'Accounts Receivable', type: 'ar' },
  { code: 'AP_SUPPLIER', name: 'Suppliers Payable', type: 'ap' },
  { code: 'AP_VENDOR', name: 'Vendors Payable', type: 'ap' },
  { code: 'AP_MECHANIC', name: 'Mechanics Payable', type: 'ap' },
  { code: 'SALES', name: 'Freight Revenue', type: 'income' },
  { code: 'EXPENSE_DEFAULT', name: 'Operating Expense', type: 'expense' },
  { code: 'CUSTOMER_ADVANCE', name: 'Customer Advance (Unapplied)', type: 'contra' },
  { code: 'SUSPENSE', name: 'Suspense', type: 'contra' },
  { code: 'INTER_ACCOUNT', name: 'Inter-Account Transit', type: 'contra' },
  { code: 'DRIVER_OUTFLOW', name: 'Driver Payments Outflow', type: 'expense' },
];

/** services_fin_txn._MODE_TO_ACCOUNT */
const MODE_TO_ACCOUNT: Record<string, string> = {
  Cash: 'CASH',
  Bank: 'BANK_DEFAULT',
  UPI: 'BANK_DEFAULT',
  IMPS: 'BANK_DEFAULT',
  NEFT: 'BANK_DEFAULT',
  RTGS: 'BANK_DEFAULT',
  Cheque: 'BANK_DEFAULT',
  Other: 'BANK_DEFAULT',
};

/** services_fin_txn._mode_account */
export function modeAccount(mode: unknown): string {
  const key = typeof mode === 'string' && mode !== '' ? mode : 'Bank';
  return MODE_TO_ACCOUNT[key] ?? 'BANK_DEFAULT';
}

/**
 * services_fin_txn._q2 — Python's round() is banker's rounding (round-half-to-
 * even), which differs from JavaScript's Math.round on exact .005 cases.
 * Money must match to the paisa, so the tie case is handled explicitly.
 */
export function q2(x: unknown): number {
  const n = typeof x === 'number' ? x : Number(x ?? 0);
  if (!Number.isFinite(n)) return 0;
  const scaled = n * 100;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  let rounded: number;
  if (Math.abs(diff - 0.5) < Number.EPSILON * Math.abs(scaled) + 1e-9) {
    // exact tie: round half to even, as Python does
    rounded = floor % 2 === 0 ? floor : floor + 1;
  } else {
    rounded = Math.round(scaled);
  }
  return rounded / 100;
}

export interface Leg {
  account_code: string;
  counter_account_code: string;
  direction: 'in' | 'out';
  amount: number;
  txn_date: string;
  txn_type: string;
  source_type: string;
  source_id: string;
  source_key: string;
  ref_source_key: string;
  party_type: string;
  party_id: string;
  party_name: string;
  vehicle_id: string;
  trip_id: string;
  category: string;
  narration: string;
  is_supplier_settlement_recovery: boolean;
}

interface LegInput {
  txn_date: string;
  account_code: string;
  direction: 'in' | 'out';
  amount: number;
  counter_account_code: string;
  txn_type: string;
  source_type: string;
  source_id: string;
  ref_leg: string;
  party_type?: string;
  party_id?: string;
  party_name?: string;
  vehicle_id?: string;
  trip_id?: string;
  category?: string;
  narration?: string;
  source_key?: string;
  is_supplier_settlement_recovery?: boolean;
}

/** services_fin_txn._leg — key order matches the Python dict literal. */
export function leg(i: LegInput): Leg {
  return {
    account_code: i.account_code,
    counter_account_code: i.counter_account_code,
    direction: i.direction,
    amount: q2(i.amount),
    txn_date: i.txn_date,
    txn_type: i.txn_type,
    source_type: i.source_type,
    source_id: i.source_id,
    source_key: i.source_key ?? '',
    ref_source_key: `${i.source_type}:${i.source_id}:${i.ref_leg}`,
    party_type: i.party_type ?? '',
    party_id: i.party_id ?? '',
    party_name: i.party_name ?? '',
    vehicle_id: i.vehicle_id ?? '',
    trip_id: i.trip_id ?? '',
    category: i.category ?? '',
    narration: i.narration ? i.narration.slice(0, 400) : '',
    is_supplier_settlement_recovery: i.is_supplier_settlement_recovery ?? false,
  };
}

type Doc = Record<string, unknown>;
const str = (v: unknown): string => (typeof v === 'string' ? v : '');

/**
 * services_fin_txn._party_payment_legs, specialised for vendors via
 * project_vendor_payment (ap_code AP_VENDOR, txn_type prefix "vendor").
 */
export function projectVendorPayment(p: Doc): Leg[] {
  if (p['is_deleted'] || p['is_reversed']) return [];
  const amt = q2(p['amount'] ?? 0);
  if (amt <= 0) return [];
  const date = str(p['date']);
  const bankCode = modeAccount(p['mode']);
  const typ = str(p['type']) || 'payment_out';
  // Python: f"Vendor {typ} · {ref_no}".strip(" ·") — strip() removes any
  // leading/trailing space or "·" characters, not a single suffix.
  const narration = `Vendor ${typ} · ${str(p['ref_no'])}`.replace(/^[ ·]+|[ ·]+$/g, '');
  const common = {
    source_type: 'vendor_payment',
    source_id: str(p['id']),
    party_type: 'vendor',
    party_id: str(p['vendor_id']),
    narration,
  };
  if (typ === 'payment_out') {
    return [
      leg({
        ...common,
        txn_date: date,
        account_code: 'AP_VENDOR',
        direction: 'in',
        amount: amt,
        counter_account_code: bankCode,
        txn_type: 'vendor_payment_out',
        ref_leg: 'ap_debit',
      }),
      leg({
        ...common,
        txn_date: date,
        account_code: bankCode,
        direction: 'out',
        amount: amt,
        counter_account_code: 'AP_VENDOR',
        txn_type: 'vendor_payment_out',
        ref_leg: 'bank_credit',
      }),
    ];
  }
  return [
    leg({
      ...common,
      txn_date: date,
      account_code: bankCode,
      direction: 'in',
      amount: amt,
      counter_account_code: 'AP_VENDOR',
      txn_type: 'vendor_receipt_in',
      ref_leg: 'bank_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: 'AP_VENDOR',
      direction: 'out',
      amount: amt,
      counter_account_code: bankCode,
      txn_type: 'vendor_receipt_in',
      ref_leg: 'ap_credit',
    }),
  ];
}

/**
 * services_fin_txn.project_vendor_bill — a bill projects legs ONLY when it has
 * no paired Expense, because in the canonical flow the Expense carries the
 * EXPENSE + AP_VENDOR legs and projecting both would double-count AP_VENDOR.
 */
export function projectVendorBill(vb: Doc, hasPairedExpense: boolean): Leg[] {
  if (vb['is_deleted']) return [];
  if (hasPairedExpense) return [];
  const amt = q2(vb['bill_amount'] ?? 0);
  if (amt <= 0) return [];
  const date = str(vb['bill_date']);
  const common = {
    source_type: 'vendor_bill',
    source_id: str(vb['id']),
    party_type: 'vendor',
    party_id: str(vb['vendor_id']),
    party_name: str(vb['vendor_name']),
    vehicle_id: str(vb['vehicle_id']),
    trip_id: str(vb['trip_id']),
    narration: `VendorBill ${str(vb['bill_number'])} (orphan)`,
  };
  return [
    leg({
      ...common,
      txn_date: date,
      account_code: 'SUSPENSE',
      direction: 'in',
      amount: amt,
      counter_account_code: 'AP_VENDOR',
      txn_type: 'vendor_bill_orphan',
      ref_leg: 'suspense_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: 'AP_VENDOR',
      direction: 'out',
      amount: amt,
      counter_account_code: 'SUSPENSE',
      txn_type: 'vendor_bill_orphan',
      ref_leg: 'ap_credit',
    }),
  ];
}

const nowIso = (): string => `${new Date().toISOString().slice(0, -1)}000+00:00`;

/** services_fin_txn.ensure_system_accounts — idempotent, returns code -> id. */
export async function ensureSystemAccounts(
  mongo: Db,
  uid: string,
  cid: string,
): Promise<Record<string, string>> {
  const codeToId: Record<string, string> = {};
  for (const seed of FIN_SYSTEM_ACCOUNTS) {
    const existing = await mongo
      .collection<Doc>('fin_accounts')
      .findOne({ user_id: uid, company_id: cid, code: seed.code }, { projection: { _id: 0, id: 1 } });
    if (existing) {
      codeToId[seed.code] = str(existing['id']);
      continue;
    }
    const id = `acc_${seed.code.toLowerCase()}_${uid.slice(-6)}_${cid.slice(-6)}`;
    try {
      await mongo.collection('fin_accounts').insertOne({
        id,
        user_id: uid,
        company_id: cid,
        code: seed.code,
        name: seed.name,
        type: seed.type,
        is_system: true,
        is_active: true,
        remarks: 'seeded by Iter150A-1',
        created_at: nowIso(),
      });
    } catch {
      /* Python swallows a racing insert and re-reads below. */
    }
    codeToId[seed.code] = id;
  }
  return codeToId;
}

/** services_fin_txn._has_paired_expense */
async function hasPairedExpense(mongo: Db, uid: string, cid: string, billId: string): Promise<boolean> {
  const row = await mongo.collection<Doc>('expenses').findOne(
    {
      user_id: uid,
      company_id: cid,
      is_deleted: { $ne: true },
      is_reversed: { $ne: true },
      vendor_bill_id: billId,
    },
    { projection: { _id: 0, id: 1 } },
  );
  return Boolean(row);
}

/** services_fin_txn._delete_by_source (exact-match form; vendors need no cascade). */
async function deleteBySource(
  mongo: Db,
  uid: string,
  cid: string,
  sourceType: string,
  sourceId: string,
): Promise<number> {
  const res = await mongo
    .collection('fin_txn')
    .deleteMany({ user_id: uid, company_id: cid, source_type: sourceType, source_id: sourceId });
  return res.deletedCount ?? 0;
}

/** services_fin_txn._persist_legs — upsert by ref_source_key, replay-safe. */
async function persistLegs(
  mongo: Db,
  uid: string,
  cid: string,
  legs: Leg[],
  codeToId: Record<string, string>,
): Promise<number> {
  if (!legs.length) return 0;
  const stamp = nowIso();
  let written = 0;
  for (const l of legs) {
    const accountId = codeToId[l.account_code];
    const counterId = l.counter_account_code ? (codeToId[l.counter_account_code] ?? '') : '';
    if (!accountId) {
      throw new Error(`unknown account code '${l.account_code}' for tenant (${uid},${cid})`);
    }
    const doc = {
      id: `fintxn_${l.ref_source_key.replace(/:/g, '_').slice(0, 60)}`,
      user_id: uid,
      company_id: cid,
      txn_date: l.txn_date,
      account_id: accountId,
      account_code: l.account_code,
      direction: l.direction,
      amount: l.amount,
      counter_account_id: counterId,
      counter_account_code: l.counter_account_code,
      txn_type: l.txn_type,
      source_type: l.source_type,
      source_id: l.source_id,
      source_key: l.source_key,
      ref_source_key: l.ref_source_key,
      party_type: l.party_type,
      party_id: l.party_id,
      party_name: l.party_name,
      vehicle_id: l.vehicle_id,
      trip_id: l.trip_id,
      category: l.category,
      narration: l.narration,
      transfer_group_id: '',
      adjustment_group_id: '',
      reversal_of: '',
      is_reversal: false,
      status: 'active',
      is_supplier_settlement_recovery: l.is_supplier_settlement_recovery,
      reconciled_at: '',
      reconciled_ref: '',
      created_at: stamp,
      projected_at: stamp,
    };
    await mongo
      .collection('fin_txn')
      .updateOne(
        { user_id: uid, company_id: cid, ref_source_key: l.ref_source_key },
        { $set: doc },
        { upsert: true },
      );
    written += 1;
  }
  return written;
}

export const VENDOR_SOURCE_TYPES = ['vendor_payment', 'vendor_bill'] as const;
export type VendorSourceType = (typeof VENDOR_SOURCE_TYPES)[number];

/**
 * services_fin_txn.reproject_source, vendor branches only. Delete-then-insert,
 * idempotent, and — like the Python hook — never raises into the caller's write
 * path: a projection failure is recorded in fin_hook_failures for the retry
 * driver to drain, exactly as services_fin_txn_hooks does.
 */
export async function reprojectVendorSource(
  mongo: Db,
  uid: string,
  cid: string,
  sourceType: VendorSourceType,
  sourceId: string,
): Promise<{ ok: boolean; deleted: number; written: number; error?: string }> {
  try {
    const codeToId = await ensureSystemAccounts(mongo, uid, cid);
    const deleted = await deleteBySource(mongo, uid, cid, sourceType, sourceId);

    let legs: Leg[] = [];
    if (sourceType === 'vendor_payment') {
      const doc = await mongo
        .collection<Doc>('vendor_payments')
        .findOne({ user_id: uid, company_id: cid, id: sourceId }, { projection: { _id: 0 } });
      if (doc) legs = projectVendorPayment(doc);
    } else {
      const doc = await mongo
        .collection<Doc>('vendor_bills')
        .findOne({ user_id: uid, company_id: cid, id: sourceId }, { projection: { _id: 0 } });
      if (doc) legs = projectVendorBill(doc, await hasPairedExpense(mongo, uid, cid, sourceId));
    }

    const written = await persistLegs(mongo, uid, cid, legs, codeToId);
    return { ok: true, deleted, written };
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    try {
      await mongo.collection('fin_hook_failures').updateOne(
        { user_id: uid, company_id: cid, source_type: sourceType, source_id: sourceId },
        {
          $set: {
            user_id: uid,
            company_id: cid,
            source_type: sourceType,
            source_id: sourceId,
            error,
            failed_at: nowIso(),
            origin: 'nestjs',
          },
        },
        { upsert: true },
      );
    } catch {
      /* the failure log is best-effort, as in Python */
    }
    return { ok: false, deleted: 0, written: 0, error };
  }
}
