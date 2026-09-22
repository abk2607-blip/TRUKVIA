/**
 * Unit tests for slice 2c unit 8 — the `wallet_adjustment` projection.
 *
 * A real financial adjustment booked against SUSPENSE, so the correction stays
 * visible on both sides instead of vanishing into the wallet.
 *
 * This is the first ported projection whose ACCOUNT CODE comes from the
 * document, so that gets the most attention — along with two details that are
 * invisible to the eye and would break byte parity silently: the sign is
 * U+2212 MINUS SIGN, and a `reason` present as null interpolates as the
 * literal text "None".
 */
import { describe, expect, it } from 'vitest';
import { PORTED_SOURCE_TYPES, projectWalletAdjustment } from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const wa = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'wa_1',
  amount: 100,
  date: '2026-09-02',
  wallet_code: 'WALLET_FASTAG',
  direction: 'increase',
  reason: 'Top-up correction',
  is_deleted: false,
  ...over,
});

describe('the two directions are exact mirrors against SUSPENSE', () => {
  it('an increase debits the wallet and credits SUSPENSE', () => {
    const legs = projectWalletAdjustment(wa());
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['WALLET_FASTAG', 'in', 100],
      ['SUSPENSE', 'out', 100],
    ]);
    expect(legs.map((l) => l.counter_account_code)).toEqual(['SUSPENSE', 'WALLET_FASTAG']);
    expect(legs.every((l) => l.txn_type === 'wallet_adjustment_increase')).toBe(true);
    expect(legs.map((l) => l.ref_source_key)).toEqual([
      'wallet_adjustment:wa_1:wallet_debit',
      'wallet_adjustment:wa_1:suspense_credit',
    ]);
  });

  it('a decrease credits the wallet and debits SUSPENSE', () => {
    const legs = projectWalletAdjustment(wa({ direction: 'decrease' }));
    expect(legs.map((l) => [l.account_code, l.direction])).toEqual([
      ['WALLET_FASTAG', 'out'],
      ['SUSPENSE', 'in'],
    ]);
    expect(legs.every((l) => l.txn_type === 'wallet_adjustment_decrease')).toBe(true);
    expect(legs.map((l) => l.ref_source_key)).toEqual([
      'wallet_adjustment:wa_1:wallet_credit',
      'wallet_adjustment:wa_1:suspense_debit',
    ]);
  });
});

describe('the account code comes from the document', () => {
  it.each(['WALLET_FASTAG', 'WALLET_FUEL', 'CASH', 'SUSPENSE', 'WALLET_MYSTERY'])(
    'uses %s verbatim as the wallet leg account',
    (wallet_code) => {
      // The projection does not restrict the code to wallet accounts. One that
      // is not in the seed catalog passes this guard and then makes the
      // PERSIST layer raise, which the hook records as a failure — it is not
      // silently skipped here.
      expect(projectWalletAdjustment(wa({ wallet_code }))[0]?.account_code).toBe(wallet_code);
    },
  );

  it('self-guards an empty, absent or null wallet_code', () => {
    for (const wallet_code of ['', undefined, null]) {
      expect(projectWalletAdjustment(wa({ wallet_code }))).toEqual([]);
    }
  });

  it('never names an account the counter leg does not mirror', () => {
    const legs = projectWalletAdjustment(wa({ wallet_code: 'WALLET_FUEL' }));
    expect(legs[0]?.counter_account_code).toBe('SUSPENSE');
    expect(legs[1]?.counter_account_code).toBe('WALLET_FUEL');
  });
});

describe('direction matching is exact', () => {
  it.each(['increase', 'decrease'])('accepts %j', (direction) => {
    expect(projectWalletAdjustment(wa({ direction }))).toHaveLength(2);
  });

  it.each(['INCREASE', 'Increase', 'increase ', ' increase', 'up', 'inc', 'DECREASE'])(
    'rejects %j — no case folding and no trimming',
    (direction) => {
      expect(projectWalletAdjustment(wa({ direction }))).toEqual([]);
    },
  );

  it.each([undefined, null, '', 0, false])('rejects falsy %j', (direction) => {
    expect(projectWalletAdjustment(wa({ direction }))).toEqual([]);
  });
});

