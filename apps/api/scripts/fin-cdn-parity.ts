/**
 * Focused parity for slice 2c unit 5 — the `credit_debit_note` projection.
 *
 *   npx tsx scripts/fin-cdn-parity.ts
 *
 * The orchestration lives in ./lib/projection-parity.ts. This is the first
 * NON party-payment projection, so the fixtures target what is genuinely
 * different rather than re-running the party-payment matrix:
 *
 *   • both legs are the fixed pair AR/SALES — there is no `mode` and no bank
 *     account resolution at all;
 *   • the guards are `status != "issued"` and `is_historical`; there is no
 *     is_deleted or is_reversed, because those fields do not exist on the
 *     model and a cancelled note carries status "cancelled";
 *   • the amount field is `total_amount` and the date field is `note_date`;
 *   • `kind` selects by `== "credit"`, so falsy defaults to credit and ANY
 *     other value takes the debit branch;
 *   • the narration is NOT stripped, unlike every projection before it.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_cdnparity';
const CID = 'co_cdnparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_cdnparity_other';
const CID2 = 'co_cdnparity_other';

const base = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  kind: 'credit',
  status: 'issued',
  total_amount: 1000,
  note_date: '2026-09-02',
  customer_id: 'cust_1',
  note_number: 'CN-001',
  invoice_number_snapshot: 'INV-9',
  invoice_id: 'inv_1',
  is_historical: false,
  ...over,
});

const documents: Doc[] = [
  // both branches
  base({ id: 'cdn_credit' }),
  base({ id: 'cdn_debit', kind: 'debit', note_number: 'DN-001' }),
  // kind resolution: falsy -> credit, anything else -> debit
  base({ id: 'cdn_kind_blank', kind: '' }),
  base({ id: 'cdn_kind_missing', kind: undefined }),
  base({ id: 'cdn_kind_null', kind: null }),
  base({ id: 'cdn_kind_unknown', kind: 'weird' }), // -> debit branch
  base({ id: 'cdn_kind_uppercase', kind: 'CREDIT' }), // -> debit branch, not credit
  // Truthy NON-strings survive `or "credit"` and then fail `== "credit"`,
  // so Python takes the debit branch. Coercing to a string first would have
  // flipped the sign of the note.
  base({ id: 'cdn_kind_number', kind: 5 }),
  base({ id: 'cdn_kind_true', kind: true }),
  base({ id: 'cdn_kind_list', kind: ['x'] }),
  // ...while EMPTY containers are falsy in Python and default to credit.
  base({ id: 'cdn_kind_empty_list', kind: [] }),
  // status guard — the only way a note is withdrawn
  base({ id: 'cdn_draft', status: 'draft' }),
  base({ id: 'cdn_cancelled', status: 'cancelled' }),
  base({ id: 'cdn_status_blank', status: '' }),
  base({ id: 'cdn_status_missing', status: undefined }),
  base({ id: 'cdn_status_issued_upper', status: 'ISSUED' }), // != "issued" -> skipped
  // historical guard
  base({ id: 'cdn_historical', is_historical: true }),
  base({ id: 'cdn_historical_falsy', is_historical: 0 }), // falsy -> still projects
  base({ id: 'cdn_historical_missing', is_historical: undefined }),
  // amount guards — note the field is total_amount, not amount
  base({ id: 'cdn_zero', total_amount: 0 }),
  base({ id: 'cdn_negative', total_amount: -500 }),
  base({ id: 'cdn_null_amount', total_amount: null }),
  base({ id: 'cdn_missing_amount', total_amount: undefined }),
  base({ id: 'cdn_tiny', total_amount: 0.004 }), // rounds to 0.0 -> zero legs
  // an `amount` field must be ignored entirely
  base({ id: 'cdn_wrong_amount_field', amount: 9999, total_amount: 250 }),
  // midpoint rounding
  base({ id: 'cdn_round_half_even', total_amount: 2.675 }), // Python round() -> 2.67
  base({ id: 'cdn_round_tie', total_amount: 0.125 }), // exact tie -> 0.12
  base({ id: 'cdn_round_tie_up', total_amount: 0.375 }), // exact tie -> 0.38
  base({ id: 'cdn_round_below', total_amount: 1.005 }), // -> 1.0
  base({ id: 'cdn_paise', total_amount: 1234.56 }),
  base({ id: 'cdn_string_amount', total_amount: '750.25' }),
  base({ id: 'cdn_big', total_amount: 98765432.1 }),
  // narration — NOT stripped, so the separator survives
  base({ id: 'cdn_no_number', note_number: '', invoice_number_snapshot: '' }),
  base({ id: 'cdn_missing_number', note_number: undefined, invoice_number_snapshot: undefined }),
  // A PRESENT null on either field renders as the literal "None" — the
  // f-string default applies only to an ABSENT key. Slice 2c step 7.
  base({ id: 'cdn_null_number', note_number: null }),
  base({ id: 'cdn_null_invoice', invoice_number_snapshot: null }),
  base({ id: 'cdn_null_both', note_number: null, invoice_number_snapshot: null }),
  base({ id: 'cdn_no_invoice_snap', invoice_number_snapshot: '' }),
  base({ id: 'cdn_long_number', note_number: 'N'.repeat(500) }), // narration caps at 400
  base({ id: 'cdn_unicode', note_number: 'क्रेडिट · 数', invoice_number_snapshot: 'चालान' }),
  // party and date edges
  base({ id: 'cdn_no_customer', customer_id: '' }),
  base({ id: 'cdn_missing_customer', customer_id: undefined }),
  base({ id: 'cdn_missing_date', note_date: undefined }),
  // a second tenant holding the SAME id, to prove scoping
  base({
    id: 'cdn_credit',
    user_id: UID2,
    company_id: CID2,
    total_amount: 4242,
    note_number: 'OTHER',
  }),
];

void runProjectionParity({
  sourceType: 'credit_debit_note',
  collection: 'credit_debit_notes',
  slug: 'cdn',
  nestPort: 8451,
  documents,
  zeroLegged: [
    'cdn_draft',
    'cdn_cancelled',
    'cdn_status_blank',
    'cdn_status_missing',
    'cdn_status_issued_upper',
    'cdn_historical',
    'cdn_zero',
    'cdn_negative',
    'cdn_null_amount',
    'cdn_missing_amount',
    'cdn_tiny',
  ],
  sharedId: 'cdn_credit',
  extraChecks: (rows, report) => {
    const of = (id: string): Doc[] =>
      rows
        .filter((r) => r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 0. The f-string fields: an ABSENT key takes the "" default, a PRESENT
    //    null renders as the literal "None". Slice 2c step 7.
    report(
      String(of('cdn_null_number')[0]?.['narration']) === 'CN None · Inv INV-9',
      'a null note_number interpolates as the literal "None"',
      JSON.stringify(of('cdn_null_number')[0]?.['narration']),
    );
    report(
      String(of('cdn_null_invoice')[0]?.['narration']) === 'CN CN-001 · Inv None',
      'a null invoice_number_snapshot interpolates as the literal "None"',
      JSON.stringify(of('cdn_null_invoice')[0]?.['narration']),
    );
    report(
      String(of('cdn_null_both')[0]?.['narration']) === 'CN None · Inv None',
      'both nulls render together',
      JSON.stringify(of('cdn_null_both')[0]?.['narration']),
    );
    report(
      String(of('cdn_missing_number')[0]?.['narration']) === 'CN  · Inv ',
      'an ABSENT key still takes the "" default, spacing and all',
      JSON.stringify(of('cdn_missing_number')[0]?.['narration']),
    );

    // 1. A credit note REVERSES the receivable; a debit note adds to it.
    report(
      JSON.stringify(
        of('cdn_credit').map((r) => [r['ref_source_key'], r['account_code'], r['direction'], r['txn_type']]),
      ) ===
        JSON.stringify([
          ['credit_debit_note:cdn_credit:ar_credit', 'AR', 'out', 'credit_note_issue'],
          ['credit_debit_note:cdn_credit:sales_debit', 'SALES', 'in', 'credit_note_issue'],
        ]),
      'a credit note debits SALES and credits AR, with the documented ref_source_key',
    );
    report(
      JSON.stringify(
        of('cdn_debit').map((r) => [r['ref_source_key'], r['account_code'], r['direction'], r['txn_type']]),
      ) ===
        JSON.stringify([
          ['credit_debit_note:cdn_debit:ar_debit', 'AR', 'in', 'debit_note_issue'],
          ['credit_debit_note:cdn_debit:sales_credit', 'SALES', 'out', 'debit_note_issue'],
        ]),
      'a debit note is the exact mirror',
    );

    // 2. kind resolution, both directions.
    const creditish = ['cdn_kind_blank', 'cdn_kind_missing', 'cdn_kind_null', 'cdn_kind_empty_list'];
    report(
      creditish.every((id) => of(id).every((r) => r['txn_type'] === 'credit_note_issue')),
      'a falsy kind defaults to credit',
    );
    const debitish = ['cdn_kind_unknown', 'cdn_kind_uppercase', 'cdn_kind_number', 'cdn_kind_true', 'cdn_kind_list'];
    report(
      debitish.every((id) => of(id).every((r) => r['txn_type'] === 'debit_note_issue')),
      'any kind other than exactly "credit" takes the debit branch',
    );

    // 3. The narration is NOT stripped — this is the trap.
    report(
      of('cdn_no_number')[0]?.['narration'] === 'CN  · Inv ',
      'an empty note number leaves "CN  · Inv " intact, separator and all',
      `got ${JSON.stringify(of('cdn_no_number')[0]?.['narration'])}`,
    );
    report(
      of('cdn_missing_number')[0]?.['narration'] === 'CN  · Inv ',
      'an absent note number behaves the same as an empty one',
    );
    report(
      String(of('cdn_long_number')[0]?.['narration']).length === 400,
      'the narration still truncates at 400 characters',
    );

    // 4. The amount comes from total_amount; a stray `amount` is ignored.
    report(
      of('cdn_wrong_amount_field').every((r) => r['amount'] === 250),
      'the projection reads total_amount, never a stray amount field',
    );
    report(
      of('cdn_round_half_even').every((r) => r['amount'] === 2.67),
      'a 2.675 note projects as 2.67, not 2.68',
    );

    // 5. No money side at all: no mode, no bank account, no trip or vehicle.
    report(
      rows.every((r) => r['account_code'] === 'AR' || r['account_code'] === 'SALES'),
      'every leg touches only AR and SALES',
    );
    report(
      rows.every((r) => r['party_type'] === 'customer' && r['trip_id'] === '' && r['vehicle_id'] === ''),
      'every leg is a customer leg with no trip or vehicle',
    );

    // 6. The shared id rule.
    report(
      rows.every((r) => {
        const expected = `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
        return r['id'] === expected;
      }),
      'fin_txn ids follow the ref_source_key rule, truncated at 60',
    );
  },
});
