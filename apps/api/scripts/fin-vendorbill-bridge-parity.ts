/**
 * Slice 2c step 6 — the reverse-bridge switch, `vendor_bill` half.
 *
 *   npx tsx scripts/fin-vendorbill-bridge-parity.ts
 *
 * The companion to fin-vendorpay-bridge-parity.ts. Same standard of proof,
 * inverted dependency: here vendor_bill is under test and `expense` is
 * pre-projected under a DIFFERENT owner on each database.
 *
 * That inversion is the point. vendor_bill projects legs ONLY when it has no
 * paired Expense, so its output depends on a lookup into a collection whose
 * projection may be owned by either side. `_has_paired_expense` reads the
 * SOURCE collection rather than the ledger, so ownership should not matter —
 * and `preProject` is what turns that "should" into a measurement.
 *
 * The pairing filter is exercised in both directions: bills paired with a
 * live expense (suppressed), with a deleted or reversed expense (NOT
 * suppressed, because the filter excludes those), and with none at all.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_vbbridge';
const CID = 'co_vbbridge';
/** A second tenant, to prove one scope cannot pair or project across. */
const UID2 = 'user_vbbridge_other';
const CID2 = 'co_vbbridge_other';

const vb = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  vendor_id: 'vend_1',
  vendor_name: 'Vend One',
  bill_amount: 1000,
  bill_date: '2026-09-02',
  bill_number: 'VB-1',
  is_deleted: false,
  ...over,
});

const exp = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  amount: 400,
  date: '2026-09-02',
  category: 'Repair',
  payment_status: 'unpaid',
  is_deleted: false,
  is_reversed: false,
  ...over,
});

/**
 * The expenses that decide the pairing. Each names the bill it pairs with.
 * The deleted / reversed ones are the interesting cases: the filter carries
 * `is_deleted: {$ne: true}` and `is_reversed: {$ne: true}`, so they do NOT
 * suppress their bill and the bill must still project as an orphan.
 */
const expenses: Doc[] = [
  exp({ id: 'ex_pair_live', vendor_bill_id: 'vb_paired' }),
  exp({ id: 'ex_pair_deleted', vendor_bill_id: 'vb_paired_deleted_expense', is_deleted: true }),
  exp({ id: 'ex_pair_reversed', vendor_bill_id: 'vb_paired_reversed_expense', is_reversed: true }),
  // Two live expenses against one bill — one match is enough to suppress.
  exp({ id: 'ex_pair_multi_a', vendor_bill_id: 'vb_paired_multi' }),
  exp({ id: 'ex_pair_multi_b', vendor_bill_id: 'vb_paired_multi', amount: 600 }),
  /**
   * A live expense under the OTHER tenant, naming a bill id that only the
   * FIRST tenant holds. It must not suppress that bill.
   *
   * It deliberately does NOT name `vb_orphan`: that id exists under both
   * tenants, so pairing it would correctly suppress the second tenant's own
   * copy and destroy the per-tenant scoping fixture rather than test it.
   */
  exp({
    id: 'ex_pair_other_tenant',
    user_id: UID2,
    company_id: CID2,
    vendor_bill_id: 'vb_orphan_2',
  }),
  // An expense pairing a mechanic work order, not a bill — must not match.
  exp({ id: 'ex_pair_wo', mechanic_work_order_id: 'vb_orphan' }),
];

const documents: Doc[] = [
  // ── the orphan case: no paired expense, so the bill projects ─────────
  vb({ id: 'vb_orphan' }),
  vb({ id: 'vb_orphan_2', bill_amount: 250, bill_number: 'VB-2', vendor_id: 'vend_2' }),

  // ── pairing ──────────────────────────────────────────────────────────
  vb({ id: 'vb_paired' }), // suppressed by a live expense
  vb({ id: 'vb_paired_multi' }), // suppressed by either of two
  vb({ id: 'vb_paired_deleted_expense' }), // NOT suppressed
  vb({ id: 'vb_paired_reversed_expense' }), // NOT suppressed

  // ── guards ───────────────────────────────────────────────────────────
  vb({ id: 'vb_deleted', is_deleted: true }),
  vb({ id: 'vb_deleted_falsy', is_deleted: 0 }),
  // vendor_bill has NO is_reversed and NO is_historical guard of its own.
  vb({ id: 'vb_reversed', is_reversed: true }),
  vb({ id: 'vb_historical', is_historical: true }),
  vb({ id: 'vb_zero', bill_amount: 0 }),
  vb({ id: 'vb_negative', bill_amount: -100 }),
  vb({ id: 'vb_null_amount', bill_amount: null }),
  vb({ id: 'vb_missing_amount', bill_amount: undefined }),
  vb({ id: 'vb_tiny', bill_amount: 0.004 }),

  // ── money ────────────────────────────────────────────────────────────
  vb({ id: 'vb_round', bill_amount: 2.675 }),
  vb({ id: 'vb_tie', bill_amount: 0.125 }),
  vb({ id: 'vb_tie_up', bill_amount: 0.375 }),
  vb({ id: 'vb_string_amt', bill_amount: '750.25' }),

  // ── narration: NOT stripped, so the blank cases keep their spacing ───
  vb({ id: 'vb_no_number', bill_number: '' }),
  vb({ id: 'vb_missing_number', bill_number: undefined }),
  vb({ id: 'vb_null_number', bill_number: null }),

  // ── the optional carried fields ──────────────────────────────────────
  vb({ id: 'vb_with_vehicle', vehicle_id: 'veh_1', trip_id: 'trip_1' }),
  vb({ id: 'vb_missing_vendor_name', vendor_name: undefined }),
  vb({ id: 'vb_null_vendor_name', vendor_name: null }),
  vb({ id: 'vb_missing_date', bill_date: undefined }),

  // ── a second tenant holding the SAME id ──────────────────────────────
  vb({ id: 'vb_orphan', user_id: UID2, company_id: CID2, bill_amount: 4242 }),
];

