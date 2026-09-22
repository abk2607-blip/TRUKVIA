/**
 * Unit tests for slice 2c units 10 and 11 — `wallet_recharge` and
 * `wallet_transfer`.
 *
 * They are tested together because the interesting thing about them is the
 * CONTRAST: recharge does not guard its wallet code, transfer guards both of
 * its own. Getting that backwards in either direction turns a recorded,
 * retryable failure into a silent no-op, or vice versa.
 *
 * Both also carry an invisible unicode character in their narration, so both
 * have a codepoint assertion.
 */
import { describe, expect, it } from 'vitest';
import {
  PORTED_SOURCE_TYPES,
  projectWalletRecharge,
  projectWalletTransfer,
} from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const wr = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'wr_1',
  amount: 100,
  date: '2026-09-02',
  wallet_code: 'WALLET_FASTAG',
  funding_mode: 'Bank',
  reference: 'TXN-1',
  is_deleted: false,
  ...over,
});

const wt = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'wt_1',
  amount: 100,
  date: '2026-09-02',
  source_wallet_code: 'WALLET_FASTAG',
  destination_wallet_code: 'WALLET_FUEL',
  is_deleted: false,
  ...over,
});

describe('wallet_recharge — the leg shape', () => {
  it('debits the wallet and credits the funding account', () => {
    const legs = projectWalletRecharge(wr({ funding_mode: 'Cash' }));
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['WALLET_FASTAG', 'in', 100],
      ['CASH', 'out', 100],
    ]);
    expect(legs.every((l) => l.txn_type === 'wallet_recharge_in')).toBe(true);
    expect(legs.map((l) => l.ref_source_key)).toEqual([
      'wallet_recharge:wr_1:wallet_debit',
      'wallet_recharge:wr_1:funding_credit',
    ]);
  });

  it.each([
    ['Bank', 'BANK_DEFAULT'],
    ['Cash', 'CASH'],
    ['Crypto', 'BANK_DEFAULT'],
    ['', 'BANK_DEFAULT'],
  ])('funding mode %j resolves to %s', (funding_mode, code) => {
    expect(projectWalletRecharge(wr({ funding_mode }))[1]?.account_code).toBe(code);
  });
});

describe('wallet_recharge — NO guard on wallet_code', () => {
  it.each(['', null, undefined, 'WALLET_MYSTERY', 7])(
    'still emits legs for wallet_code %j, leaving the failure to the persist layer',
    (wallet_code) => {
      // This is the whole point of the unit. Python does not skip these — it
      // builds a leg whose account_code cannot be resolved, and _persist_legs
      // raises, which the hook records in fin_hook_failures. Guarding here
      // would convert a retryable failure into a silent no-op.
      const legs = projectWalletRecharge(wr({ wallet_code }));
      expect(legs).toHaveLength(2);
    },
  );

  it('carries the unresolvable code through verbatim', () => {
    expect(projectWalletRecharge(wr({ wallet_code: '' }))[0]?.account_code).toBe('');
    expect(projectWalletRecharge(wr({ wallet_code: 'WALLET_MYSTERY' }))[0]?.account_code).toBe(
      'WALLET_MYSTERY',
    );
  });

  it('lets a real guard fire first, so no failure is produced', () => {
    // is_deleted and the amount are checked BEFORE the code is read.
    expect(projectWalletRecharge(wr({ wallet_code: '', amount: 0 }))).toEqual([]);
    expect(projectWalletRecharge(wr({ wallet_code: '', is_deleted: true }))).toEqual([]);
  });
});

describe('wallet_transfer — guards BOTH codes, unlike recharge', () => {
  it('projects a normal transfer', () => {
    const legs = projectWalletTransfer(wt());
    expect(legs.map((l) => [l.account_code, l.direction])).toEqual([
      ['WALLET_FASTAG', 'out'],
      ['WALLET_FUEL', 'in'],
    ]);
    expect(legs.map((l) => l.ref_source_key)).toEqual([
      'wallet_transfer:wt_1:src_credit',
      'wallet_transfer:wt_1:dst_debit',
    ]);
  });

  it.each([
    ['source empty', { source_wallet_code: '' }],
    ['destination empty', { destination_wallet_code: '' }],
    ['source absent', { source_wallet_code: undefined }],
    ['destination absent', { destination_wallet_code: undefined }],
    ['source null', { source_wallet_code: null }],
    ['destination null', { destination_wallet_code: null }],
    ['same wallet', { destination_wallet_code: 'WALLET_FASTAG' }],
  ])('projects nothing when the %s', (_name, over) => {
    expect(projectWalletTransfer(wt(over))).toEqual([]);
  });

  it('still lets an unknown-but-non-empty code through to fail at persist', () => {
    // The guard is on emptiness and sameness, NOT on membership. An unknown
    // destination must not be silently dropped.
    expect(projectWalletTransfer(wt({ destination_wallet_code: 'WALLET_MYSTERY' }))).toHaveLength(2);
    expect(projectWalletTransfer(wt({ source_wallet_code: 'AAA', destination_wallet_code: 'BBB' }))).toHaveLength(
      2,
    );
  });

  it('is the contrast with recharge, stated directly', () => {
    // recharge: no code guard -> legs. transfer: code guard -> no legs.
    expect(projectWalletRecharge(wr({ wallet_code: '' }))).toHaveLength(2);
    expect(projectWalletTransfer(wt({ source_wallet_code: '' }))).toEqual([]);
  });
});

