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
import { pyRound2 } from '../common/py-round';
import { pyTruthy } from '../common/identity';

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
 * services_fin_txn._q2 — `round(float(x or 0), 2)`.
 *
 * Python rounds half-to-even against the double's TRUE binary value, so
 * `round(2.675, 2)` is 2.67: the nearest double to 2.675 is below the midpoint.
 * The scale-by-100-and-compare version that used to live here read that as a
 * tie and returned 2.68 — a one-paisa error in a real ledger leg, which this
 * slice's parity run caught on a mechanic payment of 2.675. `pyRound2` decides
 * in exact BigInt arithmetic instead.
 */
export function q2(x: unknown): number {
  const n = typeof x === 'number' ? x : Number(x ?? 0);
  if (!Number.isFinite(n)) return 0;
  return pyRound2(n);
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
 * services_fin_txn._party_payment_legs — the shared two-leg party payment.
 *
 * Python has ONE helper that vendor, mechanic and driver payments each call
 * with different parameters. Keeping one helper here too is the point: two
 * copies of this shape drift, and the drift would be a wrong ledger rather
 * than a failing type.
 */
export interface PartyPaymentOpts {
  apCode: string;
  partyType: string;
  partyIdKey: string;
  srcType: string;
  txnTypePrefix: string;
  /**
   * `project_supplier_payment` ALSO skips historical documents. The shared
   * helper does not, so vendor and mechanic keep their exact behaviour.
   */
  skipIfHistorical?: boolean;
  /**
   * `project_supplier_payment` ALSO carries trip_id on every leg. The shared
   * helper leaves it empty unless a key is named.
   */
  tripIdKey?: string;
}

export function partyPaymentLegs(p: Doc, opts: PartyPaymentOpts): Leg[] {
  if (p['is_deleted'] || p['is_reversed']) return [];
  if (opts.skipIfHistorical && p['is_historical']) return [];
  const amt = q2(p['amount'] ?? 0);
  if (amt <= 0) return [];
  const date = str(p['date']);
  const bankCode = modeAccount(p['mode']);
  /**
   * Python: `typ = p.get("type") or "payment_out"`, keeping the RAW value.
   * It is then compared to the string, so a non-string type can never equal
   * "payment_out" and always takes the receipt branch — while still being
   * interpolated into the narration as Python would render it.
   */
  const typ: unknown = pyTruthy(p['type']) ? p['type'] : 'payment_out';
  /**
   * Python: f"{party_type.title()} {typ} · {p.get('ref_no', '')}".strip(" ·")
   *
   * Two details, both measured by scripts/fin-vendorpay-bridge-parity.ts:
   *
   *   - `.get('ref_no', '')` defaults ONLY when the key is absent. A key
   *     present with value None interpolates as the literal text "None" and
   *     survives the strip, because "None" ends in a letter. `str()` gave ""
   *     for both and silently lost a reference that Python shows.
   *   - strip(" ·") removes ALL leading and trailing spaces and middots,
   *     not one suffix.
   */
  const title = opts.partyType.charAt(0).toUpperCase() + opts.partyType.slice(1);
  const narration = `${title} ${pyInterp(typ)} · ${pyInterp(p['ref_no'])}`.replace(
    /^[ ·]+|[ ·]+$/g,
    '',
  );
  const common = {
    source_type: opts.srcType,
    source_id: str(p['id']),
    party_type: opts.partyType,
    party_id: str(p[opts.partyIdKey]),
    ...(opts.tripIdKey ? { trip_id: str(p[opts.tripIdKey]) } : {}),
    narration,
  };
  if (typ === 'payment_out') {
    return [
      leg({
        ...common,
        txn_date: date,
        account_code: opts.apCode,
        direction: 'in',
        amount: amt,
        counter_account_code: bankCode,
        txn_type: `${opts.txnTypePrefix}_payment_out`,
        ref_leg: 'ap_debit',
      }),
      leg({
        ...common,
        txn_date: date,
        account_code: bankCode,
        direction: 'out',
        amount: amt,
        counter_account_code: opts.apCode,
        txn_type: `${opts.txnTypePrefix}_payment_out`,
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
      counter_account_code: opts.apCode,
      txn_type: `${opts.txnTypePrefix}_receipt_in`,
      ref_leg: 'bank_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: opts.apCode,
      direction: 'out',
      amount: amt,
      counter_account_code: bankCode,
      txn_type: `${opts.txnTypePrefix}_receipt_in`,
      ref_leg: 'ap_credit',
    }),
  ];
}

/** services_fin_txn.project_vendor_payment. */
export function projectVendorPayment(p: Doc): Leg[] {
  return partyPaymentLegs(p, {
    apCode: 'AP_VENDOR',
    partyType: 'vendor',
    partyIdKey: 'vendor_id',
    srcType: 'vendor_payment',
    txnTypePrefix: 'vendor',
  });
}

/**
 * services_fin_txn.project_mechanic_payment — slice 2c unit 2.
 *
 * Identical in structure to the vendor case; only the payable account, the
 * party fields and the txn_type prefix differ. It reads one collection, has no
 * cascade and no paired-document lookup, which is why it was chosen first.
 */
export function projectMechanicPayment(p: Doc): Leg[] {
  return partyPaymentLegs(p, {
    apCode: 'AP_MECHANIC',
    partyType: 'mechanic',
    partyIdKey: 'mechanic_id',
    srcType: 'mechanic_payment',
    txnTypePrefix: 'mechanic',
  });
}

/**
 * services_fin_txn.project_invoice — slice 2c unit 12, the COUPLED unit.
 *
 * `invoice` and `invoice_payment` are one migration by construction, not by
 * choice: a single Python function emits BOTH. There is no
 * `project_invoice_payment` anywhere — the payments are embedded in the invoice
 * document and projected inline with their own source_type and a compound
 * source_id, `{invoice_id}:{payment_id}`. Splitting them would have meant
 * inventing a second producer that Python does not have.
 *
 * Up to three leg pairs, always in this order:
 *
 *   1. the raise          AR in (ar_debit) / SALES out (sales_credit)
 *                         txn_type invoice_raise
 *   2. the advance offset, only when advance+diesel deductions round above 0
 *                         CUSTOMER_ADVANCE in (cust_adv_debit)
 *                         SALES out (sales_offset_credit)
 *                         txn_type invoice_advance_offset
 *   3. one pair PER embedded payment, source_type invoice_payment
 *                         bank in (bank_in) / AR out (ar_credit)
 *                         txn_type invoice_receipt
 *
 * Four details that matter:
 *
 *   • a payment with NO id is skipped outright. Unlike trip_customer_receipt
 *     there is no array-index fallback, so a legacy payment without an id is
 *     simply never projected;
 *   • `total_amount <= 0` kills the WHOLE document — the payments do not
 *     project either, even when they have real amounts;
 *   • the offset is double-rounded: each deduction is rounded, then their sum
 *     is rounded again. `_q2(_q2(a) + _q2(b))`, not `_q2(a + b)`;
 *   • a payment's date falls back to the INVOICE date, and neither narration
 *     is stripped — a blank invoice number leaves the trailing space in
 *     `"Invoice "`.
 */
export function projectInvoice(inv: Doc): Leg[] {
  if (pyTruthy(inv['is_historical'])) return [];
  const invId = str(inv['id']);
  const total = q2(inv['total_amount'] ?? 0);
  // A zero-value invoice projects nothing at all, payments included.
  if (total <= 0) return [];

  const date = str(inv['invoice_date']);
  const customerId = str(inv['customer_id']);
  const invoiceNumber = pyInterp(inv['invoice_number']);
  const common = {
    source_type: 'invoice',
    source_id: invId,
    party_type: 'customer',
    party_id: customerId,
    narration: `Invoice ${invoiceNumber}`, // not stripped
  };

  const legs: Leg[] = [
    leg({
      ...common,
      txn_date: date,
      account_code: 'AR',
      direction: 'in',
      amount: total,
      counter_account_code: 'SALES',
      txn_type: 'invoice_raise',
      ref_leg: 'ar_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: 'SALES',
      direction: 'out',
      amount: total,
      counter_account_code: 'AR',
      txn_type: 'invoice_raise',
      ref_leg: 'sales_credit',
    }),
  ];

  // Each deduction is rounded BEFORE the sum, and the sum rounded again.
  const offset = q2(q2(inv['advance_deduction_total'] ?? 0) + q2(inv['diesel_deduction_total'] ?? 0));
  if (offset > 0) {
    legs.push(
      leg({
        ...common,
        txn_date: date,
        account_code: 'CUSTOMER_ADVANCE',
        direction: 'in',
        amount: offset,
        counter_account_code: 'SALES',
        txn_type: 'invoice_advance_offset',
        ref_leg: 'cust_adv_debit',
      }),
    );
    legs.push(
      leg({
        ...common,
        txn_date: date,
        account_code: 'SALES',
        direction: 'out',
        amount: offset,
        counter_account_code: 'CUSTOMER_ADVANCE',
        txn_type: 'invoice_advance_offset',
        ref_leg: 'sales_offset_credit',
      }),
    );
  }

  const payments = Array.isArray(inv['payments']) ? inv['payments'] : [];
  for (const raw of payments) {
    const p = (raw ?? {}) as Doc;
    const pid = pyTruthy(p['id']) ? String(p['id']) : '';
    const amt = q2(p['amount'] ?? 0);
    // No index fallback here: a payment without an id is simply skipped.
    if (amt <= 0 || !pid) continue;

    const pCommon = {
      source_type: 'invoice_payment',
      source_id: `${invId}:${pid}`,
      party_type: 'customer',
      party_id: customerId,
      narration: `Receipt ${pyInterp(p['reference'])} · Inv ${invoiceNumber}`, // not stripped
    };
    const bankCode = modeAccount(pyTruthy(p['mode']) ? p['mode'] : 'Bank');
    const pDate = pyTruthy(p['date']) ? str(p['date']) : date;
    legs.push(
      leg({
        ...pCommon,
        txn_date: pDate,
        account_code: bankCode,
        direction: 'in',
        amount: amt,
        counter_account_code: 'AR',
        txn_type: 'invoice_receipt',
        ref_leg: 'bank_in',
      }),
    );
    legs.push(
      leg({
        ...pCommon,
        txn_date: pDate,
        account_code: 'AR',
        direction: 'out',
        amount: amt,
        counter_account_code: bankCode,
        txn_type: 'invoice_receipt',
        ref_leg: 'ar_credit',
      }),
    );
  }
  return legs;
}

/**
 * services_fin_txn.project_wallet_transfer — slice 2c unit 11.
 *
 * A direct two-leg wallet-to-wallet move, with no INTER_ACCOUNT contra:
 *
 *   source_wallet_code      out (src_credit)  — money leaves the source
 *   destination_wallet_code in  (dst_debit)   — money lands in the destination
 *
 * BOTH account codes are dynamic, which makes this the only projection reading
 * two document-supplied accounts. Unlike wallet_recharge it self-guards them:
 * an empty or absent source OR destination returns no legs, as does a
 * same-wallet transfer (the router already rejects that with a 422; this is the
 * defensive second line).
 *
 * The failure class that DOES survive is the same one recharge has: a code that
 * is non-empty but not in the seed catalog passes the guard and makes
 * `_persist_legs` raise, so it is recorded in fin_hook_failures rather than
 * silently skipped. An invalid destination is never quietly dropped.
 *
 * The narration contains U+2192 RIGHTWARDS ARROW and is NOT stripped — another
 * invisible character that a find-and-replace would corrupt, so a unit test
 * asserts its codepoint.
 *
 * Guards are `is_deleted`, `amount <= 0`, then the two codes. Verified: neither
 * is_historical nor is_reversed is consulted.
 */
export function projectWalletTransfer(wt: Doc): Leg[] {
  if (pyTruthy(wt['is_deleted'])) return [];
  const amt = q2(wt['amount'] ?? 0);
  if (amt <= 0) return [];

  const src = pyTruthy(wt['source_wallet_code']) ? String(wt['source_wallet_code']) : '';
  const dst = pyTruthy(wt['destination_wallet_code']) ? String(wt['destination_wallet_code']) : '';
  if (!src || !dst || src === dst) return [];

  const date = str(wt['date']);
  const common = {
    source_type: 'wallet_transfer',
    source_id: str(wt['id']),
    // U+2192, and no .strip() on this one.
    narration: `Wallet transfer ${src} → ${dst}`,
  };
  return [
    leg({
      ...common,
      txn_date: date,
      account_code: src,
      direction: 'out',
      amount: amt,
      counter_account_code: dst,
      txn_type: 'wallet_transfer',
      ref_leg: 'src_credit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: dst,
      direction: 'in',
      amount: amt,
      counter_account_code: src,
      txn_type: 'wallet_transfer',
      ref_leg: 'dst_debit',
    }),
  ];
}

/**
 * services_fin_txn.project_wallet_recharge — slice 2c unit 10.
 *
 * BANK/CASH -> WALLET. Two legs: the wallet is debited, the funding account
 * credited.
 *
 * THE IMPORTANT DIFFERENCE FROM wallet_adjustment: there is **no guard on
 * wallet_code**. An empty, absent or unknown code is NOT skipped — it becomes
 * the leg's `account_code` and the failure surfaces later, when `_persist_legs`
 * cannot resolve it and raises. That distinction is deliberate and preserved:
 *
 *   projection guard (is_deleted, amount <= 0) -> zero legs, ok=true, written 0
 *   persistence lookup failure (bad wallet_code) -> RAISES -> ok=false and a
 *                                                   fin_hook_failures row
 *
 * Collapsing the second case into the first would turn a recorded, retryable
 * failure into a silent no-op, which is exactly the class of bug the hook
 * queue exists to catch. The model constrains the field to the two seeded
 * wallets, so this is reachable only from legacy or imported data.
 *
 * Guards are `is_deleted` and `amount <= 0` — nothing else. Verified: neither
 * is_historical nor is_reversed is consulted.
 */
export function projectWalletRecharge(wr: Doc): Leg[] {
  if (pyTruthy(wr['is_deleted'])) return [];
  const amt = q2(wr['amount'] ?? 0);
  if (amt <= 0) return [];

  const date = str(wr['date']);
  // No guard: an empty code flows straight through to the persist layer.
  const walletCode = pyTruthy(wr['wallet_code']) ? String(wr['wallet_code']) : '';
  const fundingCode = modeAccount(pyTruthy(wr['funding_mode']) ? wr['funding_mode'] : 'Bank');
  const common = {
    source_type: 'wallet_recharge',
    source_id: str(wr['id']),
    narration: `Wallet recharge · ${pyInterp(wr['reference'])}`.replace(/^[ ·]+|[ ·]+$/g, ''),
  };
  return [
    leg({
      ...common,
      txn_date: date,
      account_code: walletCode,
      direction: 'in',
      amount: amt,
      counter_account_code: fundingCode,
      txn_type: 'wallet_recharge_in',
      ref_leg: 'wallet_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: fundingCode,
      direction: 'out',
      amount: amt,
      counter_account_code: walletCode,
      txn_type: 'wallet_recharge_in',
      ref_leg: 'funding_credit',
    }),
  ];
}

/**
 * services_fin_txn.project_trip_customer_receipts — slice 2c unit 9.
 *
 * Money received from a customer against a specific trip, OUTSIDE the invoice
 * flow. The source document is the TRIP, and the reproject key is the trip id —
 * but each embedded receipt gets its OWN compound source_id, `{trip_id}:{rid}`,
 * which is why this source type needs the prefix cascade when the parent is
 * reprojected.
 *
 * It deliberately does NOT credit AR: Invoice.total_amount is already net of
 * these deductions, so crediting AR here would double-reduce it. The offset
 * lives in the invoice projection instead.
 *
 * Three things to get right:
 *
 *   1. the receipt key falls back to the ORIGINAL ARRAY POSITION when a legacy
 *      receipt carries no id — `idx0`, `idx1`, … Skipped receipts do NOT
 *      renumber the ones after them, so a middle receipt with a zero amount
 *      leaves `idx0` and `idx2`. Filtering before enumerating would silently
 *      rewrite every downstream key and break idempotency;
 *   2. a zero or negative receipt is SKIPPED, not fatal — the rest of the
 *      array still projects;
 *   3. the receipt `type` is interpolated into the txn_type AND the category,
 *      so txn_type is dynamic: trip_customer_advance_receipt,
 *      trip_customer_diesel_receipt, and whatever else the data holds.
 *
 * Guards: `is_historical` on the trip, and an empty receipts array. There is
 * NO is_deleted guard on the trip — verified against the interpreter.
 */
export function projectTripCustomerReceipts(trip: Doc): Leg[] {
  if (pyTruthy(trip['is_historical'])) return [];
  const receipts = Array.isArray(trip['customer_receipts']) ? trip['customer_receipts'] : [];
  if (receipts.length === 0) return [];

  const tripId = str(trip['id']);
  const customerId = str(trip['customer_id']);
  const tripDate = str(trip['date']);
  const legs: Leg[] = [];

  receipts.forEach((raw, i) => {
    const r = (raw ?? {}) as Doc;
    // `str(r.get("id") or "").strip() or f"idx{i}"` — note the index is the
    // POSITION in the original array, not a count of projected receipts.
    const rid = (pyTruthy(r['id']) ? String(r['id']) : '').trim() || `idx${i}`;
    const amt = q2(r['amount'] ?? 0);
    if (amt <= 0) return; // skip this receipt only

    const date = pyTruthy(r['date']) ? str(r['date']) : tripDate;
    const bankCode = modeAccount(pyTruthy(r['mode']) ? r['mode'] : 'Bank');
    const rtype = pyTruthy(r['type']) ? String(r['type']) : 'advance';
    const common = {
      source_type: 'trip_customer_receipt',
      source_id: `${tripId}:${rid}`,
      party_type: 'customer',
      party_id: customerId,
      trip_id: tripId,
      narration: `Trip customer ${rtype} receipt`,
      category: rtype,
    };
    legs.push(
      leg({
        ...common,
        txn_date: date,
        account_code: bankCode,
        direction: 'in',
        amount: amt,
        counter_account_code: 'CUSTOMER_ADVANCE',
        txn_type: `trip_customer_${rtype}_receipt`,
        ref_leg: 'bank_debit',
      }),
    );
    legs.push(
      leg({
        ...common,
        txn_date: date,
        account_code: 'CUSTOMER_ADVANCE',
        direction: 'out',
        amount: amt,
        counter_account_code: bankCode,
        txn_type: `trip_customer_${rtype}_receipt`,
        ref_leg: 'cust_adv_credit',
      }),
    );
  });
  return legs;
}

/**
 * Python's f-string interpolation, for the one field that needs it.
 *
 * `f"… {wa.get('reason', '')}"` renders whatever the value IS. The default
 * only applies when the key is ABSENT — a key present with value None
 * interpolates as the literal text "None", which is visible in the narration.
 * `str()` would give "" for both and silently lose the difference.
 *
 * Deliberately narrow: it covers the types a Mongo document can hold here.
 * The wider `pyStr()` fidelity question across the older projections is still
 * the separate unit recorded in slice 2c unit 5.
 */
function pyInterp(v: unknown): string {
  if (v === undefined) return ''; // absent key -> the .get() default
  if (v === null) return 'None';
  if (typeof v === 'boolean') return v ? 'True' : 'False';
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(v);
  return String(v);
}

/**
 * services_fin_txn.project_wallet_adjustment — slice 2c unit 8.
 *
 * A real financial adjustment booked against SUSPENSE, so the correction is
 * always visible on both sides rather than vanishing into the wallet:
 *
 *   increase -> wallet_code in  (wallet_debit)  / SUSPENSE out (suspense_credit)
 *   decrease -> wallet_code out (wallet_credit) / SUSPENSE in  (suspense_debit)
 *
 * The account code comes from the DOCUMENT, not from a fixed literal — this is
 * the first ported projection where that is true. It is nonetheless safe to
 * port in isolation:
 *
 *   • the model constrains it to Literal["WALLET_FASTAG", "WALLET_FUEL"], and
 *     BOTH are already in the seed catalog;
 *   • the projection self-guards — an empty or missing wallet_code returns no
 *     legs rather than reaching the persist layer;
 *   • nothing here creates an account. `_persist_legs` only LOOKS UP the code
 *     in the map `ensure_system_accounts` built, so there is no lazy seeding
 *     and no dependency on GET /api/fin/accounts.
 *
 * A wallet_code that is non-empty but NOT in the catalog — only reachable from
 * legacy or imported data, never through the API — passes the guard and makes
 * `_persist_legs` raise. That is a projection FAILURE recorded in
 * fin_hook_failures, not a silent skip, and the port preserves it by using the
 * same persist path.
 *
 * `reverses_id` is deliberately ignored: a reversal is a separate document with
 * the opposite direction, and both project identically for a net-zero effect
 * with the history intact.
 */
export function projectWalletAdjustment(wa: Doc): Leg[] {
  if (pyTruthy(wa['is_deleted'])) return [];
  const amt = q2(wa['amount'] ?? 0);
  if (amt <= 0) return [];

  const walletCode = pyTruthy(wa['wallet_code']) ? String(wa['wallet_code']) : '';
  const direction = pyTruthy(wa['direction']) ? String(wa['direction']) : '';
  // Exact membership: "INCREASE", "Increase" and "increase " are all rejected.
  if (!walletCode || (direction !== 'increase' && direction !== 'decrease')) return [];

  const date = str(wa['date']);
  // U+2212 MINUS SIGN, NOT an ASCII hyphen-minus. The two are visually
  // identical and a well-meaning find-and-replace would break byte parity on
  // every decrease narration, so there is a unit test asserting the codepoint.
  const sign = direction === 'increase' ? '+' : '−';
  const common = {
    source_type: 'wallet_adjustment',
    source_id: str(wa['id']),
    narration: `Wallet adjustment (${sign}) · ${pyInterp(wa['reason'])}`.replace(/^[ ·]+|[ ·]+$/g, ''),
  };

  if (direction === 'increase') {
    return [
      leg({
        ...common,
        txn_date: date,
        account_code: walletCode,
        direction: 'in',
        amount: amt,
        counter_account_code: 'SUSPENSE',
        txn_type: 'wallet_adjustment_increase',
        ref_leg: 'wallet_debit',
      }),
      leg({
        ...common,
        txn_date: date,
        account_code: 'SUSPENSE',
        direction: 'out',
        amount: amt,
        counter_account_code: walletCode,
        txn_type: 'wallet_adjustment_increase',
        ref_leg: 'suspense_credit',
      }),
    ];
  }
  return [
    leg({
      ...common,
      txn_date: date,
      account_code: walletCode,
      direction: 'out',
      amount: amt,
      counter_account_code: 'SUSPENSE',
      txn_type: 'wallet_adjustment_decrease',
      ref_leg: 'wallet_credit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: 'SUSPENSE',
      direction: 'in',
      amount: amt,
      counter_account_code: walletCode,
      txn_type: 'wallet_adjustment_decrease',
      ref_leg: 'suspense_debit',
    }),
  ];
}

/**
 * services_fin_txn.project_mechanic_work_order — slice 2c unit 7.
 *
 * An ORPHAN-ONLY projection, and the shortest guard list of any unit so far.
 * A work order posts legs only when NO paired expense exists: in the canonical
 * flow the Expense carries the real cost, and projecting both would
 * double-count AP_MECHANIC. When unpaired, the cost is parked in SUSPENSE so
 * it is visible rather than lost.
 *
 * Guard order is `is_deleted`, then the pairing, then the amount. Note what is
 * NOT here: there is **no is_reversed guard and no is_historical guard** —
 * unlike every other projection ported so far. Verified against the
 * interpreter: a reversed or historical work order still projects.
 *
 * The date field is `work_date`, not `date`, and the narration is a fixed
 * `f"WO {id} (orphan)"` with no fallback and no strip — only _leg's 400-char
 * cap applies. No source_key and no category are set.
 */
export function projectMechanicWorkOrder(wo: Doc, hasPaired: boolean): Leg[] {
  if (pyTruthy(wo['is_deleted'])) return [];
  if (hasPaired) return [];
  const amt = q2(wo['amount'] ?? 0);
  if (amt <= 0) return [];

  const date = str(wo['work_date']);
  const id = str(wo['id']);
  const common = {
    source_type: 'mechanic_work_order',
    source_id: id,
    party_type: 'mechanic',
    party_id: str(wo['mechanic_id']),
    party_name: str(wo['mechanic_name']),
    vehicle_id: str(wo['vehicle_id']),
    trip_id: str(wo['trip_id']),
    narration: `WO ${id} (orphan)`,
  };
  return [
    leg({
      ...common,
      txn_date: date,
      account_code: 'SUSPENSE',
      direction: 'in',
      amount: amt,
      counter_account_code: 'AP_MECHANIC',
      txn_type: 'mechanic_wo_orphan',
      ref_leg: 'suspense_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: 'AP_MECHANIC',
      direction: 'out',
      amount: amt,
      counter_account_code: 'SUSPENSE',
      txn_type: 'mechanic_wo_orphan',
      ref_leg: 'ap_credit',
    }),
  ];
}

/**
 * services_fin_txn.project_expense — slice 2c unit 6.
 *
 * The canonical cost projection, and by volume the most important one: roughly
 * 79% of existing ledger rows come through here. Every payable, vendor and
 * supplier-recovery leg is funnelled into this one function precisely so a
 * paired VendorBill or MechanicWorkOrder cannot double-count the same cost.
 *
 * The debit side is always EXPENSE_DEFAULT. What varies is the CREDIT side,
 * chosen by a top-down chain in which the FIRST match wins — verified branch by
 * branch against the running interpreter:
 *
 *   1a. supplier_owned_vehicle AND mode "supplier_settlement_adjustment"
 *         -> AP_SUPPLIER, expense_supplier_settlement_recovery
 *            party_type is FORCED to "supplier", overriding the document,
 *            and the credit leg carries is_supplier_settlement_recovery.
 *   1b. supplier_owned_vehicle AND mode "company_borne" -> CASH
 *   2.  document source_type "fastag_import"     -> WALLET_FASTAG
 *   3.  document source_type "fleet_card_import" -> WALLET_FUEL
 *   4.  vendor_bill_id set          -> AP_VENDOR
 *   5.  mechanic_work_order_id set  -> AP_MECHANIC
 *   6.  settlement_mode "cash_now"  -> CASH
 *   7.  otherwise                   -> SUSPENSE, expense_unrouted
 *
 * Two things about that chain are easy to get wrong and are tested both ways:
 *
 *   • a supplier-owned vehicle whose mode is NEITHER of the two named ones
 *     falls THROUGH to rules 2-7 rather than landing anywhere supplier-ish;
 *   • `supplier_owned_vehicle` is read with `bool()`, not `== True`, so the
 *     STRING "false" is truthy and selects the supplier branch. pyTruthy
 *     reproduces that; a `=== true` test would silently reroute the row.
 *
 * The credit leg's ref_leg is DYNAMIC — `f"{credit_code.lower()}_credit"` —
 * so ref_source_key varies with the branch: ap_supplier_credit, cash_credit,
 * wallet_fastag_credit, wallet_fuel_credit, ap_vendor_credit,
 * ap_mechanic_credit, suspense_credit.
 *
 * All eight accounts it can name are already in the seed catalog, so no branch
 * lazily creates anything new.
 */
export function projectExpense(exp: Doc): Leg[] {
  if (pyTruthy(exp['is_deleted']) || pyTruthy(exp['is_reversed'])) return [];
  const amt = q2(exp['amount'] ?? 0);
  if (amt <= 0) return [];
  // Python checks is_historical AFTER the amount; the order is unobservable
  // because both return [], but it is kept for line-by-line comparison.
  if (pyTruthy(exp['is_historical'])) return [];

  const date = str(exp['date']);
  const srcKey = str(exp['source_key']);
  // The DOCUMENT's own source_type, not the leg's — the leg is always
  // source_type "expense".
  const docSourceType = pyTruthy(exp['source_type']) ? exp['source_type'] : 'manual';
  const suppOwned = pyTruthy(exp['supplier_owned_vehicle']);
  const suppMode = pyTruthy(exp['supplier_settlement_mode'])
    ? exp['supplier_settlement_mode']
    : 'n/a';
  const settlement = pyTruthy(exp['settlement_mode']) ? exp['settlement_mode'] : 'payable';
  // vendor_bill_id and mechanic_work_order_id are only ever TESTED, never
  // emitted, so Python truthiness on the raw value is exactly right.
  const hasVendorBill = pyTruthy(exp['vendor_bill_id']);
  const hasWorkOrder = pyTruthy(exp['mechanic_work_order_id']);

  let partyType = str(exp['party_type']);
  let creditCode: string;
  let txnType: string;
  let isSettlementRecovery = false;

  if (suppOwned && suppMode === 'supplier_settlement_adjustment') {
    creditCode = 'AP_SUPPLIER';
    txnType = 'expense_supplier_settlement_recovery';
    // Forced, overriding whatever the document carried.
    partyType = 'supplier';
    isSettlementRecovery = true;
  } else if (suppOwned && suppMode === 'company_borne') {
    creditCode = 'CASH';
    txnType = 'expense_company_borne';
  } else if (docSourceType === 'fastag_import') {
    creditCode = 'WALLET_FASTAG';
    txnType = 'expense_fastag_toll';
  } else if (docSourceType === 'fleet_card_import') {
    creditCode = 'WALLET_FUEL';
    txnType = 'expense_fleet_diesel';
  } else if (hasVendorBill) {
    creditCode = 'AP_VENDOR';
    txnType = 'expense_vendor_payable';
  } else if (hasWorkOrder) {
    creditCode = 'AP_MECHANIC';
    txnType = 'expense_mechanic_payable';
  } else if (settlement === 'cash_now') {
    creditCode = 'CASH';
    txnType = 'expense_cash_now';
  } else {
    creditCode = 'SUSPENSE';
    txnType = 'expense_unrouted';
  }

  const category = str(exp['category']);
  // Python: (narration or category or "")[:400]. `category` itself is NOT
  // truncated on the leg — only the narration is.
  const narrationSource = pyTruthy(exp['narration'])
    ? str(exp['narration'])
    : pyTruthy(exp['category'])
      ? category
      : '';
  const common = {
    source_type: 'expense',
    source_id: str(exp['id']),
    source_key: srcKey,
    party_type: partyType,
    party_id: str(exp['party_id']),
    party_name: str(exp['party_name']),
    vehicle_id: str(exp['vehicle_id']),
    trip_id: str(exp['trip_id']),
    category,
    narration: narrationSource.slice(0, 400),
  };

  return [
    leg({
      ...common,
      txn_date: date,
      account_code: 'EXPENSE_DEFAULT',
      direction: 'in',
      amount: amt,
      counter_account_code: creditCode,
      txn_type: txnType,
      ref_leg: 'expense_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: creditCode,
      direction: 'out',
      amount: amt,
      counter_account_code: 'EXPENSE_DEFAULT',
      txn_type: txnType,
      ref_leg: `${creditCode.toLowerCase()}_credit`,
      // Only the CREDIT leg carries the flag, and only on branch 1a.
      is_supplier_settlement_recovery: isSettlementRecovery,
    }),
  ];
}

/**
 * services_fin_txn.project_credit_debit_note — slice 2c unit 5.
 *
 * NOT a party payment, and deliberately not routed through the shared helper:
 * there is no money side here at all. Both legs are the fixed pair AR/SALES,
 * so no `mode` is read and no bank account is resolved. A credit note reverses
 * the customer's receivable; a debit note adds to it.
 *
 * Four things differ from every projection ported so far, each verified
 * against the running interpreter rather than assumed:
 *
 *   1. the guards are `status != "issued"` and `is_historical`. There is NO
 *      is_deleted or is_reversed check — those fields do not exist on the
 *      CreditDebitNote model; a cancelled note carries status "cancelled",
 *      which the status guard already rejects;
 *   2. the amount field is `total_amount`, not `amount`, and the date field is
 *      `note_date`, not `date`;
 *   3. `kind` selects the branch by `== "credit"`, so a falsy kind defaults to
 *      credit and ANY other value — "debit", "weird" — takes the debit branch;
 *   4. the narration is NOT stripped. Every other projection ends with
 *      `.strip(" ·")`; this one does not, so an empty note_number and
 *      invoice_number_snapshot produce exactly `"CN  · Inv "`, two spaces and
 *      a dangling separator included. Trimming it would be a silent
 *      difference in a field that reaches the day-book.
 */
export function projectCreditDebitNote(note: Doc): Leg[] {
  if (note['status'] !== 'issued') return [];
  if (note['is_historical']) return [];
  const total = q2(note['total_amount'] ?? 0);
  if (total <= 0) return [];

  /**
   * Python: `note.get("kind") or "credit"`, then `kind == "credit"`.
   *
   * The `or` is PYTHON truthiness, and the comparison is against the raw value
   * — not a stringified one. A truthy NON-string kind therefore survives the
   * default and fails the equality test, so Python takes the DEBIT branch.
   * Coercing with str() first would have turned it into "" and then "credit",
   * silently flipping the sign of the note. Verified against the interpreter
   * for 5, True, ['x'] and {'a': 1} — all four give debit_note_issue.
   */
  const rawKind = note['kind'];
  const kind: unknown = pyTruthy(rawKind) ? rawKind : 'credit';
  const date = str(note['note_date']);
  const common = {
    source_type: 'credit_debit_note',
    source_id: str(note['id']),
    party_type: 'customer',
    party_id: str(note['customer_id']),
    /**
     * Python f-string, with no .strip() — see note 4 above.
     *
     * `note.get('note_number', '')` defaults ONLY on an absent key, so a
     * present None renders as the literal "None" on both fields. `str()`
     * flattened the two cases together; pyInterp keeps them apart.
     */
    narration: `${kind === 'credit' ? 'CN' : 'DN'} ${pyInterp(note['note_number'])} · Inv ${pyInterp(
      note['invoice_number_snapshot'],
    )}`,
  };

  if (kind === 'credit') {
    return [
      leg({
        ...common,
        txn_date: date,
        account_code: 'AR',
        direction: 'out',
        amount: total,
        counter_account_code: 'SALES',
        txn_type: 'credit_note_issue',
        ref_leg: 'ar_credit',
      }),
      leg({
        ...common,
        txn_date: date,
        account_code: 'SALES',
        direction: 'in',
        amount: total,
        counter_account_code: 'AR',
        txn_type: 'credit_note_issue',
        ref_leg: 'sales_debit',
      }),
    ];
  }
  return [
    leg({
      ...common,
      txn_date: date,
      account_code: 'AR',
      direction: 'in',
      amount: total,
      counter_account_code: 'SALES',
      txn_type: 'debit_note_issue',
      ref_leg: 'ar_debit',
    }),
    leg({
      ...common,
      txn_date: date,
      account_code: 'SALES',
      direction: 'out',
      amount: total,
      counter_account_code: 'AR',
      txn_type: 'debit_note_issue',
      ref_leg: 'sales_credit',
    }),
  ];
}

/**
 * services_fin_txn.project_driver_payment — slice 2c unit 4.
 *
 * Verified against the source: it IS a plain `_party_payment_legs` call, with
 * no is_historical guard and no trip_id — the mechanic shape with a different
 * payable account. The interesting part of this source type is not the ledger
 * maths but how it is REACHED: the bottom of services_fin_txn.py replaces
 * `reproject_source` with a wrapper that handles driver_payment itself, so the
 * dispatcher's if/elif chain never sees it on the Python side.
 *
 * DRIVER_OUTFLOW is the account behind the 13-vs-14 fin_accounts split that
 * slice 2a documented. It is in the seed catalog on both sides, so projecting
 * a driver payment into a 13-account scope seeds it — the same lazy
 * self-healing Python performs, not a normalisation.
 */
export function projectDriverPayment(p: Doc): Leg[] {
  return partyPaymentLegs(p, {
    apCode: 'DRIVER_OUTFLOW',
    partyType: 'driver',
    partyIdKey: 'driver_id',
    srcType: 'driver_payment',
    txnTypePrefix: 'driver',
  });
}

/**
 * services_fin_txn.project_supplier_payment — slice 2c unit 3.
 *
 * Python keeps this as a STANDALONE function rather than a `_party_payment_legs`
 * call, and it is not a pure rename: it differs in exactly two ways, both
 * verified against the source rather than assumed.
 *
 *   1. an extra `is_historical` guard, which the shared helper has not;
 *   2. `trip_id` carried on every leg, which the shared helper leaves empty.
 *
 * Everything else is identical — the fixed AP_SUPPLIER account, the mode
 * resolution, the `type` default, the leg order, the ref_leg names and the
 * txn_types. Python's literal "Supplier" in the narration equals the helper's
 * `party_type.title()` for "supplier", so that matches too. The two real
 * differences are passed as options so the ledger maths stays in one place.
 */
export function projectSupplierPayment(p: Doc): Leg[] {
  return partyPaymentLegs(p, {
    apCode: 'AP_SUPPLIER',
    partyType: 'supplier',
    partyIdKey: 'supplier_id',
    srcType: 'supplier_payment',
    txnTypePrefix: 'supplier',
    skipIfHistorical: true,
    tripIdKey: 'trip_id',
  });
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
    // Python: f"VendorBill {vb.get('bill_number', '')} (orphan)" — NOT
    // stripped, so an absent number leaves the double space and a present
    // None renders as the literal "None". See partyPaymentLegs above.
    narration: `VendorBill ${pyInterp(vb['bill_number'])} (orphan)`,
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
    } catch (err) {
      /**
       * Python re-reads and RE-RAISES; this port dropped both, which made a
       * refused insert look like a success:
       *
       *   except Exception:
       *       hit = await db.fin_accounts.find_one({...})
       *       if hit: code_to_id[code] = hit["id"]; continue
       *       raise
       *
       * A racing seeder is benign — the id is derived positionally, so the
       * winner wrote the same row and the re-read finds it. Anything else is
       * not benign: swallowing it left `codeToId` holding an id for a row that
       * does not exist, `persistLegs` then found a truthy id and wrote a
       * fin_txn leg pointing at a missing account — silently, with no error
       * and no failure-queue entry. Re-raising keeps the projection atomic:
       * it throws before any delete or persist, so the caller records the
       * failure and no ledger row is written.
       */
      const hit = await mongo
        .collection<Doc>('fin_accounts')
        .findOne({ user_id: uid, company_id: cid, code: seed.code }, { projection: { _id: 0, id: 1 } });
      if (hit) {
        codeToId[seed.code] = str(hit['id']);
        continue;
      }
      throw err;
    }
    codeToId[seed.code] = id;
  }
  return codeToId;
}