void runProjectionParity({
  sourceType: 'vendor_bill',
  collection: 'vendor_bills',
  slug: 'vbbridge',
  nestPort: 8541,
  documents,
  extraCollections: { expenses },
  // The expenses are projected FIRST, by a different owner on each database.
  preProject: {
    sourceType: 'expense',
    ids: expenses.map(
      (e) => [String(e['id']), String(e['user_id']), String(e['company_id'])] as [string, string, string],
    ),
  },
  zeroLegged: [
    'vb_paired',
    'vb_paired_multi',
    'vb_deleted',
    'vb_zero',
    'vb_negative',
    'vb_null_amount',
    'vb_missing_amount',
    'vb_tiny',
  ],
  sharedId: 'vb_orphan',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const of = (id: string): Doc[] =>
      rows
        .filter((r) => r['source_type'] === 'vendor_bill' && r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. The orphan leg shape: SUSPENSE against AP_VENDOR.
    report(
      JSON.stringify(of('vb_orphan').map((r) => [r['ref_source_key'], r['account_code'], r['direction']])) ===
        JSON.stringify([
          ['vendor_bill:vb_orphan:ap_credit', 'AP_VENDOR', 'out'],
          ['vendor_bill:vb_orphan:suspense_debit', 'SUSPENSE', 'in'],
        ]),
      'an orphan bill books SUSPENSE against AP_VENDOR',
    );
    report(
      of('vb_orphan').every((r) => r['txn_type'] === 'vendor_bill_orphan'),
      'the txn_type marks it as an orphan',
    );

    // 2. Pairing, in both directions.
    report(
      of('vb_paired').length === 0 && of('vb_paired_multi').length === 0,
      'a live paired expense suppresses the bill, and one of two is enough',
    );
    report(
      of('vb_paired_deleted_expense').length === 2,
      'a DELETED paired expense does not suppress — the bill projects as an orphan',
    );
    report(
      of('vb_paired_reversed_expense').length === 2,
      'a REVERSED paired expense does not suppress either',
    );
    report(
      of('vb_orphan_2').length === 2,
      'a live expense under ANOTHER tenant cannot suppress this tenant’s bill',
    );
    report(
      of('vb_orphan').length === 2,
      'an expense pairing a mechanic_work_order id does not match a vendor_bill id',
    );

    // 3. Guards it does NOT have.
    report(
      of('vb_reversed').length === 2 && of('vb_historical').length === 2,
      'is_reversed and is_historical are not guards for vendor_bill',
    );
    report(of('vb_deleted_falsy').length === 2, 'a falsy is_deleted still projects');

    // 4. Narration — NOT stripped, so the spacing is part of the contract.
    report(
      String(of('vb_orphan')[0]?.['narration']) === 'VendorBill VB-1 (orphan)',
      'the narration names the bill number',
      JSON.stringify(of('vb_orphan')[0]?.['narration']),
    );
    report(
      ['vb_no_number', 'vb_missing_number'].every(
        (id) => String(of(id)[0]?.['narration']) === 'VendorBill  (orphan)',
      ),
      'a blank or absent number leaves the DOUBLE space — there is no strip here',
      ['vb_no_number', 'vb_missing_number']
        .map((id) => `${id}=${JSON.stringify(of(id)[0]?.['narration'])}`)
        .join(' '),
    );
    report(
      String(of('vb_null_number')[0]?.['narration']) === 'VendorBill None (orphan)',
      'a NULL number interpolates as the literal "None"',
      JSON.stringify(of('vb_null_number')[0]?.['narration']),
    );

    // 5. The carried fields.
    report(
      of('vb_with_vehicle').every((r) => r['vehicle_id'] === 'veh_1' && r['trip_id'] === 'trip_1'),
      'the vehicle and trip are carried onto both legs',
    );
    report(
      of('vb_orphan').every((r) => r['party_type'] === 'vendor' && r['party_name'] === 'Vend One'),
      'the vendor name is carried',
    );
    report(
      ['vb_missing_vendor_name', 'vb_null_vendor_name'].every((id) =>
        of(id).every((r) => r['party_name'] === ''),
      ),
      'an absent or null vendor name becomes an empty string — `or ""`, not an f-string',
    );

    // 6. Money.
    report(of('vb_round').every((r) => r['amount'] === 2.67), 'a 2.675 bill projects as 2.67');
    report(of('vb_tie').every((r) => r['amount'] === 0.12), 'a 0.125 bill projects as 0.12');

    report(
      rows.every((r) => {
        const expected = `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
        return r['id'] === expected;
      }),
      'fin_txn ids follow the ref_source_key rule, truncated at 60',
    );
  },
});
