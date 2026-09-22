/**
 * Unit tests for slice 2c unit 9 — the `trip_customer_receipt` projection.
 *
 * The source document is the TRIP; each embedded receipt becomes its own
 * compound source id, `{trip_id}:{receipt_id}`. The behaviour most worth
 * pinning is the key fallback: a legacy receipt with no id is keyed by its
 * ARRAY POSITION, and a skipped receipt must not renumber the ones after it.
 * Filtering before enumerating would rewrite every downstream key and quietly
 * break idempotency.
 */
import { describe, expect, it } from 'vitest';
import { PORTED_SOURCE_TYPES, projectTripCustomerReceipts } from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const trip = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'trip_1',
  customer_id: 'cust_1',
  date: '2026-09-01',
  is_historical: false,
  customer_receipts: [{ id: 'r1', amount: 100 }],
  ...over,
});

const idsOf = (t: Record<string, unknown>): string[] => [
  ...new Set(projectTripCustomerReceipts(t).map((l) => l.source_id)),
];

describe('the leg shape', () => {
  it('debits the bank and credits CUSTOMER_ADVANCE', () => {
    const legs = projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'r1', amount: 100, mode: 'Cash' }] }));
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['CASH', 'in', 100],
      ['CUSTOMER_ADVANCE', 'out', 100],
    ]);
    expect(legs.map((l) => l.counter_account_code)).toEqual(['CUSTOMER_ADVANCE', 'CASH']);
  });

  it('builds a compound source id and the ref legs', () => {
    const legs = projectTripCustomerReceipts(trip());
    expect(legs.every((l) => l.source_id === 'trip_1:r1')).toBe(true);
    expect(legs.map((l) => l.ref_source_key)).toEqual([
      'trip_customer_receipt:trip_1:r1:bank_debit',
      'trip_customer_receipt:trip_1:r1:cust_adv_credit',
    ]);
  });

  it('carries the customer and the trip on every leg', () => {
    const legs = projectTripCustomerReceipts(trip());
    expect(legs.every((l) => l.party_type === 'customer' && l.party_id === 'cust_1')).toBe(true);
    expect(legs.every((l) => l.trip_id === 'trip_1')).toBe(true);
  });

  it('emits two legs per projected receipt', () => {
    expect(
      projectTripCustomerReceipts(
        trip({ customer_receipts: [{ id: 'a', amount: 1 }, { id: 'b', amount: 2 }, { id: 'c', amount: 3 }] }),
      ),
    ).toHaveLength(6);
  });
});

describe('the array-position key fallback', () => {
  it('keys a receipt with no id by its index', () => {
    expect(idsOf(trip({ customer_receipts: [{ amount: 100 }] }))).toEqual(['trip_1:idx0']);
  });

  it('treats a blank or whitespace id as absent', () => {
    expect(idsOf(trip({ customer_receipts: [{ id: '   ', amount: 100 }] }))).toEqual(['trip_1:idx0']);
    expect(idsOf(trip({ customer_receipts: [{ id: '', amount: 100 }] }))).toEqual(['trip_1:idx0']);
  });

  it('does NOT renumber after a skipped receipt', () => {
    // The single most important assertion in this file: idx0 and idx2, never
    // idx0 and idx1. Renumbering would rewrite the key of every receipt after
    // a skipped one and break idempotency on the next reproject.
    expect(idsOf(trip({ customer_receipts: [{ amount: 100 }, { amount: 0 }, { amount: 50 }] }))).toEqual([
      'trip_1:idx0',
      'trip_1:idx2',
    ]);
  });

  it('lets explicit ids and index fallbacks coexist at their own positions', () => {
    expect(
      idsOf(trip({ customer_receipts: [{ amount: 10 }, { id: 'x', amount: 20 }, { amount: 30 }] })),
    ).toEqual(['trip_1:idx0', 'trip_1:x', 'trip_1:idx2']);
  });

  it('trims a padded id rather than falling back', () => {
    expect(idsOf(trip({ customer_receipts: [{ id: '  r9  ', amount: 1 }] }))).toEqual(['trip_1:r9']);
  });
});

