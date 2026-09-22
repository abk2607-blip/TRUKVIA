/**
 * Focused parity for slice 2c unit 6 — the `expense` projection.
 *
 *   npx tsx scripts/fin-expense-parity.ts
 *
 * The highest-value unit in 2c: expenses are roughly 79% of existing ledger
 * rows. The fixtures below walk the whole routing chain rather than sampling
 * it, and cover the two places it is easy to get wrong in the opposite
 * direction — a supplier-owned vehicle whose mode matches NEITHER named case
 * falls through to the later rules, and `supplier_owned_vehicle` is read with
 * Python's bool(), so the STRING "false" is truthy.
 *
 * `verifyRouting` is on: with 79% of rows behind it, "exactly once from each
 * entry point" is worth measuring here too, not just on driver_payment.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_expparity';
const CID = 'co_expparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_expparity_other';
const CID2 = 'co_expparity_other';

const base = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  amount: 1000,
  date: '2026-09-02',
  category: 'fuel',
  narration: 'Diesel top-up',
  is_deleted: false,
  is_reversed: false,
  is_historical: false,
  ...over,
});

const documents: Doc[] = [
  // ── the routing chain, one fixture per rule ──────────────────────────
  base({
    id: 'exp_settlement_recovery',
    supplier_owned_vehicle: true,
    supplier_settlement_mode: 'supplier_settlement_adjustment',
  }),
  base({
    // party_type is FORCED to "supplier" here, overriding the document.
    id: 'exp_recovery_overrides_party',
    supplier_owned_vehicle: true,
    supplier_settlement_mode: 'supplier_settlement_adjustment',
    party_type: 'vendor',
    party_id: 'ven_1',
    party_name: 'Some Vendor',
  }),
  base({
    id: 'exp_company_borne',
    supplier_owned_vehicle: true,
    supplier_settlement_mode: 'company_borne',
  }),
  base({ id: 'exp_fastag', source_type: 'fastag_import' }),
  base({ id: 'exp_fleet_card', source_type: 'fleet_card_import' }),
  base({ id: 'exp_vendor_bill', vendor_bill_id: 'vbl_1' }),
  base({ id: 'exp_work_order', mechanic_work_order_id: 'wo_1' }),
  base({ id: 'exp_cash_now', settlement_mode: 'cash_now' }),
  base({ id: 'exp_unrouted' }), // fallback -> SUSPENSE
  base({ id: 'exp_settlement_payable', settlement_mode: 'payable' }), // -> SUSPENSE
  base({ id: 'exp_settlement_missing', settlement_mode: undefined }), // -> SUSPENSE

  // ── fall-through: supplier-owned with an unnamed mode ────────────────
  base({ id: 'exp_supp_other_mode', supplier_owned_vehicle: true, supplier_settlement_mode: 'weird' }),
  base({
    id: 'exp_supp_other_mode_fastag',
    supplier_owned_vehicle: true,
    supplier_settlement_mode: 'weird',
    source_type: 'fastag_import',
  }),
  base({ id: 'exp_supp_no_mode_vb', supplier_owned_vehicle: true, vendor_bill_id: 'vbl_2' }),
  base({
    id: 'exp_supp_no_mode_cash',
    supplier_owned_vehicle: true,
    settlement_mode: 'cash_now',
  }),

  // ── bool() truthiness on supplier_owned_vehicle ──────────────────────
  // A NON-EMPTY string is truthy in Python, so "false" selects the branch.
  base({
    id: 'exp_supp_string_false',
    supplier_owned_vehicle: 'false',
    supplier_settlement_mode: 'company_borne',
  }),
  base({ id: 'exp_supp_zero', supplier_owned_vehicle: 0, supplier_settlement_mode: 'company_borne' }),
  base({ id: 'exp_supp_empty', supplier_owned_vehicle: '', supplier_settlement_mode: 'company_borne' }),
  base({ id: 'exp_supp_null', supplier_owned_vehicle: null, supplier_settlement_mode: 'company_borne' }),
  base({ id: 'exp_supp_one', supplier_owned_vehicle: 1, supplier_settlement_mode: 'company_borne' }),

  // ── precedence, where two rules could both match ─────────────────────
  base({ id: 'exp_prec_fastag_vb', source_type: 'fastag_import', vendor_bill_id: 'vbl_3' }),
  base({ id: 'exp_prec_vb_wo', vendor_bill_id: 'vbl_4', mechanic_work_order_id: 'wo_2' }),
  base({ id: 'exp_prec_wo_cash', mechanic_work_order_id: 'wo_3', settlement_mode: 'cash_now' }),
  base({
    id: 'exp_prec_recovery_beats_all',
    supplier_owned_vehicle: true,
    supplier_settlement_mode: 'supplier_settlement_adjustment',
    source_type: 'fastag_import',
    vendor_bill_id: 'vbl_5',
    mechanic_work_order_id: 'wo_4',
    settlement_mode: 'cash_now',
  }),
  // vendor_bill_id is only TESTED, so a truthy non-string still routes.
  base({ id: 'exp_vb_nonstring', vendor_bill_id: 5 }),
  base({ id: 'exp_vb_empty', vendor_bill_id: '' }), // falsy -> falls through
  base({ id: 'exp_wo_empty', mechanic_work_order_id: '' }),

  // ── guards ───────────────────────────────────────────────────────────
  base({ id: 'exp_deleted', is_deleted: true }),
  base({ id: 'exp_reversed', is_reversed: true }),
  base({ id: 'exp_historical', is_historical: true }),
  base({ id: 'exp_deleted_falsy', is_deleted: 0 }),
  base({ id: 'exp_historical_falsy', is_historical: 0 }),
  base({ id: 'exp_zero', amount: 0 }),
  base({ id: 'exp_negative', amount: -50 }),
  base({ id: 'exp_null_amount', amount: null }),
  base({ id: 'exp_missing_amount', amount: undefined }),
  base({ id: 'exp_tiny', amount: 0.004 }),

  // ── money ────────────────────────────────────────────────────────────
  base({ id: 'exp_round_half_even', amount: 2.675 }),
  base({ id: 'exp_round_tie', amount: 0.125 }),
  base({ id: 'exp_round_tie_up', amount: 0.375 }),
  base({ id: 'exp_round_below', amount: 1.005 }),
  base({ id: 'exp_paise', amount: 1234.56 }),
  base({ id: 'exp_string_amount', amount: '750.25' }),
  base({ id: 'exp_big', amount: 98765432.1 }),

  // ── narration: narration OR category OR "" ───────────────────────────
  base({ id: 'exp_narr_set', narration: 'Explicit note', category: 'fuel' }),
  base({ id: 'exp_narr_blank', narration: '', category: 'fuel' }),
  base({ id: 'exp_narr_missing', narration: undefined, category: 'fuel' }),
  base({ id: 'exp_narr_and_cat_blank', narration: '', category: '' }),
  base({ id: 'exp_narr_and_cat_missing', narration: undefined, category: undefined }),
  base({ id: 'exp_narr_long', narration: 'N'.repeat(500) }), // caps at 400
  // the CATEGORY field itself is NOT truncated, only the narration derived
  // from it — 500 characters must survive on `category`.
  base({ id: 'exp_cat_long', narration: '', category: 'C'.repeat(500) }),
  base({ id: 'exp_unicode', narration: 'ईंधन · 数 · ⛽', category: 'ईंधन' }),

  // ── denormalised fields ──────────────────────────────────────────────
  base({ id: 'exp_full_denorm', source_key: 'fastag:TXN123', party_type: 'vendor', party_id: 'ven_9', party_name: 'Vendor Nine', vehicle_id: 'veh_9', trip_id: 'trip_9' }),
  base({ id: 'exp_no_denorm', source_key: '', party_type: '', party_id: '', party_name: '', vehicle_id: '', trip_id: '' }),
  base({ id: 'exp_missing_denorm', source_key: undefined, party_type: undefined, party_id: undefined, party_name: undefined, vehicle_id: undefined, trip_id: undefined }),
  base({ id: 'exp_missing_date', date: undefined }),

  // ── a second tenant holding the SAME id ──────────────────────────────
  base({
    id: 'exp_settlement_recovery',
    user_id: UID2,
    company_id: CID2,
    amount: 4242,
    narration: 'OTHER',
    supplier_owned_vehicle: true,
    supplier_settlement_mode: 'supplier_settlement_adjustment',
  }),
];

/** Expected (credit account, txn_type) per fixture id. */
const EXPECTED: Record<string, [string, string]> = {
  exp_settlement_recovery: ['AP_SUPPLIER', 'expense_supplier_settlement_recovery'],
  exp_recovery_overrides_party: ['AP_SUPPLIER', 'expense_supplier_settlement_recovery'],
  exp_company_borne: ['CASH', 'expense_company_borne'],
  exp_fastag: ['WALLET_FASTAG', 'expense_fastag_toll'],
  exp_fleet_card: ['WALLET_FUEL', 'expense_fleet_diesel'],
  exp_vendor_bill: ['AP_VENDOR', 'expense_vendor_payable'],
  exp_work_order: ['AP_MECHANIC', 'expense_mechanic_payable'],
  exp_cash_now: ['CASH', 'expense_cash_now'],
  exp_unrouted: ['SUSPENSE', 'expense_unrouted'],
  exp_settlement_payable: ['SUSPENSE', 'expense_unrouted'],
  exp_settlement_missing: ['SUSPENSE', 'expense_unrouted'],
  exp_supp_other_mode: ['SUSPENSE', 'expense_unrouted'],
  exp_supp_other_mode_fastag: ['WALLET_FASTAG', 'expense_fastag_toll'],
  exp_supp_no_mode_vb: ['AP_VENDOR', 'expense_vendor_payable'],
  exp_supp_no_mode_cash: ['CASH', 'expense_cash_now'],
  exp_supp_string_false: ['CASH', 'expense_company_borne'],
  exp_supp_zero: ['SUSPENSE', 'expense_unrouted'],
  exp_supp_empty: ['SUSPENSE', 'expense_unrouted'],
  exp_supp_null: ['SUSPENSE', 'expense_unrouted'],
  exp_supp_one: ['CASH', 'expense_company_borne'],
  exp_prec_fastag_vb: ['WALLET_FASTAG', 'expense_fastag_toll'],
  exp_prec_vb_wo: ['AP_VENDOR', 'expense_vendor_payable'],
  exp_prec_wo_cash: ['AP_MECHANIC', 'expense_mechanic_payable'],
  exp_prec_recovery_beats_all: ['AP_SUPPLIER', 'expense_supplier_settlement_recovery'],
  exp_vb_nonstring: ['AP_VENDOR', 'expense_vendor_payable'],
  exp_vb_empty: ['SUSPENSE', 'expense_unrouted'],
  exp_wo_empty: ['SUSPENSE', 'expense_unrouted'],
};

