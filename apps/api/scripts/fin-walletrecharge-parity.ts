/**
 * Focused parity for slice 2c unit 10 — the `wallet_recharge` projection.
 *
 *   npx tsx scripts/fin-walletrecharge-parity.ts
 *
 * The point of this run is the distinction wallet_adjustment does NOT have:
 *
 *   projection guard (is_deleted, amount <= 0)   -> zero legs, ok=true
 *   persistence lookup failure (bad wallet_code) -> RAISES -> ok=false and a
 *                                                   fin_hook_failures row
 *
 * There is no guard on wallet_code here, so an empty or unknown code produces
 * legs that then fail to persist. `expectedFailures` tells the harness those
 * ids are meant to fail, and the resulting queue rows are compared between the
 * two sides — because a recorded, retryable failure silently becoming a no-op
 * is exactly what the hook queue exists to catch.
 */
export {}; // keeps this a module, so it does not share scope with the other scripts

import { runProjectionParity, type Doc } from './lib/projection-parity';

const UID = 'user_wrparity';
const CID = 'co_wrparity';
/** A second tenant, to prove one scope cannot project another's document. */
const UID2 = 'user_wrparity_other';
const CID2 = 'co_wrparity_other';

const wr = (over: Doc): Doc => ({
  user_id: UID,
  company_id: CID,
  amount: 100,
  date: '2026-09-02',
  wallet_code: 'WALLET_FASTAG',
  funding_mode: 'Bank',
  reference: 'TXN-1',
  is_deleted: false,
  ...over,
});

const documents: Doc[] = [
  // ── A. valid seeded wallet accounts ──────────────────────────────────
  wr({ id: 'wr_fastag' }),
  wr({ id: 'wr_fuel', wallet_code: 'WALLET_FUEL' }),

  // ── B/C/D/E. wallet codes that reach the persist layer and FAIL ──────
  wr({ id: 'wr_code_empty', wallet_code: '' }),
  wr({ id: 'wr_code_missing', wallet_code: undefined }),
  wr({ id: 'wr_code_null', wallet_code: null }),
  wr({ id: 'wr_code_unknown', wallet_code: 'WALLET_MYSTERY' }),
  wr({ id: 'wr_code_number', wallet_code: 7 }), // legacy non-string

  // ── funding mode resolution ──────────────────────────────────────────
  wr({ id: 'wr_fund_bank', funding_mode: 'Bank' }),
  wr({ id: 'wr_fund_cash', funding_mode: 'Cash' }),
  wr({ id: 'wr_fund_unknown', funding_mode: 'Crypto' }), // -> BANK_DEFAULT
  wr({ id: 'wr_fund_blank', funding_mode: '' }), // falsy -> "Bank"
  wr({ id: 'wr_fund_missing', funding_mode: undefined }),

  // ── guards: only is_deleted and the amount ───────────────────────────
  wr({ id: 'wr_deleted', is_deleted: true }),
  wr({ id: 'wr_deleted_falsy', is_deleted: 0 }),
  wr({ id: 'wr_historical', is_historical: true }), // NO guard -> projects
  wr({ id: 'wr_reversed', is_reversed: true }), // NO guard -> projects
  wr({ id: 'wr_zero', amount: 0 }),
  wr({ id: 'wr_negative', amount: -50 }),
  wr({ id: 'wr_null_amount', amount: null }),
  wr({ id: 'wr_missing_amount', amount: undefined }),
  wr({ id: 'wr_tiny', amount: 0.004 }),
  // A bad code AND a zero amount: the guard wins, so no failure is recorded.
  wr({ id: 'wr_bad_code_zero_amount', wallet_code: '', amount: 0 }),

  // ── money ────────────────────────────────────────────────────────────
  wr({ id: 'wr_round', amount: 2.675 }),
  wr({ id: 'wr_tie', amount: 0.125 }),
  wr({ id: 'wr_tie_up', amount: 0.375 }),
  wr({ id: 'wr_below', amount: 1.005 }),
  wr({ id: 'wr_string_amt', amount: '750.25' }),
  wr({ id: 'wr_big', amount: 98765432.1 }),

  // ── narration, from `reference` ──────────────────────────────────────
  wr({ id: 'wr_ref_blank', reference: '' }),
  wr({ id: 'wr_ref_missing', reference: undefined }),
  wr({ id: 'wr_ref_null', reference: null }), // -> the literal "None"
  wr({ id: 'wr_ref_long', reference: 'R'.repeat(500) }),
  wr({ id: 'wr_ref_unicode', reference: 'रिचार्ज · 数' }),
  wr({ id: 'wr_missing_date', date: undefined }),

  // ── F. a second tenant holding the SAME id ───────────────────────────
  wr({ id: 'wr_fastag', user_id: UID2, company_id: CID2, amount: 4242, reference: 'OTHER' }),
];

