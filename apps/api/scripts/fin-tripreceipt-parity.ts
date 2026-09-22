/**
 * Focused parity for slice 2c unit 9 — the `trip_customer_receipt` projection.
 *
 *   npx tsx scripts/fin-tripreceipt-parity.ts
 *
 * The first source type with a PREFIX CASCADE. Its rows live under
 * `{trip_id}:{receipt_id}`, so a reproject of the parent trip has to clear
 * them with a prefix delete — and must not reach anything else.
 *
 * The fixtures therefore lean on three things the naive port gets wrong:
 * the array-position key fallback (skipped receipts must NOT renumber the
 * ones after them), the per-receipt skip rather than a fatal guard, and the
 * cascade's scope.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_tcrparity';
const CID = 'co_tcrparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_tcrparity_other';
const CID2 = 'co_tcrparity_other';

const trip = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  customer_id: 'cust_1',
  date: '2026-09-01',
  is_historical: false,
  ...over,
});

const r = (over: Doc = {}): Doc => ({ id: 'r1', amount: 100, ...over });

const documents: Doc[] = [
  // ── the ordinary shapes ──────────────────────────────────────────────
  trip({ id: 'trip_one', customer_receipts: [r({ mode: 'Cash', type: 'advance', date: '2026-09-02' })] }),
  trip({ id: 'trip_two', customer_receipts: [r({ id: 'r1' }), r({ id: 'r2', amount: 250 })] }),
  trip({
    id: 'trip_many',
    customer_receipts: [r({ id: 'a' }), r({ id: 'b', amount: 5 }), r({ id: 'c', amount: 7.5 })],
  }),

  // ── the array-position key fallback ──────────────────────────────────
  trip({ id: 'trip_noid', customer_receipts: [{ amount: 100 }] }), // -> idx0
  trip({ id: 'trip_blankid', customer_receipts: [{ id: '   ', amount: 100 }] }), // -> idx0
  // A skipped receipt must NOT renumber the ones after it: idx0 and idx2.
  trip({ id: 'trip_gap', customer_receipts: [{ amount: 100 }, { amount: 0 }, { amount: 50 }] }),
  // Mixed: some receipts carry ids, some do not.
  trip({ id: 'trip_mixed', customer_receipts: [{ amount: 10 }, { id: 'x', amount: 20 }, { amount: 30 }] }),

  // ── per-receipt skip, not a fatal guard ──────────────────────────────
  trip({ id: 'trip_zero_first', customer_receipts: [{ id: 'z', amount: 0 }, { id: 'ok', amount: 10 }] }),
  trip({ id: 'trip_all_zero', customer_receipts: [{ id: 'z1', amount: 0 }, { id: 'z2', amount: -5 }] }),
  trip({
    id: 'trip_bad_amounts',
    customer_receipts: [
      { id: 'n', amount: null },
      { id: 'm', amount: undefined },
      { id: 't', amount: 0.004 },
      { id: 'g', amount: 25 },
    ],
  }),

  // ── receipt type drives txn_type AND category ────────────────────────
  trip({ id: 'trip_diesel', customer_receipts: [r({ type: 'diesel' })] }),
  trip({ id: 'trip_type_missing', customer_receipts: [r({ type: undefined })] }), // -> advance
  trip({ id: 'trip_type_blank', customer_receipts: [r({ type: '' })] }), // -> advance
  trip({ id: 'trip_type_odd', customer_receipts: [r({ type: 'custom_thing' })] }),
  trip({ id: 'trip_type_unicode', customer_receipts: [r({ type: 'अग्रिम' })] }),

  // ── mode resolution ──────────────────────────────────────────────────
  trip({ id: 'trip_mode_cash', customer_receipts: [r({ mode: 'Cash' })] }),
  trip({ id: 'trip_mode_upi', customer_receipts: [r({ mode: 'UPI' })] }),
  trip({ id: 'trip_mode_unknown', customer_receipts: [r({ mode: 'Crypto' })] }),
  trip({ id: 'trip_mode_blank', customer_receipts: [r({ mode: '' })] }),
  trip({ id: 'trip_mode_missing', customer_receipts: [r({ mode: undefined })] }),

  // ── date fallback: receipt date, else trip date, else "" ─────────────
  trip({ id: 'trip_date_receipt', customer_receipts: [r({ date: '2026-09-05' })] }),
  trip({ id: 'trip_date_from_trip', customer_receipts: [r({ date: undefined })] }),
  trip({ id: 'trip_date_none', date: undefined, customer_receipts: [r({ date: undefined })] }),

  // ── trip-level guards ────────────────────────────────────────────────
  trip({ id: 'trip_historical', is_historical: true, customer_receipts: [r()] }),
  trip({ id: 'trip_hist_falsy', is_historical: 0, customer_receipts: [r()] }),
  // There is NO is_deleted guard on the trip.
  trip({ id: 'trip_deleted', is_deleted: true, customer_receipts: [r()] }),
  trip({ id: 'trip_empty', customer_receipts: [] }),
  trip({ id: 'trip_no_field' }),
  trip({ id: 'trip_null_field', customer_receipts: null }),

  // ── money ────────────────────────────────────────────────────────────
  trip({ id: 'trip_round', customer_receipts: [r({ amount: 2.675 })] }),
  trip({ id: 'trip_tie', customer_receipts: [r({ amount: 0.125 })] }),
  trip({ id: 'trip_tie_up', customer_receipts: [r({ amount: 0.375 })] }),
  trip({ id: 'trip_below', customer_receipts: [r({ amount: 1.005 })] }),
  trip({ id: 'trip_string_amt', customer_receipts: [r({ amount: '750.25' })] }),

  // ── ids and customers ────────────────────────────────────────────────
  trip({ id: 'trip_no_customer', customer_id: '', customer_receipts: [r()] }),
  trip({ id: 'trip_long_rid', customer_receipts: [r({ id: 'R'.repeat(80) })] }), // id caps at 60
  trip({ id: 'trip_unicode_rid', customer_receipts: [r({ id: 'रसीद' })] }),

  // ── a second tenant holding the SAME trip id ─────────────────────────
  trip({ id: 'trip_one', user_id: UID2, company_id: CID2, customer_receipts: [r({ amount: 4242 })] }),
];

void runProjectionParity({
  sourceType: 'trip_customer_receipt',
  collection: 'trips',
  slug: 'tcr',
  nestPort: 8491,
  documents,
  zeroLegged: [
    // NOTE: these are TRIP ids; the rows carry `{trip}:{rid}` source ids, so
    // the shared check looks for the trip id and correctly finds nothing.
    'trip_all_zero',
    'trip_historical',
    'trip_empty',
    'trip_no_field',
    'trip_null_field',
  ],
  sharedId: 'trip_one:r1',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const mine = rows.filter((x) => x['user_id'] === UID);
    const forTrip = (tid: string): Doc[] =>
      mine
        .filter((x) => String(x['source_id']).startsWith(`${tid}:`))
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));
    const idsFor = (tid: string): string[] => [
      ...new Set(forTrip(tid).map((x) => String(x['source_id']))),
    ].sort();

    // 1. Two legs per projected receipt, against CUSTOMER_ADVANCE.
    report(
      JSON.stringify(
        forTrip('trip_one').map((x) => [x['account_code'], x['direction'], x['txn_type']]),
      ) ===
        JSON.stringify([
          ['CASH', 'in', 'trip_customer_advance_receipt'],
          ['CUSTOMER_ADVANCE', 'out', 'trip_customer_advance_receipt'],
        ]),
      'a receipt debits the bank and credits CUSTOMER_ADVANCE',
    );
    report(forTrip('trip_two').length === 4, 'two receipts give four legs');
    report(forTrip('trip_many').length === 6, 'three receipts give six legs');

    // 2. The array-position fallback, including the gap.
    report(idsFor('trip_noid').join() === 'trip_noid:idx0', 'a receipt with no id falls back to idx0');
    report(idsFor('trip_blankid').join() === 'trip_blankid:idx0', 'a blank id falls back too');
    report(
      idsFor('trip_gap').join() === 'trip_gap:idx0,trip_gap:idx2',
      'a skipped receipt does NOT renumber the ones after it',
      idsFor('trip_gap').join(),
    );
    report(
      idsFor('trip_mixed').join() === 'trip_mixed:idx0,trip_mixed:idx2,trip_mixed:x',
      'explicit ids and index fallbacks coexist at their own positions',
      idsFor('trip_mixed').join(),
    );

    // 3. Per-receipt skip rather than a fatal guard.
    report(idsFor('trip_zero_first').join() === 'trip_zero_first:ok', 'a leading zero receipt is skipped alone');
    report(forTrip('trip_all_zero').length === 0, 'a trip whose receipts are all invalid projects nothing');
    report(
      idsFor('trip_bad_amounts').join() === 'trip_bad_amounts:g',
      'null, missing and rounds-to-zero amounts are each skipped individually',
      idsFor('trip_bad_amounts').join(),
    );

    // 4. The receipt type drives txn_type and category.
    report(
      forTrip('trip_diesel').every(
        (x) => x['txn_type'] === 'trip_customer_diesel_receipt' && x['category'] === 'diesel',
      ),
      'the receipt type reaches both txn_type and category',
    );
    report(
      forTrip('trip_type_missing').every((x) => x['txn_type'] === 'trip_customer_advance_receipt') &&
        forTrip('trip_type_blank').every((x) => x['txn_type'] === 'trip_customer_advance_receipt'),
      'a missing or blank type defaults to advance',
    );
    report(
      forTrip('trip_one')[0]?.['narration'] === 'Trip customer advance receipt',
      'the narration names the receipt type',
    );

    // 5. Date fallback.
    report(forTrip('trip_date_receipt').every((x) => x['txn_date'] === '2026-09-05'), 'the receipt date wins');
    report(
      forTrip('trip_date_from_trip').every((x) => x['txn_date'] === '2026-09-01'),
      'an absent receipt date falls back to the trip date',
    );
    report(forTrip('trip_date_none').every((x) => x['txn_date'] === ''), 'with neither, the date is empty');

    // 6. Trip-level guards.
    report(forTrip('trip_historical').length === 0, 'a historical trip projects nothing');
    report(forTrip('trip_hist_falsy').length === 2, 'a falsy is_historical still projects');
    report(forTrip('trip_deleted').length === 2, 'there is NO is_deleted guard on the trip');

    // 7. Every leg carries the trip and the customer.
    report(
      mine.every((x) => x['party_type'] === 'customer' && pyIsTrip(String(x['trip_id']))),
      'every leg carries party_type customer and its trip id',
    );
    report(
      forTrip('trip_no_customer').every((x) => x['party_id'] === ''),
      'a trip with no customer leaves party_id empty',
    );

    // 8. The compound id and the 60-character truncation.
    report(
      forTrip('trip_one').every(
        (x) => String(x['ref_source_key']) === `trip_customer_receipt:trip_one:r1:${String(x['ref_source_key']).split(':').pop()}`,
      ),
      'ref_source_key is source_type:trip:receipt:leg',
    );
    report(
      mine.every((x) => {
        const expected = `fintxn_${String(x['ref_source_key']).replace(/:/g, '_').slice(0, 60)}`;
        return x['id'] === expected;
      }),
      'fin_txn ids follow the ref_source_key rule, truncated at 60',
    );
    // A long receipt id proves the truncation actually bites.
    report(
      forTrip('trip_long_rid').every((x) => String(x['id']).length === 67),
      'a long receipt id truncates the generated fin_txn id at 60 characters',
      forTrip('trip_long_rid').map((x) => String(x['id']).length).join(','),
    );

    report(
      forTrip('trip_round').every((x) => x['amount'] === 2.67),
      'a 2.675 receipt projects as 2.67',
    );

    function pyIsTrip(v: string): boolean {
      return v.startsWith('trip_');
    }
  },
});