/** services_fin_txn._has_paired_expense */
/**
 * services_fin_txn._has_paired_expense.
 *
 * It reads the `expenses` SOURCE collection, not `fin_txn`. That matters more
 * than it looks: the answer does not depend on who owns the expense
 * PROJECTION, so pairing behaves identically whether Python or NestJS
 * projected the expense, or neither has yet. MongoDB owns `expenses` either
 * way.
 *
 * Two details are Mongo semantics rather than Python ones, and both are
 * deliberate:
 *
 *   • `$ne: true` excludes ONLY BSON true. An expense with `is_deleted: 1`,
 *     `"false"`, `0`, null or the field absent still counts as paired —
 *     verified against the server. So an expense that projects nothing because
 *     `pyTruthy(1)` skips it can still SUPPRESS its work order, leaving both
 *     documents with zero legs. That is Python's behaviour, not a defect here.
 *   • the probe checks neither `is_historical` nor the amount, so a historical
 *     or zero-amount expense also suppresses.
 *
 * Python applies each key only when truthy, so both can be set at once; the
 * dispatcher passes exactly one.
 */
async function hasPairedExpense(
  mongo: Db,
  uid: string,
  cid: string,
  opts: { vendorBillId?: string; mechanicWorkOrderId?: string },
): Promise<boolean> {
  const filter: Doc = {
    user_id: uid,
    company_id: cid,
    is_deleted: { $ne: true },
    is_reversed: { $ne: true },
  };
  if (pyTruthy(opts.vendorBillId)) filter['vendor_bill_id'] = opts.vendorBillId;
  if (pyTruthy(opts.mechanicWorkOrderId)) {
    filter['mechanic_work_order_id'] = opts.mechanicWorkOrderId;
  }
  const row = await mongo
    .collection<Doc>('expenses')
    .findOne(filter, { projection: { _id: 0, id: 1 } });
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
  const filter: Doc = { user_id: uid, company_id: cid, source_type: sourceType };
  if (sourceId.endsWith(':*')) {
    /**
     * The PREFIX form, for compound keys like `{trip_id}:{receipt_id}`, so a
     * parent's reproject also clears its embedded children.
     *
     * Python builds `{"$regex": f"^{prefix}"}` with NO escaping, and that is
     * reproduced deliberately: escaping would change which rows a source id
     * containing a regex metacharacter deletes. The scope is still narrowed by
     * source_type, so a cascade can never reach another projection's rows.
     */
    filter['source_id'] = { $regex: `^${sourceId.slice(0, -1)}` };
  } else {
    filter['source_id'] = sourceId;
  }
  const res = await mongo.collection('fin_txn').deleteMany(filter);
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

/**
 * The source types with a TypeScript projection. Everything else still goes to
 * Python through the forward bridge — see src/fin/fin-hook.ts.
 */
export const PORTED_SOURCE_TYPES = [
  'vendor_payment',
  'vendor_bill',
  'mechanic_payment',
  'supplier_payment',
  'driver_payment',
  'credit_debit_note',
  'expense',
  'mechanic_work_order',
  'wallet_adjustment',
  'trip_customer_receipt',
  'wallet_recharge',
  'wallet_transfer',
  'invoice',
] as const;
export type PortedSourceType = (typeof PORTED_SOURCE_TYPES)[number];

/** @deprecated kept so existing imports keep compiling; prefer PORTED_SOURCE_TYPES. */
export const VENDOR_SOURCE_TYPES = PORTED_SOURCE_TYPES;
export type VendorSourceType = PortedSourceType;

/**
 * services_fin_txn.reproject_source, vendor branches only — the THROWING form.
 *
 * Failure handling deliberately does not live here. It belongs to the canonical
 * hook in ./fin-hook.ts, which owns the fin_hook_failures contract the Python
 * retry driver depends on. Having both record failures would double-write the
 * row, and this file previously recorded one in a shape nothing could drain.
 */
export async function reprojectVendorSourceOrThrow(
  mongo: Db,
  uid: string,
  cid: string,
  sourceType: PortedSourceType,
  sourceId: string,
): Promise<{ deleted: number; written: number }> {
  const codeToId = await ensureSystemAccounts(mongo, uid, cid);
  /**
   * The cascade, exactly as reproject_source orders it: the PREFIX delete
   * first, then the exact-match one. trip_customer_receipt stores its rows
   * under `{trip_id}:{receipt_id}`, so only the prefix form finds them; the
   * exact delete that follows is a no-op for this type but is kept because
   * Python performs it and its count feeds the returned `deleted`.
   */
  let deleted = 0;
  if (sourceType === 'invoice') {
    // The parent's reproject clears its embedded payment legs, which live
    // under a DIFFERENT source_type — the only cascade that crosses one.
    deleted += await deleteBySource(mongo, uid, cid, 'invoice_payment', `${sourceId}:*`);
  }
  if (sourceType === 'trip_customer_receipt') {
    deleted += await deleteBySource(mongo, uid, cid, 'trip_customer_receipt', `${sourceId}:*`);
  }
  deleted += await deleteBySource(mongo, uid, cid, sourceType, sourceId);

  const findSource = (collection: string): Promise<Doc | null> =>
    mongo
      .collection<Doc>(collection)
      .findOne({ user_id: uid, company_id: cid, id: sourceId }, { projection: { _id: 0 } });

  let legs: Leg[] = [];
  if (sourceType === 'vendor_payment') {
    const doc = await findSource('vendor_payments');
    if (doc) legs = projectVendorPayment(doc);
  } else if (sourceType === 'mechanic_payment') {
    const doc = await findSource('mechanic_payments');
    if (doc) legs = projectMechanicPayment(doc);
  } else if (sourceType === 'supplier_payment') {
    const doc = await findSource('supplier_payments');
    if (doc) legs = projectSupplierPayment(doc);
  } else if (sourceType === 'driver_payment') {
    const doc = await findSource('driver_payments');
    if (doc) legs = projectDriverPayment(doc);
  } else if (sourceType === 'credit_debit_note') {
    const doc = await findSource('credit_debit_notes');
    if (doc) legs = projectCreditDebitNote(doc);
  } else if (sourceType === 'expense') {
    const doc = await findSource('expenses');
    if (doc) legs = projectExpense(doc);
  } else if (sourceType === 'invoice') {
    const doc = await findSource('invoices');
    if (doc) legs = projectInvoice(doc);
  } else if (sourceType === 'wallet_transfer') {
    const doc = await findSource('wallet_transfers');
    if (doc) legs = projectWalletTransfer(doc);
  } else if (sourceType === 'wallet_recharge') {
    const doc = await findSource('wallet_recharges');
    if (doc) legs = projectWalletRecharge(doc);
  } else if (sourceType === 'trip_customer_receipt') {
    // The reproject key is the TRIP id; the receipts live inside the document.
    const doc = await findSource('trips');
    if (doc) legs = projectTripCustomerReceipts(doc);
  } else if (sourceType === 'wallet_adjustment') {
    const doc = await findSource('wallet_adjustments');
    if (doc) legs = projectWalletAdjustment(doc);
  } else if (sourceType === 'mechanic_work_order') {
    const doc = await findSource('mechanic_work_orders');
    // Two reads, exactly as Python: the work order, then the pairing probe.
    if (doc) {
      legs = projectMechanicWorkOrder(
        doc,
        await hasPairedExpense(mongo, uid, cid, { mechanicWorkOrderId: sourceId }),
      );
    }
  } else {
    const doc = await findSource('vendor_bills');
    if (doc) legs = projectVendorBill(doc, await hasPairedExpense(mongo, uid, cid, { vendorBillId: sourceId }));
  }

  const written = await persistLegs(mongo, uid, cid, legs, codeToId);
  return { deleted, written };
}