void runProjectionParity({
  sourceType: 'expense',
  collection: 'expenses',
  slug: 'exp',
  nestPort: 8461,
  documents,
  zeroLegged: [
    'exp_deleted',
    'exp_reversed',
    'exp_historical',
    'exp_zero',
    'exp_negative',
    'exp_null_amount',
    'exp_missing_amount',
    'exp_tiny',
  ],
  sharedId: 'exp_settlement_recovery',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const of = (id: string): Doc[] =>
      rows
        .filter((r) => r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. Every routing rule lands on the account and txn_type it should.
    const wrong: string[] = [];
    for (const [id, [code, txnType]] of Object.entries(EXPECTED)) {
      const legs = of(id);
      const credit = legs.find((r) => r['account_code'] === code && r['direction'] === 'out');
      const debit = legs.find((r) => r['account_code'] === 'EXPENSE_DEFAULT');
      if (legs.length !== 2 || !credit || !debit || legs.some((r) => r['txn_type'] !== txnType)) {
        wrong.push(`${id} -> expected ${code}/${txnType}, got ${legs.map((r) => `${String(r['account_code'])}/${String(r['txn_type'])}`).join(' ')}`);
      }
    }
    report(wrong.length === 0, `all ${Object.keys(EXPECTED).length} routing rules land correctly`, wrong.slice(0, 4).join('\n        '));

    // 2. The credit leg's ref_leg is derived from the account code.
    const refOk = rows
      .filter((r) => r['direction'] === 'out')
      .every((r) => {
        const expected = `${String(r['account_code']).toLowerCase()}_credit`;
        return String(r['ref_source_key']).endsWith(`:${expected}`);
      });
    report(refOk, 'every credit leg uses a ref_leg derived from its account code');
    report(
      rows.filter((r) => r['direction'] === 'in').every((r) => String(r['ref_source_key']).endsWith(':expense_debit')),
      'every debit leg uses expense_debit',
    );

    // 3. is_supplier_settlement_recovery: credit leg of branch 1a ONLY.
    const flagged = rows.filter((r) => r['is_supplier_settlement_recovery'] === true);
    const expectedFlagged = new Set([
      'exp_settlement_recovery',
      'exp_recovery_overrides_party',
      'exp_prec_recovery_beats_all',
    ]);
    report(
      flagged.every((r) => expectedFlagged.has(String(r['source_id'])) && r['direction'] === 'out'),
      'only the credit leg of a settlement recovery carries the flag',
      flagged.map((r) => `${String(r['source_id'])}/${String(r['direction'])}`).join(', '),
    );
    report(
      of('exp_settlement_recovery').filter((r) => r['is_supplier_settlement_recovery'] === true).length === 1,
      'the DEBIT leg of a settlement recovery does not carry the flag',
    );

    // 4. party_type is forced to supplier on branch 1a, overriding the doc.
    report(
      of('exp_recovery_overrides_party').every((r) => r['party_type'] === 'supplier'),
      'a settlement recovery overrides the document party_type with "supplier"',
    );
    report(
      of('exp_recovery_overrides_party').every((r) => r['party_id'] === 'ven_1'),
      'but party_id and party_name are left exactly as denormalised',
    );

    // 5. narration is narration OR category OR "", capped at 400; the
    //    category field itself is NOT capped.
    report(of('exp_narr_blank')[0]?.['narration'] === 'fuel', 'a blank narration falls back to the category');
    report(of('exp_narr_missing')[0]?.['narration'] === 'fuel', 'an absent narration falls back too');
    report(of('exp_narr_and_cat_blank')[0]?.['narration'] === '', 'both blank gives an empty narration');
    report(String(of('exp_narr_long')[0]?.['narration']).length === 400, 'the narration caps at 400');
    report(
      String(of('exp_cat_long')[0]?.['narration']).length === 400 &&
        String(of('exp_cat_long')[0]?.['category']).length === 500,
      'a long category truncates only the NARRATION, never the category field',
    );

    // 6. source_key is carried — expense is the first projection that sets it.
    report(of('exp_full_denorm')[0]?.['source_key'] === 'fastag:TXN123', 'source_key is carried onto both legs');
    report(
      of('exp_no_denorm').every((r) => r['source_key'] === '' && r['party_id'] === '' && r['vehicle_id'] === ''),
      'blank denormalised fields stay empty strings',
    );

    // 7. Both legs of every projected expense share the amount and the debit
    //    side is always EXPENSE_DEFAULT.
    report(
      rows.filter((r) => r['direction'] === 'in').every((r) => r['account_code'] === 'EXPENSE_DEFAULT'),
      'the debit side is always EXPENSE_DEFAULT',
    );
    report(
      of('exp_round_half_even').every((r) => r['amount'] === 2.67),
      'a 2.675 expense projects as 2.67 on both legs',
    );

    report(
      rows.every((r) => {
        const expected = `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
        return r['id'] === expected;
      }),
      'fin_txn ids follow the ref_source_key rule, truncated at 60',
    );
  },
});
