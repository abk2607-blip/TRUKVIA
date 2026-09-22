/**
 * Slice 2c step 6 — the reverse-bridge switch, `vendor_payment` half.
 *
 *   npx tsx scripts/fin-vendorpay-bridge-parity.ts
 *
 * vendor_payment was the FIRST projection ported, back when the bridge only
 * ran forward (NestJS -> Python). Its ledger mathematics are already verified
 * against real restored production data by scripts/fin-projection-parity.ts
 * and are deliberately NOT touched here.
 *
 * What is unverified is the direction. Every later unit was built with the
 * reverse bridge in place and proved it as it went; vendor_payment never was.
 * This script closes that gap, using the same runner and therefore the same
 * standard of proof as units 2–12:
 *
 *   - Python native vs the NestJS port, byte-exact on fin_txn
 *   - Python delegating through the reverse bridge vs Python native
 *   - delegation OFF for a type not in the list, and OFF with no env at all
 *   - a well-formed ok=false does NOT fall back and double-handle
 *   - an unreachable NestJS DOES fall back, so the ledger is never stale
 *   - exactly one bridge call from EACH entry point — hook and reproject
 *   - every document reprojected twice, so no duplicate row can hide
 *
 * `preProject` runs vendor_bill first under a DIFFERENT owner on each of the
 * three databases. vendor_bill and vendor_payment both touch AP_VENDOR, so
 * "mixed Python/NestJS ownership is safe" is measured here rather than argued.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_vpbridge';
const CID = 'co_vpbridge';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_vpbridge_other';
const CID2 = 'co_vpbridge_other';

const vp = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  vendor_id: 'vend_1',
  amount: 1000,
  date: '2026-09-02',
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'VP-1',
  is_deleted: false,
  ...over,
});

/**
 * vendor_bill documents for the pre-projection. They are deliberately ORPHANS
 * — no paired expense is seeded — so they project real AP_VENDOR legs and the
 * mixed-ownership question is a live one rather than a vacuous one.
 */
const vendor_bills: Doc[] = [
  {
    id: 'vb_pre_a',
    user_id: UID,
    company_id: CID,
    vendor_id: 'vend_1',
    vendor_name: 'Vend One',
    bill_amount: 500,
    bill_date: '2026-09-01',
    bill_number: 'VB-PRE-A',
    is_deleted: false,
  },
  {
    id: 'vb_pre_b',
    user_id: UID,
    company_id: CID,
    vendor_id: 'vend_2',
    vendor_name: 'Vend Two',
    bill_amount: 2.675,
    bill_date: '2026-09-01',
    bill_number: 'VB-PRE-B',
    is_deleted: false,
  },
];

const documents: Doc[] = [
  // ── the two directions ───────────────────────────────────────────────
  vp({ id: 'vp_out' }),
  vp({ id: 'vp_in', type: 'receipt_in', ref_no: 'VP-IN' }),
  // An unknown type falls through to the payment_out branch, because the
  // branch tests for equality with "payment_out" only on a defaulted value.
  vp({ id: 'vp_type_blank', type: '' }),
  vp({ id: 'vp_type_missing', type: undefined }),
  vp({ id: 'vp_type_odd', type: 'something_else' }),

  // ── every payment mode ───────────────────────────────────────────────
  vp({ id: 'vp_cash', mode: 'Cash' }),
  vp({ id: 'vp_upi', mode: 'UPI' }),
  vp({ id: 'vp_cheque', mode: 'Cheque' }),
  vp({ id: 'vp_mode_blank', mode: '' }),
  vp({ id: 'vp_mode_missing', mode: undefined }),
  vp({ id: 'vp_mode_null', mode: null }),

  // ── guards ───────────────────────────────────────────────────────────
  vp({ id: 'vp_deleted', is_deleted: true }),
  vp({ id: 'vp_reversed', is_reversed: true }),
  vp({ id: 'vp_deleted_falsy', is_deleted: 0 }),
  // vendor_payment does NOT skip historical — only supplier_payment does.
  vp({ id: 'vp_historical', is_historical: true }),
  vp({ id: 'vp_zero', amount: 0 }),
  vp({ id: 'vp_negative', amount: -50 }),
  vp({ id: 'vp_null_amount', amount: null }),
  vp({ id: 'vp_missing_amount', amount: undefined }),
  vp({ id: 'vp_tiny', amount: 0.004 }),

  // ── money, including the half-to-even ties ───────────────────────────
  vp({ id: 'vp_round', amount: 2.675 }),
  vp({ id: 'vp_tie', amount: 0.125 }),
  vp({ id: 'vp_tie_up', amount: 0.375 }),
  vp({ id: 'vp_below', amount: 1.005 }),
  vp({ id: 'vp_string_amt', amount: '750.25' }),
  vp({ id: 'vp_big', amount: 98765432.1 }),

  // ── narration stripping ──────────────────────────────────────────────
  vp({ id: 'vp_no_ref', ref_no: '' }),
  vp({ id: 'vp_null_ref', ref_no: null }),
  vp({ id: 'vp_missing_ref', ref_no: undefined }),
  vp({ id: 'vp_dotted_ref', ref_no: ' · · ' }),
  vp({ id: 'vp_missing_date', date: undefined }),
  vp({ id: 'vp_missing_vendor', vendor_id: undefined }),

  // ── a second tenant holding the SAME id ──────────────────────────────
  vp({ id: 'vp_out', user_id: UID2, company_id: CID2, amount: 4242 }),
];