describe('a bad receipt is skipped, not fatal', () => {
  it.each([
    ['zero', 0],
    ['negative', -5],
    ['null', null],
    ['missing', undefined],
    ['rounding to zero', 0.004],
  ])('skips a %s amount and keeps the rest', (_name, amount) => {
    const legs = projectTripCustomerReceipts(
      trip({ customer_receipts: [{ id: 'bad', amount }, { id: 'good', amount: 25 }] }),
    );
    expect(legs).toHaveLength(2);
    expect(legs[0]?.source_id).toBe('trip_1:good');
  });

  it('projects nothing when every receipt is invalid', () => {
    expect(
      projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'a', amount: 0 }, { id: 'b', amount: -1 }] })),
    ).toEqual([]);
  });
});

describe('receipt type drives txn_type and category', () => {
  it.each([
    ['advance', 'trip_customer_advance_receipt'],
    ['diesel', 'trip_customer_diesel_receipt'],
    ['custom_thing', 'trip_customer_custom_thing_receipt'],
  ])('type %s gives %s', (type, txnType) => {
    const legs = projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'r', amount: 1, type }] }));
    expect(legs.every((l) => l.txn_type === txnType && l.category === type)).toBe(true);
  });

  it('defaults a missing or blank type to advance', () => {
    for (const type of [undefined, '', null]) {
      const legs = projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'r', amount: 1, type }] }));
      expect(legs[0]?.txn_type).toBe('trip_customer_advance_receipt');
      expect(legs[0]?.category).toBe('advance');
    }
  });

  it('names the type in the narration', () => {
    expect(projectTripCustomerReceipts(trip())[0]?.narration).toBe('Trip customer advance receipt');
    expect(
      projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'r', amount: 1, type: 'diesel' }] }))[0]
        ?.narration,
    ).toBe('Trip customer diesel receipt');
  });
});

describe('mode and date resolution', () => {
  it.each([
    ['Cash', 'CASH'],
    ['Bank', 'BANK_DEFAULT'],
    ['UPI', 'BANK_DEFAULT'],
    ['Crypto', 'BANK_DEFAULT'],
    ['', 'BANK_DEFAULT'],
  ])('mode %j resolves to %s', (mode, code) => {
    expect(projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'r', amount: 1, mode }] }))[0]
      ?.account_code).toBe(code);
  });

  it('prefers the receipt date, then the trip date, then empty', () => {
    expect(
      projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'r', amount: 1, date: '2026-09-05' }] }))[0]
        ?.txn_date,
    ).toBe('2026-09-05');
    expect(projectTripCustomerReceipts(trip())[0]?.txn_date).toBe('2026-09-01');
    expect(
      projectTripCustomerReceipts(trip({ date: undefined, customer_receipts: [{ id: 'r', amount: 1 }] }))[0]
        ?.txn_date,
    ).toBe('');
  });
});

describe('trip-level guards', () => {
  it('skips a historical trip entirely', () => {
    expect(projectTripCustomerReceipts(trip({ is_historical: true }))).toEqual([]);
  });

  it('still projects when is_historical is falsy', () => {
    for (const is_historical of [false, 0, '', null, undefined]) {
      expect(projectTripCustomerReceipts(trip({ is_historical }))).toHaveLength(2);
    }
  });

  it('has NO is_deleted guard on the trip', () => {
    expect(projectTripCustomerReceipts(trip({ is_deleted: true }))).toHaveLength(2);
  });

  it('projects nothing for an empty, absent or non-array receipts field', () => {
    for (const customer_receipts of [[], undefined, null, 'nope', 0]) {
      expect(projectTripCustomerReceipts(trip({ customer_receipts }))).toEqual([]);
    }
  });

  it('leaves party_id empty when the trip has no customer', () => {
    expect(projectTripCustomerReceipts(trip({ customer_id: undefined }))[0]?.party_id).toBe('');
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
      expect(
        projectTripCustomerReceipts(trip({ customer_receipts: [{ id: 'r', amount }] })).map((l) => l.amount),
      ).toEqual([expected, expected]);
    }
  });
});

describe('registration', () => {
  it('joins the ported list', () => {
    expect([...PORTED_SOURCE_TYPES]).toContain('trip_customer_receipt');
  });

  it('is no longer among the types Python owns', () => {
    // The exact remaining list lives in the NEWEST slice's tests.
    const unported = SUPPORTED_SOURCE_TYPES.filter(
      (t) => !(PORTED_SOURCE_TYPES as readonly string[]).includes(t),
    );
    expect(unported).not.toContain('trip_customer_receipt');
  });
});
