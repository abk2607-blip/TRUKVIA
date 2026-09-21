/**
 * Focused parity for slice 2c unit 3 — the `supplier_payment` projection.
 *
 *   npx tsx scripts/fin-supplier-parity.ts
 *
 * The orchestration lives in ./lib/party-payment-parity.ts. These fixtures
 * cover the same ground as the mechanic run PLUS the two things that make
 * supplier_payment genuinely different from _party_payment_legs:
 *
 *   1. an extra `is_historical` guard;
 *   2. `trip_id` carried on every leg.
 *
 * Both are asserted explicitly, in both the positive and the negative, because
 * they are the only places a shared helper could silently get it wrong.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runPartyPaymentParity, type Doc } from './lib/party-payment-parity';

const UID = 'user_supparity';
const CID = 'co_supparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_supparity_other';
const CID2 = 'co_supparity_other';

const base = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  supplier_id: 'sup_1',
  date: '2026-09-02',
  amount: 1000,
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'SP-001',
  trip_id: 'trip_1',
  is_deleted: false,
  is_reversed: false,
  is_historical: false,
  ...over,
});

const documents: Doc[] = [
  base({ id: 'sp_out_bank' }),
  base({ id: 'sp_out_cash', mode: 'Cash' }),
  base({ id: 'sp_out_upi', mode: 'UPI' }),
  base({ id: 'sp_out_imps', mode: 'IMPS' }),
  base({ id: 'sp_out_cheque', mode: 'Cheque' }),
  base({ id: 'sp_out_unknown_mode', mode: 'Crypto' }), // -> BANK_DEFAULT
  base({ id: 'sp_out_blank_mode', mode: '' }), // falsy -> "Bank"
  base({ id: 'sp_out_missing_mode', mode: undefined }),
  base({ id: 'sp_in_receipt', type: 'receipt_in' }),
  base({ id: 'sp_in_receipt_cash', type: 'receipt_in', mode: 'Cash' }),
  base({ id: 'sp_missing_type', type: undefined }), // -> payment_out
  base({ id: 'sp_blank_type', type: '' }), // falsy -> payment_out
  base({ id: 'sp_unknown_type', type: 'refund' }), // not payment_out -> receipt branch
  // guards: each must project ZERO legs
  base({ id: 'sp_deleted', is_deleted: true }),
  base({ id: 'sp_reversed', is_reversed: true }),
  // THE supplier-specific guard — mechanic and vendor do not have it
  base({ id: 'sp_historical', is_historical: true }),
  base({ id: 'sp_historical_and_receipt', is_historical: true, type: 'receipt_in' }),
  base({ id: 'sp_zero', amount: 0 }),
  base({ id: 'sp_negative', amount: -50 }),
  base({ id: 'sp_null_amount', amount: null }),
  base({ id: 'sp_missing_amount', amount: undefined }),
  // a falsy-but-present is_historical must NOT skip
  base({ id: 'sp_historical_false_zero', is_historical: 0 }),
  base({ id: 'sp_historical_missing', is_historical: undefined }),
  // money semantics
  base({ id: 'sp_round_half_even', amount: 2.675 }), // Python round() -> 2.67
  base({ id: 'sp_round_tie', amount: 0.125 }), // exact tie -> 0.12
  base({ id: 'sp_round_tie_up', amount: 0.375 }), // exact tie -> 0.38
  base({ id: 'sp_round_below', amount: 1.005 }), // -> 1.0
  base({ id: 'sp_paise', amount: 1234.56 }),
  base({ id: 'sp_string_amount', amount: '750.25' }),
  base({ id: 'sp_big', amount: 98765432.1 }),
  base({ id: 'sp_tiny', amount: 0.004 }), // rounds to 0.0 -> zero legs
  // narration and party edges
  base({ id: 'sp_no_ref', ref_no: '' }), // strip(" ·") eats the separator
  base({ id: 'sp_missing_ref', ref_no: undefined }),
  base({ id: 'sp_long_ref', ref_no: 'R'.repeat(500) }), // narration caps at 400
  base({ id: 'sp_unicode_ref', ref_no: 'ref · आपूर्ति · 数' }),
  base({ id: 'sp_no_supplier', supplier_id: '' }),
  base({ id: 'sp_missing_supplier', supplier_id: undefined }),
  base({ id: 'sp_missing_date', date: undefined }),
  // trip_id is supplier-specific: present, blank and absent must all round-trip
  base({ id: 'sp_no_trip', trip_id: '' }),
  base({ id: 'sp_missing_trip', trip_id: undefined }),
  // a second tenant holding the SAME id, to prove scoping
  base({ id: 'sp_out_bank', user_id: UID2, company_id: CID2, amount: 4242, ref_no: 'OTHER' }),
];

void runPartyPaymentParity({
  sourceType: 'supplier_payment',
  collection: 'supplier_payments',
  slug: 'sup',
  nestPort: 8431,
  documents,
  zeroLegged: [
    'sp_deleted',
    'sp_reversed',
    'sp_historical',
    'sp_historical_and_receipt',
    'sp_zero',
    'sp_negative',
    'sp_null_amount',
    'sp_missing_amount',
    'sp_tiny',
  ],
  sharedId: 'sp_out_bank',
  extraChecks: (rows, report) => {
    // 1. The supplier-specific is_historical guard, in both directions.
    const hist = rows.filter((r) => String(r['source_id']).startsWith('sp_historical'));
    const skipped = hist.filter((r) => ['sp_historical', 'sp_historical_and_receipt'].includes(String(r['source_id'])));
    report(skipped.length === 0, 'a historical supplier payment projects nothing');
    const falsy = rows.filter((r) =>
      ['sp_historical_false_zero', 'sp_historical_missing'].includes(String(r['source_id'])),
    );
    report(falsy.length === 4, 'a falsy or absent is_historical still projects');

    // 2. trip_id, which _party_payment_legs never sets.
    const tripped = rows.filter((r) => r['source_id'] === 'sp_out_bank' && r['user_id'] === 'user_supparity');
    report(
      tripped.length === 2 && tripped.every((r) => r['trip_id'] === 'trip_1'),
      'supplier legs carry trip_id',
    );
    const noTrip = rows.filter((r) => ['sp_no_trip', 'sp_missing_trip'].includes(String(r['source_id'])));
    report(
      noTrip.length === 4 && noTrip.every((r) => r['trip_id'] === ''),
      'a blank or absent trip_id becomes an empty string',
    );

    // 3. The fixed payable account and the leg order.
    const out = rows
      .filter((r) => r['source_id'] === 'sp_out_bank' && r['user_id'] === 'user_supparity')
      .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));
    report(
      JSON.stringify(out.map((r) => [r['ref_source_key'], r['account_code'], r['direction']])) ===
        JSON.stringify([
          ['supplier_payment:sp_out_bank:ap_debit', 'AP_SUPPLIER', 'in'],
          ['supplier_payment:sp_out_bank:bank_credit', 'BANK_DEFAULT', 'out'],
        ]),
      'payment_out uses AP_SUPPLIER with the documented ref_source_key and order',
    );

    // 4. Generated fin_txn ids: fintxn_ + ref_source_key, ":" -> "_", cap 60.
    const idsOk = rows.every((r) => {
      const expected = `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
      return r['id'] === expected;
    });
    report(idsOk, 'fin_txn ids follow the ref_source_key rule, truncated at 60');

    // 5. The party is the supplier on every leg.
    report(
      rows.every((r) => r['party_type'] === 'supplier'),
      'every leg carries party_type "supplier"',
    );
  },
});
