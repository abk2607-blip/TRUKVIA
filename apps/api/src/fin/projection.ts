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
  const typ = str(p['type']) || 'payment_out';
  // Python: f"{party_type.title()} {typ} · {ref_no}".strip(" ·") — strip()
  // removes any leading/trailing space or "·" characters, not one suffix.
  const title = opts.partyType.charAt(0).toUpperCase() + opts.partyType.slice(1);
  const narration = `${title} ${typ} · ${str(p['ref_no'])}`.replace(/^[ ·]+|[ ·]+$/g, '');
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
    // Python f-string, with no .strip() — see note 4 above.
    narration: `${kind === 'credit' ? 'CN' : 'DN'} ${str(note['note_number'])} · Inv ${str(
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
  // None of the ported types has a prefix cascade: invoice and
  // trip_customer_receipt are the only two that do, and neither is ported.
  const deleted = await deleteBySource(mongo, uid, cid, sourceType, sourceId);

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