describe('shared guard behaviour', () => {
  it.each([
    ['deleted', { is_deleted: true }],
    ['zero amount', { amount: 0 }],
    ['negative amount', { amount: -50 }],
    ['null amount', { amount: null }],
    ['missing amount', { amount: undefined }],
    ['amount rounding to zero', { amount: 0.004 }],
  ])('both projections skip a %s document', (_name, over) => {
    expect(projectWalletRecharge(wr(over))).toEqual([]);
    expect(projectWalletTransfer(wt(over))).toEqual([]);
  });

  it('neither has an is_historical or is_reversed guard', () => {
    expect(projectWalletRecharge(wr({ is_historical: true, is_reversed: true }))).toHaveLength(2);
    expect(projectWalletTransfer(wt({ is_historical: true, is_reversed: true }))).toHaveLength(2);
  });

  it('both round half-to-even on the true binary value', () => {
    for (const [amount, expected] of [
      [2.675, 2.67],
      [0.125, 0.12],
      [0.375, 0.38],
      [1.005, 1.0],
      ['750.25', 750.25],
    ] as Array<[unknown, number]>) {
      expect(projectWalletRecharge(wr({ amount })).map((l) => l.amount)).toEqual([expected, expected]);
      expect(projectWalletTransfer(wt({ amount })).map((l) => l.amount)).toEqual([expected, expected]);
    }
  });

  it('neither carries a party, trip, vehicle, category or source_key', () => {
    for (const legs of [projectWalletRecharge(wr()), projectWalletTransfer(wt())]) {
      expect(
        legs.every(
          (l) =>
            l.party_type === '' &&
            l.party_id === '' &&
            l.trip_id === '' &&
            l.vehicle_id === '' &&
            l.category === '' &&
            l.source_key === '',
        ),
      ).toBe(true);
    }
  });
});

describe('narration — two invisible characters', () => {
  it('recharge names the reference and strips a dangling separator', () => {
    expect(projectWalletRecharge(wr())[0]?.narration).toBe('Wallet recharge · TXN-1');
    for (const reference of ['', undefined, '·']) {
      expect(projectWalletRecharge(wr({ reference }))[0]?.narration).toBe('Wallet recharge');
    }
  });

  it('recharge interpolates a reference present as null into the literal "None"', () => {
    expect(projectWalletRecharge(wr({ reference: null }))[0]?.narration).toBe('Wallet recharge · None');
  });

  it('recharge caps at 400 characters', () => {
    expect(projectWalletRecharge(wr({ reference: 'R'.repeat(500) }))[0]?.narration).toHaveLength(400);
  });

  it('transfer uses U+2192 RIGHTWARDS ARROW, not "->"', () => {
    const n = String(projectWalletTransfer(wt())[0]?.narration);
    expect(n).toBe('Wallet transfer WALLET_FASTAG → WALLET_FUEL');
    expect(n.codePointAt(30)).toBe(0x2192);
    expect(n).not.toContain('->');
  });

  it('transfer does NOT strip its narration', () => {
    // There is no .strip(" ·") on this one; the codes are always non-empty by
    // the time the narration is built, so there is nothing to strip anyway.
    expect(projectWalletTransfer(wt({ source_wallet_code: 'A', destination_wallet_code: 'B' }))[0]
      ?.narration).toBe('Wallet transfer A → B');
  });
});

describe('registration', () => {
  it('both join the ported list', () => {
    expect([...PORTED_SOURCE_TYPES]).toContain('wallet_recharge');
    expect([...PORTED_SOURCE_TYPES]).toContain('wallet_transfer');
  });

  // The full "nothing is left with Python" check lives in
  // test/fin-invoice-projection.test.ts, which ports the last source type.
  it('both are reachable through the hook', () => {
    expect(SUPPORTED_SOURCE_TYPES).toContain('wallet_recharge');
    expect(SUPPORTED_SOURCE_TYPES).toContain('wallet_transfer');
  });
});
