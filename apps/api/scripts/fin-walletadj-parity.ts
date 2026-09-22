/**
 * Focused parity for slice 2c unit 8 — the `wallet_adjustment` projection.
 *
 *   npx tsx scripts/fin-walletadj-parity.ts
 *
 * The first ported projection whose ACCOUNT CODE comes from the document
 * rather than a literal, so the fixtures concentrate on that: every wallet
 * code the model allows, plus the empty/missing/unknown cases on either side
 * of the self-guard.
 *
 * Note what is NOT exercised here and why: nothing in this projection creates
 * an account. `_persist_legs` only looks the code up in the map
 * `ensure_system_accounts` built, so there is no lazy-seeding path to test —
 * and the harness's `fin_accounts identical` check proves the seeded catalog
 * is the same on both sides either way.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_waparity';
const CID = 'co_waparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_waparity_other';
const CID2 = 'co_waparity_other';

const wa = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  amount: 100,
  date: '2026-09-02',
  wallet_code: 'WALLET_FASTAG',
  direction: 'increase',
  reason: 'Top-up correction',
  is_deleted: false,
  ...over,
});

const documents: Doc[] = [
  // ── both directions, both allowed wallets ────────────────────────────
  wa({ id: 'wa_inc_fastag' }),
  wa({ id: 'wa_dec_fastag', direction: 'decrease' }),
  wa({ id: 'wa_inc_fuel', wallet_code: 'WALLET_FUEL' }),
  wa({ id: 'wa_dec_fuel', wallet_code: 'WALLET_FUEL', direction: 'decrease' }),

  // ── direction must match EXACTLY; everything else projects nothing ───
  wa({ id: 'wa_dir_blank', direction: '' }),
  wa({ id: 'wa_dir_missing', direction: undefined }),
  wa({ id: 'wa_dir_null', direction: null }),
  wa({ id: 'wa_dir_upper', direction: 'INCREASE' }),
  wa({ id: 'wa_dir_title', direction: 'Increase' }),
  wa({ id: 'wa_dir_spaced', direction: 'increase ' }),
  wa({ id: 'wa_dir_unknown', direction: 'up' }),

  // ── wallet_code: the self-guard, and a code outside the wallet pair ──
  wa({ id: 'wa_code_blank', wallet_code: '' }),
  wa({ id: 'wa_code_missing', wallet_code: undefined }),
  wa({ id: 'wa_code_null', wallet_code: null }),
  // Not a wallet, but it IS in the seed catalog, so it projects cleanly.
  wa({ id: 'wa_code_cash', wallet_code: 'CASH' }),
  wa({ id: 'wa_code_suspense', wallet_code: 'SUSPENSE' }),

  // ── guards ───────────────────────────────────────────────────────────
  wa({ id: 'wa_deleted', is_deleted: true }),
  wa({ id: 'wa_deleted_falsy', is_deleted: 0 }),
  // There is NO is_reversed and NO is_historical guard on this model.
  wa({ id: 'wa_reversed_flag', is_reversed: true }),
  wa({ id: 'wa_historical_flag', is_historical: true }),
  // reverses_id is ignored: a reversal is its own document, projected alike.
  wa({ id: 'wa_reversal_doc', direction: 'decrease', reverses_id: 'wa_inc_fastag' }),
  wa({ id: 'wa_zero', amount: 0 }),
  wa({ id: 'wa_negative', amount: -50 }),
  wa({ id: 'wa_null_amount', amount: null }),
  wa({ id: 'wa_missing_amount', amount: undefined }),
  wa({ id: 'wa_tiny', amount: 0.004 }),

  // ── money ────────────────────────────────────────────────────────────
  wa({ id: 'wa_round_half_even', amount: 2.675 }),
  wa({ id: 'wa_round_tie', amount: 0.125 }),
  wa({ id: 'wa_round_tie_up', amount: 0.375 }),
  wa({ id: 'wa_round_below', amount: 1.005 }),
  wa({ id: 'wa_paise', amount: 1234.56 }),
  wa({ id: 'wa_string_amount', amount: '750.25' }),
  wa({ id: 'wa_big', amount: 98765432.1 }),

  // ── narration ────────────────────────────────────────────────────────
  wa({ id: 'wa_reason_blank', reason: '' }), // strip eats the separator
  wa({ id: 'wa_reason_missing', reason: undefined }), // .get default -> ''
  // A key PRESENT with null interpolates as the literal text "None".
  wa({ id: 'wa_reason_null', reason: null }),
  wa({ id: 'wa_reason_long', reason: 'R'.repeat(500) }), // caps at 400
  wa({ id: 'wa_reason_unicode', reason: 'कारण · 数 · ⛽' }),
  wa({ id: 'wa_reason_dot', reason: '·' }), // strip removes it entirely
  wa({ id: 'wa_missing_date', date: undefined }),

  // ── a second tenant holding the SAME id ──────────────────────────────
  wa({ id: 'wa_inc_fastag', user_id: UID2, company_id: CID2, amount: 4242, reason: 'OTHER' }),
];

void runProjectionParity({
  sourceType: 'wallet_adjustment',
  collection: 'wallet_adjustments',
  slug: 'wa',
  nestPort: 8481,
  documents,
  zeroLegged: [
    'wa_dir_blank',
    'wa_dir_missing',
    'wa_dir_null',
    'wa_dir_upper',
    'wa_dir_title',
    'wa_dir_spaced',
    'wa_dir_unknown',
    'wa_code_blank',
    'wa_code_missing',
    'wa_code_null',
    'wa_deleted',
    'wa_zero',
    'wa_negative',
    'wa_null_amount',
    'wa_missing_amount',
    'wa_tiny',
  ],
  sharedId: 'wa_inc_fastag',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const of = (id: string): Doc[] =>
      rows
        .filter((r) => r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. The two directions are exact mirrors against SUSPENSE.
    report(
      JSON.stringify(
        of('wa_inc_fastag').map((r) => [r['ref_source_key'], r['account_code'], r['direction'], r['txn_type']]),
      ) ===
        JSON.stringify([
          ['wallet_adjustment:wa_inc_fastag:suspense_credit', 'SUSPENSE', 'out', 'wallet_adjustment_increase'],
          ['wallet_adjustment:wa_inc_fastag:wallet_debit', 'WALLET_FASTAG', 'in', 'wallet_adjustment_increase'],
        ]),
      'an increase debits the wallet and credits SUSPENSE',
    );
    report(
      JSON.stringify(
        of('wa_dec_fastag').map((r) => [r['ref_source_key'], r['account_code'], r['direction'], r['txn_type']]),
      ) ===
        JSON.stringify([
          ['wallet_adjustment:wa_dec_fastag:suspense_debit', 'SUSPENSE', 'in', 'wallet_adjustment_decrease'],
          ['wallet_adjustment:wa_dec_fastag:wallet_credit', 'WALLET_FASTAG', 'out', 'wallet_adjustment_decrease'],
        ]),
      'a decrease is the exact mirror',
    );

    // 2. The account code really does come from the document.
    report(
      of('wa_inc_fuel').some((r) => r['account_code'] === 'WALLET_FUEL') &&
        of('wa_code_cash').some((r) => r['account_code'] === 'CASH') &&
        of('wa_code_suspense').every((r) => r['account_code'] === 'SUSPENSE'),
      'the wallet account is read from the document, not a literal',
    );

    // 3. Direction matching is exact — no case folding, no trimming.
    const rejected = ['wa_dir_upper', 'wa_dir_title', 'wa_dir_spaced', 'wa_dir_unknown'];
    report(
      rejected.every((id) => of(id).length === 0),
      'only the exact strings "increase" and "decrease" project',
      rejected.filter((id) => of(id).length > 0).join(', '),
    );

    // 4. The guards this model does NOT have.
    report(
      of('wa_reversed_flag').length === 2 && of('wa_historical_flag').length === 2,
      'is_reversed and is_historical are not guards here — both still project',
    );
    report(
      of('wa_reversal_doc').length === 2,
      'a reversal document projects on its own, with reverses_id ignored',
    );
    report(of('wa_deleted_falsy').length === 2, 'a falsy is_deleted still projects');

    // 5. Narration, including the minus sign and the None case.
    report(
      of('wa_inc_fastag')[0]?.['narration'] === 'Wallet adjustment (+) · Top-up correction',
      'the increase narration carries a plus',
    );
    const dec = String(of('wa_dec_fastag')[0]?.['narration']);
    report(
      dec.codePointAt(19) === 0x2212,
      'the decrease sign is U+2212 MINUS SIGN, not an ASCII hyphen',
      `got codepoint ${dec.codePointAt(19)?.toString(16)} in ${JSON.stringify(dec)}`,
    );
    report(
      of('wa_reason_blank')[0]?.['narration'] === 'Wallet adjustment (+)' &&
        of('wa_reason_missing')[0]?.['narration'] === 'Wallet adjustment (+)' &&
        of('wa_reason_dot')[0]?.['narration'] === 'Wallet adjustment (+)',
      'an empty, absent or bare-separator reason strips back to the stem',
    );
    report(
      of('wa_reason_null')[0]?.['narration'] === 'Wallet adjustment (+) · None',
      'a reason present as null interpolates as the literal "None"',
      `got ${JSON.stringify(of('wa_reason_null')[0]?.['narration'])}`,
    );
    report(String(of('wa_reason_long')[0]?.['narration']).length === 400, 'the narration caps at 400');

    // 6. No party, trip, vehicle, category or source_key on any leg.
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
      'wallet adjustment legs carry no party, trip, vehicle, category or source_key',
    );

    report(
      of('wa_round_half_even').every((r) => r['amount'] === 2.67),
      'a 2.675 adjustment projects as 2.67 on both legs',
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