void runProjectionParity({
  sourceType: 'wallet_recharge',
  collection: 'wallet_recharges',
  slug: 'wr',
  nestPort: 8501,
  documents,
  // These reach the persist layer with an unresolvable account code.
  expectedFailures: [
    'wr_code_empty',
    'wr_code_missing',
    'wr_code_null',
    'wr_code_unknown',
    'wr_code_number',
  ],
  zeroLegged: [
    'wr_code_empty',
    'wr_code_missing',
    'wr_code_null',
    'wr_code_unknown',
    'wr_code_number',
    'wr_deleted',
    'wr_zero',
    'wr_negative',
    'wr_null_amount',
    'wr_missing_amount',
    'wr_tiny',
    'wr_bad_code_zero_amount',
  ],
  sharedId: 'wr_fastag',
  verifyRouting: true,
  extraChecks: (rows, report) => {
    const of = (id: string): Doc[] =>
      rows
        .filter((r) => r['source_id'] === id && r['user_id'] === UID)
        .sort((a, b) => String(a['ref_source_key']).localeCompare(String(b['ref_source_key'])));

    // 1. The leg shape: wallet debited, funding account credited.
    report(
      JSON.stringify(
        of('wr_fastag').map((r) => [r['ref_source_key'], r['account_code'], r['direction'], r['txn_type']]),
      ) ===
        JSON.stringify([
          ['wallet_recharge:wr_fastag:funding_credit', 'BANK_DEFAULT', 'out', 'wallet_recharge_in'],
          ['wallet_recharge:wr_fastag:wallet_debit', 'WALLET_FASTAG', 'in', 'wallet_recharge_in'],
        ]),
      'a recharge debits the wallet and credits the funding account',
    );
    report(
      of('wr_fuel').some((r) => r['account_code'] === 'WALLET_FUEL'),
      'the wallet account is read from the document',
    );

    // 2. The projection-vs-persistence distinction, both halves.
    const failed = ['wr_code_empty', 'wr_code_missing', 'wr_code_null', 'wr_code_unknown', 'wr_code_number'];
    report(
      failed.every((id) => of(id).length === 0),
      'a document with an unresolvable wallet code writes NO ledger rows',
      failed.filter((id) => of(id).length > 0).join(', '),
    );
    report(
      of('wr_bad_code_zero_amount').length === 0,
      'a guard that fires first prevents the failure entirely',
    );

    // 3. Funding mode resolution.
    report(
      of('wr_fund_cash').some((r) => r['account_code'] === 'CASH'),
      'funding mode Cash resolves to CASH',
    );
    report(
      ['wr_fund_unknown', 'wr_fund_blank', 'wr_fund_missing'].every((id) =>
        of(id).some((r) => r['account_code'] === 'BANK_DEFAULT'),
      ),
      'an unknown, blank or absent funding mode resolves to BANK_DEFAULT',
    );

    // 4. The guards this projection does NOT have.
    report(
      of('wr_historical').length === 2 && of('wr_reversed').length === 2,
      'is_historical and is_reversed are not guards here — both still project',
    );
    report(of('wr_deleted_falsy').length === 2, 'a falsy is_deleted still projects');

    // 5. Narration, from `reference`.
    report(of('wr_fastag')[0]?.['narration'] === 'Wallet recharge · TXN-1', 'the narration names the reference');
    report(
      of('wr_ref_blank')[0]?.['narration'] === 'Wallet recharge' &&
        of('wr_ref_missing')[0]?.['narration'] === 'Wallet recharge',
      'an empty or absent reference strips back to the stem',
    );
    report(
      of('wr_ref_null')[0]?.['narration'] === 'Wallet recharge · None',
      'a reference present as null interpolates as the literal "None"',
      `got ${JSON.stringify(of('wr_ref_null')[0]?.['narration'])}`,
    );
    report(String(of('wr_ref_long')[0]?.['narration']).length === 400, 'the narration caps at 400');

    report(
      of('wr_round').every((r) => r['amount'] === 2.67),
      'a 2.675 recharge projects as 2.67 on both legs',
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