describe('guards', () => {
  it.each([
    ['deleted', { is_deleted: true }],
    ['zero amount', { amount: 0 }],
    ['negative amount', { amount: -50 }],
    ['null amount', { amount: null }],
    ['missing amount', { amount: undefined }],
    ['amount rounding to zero', { amount: 0.004 }],
  ])('projects nothing for a %s adjustment', (_name, over) => {
    expect(projectWalletAdjustment(wa(over))).toEqual([]);
  });

  it('still projects when is_deleted is falsy', () => {
    for (const is_deleted of [false, 0, '', null, undefined]) {
      expect(projectWalletAdjustment(wa({ is_deleted }))).toHaveLength(2);
    }
  });

  it('has NO is_reversed or is_historical guard', () => {
    // Neither field exists on the WalletAdjustment model. A reversal is a
    // SEPARATE document with the opposite direction, and both stay projected
    // for a net-zero effect with the history intact.
    expect(projectWalletAdjustment(wa({ is_reversed: true }))).toHaveLength(2);
    expect(projectWalletAdjustment(wa({ is_historical: true }))).toHaveLength(2);
  });

  it('ignores reverses_id entirely', () => {
    const legs = projectWalletAdjustment(wa({ direction: 'decrease', reverses_id: 'wa_original' }));
    expect(legs).toHaveLength(2);
    expect(legs[0]?.txn_type).toBe('wallet_adjustment_decrease');
  });
});

describe('narration', () => {
  it('carries a plus for an increase', () => {
    expect(projectWalletAdjustment(wa())[0]?.narration).toBe('Wallet adjustment (+) · Top-up correction');
  });

  it('uses U+2212 MINUS SIGN for a decrease, not an ASCII hyphen', () => {
    const n = String(projectWalletAdjustment(wa({ direction: 'decrease' }))[0]?.narration);
    expect(n.codePointAt(19)).toBe(0x2212);
    // Spelled out so a find-and-replace cannot quietly "fix" it to '-'.
    expect(n).toBe('Wallet adjustment (−) · Top-up correction');
    expect(n).not.toContain('(-)');
  });

  it('strips back to the stem for an empty, absent or bare-separator reason', () => {
    for (const reason of ['', undefined, '·', ' · ']) {
      expect(projectWalletAdjustment(wa({ reason }))[0]?.narration).toBe('Wallet adjustment (+)');
    }
  });

  it('interpolates a reason present as null into the literal "None"', () => {
    // Python's .get("reason", "") default only applies to an ABSENT key. A key
    // present with value None interpolates as "None", and that text reaches
    // the day-book. Coercing it to "" would silently lose the difference.
    expect(projectWalletAdjustment(wa({ reason: null }))[0]?.narration).toBe(
      'Wallet adjustment (+) · None',
    );
  });

  it('renders other non-string reasons the way Python does', () => {
    expect(projectWalletAdjustment(wa({ reason: 5 }))[0]?.narration).toBe('Wallet adjustment (+) · 5');
    expect(projectWalletAdjustment(wa({ reason: true }))[0]?.narration).toBe('Wallet adjustment (+) · True');
    expect(projectWalletAdjustment(wa({ reason: false }))[0]?.narration).toBe('Wallet adjustment (+) · False');
  });

  it('caps at 400 characters', () => {
    expect(projectWalletAdjustment(wa({ reason: 'R'.repeat(500) }))[0]?.narration).toHaveLength(400);
  });
});

describe('fields', () => {
  it('carries no party, trip, vehicle, category or source_key', () => {
    const legs = projectWalletAdjustment(wa({ trip_id: 'trip_9', vehicle_id: 'veh_9', category: 'x' }));
    expect(
      legs.every(
        (l) =>
          l.party_type === '' &&
          l.party_id === '' &&
          l.party_name === '' &&
          l.trip_id === '' &&
          l.vehicle_id === '' &&
          l.category === '' &&
          l.source_key === '',
      ),
    ).toBe(true);
  });

  it('empties an absent date rather than dropping the leg', () => {
    const legs = projectWalletAdjustment(wa({ date: undefined }));
    expect(legs).toHaveLength(2);
    expect(legs[0]?.txn_date).toBe('');
  });

  it('never flags is_supplier_settlement_recovery', () => {
    expect(projectWalletAdjustment(wa()).every((l) => l.is_supplier_settlement_recovery === false)).toBe(
      true,
    );
  });
});

describe('rounding', () => {
  it('rounds half-to-even on the true binary value, on both legs', () => {
    for (const [amount, expected] of [
      [2.675, 2.67],
      [0.125, 0.12],
      [0.375, 0.38],
      [1.005, 1.0],
      ['750.25', 750.25],
    ] as Array<[unknown, number]>) {
      expect(projectWalletAdjustment(wa({ amount })).map((l) => l.amount)).toEqual([expected, expected]);
    }
  });
});

describe('registration', () => {
  it('joins the ported list', () => {
    expect([...PORTED_SOURCE_TYPES]).toContain('wallet_adjustment');
    // The exact remaining list lives in the NEWEST slice's tests.
    const unported = SUPPORTED_SOURCE_TYPES.filter(
      (t) => !(PORTED_SOURCE_TYPES as readonly string[]).includes(t),
    );
    expect(unported).not.toContain('wallet_adjustment');
  });
});
