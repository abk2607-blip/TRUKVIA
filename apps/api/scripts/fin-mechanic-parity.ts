/**
 * Focused parity for slice 2c unit 2 — the `mechanic_payment` projection.
 *
 *   npx tsx scripts/fin-mechanic-parity.ts
 *
 * The orchestration lives in ./lib/projection-parity.ts; this file is only
 * the fixtures. They target the guards and the edges, not the happy path:
 * every branch of _party_payment_legs, both directions, every account-resolving
 * mode including an unknown one, the rounding rule, and the narration strip.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_mechparity';
const CID = 'co_mechparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_mechparity_other';
const CID2 = 'co_mechparity_other';

const base = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  mechanic_id: 'mech_1',
  date: '2026-09-02',
  amount: 1000,
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'MP-001',
  is_deleted: false,
  is_reversed: false,
  ...over,
});

const documents: Doc[] = [
  base({ id: 'mpay_out_bank' }),
  base({ id: 'mpay_out_cash', mode: 'Cash' }),
  base({ id: 'mpay_out_upi', mode: 'UPI' }),
  base({ id: 'mpay_out_unknown_mode', mode: 'Crypto' }), // -> BANK_DEFAULT
  base({ id: 'mpay_out_blank_mode', mode: '' }), // falsy -> "Bank"
  base({ id: 'mpay_out_missing_mode', mode: undefined }),
  base({ id: 'mpay_in_receipt', type: 'receipt_in' }),
  base({ id: 'mpay_in_receipt_cash', type: 'receipt_in', mode: 'Cash' }),
  base({ id: 'mpay_missing_type', type: undefined }), // -> payment_out
  base({ id: 'mpay_blank_type', type: '' }), // falsy -> payment_out
  base({ id: 'mpay_unknown_type', type: 'refund' }), // not payment_out -> receipt branch
  // guards: each must project ZERO legs
  base({ id: 'mpay_deleted', is_deleted: true }),
  base({ id: 'mpay_reversed', is_reversed: true }),
  base({ id: 'mpay_zero', amount: 0 }),
  base({ id: 'mpay_negative', amount: -50 }),
  base({ id: 'mpay_null_amount', amount: null }),
  base({ id: 'mpay_missing_amount', amount: undefined }),
  // mechanic_payment has NO is_historical guard — this one must still project
  base({ id: 'mpay_historical', is_historical: true }),
  // money semantics
  base({ id: 'mpay_round_half_even', amount: 2.675 }), // Python round() -> 2.67
  base({ id: 'mpay_round_tie', amount: 0.125 }), // exact tie -> 0.12
  base({ id: 'mpay_paise', amount: 1234.56 }),
  base({ id: 'mpay_string_amount', amount: '750.25' }),
  base({ id: 'mpay_big', amount: 98765432.1 }),
  // narration and party edges
  base({ id: 'mpay_no_ref', ref_no: '' }), // strip(" ·") eats the separator
  base({ id: 'mpay_missing_ref', ref_no: undefined }),
  base({ id: 'mpay_long_ref', ref_no: 'R'.repeat(500) }), // narration caps at 400
  base({ id: 'mpay_unicode_ref', ref_no: 'ref · भुगतान · 数' }),
  base({ id: 'mpay_no_mechanic', mechanic_id: '' }),
  base({ id: 'mpay_missing_mechanic', mechanic_id: undefined }),
  base({ id: 'mpay_missing_date', date: undefined }),
  // a second tenant holding the SAME id, to prove scoping
  base({ id: 'mpay_out_bank', user_id: UID2, company_id: CID2, amount: 4242, ref_no: 'OTHER' }),
];

void runProjectionParity({
  sourceType: 'mechanic_payment',
  collection: 'mechanic_payments',
  slug: 'mech',
  nestPort: 8421,
  documents,
  zeroLegged: [
    'mpay_deleted',
    'mpay_reversed',
    'mpay_zero',
    'mpay_negative',
    'mpay_null_amount',
    'mpay_missing_amount',
  ],
  sharedId: 'mpay_out_bank',
  extraChecks: (rows, report) => {
    // _party_payment_legs has NO is_historical guard; only the supplier
    // projection does. A shared helper that grew one would break this.
    const historical = rows.filter((r) => r['source_id'] === 'mpay_historical');
    report(historical.length === 2, 'a historical mechanic payment still projects');
    // The helper never sets trip_id for mechanic payments.
    report(
      rows.every((r) => r['trip_id'] === ''),
      'mechanic legs carry no trip_id',
    );
  },
});
