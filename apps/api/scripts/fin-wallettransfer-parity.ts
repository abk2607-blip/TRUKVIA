/**
 * Focused parity for slice 2c unit 11 — the `wallet_transfer` projection.
 *
 *   npx tsx scripts/fin-wallettransfer-parity.ts
 *
 * The only projection reading TWO document-supplied account codes. Unlike
 * wallet_recharge it self-guards both of them and rejects a same-wallet
 * transfer — but a code that is non-empty and simply unknown still reaches the
 * persist layer and fails there, so both halves of that distinction are
 * exercised.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_wtparity';
const CID = 'co_wtparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_wtparity_other';
const CID2 = 'co_wtparity_other';

const wt = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  amount: 100,
  date: '2026-09-02',
  source_wallet_code: 'WALLET_FASTAG',
  destination_wallet_code: 'WALLET_FUEL',
  is_deleted: false,
  ...over,
});

const documents: Doc[] = [
  // ── both directions between the two real wallets ─────────────────────
  wt({ id: 'wt_fastag_to_fuel' }),
  wt({ id: 'wt_fuel_to_fastag', source_wallet_code: 'WALLET_FUEL', destination_wallet_code: 'WALLET_FASTAG' }),
  // In-catalog accounts that are not wallets still work.
  wt({ id: 'wt_cash_to_bank', source_wallet_code: 'CASH', destination_wallet_code: 'BANK_DEFAULT' }),

  // ── the self-guards: same wallet, and each code empty/absent/null ────
  wt({ id: 'wt_same_wallet', destination_wallet_code: 'WALLET_FASTAG' }),
  wt({ id: 'wt_same_cash', source_wallet_code: 'CASH', destination_wallet_code: 'CASH' }),
  wt({ id: 'wt_src_empty', source_wallet_code: '' }),
  wt({ id: 'wt_dst_empty', destination_wallet_code: '' }),
  wt({ id: 'wt_src_missing', source_wallet_code: undefined }),
  wt({ id: 'wt_dst_missing', destination_wallet_code: undefined }),
  wt({ id: 'wt_src_null', source_wallet_code: null }),
  wt({ id: 'wt_dst_null', destination_wallet_code: null }),
  wt({ id: 'wt_both_empty', source_wallet_code: '', destination_wallet_code: '' }),

  // ── unknown but non-empty: passes the guard, FAILS at persist ────────
  wt({ id: 'wt_dst_unknown', destination_wallet_code: 'WALLET_MYSTERY' }),
  wt({ id: 'wt_src_unknown', source_wallet_code: 'WALLET_MYSTERY' }),
  wt({ id: 'wt_both_unknown', source_wallet_code: 'AAA', destination_wallet_code: 'BBB' }),

  // ── guards ───────────────────────────────────────────────────────────
  wt({ id: 'wt_deleted', is_deleted: true }),
  wt({ id: 'wt_deleted_falsy', is_deleted: 0 }),
  wt({ id: 'wt_historical', is_historical: true }), // NO guard -> projects
  wt({ id: 'wt_reversed', is_reversed: true }), // NO guard -> projects
  wt({ id: 'wt_zero', amount: 0 }),
  wt({ id: 'wt_negative', amount: -50 }),
  wt({ id: 'wt_null_amount', amount: null }),
  wt({ id: 'wt_missing_amount', amount: undefined }),
  wt({ id: 'wt_tiny', amount: 0.004 }),
  // A same-wallet transfer with a bad code: the guard fires, no failure row.
  wt({ id: 'wt_same_unknown', source_wallet_code: 'ZZZ', destination_wallet_code: 'ZZZ' }),

  // ── money ────────────────────────────────────────────────────────────
  wt({ id: 'wt_round', amount: 2.675 }),
  wt({ id: 'wt_tie', amount: 0.125 }),
  wt({ id: 'wt_tie_up', amount: 0.375 }),
  wt({ id: 'wt_below', amount: 1.005 }),
  wt({ id: 'wt_string_amt', amount: '750.25' }),
  wt({ id: 'wt_big', amount: 98765432.1 }),
  wt({ id: 'wt_missing_date', date: undefined }),

  // ── a second tenant holding the SAME id ──────────────────────────────
  wt({ id: 'wt_fastag_to_fuel', user_id: UID2, company_id: CID2, amount: 4242 }),
];

void runProjectionParity({
  sourceType: 'wallet_transfer',
  collection: 'wallet_transfers',
  slug: 'wt',
  nestPort: 8511,
  documents,
  expectedFailures: ['wt_dst_unknown', 'wt_src_unknown', 'wt_both_unknown'],
  zeroLegged: [
    'wt_same_wallet',
    'wt_same_cash',
    'wt_src_empty',
    'wt_dst_empty',
    'wt_src_missing',
    'wt_dst_missing',
    'wt_src_null',
    'wt_dst_null',
    'wt_both_empty',
    // NOT wt_dst_unknown: its SOURCE leg persists before the destination leg
    // raises, so it legitimately leaves one row behind. See below.
    'wt_src_unknown',
    'wt_both_unknown',
    'wt_deleted',
    'wt_zero',
    'wt_negative',
    'wt_null_amount',
    'wt_missing_amount',
    'wt_tiny',
    'wt_same_unknown',
  ],
  sharedId: 'wt_fastag_to_fuel',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const of = (id: string): Doc[] =>
      rows
        .filter((r) => r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. The leg shape: source credited, destination debited.
    report(
      JSON.stringify(
        of('wt_fastag_to_fuel').map((r) => [r['ref_source_key'], r['account_code'], r['direction']]),
      ) ===
        JSON.stringify([
          ['wallet_transfer:wt_fastag_to_fuel:dst_debit', 'WALLET_FUEL', 'in'],
          ['wallet_transfer:wt_fastag_to_fuel:src_credit', 'WALLET_FASTAG', 'out'],
        ]),
      'money leaves the source and lands in the destination',
    );
    report(
      of('wt_fastag_to_fuel').every((r) => r['txn_type'] === 'wallet_transfer'),
      'both legs share the wallet_transfer txn_type',
    );
    report(
      of('wt_cash_to_bank').length === 2,
      'any two distinct in-catalog accounts transfer, not just the wallets',
    );

    // 2. The self-guards.
    const guarded = [
      'wt_same_wallet',
      'wt_same_cash',
      'wt_src_empty',
      'wt_dst_empty',
      'wt_src_missing',
      'wt_dst_missing',
      'wt_src_null',
      'wt_dst_null',
      'wt_both_empty',
    ];
    report(
      guarded.every((id) => of(id).length === 0),
      'a same-wallet transfer or an empty/absent code on EITHER side projects nothing',
      guarded.filter((id) => of(id).length > 0).join(', '),
    );

    /**
     * 3. Unknown-but-non-empty passes the guard and fails at persist — and
     * WHERE it fails decides how much was already written. `_persist_legs`
     * upserts one leg at a time, so an invalid DESTINATION leaves the source
     * leg behind: a partial write, not an atomic rollback. An invalid SOURCE
     * raises on the first leg and writes nothing.
     *
     * That partial row is not a leak. The row is recorded in
     * fin_hook_failures, and the next attempt deletes by source before
     * reinserting, so a retry or a corrected document cleans it up.
     */
    report(
      of('wt_src_unknown').length === 0 && of('wt_both_unknown').length === 0,
      'an unknown SOURCE raises on the first leg and writes nothing',
    );
    report(
      of('wt_dst_unknown').length === 1 && of('wt_dst_unknown')[0]?.['account_code'] === 'WALLET_FASTAG',
      'an unknown DESTINATION persists the source leg first, then raises — a partial write',
      `${of('wt_dst_unknown').length} rows`,
    );
    report(
      of('wt_same_unknown').length === 0,
      'a same-wallet guard fires before the unknown code can fail',
    );

    // 4. The guards this projection does NOT have.
    report(
      of('wt_historical').length === 2 && of('wt_reversed').length === 2,
      'is_historical and is_reversed are not guards here — both still project',
    );
    report(of('wt_deleted_falsy').length === 2, 'a falsy is_deleted still projects');

    // 5. The narration, including the arrow.
    const n = String(of('wt_fastag_to_fuel')[0]?.['narration']);
    report(
      n === 'Wallet transfer WALLET_FASTAG → WALLET_FUEL',
      'the narration names both wallets',
      JSON.stringify(n),
    );
    report(
      n.codePointAt(30) === 0x2192,
      'the separator is U+2192 RIGHTWARDS ARROW, not "->"',
      `got codepoint ${n.codePointAt(30)?.toString(16)}`,
    );

    // 6. No party, trip, vehicle, category or source_key.
    report(
      rows.every(
        (r) =>
          r['party_type'] === '' &&
          r['party_id'] === '' &&
          r['trip_id'] === '' &&
          r['vehicle_id'] === '' &&
          r['category'] === '' &&
          r['source_key'] === '',
      ),
      'transfer legs carry no party, trip, vehicle, category or source_key',
    );

    report(
      of('wt_round').every((r) => r['amount'] === 2.67),
      'a 2.675 transfer projects as 2.67 on both legs',
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
