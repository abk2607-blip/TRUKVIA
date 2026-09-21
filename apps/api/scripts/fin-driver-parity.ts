/**
 * Focused parity for slice 2c unit 4 — the `driver_payment` projection.
 *
 *   npx tsx scripts/fin-driver-parity.ts
 *
 * The orchestration lives in ./lib/party-payment-parity.ts. Two things make
 * this run different from the mechanic and supplier ones:
 *
 *   1. `verifyRouting` is on. driver_payment is reached through the Iter150I
 *      monkey-patched `reproject_source`, so the risk here is routing rather
 *      than ledger maths: a counting proxy measures that EACH entry point —
 *      the hook, and reproject_source called directly — delegates exactly
 *      once, writes exactly two legs, and lands on identical rows.
 *
 *   2. DRIVER_OUTFLOW is the account behind the 13-vs-14 fin_accounts split.
 *      A scope without it gets it seeded by the projection, on both sides.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runPartyPaymentParity, type Doc } from './lib/party-payment-parity';

const UID = 'user_drvparity';
const CID = 'co_drvparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_drvparity_other';
const CID2 = 'co_drvparity_other';

const base = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  driver_id: 'drv_1',
  date: '2026-09-02',
  amount: 1000,
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'DP-001',
  is_deleted: false,
  is_reversed: false,
  ...over,
});

const documents: Doc[] = [
  base({ id: 'dpay_out_bank' }),
  base({ id: 'dpay_out_cash', mode: 'Cash' }),
  base({ id: 'dpay_out_upi', mode: 'UPI' }),
  base({ id: 'dpay_out_neft', mode: 'NEFT' }),
  base({ id: 'dpay_out_unknown_mode', mode: 'Crypto' }), // -> BANK_DEFAULT
  base({ id: 'dpay_out_blank_mode', mode: '' }), // falsy -> "Bank"
  base({ id: 'dpay_out_missing_mode', mode: undefined }),
  base({ id: 'dpay_in_receipt', type: 'receipt_in' }),
  base({ id: 'dpay_in_receipt_cash', type: 'receipt_in', mode: 'Cash' }),
  base({ id: 'dpay_missing_type', type: undefined }), // -> payment_out
  base({ id: 'dpay_blank_type', type: '' }), // falsy -> payment_out
  base({ id: 'dpay_unknown_type', type: 'refund' }), // not payment_out -> receipt branch
  // guards: each must project ZERO legs
  base({ id: 'dpay_deleted', is_deleted: true }),
  base({ id: 'dpay_reversed', is_reversed: true }),
  base({ id: 'dpay_zero', amount: 0 }),
  base({ id: 'dpay_negative', amount: -50 }),
  base({ id: 'dpay_null_amount', amount: null }),
  base({ id: 'dpay_missing_amount', amount: undefined }),
  base({ id: 'dpay_tiny', amount: 0.004 }), // rounds to 0.0 -> zero legs
  // driver_payment has NO is_historical guard — this one must still project
  base({ id: 'dpay_historical', is_historical: true }),
  // money semantics
  base({ id: 'dpay_round_half_even', amount: 2.675 }), // Python round() -> 2.67
  base({ id: 'dpay_round_tie', amount: 0.125 }), // exact tie -> 0.12
  base({ id: 'dpay_round_tie_up', amount: 0.375 }), // exact tie -> 0.38
  base({ id: 'dpay_round_below', amount: 1.005 }), // -> 1.0
  base({ id: 'dpay_paise', amount: 1234.56 }),
  base({ id: 'dpay_string_amount', amount: '750.25' }),
  base({ id: 'dpay_big', amount: 98765432.1 }),
  // narration and party edges
  base({ id: 'dpay_no_ref', ref_no: '' }), // strip(" ·") eats the separator
  base({ id: 'dpay_missing_ref', ref_no: undefined }),
  base({ id: 'dpay_long_ref', ref_no: 'R'.repeat(500) }), // narration caps at 400
  base({ id: 'dpay_unicode_ref', ref_no: 'ref · चालक · 数' }),
  base({ id: 'dpay_no_driver', driver_id: '' }),
  base({ id: 'dpay_missing_driver', driver_id: undefined }),
  base({ id: 'dpay_missing_date', date: undefined }),
  // trip_id must be ignored: only supplier_payment carries it
  base({ id: 'dpay_with_trip', trip_id: 'trip_9' }),
  // a second tenant holding the SAME id, to prove scoping
  base({ id: 'dpay_out_bank', user_id: UID2, company_id: CID2, amount: 4242, ref_no: 'OTHER' }),
];

void runPartyPaymentParity({
  sourceType: 'driver_payment',
  collection: 'driver_payments',
  slug: 'drv',
  nestPort: 8441,
  documents,
  zeroLegged: [
    'dpay_deleted',
    'dpay_reversed',
    'dpay_zero',
    'dpay_negative',
    'dpay_null_amount',
    'dpay_missing_amount',
    'dpay_tiny',
  ],
  sharedId: 'dpay_out_bank',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    // The payable account is DRIVER_OUTFLOW, not an AP_* code.
    const out = rows
      .filter((r) => r['source_id'] === 'dpay_out_bank' && r['user_id'] === UID)
      .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));
    report(
      JSON.stringify(out.map((r) => [r['ref_source_key'], r['account_code'], r['direction'], r['txn_type']])) ===
        JSON.stringify([
          ['driver_payment:dpay_out_bank:ap_debit', 'DRIVER_OUTFLOW', 'in', 'driver_payment_out'],
          ['driver_payment:dpay_out_bank:bank_credit', 'BANK_DEFAULT', 'out', 'driver_payment_out'],
        ]),
      'payment_out uses DRIVER_OUTFLOW with the documented ref_source_key, order and txn_type',
    );

    // No is_historical guard on this source type — the opposite of supplier.
    report(
      rows.filter((r) => r['source_id'] === 'dpay_historical').length === 2,
      'a historical driver payment still projects',
    );

    // trip_id belongs to supplier_payment alone.
    report(
      rows.every((r) => r['trip_id'] === ''),
      'driver legs carry no trip_id, even when the source document has one',
    );

    report(
      rows.every((r) => r['party_type'] === 'driver'),
      'every leg carries party_type "driver"',
    );

    report(
      rows.every((r) => {
        const expected = `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
        return r['id'] === expected;
      }),
      'fin_txn ids follow the ref_source_key rule, truncated at 60',
    );

    report(
      rows.find((r) => r['source_id'] === 'dpay_round_half_even')?.['amount'] === 2.67,
      'a 2.675 driver payment projects as 2.67, not 2.68',
    );
  },
});
