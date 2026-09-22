/**
 * Focused parity for slice 2c unit 12 — `invoice` AND its `invoice_payment`
 * cascade, as ONE coupled unit.
 *
 *   npx tsx scripts/fin-invoice-parity.ts
 *
 * They are coupled by construction, not by choice: a single Python function
 * emits both. The payments are embedded in the invoice document and projected
 * inline under their own source_type with a compound source_id, and a
 * reproject of the parent clears them through a cascade that crosses into that
 * other source_type — the only one that does.
 *
 * A single-shot comparison cannot see whether that cascade behaves over TIME,
 * so this run also drives a lifecycle: a payment added after the parent was
 * already projected, one removed, an amount changed, and a repeated reproject.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_invparity';
const CID = 'co_invparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_invparity_other';
const CID2 = 'co_invparity_other';

const inv = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  total_amount: 1000,
  invoice_date: '2026-09-02',
  customer_id: 'cust_1',
  invoice_number: 'INV-9',
  is_historical: false,
  ...over,
});

const pay = (over: Doc = {}): Doc => ({ id: 'p1', amount: 300, ...over });

const documents: Doc[] = [
  // ── 1. invoice without payment ───────────────────────────────────────
  inv({ id: 'inv_bare' }),

  // ── the advance offset ───────────────────────────────────────────────
  inv({ id: 'inv_offset_adv', advance_deduction_total: 200 }),
  inv({ id: 'inv_offset_dsl', diesel_deduction_total: 150 }),
  inv({ id: 'inv_offset_both', advance_deduction_total: 200, diesel_deduction_total: 50 }),
  inv({ id: 'inv_offset_zero', advance_deduction_total: 0, diesel_deduction_total: 0 }),
  // double rounding: each deduction rounds first, then their sum rounds again
  inv({ id: 'inv_offset_round', advance_deduction_total: 0.005, diesel_deduction_total: 0.005 }),
  inv({ id: 'inv_offset_neg', advance_deduction_total: -100 }),

  // ── 2/3. one payment, several payments ───────────────────────────────
  inv({ id: 'inv_one_pay', payments: [pay({ mode: 'Cash', date: '2026-09-05', reference: 'R1' })] }),
  inv({ id: 'inv_two_pay', payments: [pay(), pay({ id: 'p2', amount: 100 })] }),
  inv({ id: 'inv_three_pay', payments: [pay(), pay({ id: 'p2', amount: 100 }), pay({ id: 'p3', amount: 50 })] }),
  inv({ id: 'inv_offset_and_pay', advance_deduction_total: 100, payments: [pay()] }),

  // ── payments that are skipped ────────────────────────────────────────
  // No index fallback here, unlike trip_customer_receipt: no id means skipped.
  inv({ id: 'inv_pay_no_id', payments: [{ amount: 300 }] }),
  inv({ id: 'inv_pay_blank_id', payments: [{ id: '', amount: 300 }] }),
  inv({ id: 'inv_pay_null_id', payments: [{ id: null, amount: 300 }] }),
  inv({ id: 'inv_pay_zero', payments: [pay({ amount: 0 })] }),
  inv({ id: 'inv_pay_negative', payments: [pay({ amount: -5 })] }),
  inv({ id: 'inv_pay_tiny', payments: [pay({ amount: 0.004 })] }),
  inv({ id: 'inv_pay_mixed', payments: [{ amount: 1 }, pay({ id: 'good', amount: 20 }), pay({ id: 'z', amount: 0 })] }),

  // ── payment mode and date ────────────────────────────────────────────
  inv({ id: 'inv_pay_cash', payments: [pay({ mode: 'Cash' })] }),
  inv({ id: 'inv_pay_upi', payments: [pay({ mode: 'UPI' })] }),
  inv({ id: 'inv_pay_unknown_mode', payments: [pay({ mode: 'Crypto' })] }),
  inv({ id: 'inv_pay_no_mode', payments: [pay({ mode: undefined })] }),
  inv({ id: 'inv_pay_own_date', payments: [pay({ date: '2026-09-09' })] }),
  inv({ id: 'inv_pay_no_date', payments: [pay({ date: undefined })] }), // -> invoice date

  // ── invoice-level guards ─────────────────────────────────────────────
  inv({ id: 'inv_historical', is_historical: true, payments: [pay()] }),
  inv({ id: 'inv_hist_falsy', is_historical: 0 }),
  // total <= 0 kills the WHOLE document, payments included
  inv({ id: 'inv_zero_total', total_amount: 0, payments: [pay()] }),
  inv({ id: 'inv_neg_total', total_amount: -100, payments: [pay()] }),
  inv({ id: 'inv_null_total', total_amount: null }),
  inv({ id: 'inv_missing_total', total_amount: undefined }),
  inv({ id: 'inv_tiny_total', total_amount: 0.004, payments: [pay()] }),
  // NO is_deleted guard on the invoice
  inv({ id: 'inv_deleted', is_deleted: true }),

  // ── money ────────────────────────────────────────────────────────────
  inv({ id: 'inv_round', total_amount: 2.675 }),
  inv({ id: 'inv_tie', total_amount: 0.125 }),
  inv({ id: 'inv_tie_up', total_amount: 0.375 }),
  inv({ id: 'inv_below', total_amount: 1.005 }),
  inv({ id: 'inv_string_total', total_amount: '750.25' }),

  // ── narration, neither of which is stripped ──────────────────────────
  inv({ id: 'inv_no_number', invoice_number: '' }),
  inv({ id: 'inv_missing_number', invoice_number: undefined }),
  inv({ id: 'inv_null_number', invoice_number: null }),
  inv({ id: 'inv_pay_no_ref', payments: [pay({ reference: '' })] }),
  inv({ id: 'inv_pay_null_ref', payments: [pay({ reference: null })] }),
  inv({ id: 'inv_unicode', invoice_number: 'चालान-९', payments: [pay({ reference: 'रसीद' })] }),
  inv({ id: 'inv_long_number', invoice_number: 'N'.repeat(500) }),
  inv({ id: 'inv_no_customer', customer_id: '' }),

  // ── 9. an unrelated invoice with a same-LOOKING child id ─────────────
  // inv_child and inv_child_x are different invoices; a cascade on one must
  // not touch the other even though "inv_child:" is a prefix of "inv_child_x:".
  inv({ id: 'inv_child', payments: [pay({ id: 'p1', amount: 11 })] }),
  inv({ id: 'inv_child_x', payments: [pay({ id: 'p1', amount: 22 })] }),

  // ── 10. the same ids in another tenant ───────────────────────────────
  inv({ id: 'inv_one_pay', user_id: UID2, company_id: CID2, total_amount: 4242, payments: [pay({ amount: 77 })] }),
];

const ALL: Array<[string, string, string]> = documents.map(
  (d) => [String(d['id']), String(d['user_id']), String(d['company_id'])] as [string, string, string],
);
const ONE = (id: string): Array<[string, string, string]> => [[id, UID, CID]];

void runProjectionParity({
  sourceType: 'invoice',
  collection: 'invoices',
  slug: 'inv',
  nestPort: 8521,
  documents,
  zeroLegged: [
    'inv_historical',
    'inv_zero_total',
    'inv_neg_total',
    'inv_null_total',
    'inv_missing_total',
    'inv_tiny_total',
  ],
  sharedId: 'inv_one_pay',
  verifyRouting: true,

  // ── 4-8: the cascade over time ───────────────────────────────────────
  lifecycle: [
    {
      name: '4. a payment added AFTER the invoice was already projected',
      mutate: async (db) => {
        await db
          .collection('invoices')
          .updateOne({ id: 'inv_bare', user_id: UID }, { $set: { payments: [{ id: 'late', amount: 60 }] } });
      },
      reproject: ONE('inv_bare'),
    },
    {
      name: '5. that payment removed again — no orphan rows may survive',
      mutate: async (db) => {
        await db.collection('invoices').updateOne({ id: 'inv_bare', user_id: UID }, { $set: { payments: [] } });
      },
      reproject: ONE('inv_bare'),
    },
    {
      name: '6. one of three payments deleted',
      mutate: async (db) => {
        await db
          .collection('invoices')
          .updateOne(
            { id: 'inv_three_pay', user_id: UID },
            { $set: { payments: [{ id: 'p1', amount: 300 }, { id: 'p3', amount: 50 }] } },
          );
      },
      reproject: ONE('inv_three_pay'),
    },
    {
      name: '7. a payment amount changed in place',
      mutate: async (db) => {
        await db
          .collection('invoices')
          .updateOne({ id: 'inv_two_pay', user_id: UID }, { $set: { 'payments.1.amount': 999.99 } });
      },
      reproject: ONE('inv_two_pay'),
    },
    {
      name: '8. the whole set reprojected twice more, unchanged',
      mutate: async () => {
        /* no mutation: pure idempotency */
      },
      reproject: ALL,
    },
    {
      name: 'the offset appearing on an invoice that had none',
      mutate: async (db) => {
        await db
          .collection('invoices')
          .updateOne({ id: 'inv_offset_zero', user_id: UID }, { $set: { advance_deduction_total: 75 } });
      },
      reproject: ONE('inv_offset_zero'),
    },
    {
      name: 'the invoice going historical, which must clear every child row',
      mutate: async (db) => {
        await db
          .collection('invoices')
          .updateOne({ id: 'inv_two_pay', user_id: UID }, { $set: { is_historical: true } });
      },
      reproject: ONE('inv_two_pay'),
    },
  ],

  extraChecks: (rows, report) => {
    const mine = rows.filter((r) => r['user_id'] === UID);
    const forInv = (id: string): Doc[] =>
      mine
        .filter((r) => r['source_id'] === id || String(r['source_id']).startsWith(`${id}:`))
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. The raise pair.
    report(
      JSON.stringify(
        forInv('inv_bare').map((r) => [r['source_type'], r['account_code'], r['direction'], r['txn_type']]),
      ) ===
        JSON.stringify([
          ['invoice', 'AR', 'in', 'invoice_raise'],
          ['invoice', 'SALES', 'out', 'invoice_raise'],
        ]),
      'a bare invoice debits AR and credits SALES',
    );

    // 2. The offset pair and its double rounding.
    report(forInv('inv_offset_both').length === 4, 'deductions add an offset pair');
    report(
      forInv('inv_offset_both').some((r) => r['account_code'] === 'CUSTOMER_ADVANCE' && r['amount'] === 250),
      'the offset is the sum of the advance and diesel deductions',
    );
    report(forInv('inv_offset_zero').length >= 2, 'a zero deduction adds no offset pair');
    report(
      forInv('inv_offset_neg').length === 2,
      'a negative deduction total adds no offset pair',
    );
    report(
      forInv('inv_offset_round').some((r) => r['amount'] === 0.02),
      'each deduction rounds BEFORE the sum, which rounds again (0.005 + 0.005 -> 0.02)',
      forInv('inv_offset_round').map((r) => String(r['amount'])).join(','),
    );

    // 3. Payments: their own source_type and compound id.
    const p = forInv('inv_one_pay').filter((r) => r['source_type'] === 'invoice_payment');
    report(
      JSON.stringify(p.map((r) => [r['source_id'], r['account_code'], r['direction'], r['txn_type']])) ===
        JSON.stringify([
          ['inv_one_pay:p1', 'AR', 'out', 'invoice_receipt'],
          ['inv_one_pay:p1', 'CASH', 'in', 'invoice_receipt'],
        ]),
      'a payment gets its own source_type and a compound source id',
    );
    report(forInv('inv_two_pay').length === 6, 'two payments add two pairs');
    report(forInv('inv_offset_and_pay').length === 6, 'an offset and a payment coexist');

    // 4. Skipped payments — no index fallback.
    const skipped = ['inv_pay_no_id', 'inv_pay_blank_id', 'inv_pay_null_id', 'inv_pay_zero', 'inv_pay_negative', 'inv_pay_tiny'];
    report(
      skipped.every((id) => forInv(id).every((r) => r['source_type'] === 'invoice')),
      'a payment with no id or no amount is skipped, with NO index fallback',
      skipped.filter((id) => forInv(id).some((r) => r['source_type'] === 'invoice_payment')).join(', '),
    );
    report(
      forInv('inv_pay_mixed').filter((r) => r['source_type'] === 'invoice_payment').length === 2,
      'only the valid payment of a mixed array projects',
    );

    // 5. total <= 0 kills the whole document.
    report(
      ['inv_zero_total', 'inv_neg_total', 'inv_null_total', 'inv_missing_total', 'inv_tiny_total'].every(
        (id) => forInv(id).length === 0,
      ),
      'a non-positive total projects nothing at all, payments included',
    );
    report(forInv('inv_historical').length === 0, 'a historical invoice projects nothing');
    report(forInv('inv_deleted').length === 2, 'there is NO is_deleted guard on the invoice');

    // 6. Payment date and mode.
    report(
      forInv('inv_pay_own_date')
        .filter((r) => r['source_type'] === 'invoice_payment')
        .every((r) => r['txn_date'] === '2026-09-09'),
      'a payment keeps its own date',
    );
    report(
      forInv('inv_pay_no_date')
        .filter((r) => r['source_type'] === 'invoice_payment')
        .every((r) => r['txn_date'] === '2026-09-02'),
      'a payment with no date falls back to the INVOICE date',
    );
    report(
      forInv('inv_pay_unknown_mode').some((r) => r['account_code'] === 'BANK_DEFAULT'),
      'an unknown payment mode resolves to BANK_DEFAULT',
    );

    // 7. Narrations, neither stripped.
    report(forInv('inv_bare')[0]?.['narration'] === 'Invoice INV-9', 'the invoice narration names the number');
    report(
      forInv('inv_no_number')[0]?.['narration'] === 'Invoice ',
      'a blank invoice number leaves the trailing space — the narration is NOT stripped',
      JSON.stringify(forInv('inv_no_number')[0]?.['narration']),
    );
    report(
      forInv('inv_null_number')[0]?.['narration'] === 'Invoice None',
      'an invoice number present as null interpolates as the literal "None"',
    );
    report(
      forInv('inv_pay_null_ref')
        .filter((r) => r['source_type'] === 'invoice_payment')
        .every((r) => r['narration'] === 'Receipt None · Inv INV-9'),
      'a payment reference present as null does the same',
    );
    report(
      String(forInv('inv_long_number')[0]?.['narration']).length === 400,
      'the narration caps at 400',
    );

    // 8. The prefix cascade must not over-reach a same-looking sibling.
    report(
      forInv('inv_child').filter((r) => r['source_type'] === 'invoice_payment').length === 2 &&
        forInv('inv_child_x').filter((r) => r['source_type'] === 'invoice_payment').length === 2,
      'two invoices whose ids share a prefix each keep their own payment rows',
    );

    report(
      mine.every((r) => {
        const expected = `fintxn_${String(r['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
        return r['id'] === expected;
      }),
      'fin_txn ids follow the ref_source_key rule, truncated at 60',
    );
  },
});