void runProjectionParity({
  sourceType: 'vendor_payment',
  collection: 'vendor_payments',
  slug: 'vpbridge',
  nestPort: 8531,
  documents,
  extraCollections: { vendor_bills },
  // vendor_bill is projected FIRST, by a different owner on each database.
  preProject: {
    sourceType: 'vendor_bill',
    ids: vendor_bills.map(
      (b) => [String(b['id']), String(b['user_id']), String(b['company_id'])] as [string, string, string],
    ),
  },
  zeroLegged: [
    'vp_deleted',
    'vp_reversed',
    'vp_zero',
    'vp_negative',
    'vp_null_amount',
    'vp_missing_amount',
    'vp_tiny',
  ],
  sharedId: 'vp_out',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const of = (id: string): Doc[] =>
      rows
        .filter((r) => r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. The leg shape, which must be exactly what it was before step 6.
    report(
      JSON.stringify(of('vp_out').map((r) => [r['ref_source_key'], r['account_code'], r['direction']])) ===
        JSON.stringify([
          ['vendor_payment:vp_out:ap_debit', 'AP_VENDOR', 'in'],
          ['vendor_payment:vp_out:bank_credit', 'BANK_DEFAULT', 'out'],
        ]),
      'payment_out debits AP_VENDOR and credits the bank',
    );
    report(
      JSON.stringify(of('vp_in').map((r) => [r['ref_source_key'], r['account_code'], r['direction']])) ===
        JSON.stringify([
          ['vendor_payment:vp_in:ap_credit', 'AP_VENDOR', 'out'],
          ['vendor_payment:vp_in:bank_debit', 'BANK_DEFAULT', 'in'],
        ]),
      'receipt_in reverses both legs',
    );
    report(
      of('vp_out').every((r) => r['txn_type'] === 'vendor_payment_out') &&
        of('vp_in').every((r) => r['txn_type'] === 'vendor_receipt_in'),
      'the txn_type follows the direction',
    );

    // 2. The default branch. An unknown or blank type is NOT receipt_in.
    report(
      ['vp_type_blank', 'vp_type_missing'].every((id) =>
        of(id).every((r) => r['txn_type'] === 'vendor_payment_out'),
      ),
      'a blank or absent type defaults to payment_out',
    );
    report(
      of('vp_type_odd').every((r) => r['txn_type'] === 'vendor_receipt_in'),
      'any type that is not literally "payment_out" takes the receipt branch',
    );

    // 3. Guards this projection does NOT have.
    report(
      of('vp_historical').length === 2,
      'is_historical is NOT a guard for vendor_payment — only supplier_payment skips it',
    );
    report(of('vp_deleted_falsy').length === 2, 'a falsy is_deleted still projects');

    // 4. Narration stripping — strip(" ·") removes ALL leading and trailing
    //    spaces and middots, not one suffix.
    report(
      String(of('vp_out')[0]?.['narration']) === 'Vendor payment_out · VP-1',
      'the narration names the party, the type and the reference',
      JSON.stringify(of('vp_out')[0]?.['narration']),
    );
    report(
      ['vp_no_ref', 'vp_missing_ref', 'vp_dotted_ref'].every(
        (id) => String(of(id)[0]?.['narration']) === 'Vendor payment_out',
      ),
      'a blank, absent or all-middot reference strips back to "Vendor payment_out"',
      ['vp_no_ref', 'vp_missing_ref', 'vp_dotted_ref']
        .map((id) => `${id}=${JSON.stringify(of(id)[0]?.['narration'])}`)
        .join(' '),
    );
    report(
      String(of('vp_null_ref')[0]?.['narration']) === 'Vendor payment_out · None',
      'a NULL reference interpolates as the literal "None" and survives the strip',
      JSON.stringify(of('vp_null_ref')[0]?.['narration']),
    );

    // 5. Money.
    report(of('vp_round').every((r) => r['amount'] === 2.67), 'a 2.675 payment projects as 2.67');
    report(of('vp_tie').every((r) => r['amount'] === 0.12), 'a 0.125 payment projects as 0.12');
    report(of('vp_string_amt').every((r) => r['amount'] === 750.25), 'a string amount is accepted');

    // 6. The pre-projected vendor_bill rows must have survived untouched, on
    //    whichever side owned them. If a vendor_payment reprojection could
    //    disturb a bill row, mixed ownership would not be safe.
    const bills = rows.filter((r) => r['source_type'] === 'vendor_bill');
    report(
      bills.length === 4,
      'both pre-projected vendor_bills still hold their two legs each',
      `${bills.length} bill legs`,
    );
    report(
      bills.some((r) => r['source_id'] === 'vb_pre_b' && r['amount'] === 2.67),
      'the pre-projected bill kept its half-to-even rounding',
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
