/**
 * Unit tests for slice 2c unit 6 — the `expense` projection.
 *
 * Expenses are roughly 79% of existing ledger rows, so this is the projection
 * where a quietly wrong branch costs the most. The whole routing chain is
 * walked here rather than sampled, and the two traps are tested in BOTH
 * directions: the fall-through when a supplier-owned vehicle has an unnamed
 * mode, and the `bool()` truthiness that makes the string "false" select the
 * supplier branch.
 *
 * Ledger values are compared against the real Python implementation in
 * scripts/fin-expense-parity.ts.
 */
import { describe, expect, it } from 'vitest';
import { PORTED_SOURCE_TYPES, projectExpense } from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const expense = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'exp_1',
  amount: 1000,
  date: '2026-09-02',
  category: 'fuel',
  narration: 'Diesel top-up',
  is_deleted: false,
  is_reversed: false,
  is_historical: false,
  ...over,
});

/** [credit account, txn_type] of a projected expense. */
const routeOf = (over: Record<string, unknown>): [string, string] => {
  const legs = projectExpense(expense(over));
  const credit = legs[1];
  return [String(credit?.account_code), String(credit?.txn_type)];
};

describe('the routing chain, rule by rule', () => {
  it.each([
    [
      'supplier settlement adjustment',
      { supplier_owned_vehicle: true, supplier_settlement_mode: 'supplier_settlement_adjustment' },
      ['AP_SUPPLIER', 'expense_supplier_settlement_recovery'],
    ],
    [
      'company borne',
      { supplier_owned_vehicle: true, supplier_settlement_mode: 'company_borne' },
      ['CASH', 'expense_company_borne'],
    ],
    ['fastag import', { source_type: 'fastag_import' }, ['WALLET_FASTAG', 'expense_fastag_toll']],
    ['fleet card import', { source_type: 'fleet_card_import' }, ['WALLET_FUEL', 'expense_fleet_diesel']],
    ['vendor bill', { vendor_bill_id: 'vbl_1' }, ['AP_VENDOR', 'expense_vendor_payable']],
    ['work order', { mechanic_work_order_id: 'wo_1' }, ['AP_MECHANIC', 'expense_mechanic_payable']],
    ['cash now', { settlement_mode: 'cash_now' }, ['CASH', 'expense_cash_now']],
    ['fallback', {}, ['SUSPENSE', 'expense_unrouted']],
  ])('routes %s', (_name, over, expected) => {
    expect(routeOf(over as Record<string, unknown>)).toEqual(expected);
  });

  it('falls back to SUSPENSE for an unknown or absent settlement mode', () => {
    expect(routeOf({ settlement_mode: 'payable' })).toEqual(['SUSPENSE', 'expense_unrouted']);
    expect(routeOf({ settlement_mode: undefined })).toEqual(['SUSPENSE', 'expense_unrouted']);
    expect(routeOf({ settlement_mode: '' })).toEqual(['SUSPENSE', 'expense_unrouted']);
  });
});

describe('precedence — first match wins', () => {
  it('puts the settlement recovery above everything else', () => {
    expect(
      routeOf({
        supplier_owned_vehicle: true,
        supplier_settlement_mode: 'supplier_settlement_adjustment',
        source_type: 'fastag_import',
        vendor_bill_id: 'vbl_1',
        mechanic_work_order_id: 'wo_1',
        settlement_mode: 'cash_now',
      }),
    ).toEqual(['AP_SUPPLIER', 'expense_supplier_settlement_recovery']);
  });

  it.each([
    ['fastag over vendor bill', { source_type: 'fastag_import', vendor_bill_id: 'vbl_1' }, 'WALLET_FASTAG'],
    ['vendor bill over work order', { vendor_bill_id: 'vbl_1', mechanic_work_order_id: 'wo_1' }, 'AP_VENDOR'],
    ['work order over cash now', { mechanic_work_order_id: 'wo_1', settlement_mode: 'cash_now' }, 'AP_MECHANIC'],
  ])('%s', (_name, over, code) => {
    expect(routeOf(over as Record<string, unknown>)[0]).toBe(code);
  });
});

describe('the fall-through trap', () => {
  it('lets a supplier-owned vehicle with an unnamed mode fall through', () => {
    // Neither named mode matches, so rules 2-7 still apply — it does NOT get
    // parked on a supplier account.
    expect(routeOf({ supplier_owned_vehicle: true, supplier_settlement_mode: 'weird' })).toEqual([
      'SUSPENSE',
      'expense_unrouted',
    ]);
    expect(
      routeOf({ supplier_owned_vehicle: true, supplier_settlement_mode: 'weird', source_type: 'fastag_import' })[0],
    ).toBe('WALLET_FASTAG');
    expect(routeOf({ supplier_owned_vehicle: true, vendor_bill_id: 'vbl_1' })[0]).toBe('AP_VENDOR');
    expect(routeOf({ supplier_owned_vehicle: true, settlement_mode: 'cash_now' })[0]).toBe('CASH');
  });
});

describe('the bool() trap on supplier_owned_vehicle', () => {
  it.each([true, 1, 'false', 'no', 'x', ['a'], { a: 1 }])(
    'treats truthy %j as supplier-owned',
    (supplier_owned_vehicle) => {
      // Python reads bool(...), not == True. A NON-EMPTY string is truthy, so
      // the literal string "false" selects the branch. A `=== true` test would
      // silently reroute the row to SUSPENSE.
      expect(routeOf({ supplier_owned_vehicle, supplier_settlement_mode: 'company_borne' })).toEqual([
        'CASH',
        'expense_company_borne',
      ]);
    },
  );

  it.each([false, 0, '', null, undefined, []])(
    'treats falsy %j as not supplier-owned',
    (supplier_owned_vehicle) => {
      expect(routeOf({ supplier_owned_vehicle, supplier_settlement_mode: 'company_borne' })).toEqual([
        'SUSPENSE',
        'expense_unrouted',
      ]);
    },
  );
});

describe('leg shape', () => {
  it('always debits EXPENSE_DEFAULT and credits the routed account', () => {
    const legs = projectExpense(expense({ vendor_bill_id: 'vbl_1' }));
    expect(legs).toHaveLength(2);
    expect(legs.map((l) => [l.account_code, l.direction, l.counter_account_code])).toEqual([
      ['EXPENSE_DEFAULT', 'in', 'AP_VENDOR'],
      ['AP_VENDOR', 'out', 'EXPENSE_DEFAULT'],
    ]);
  });

  it('derives the credit leg ref_leg from the account code', () => {
    const cases: Array<[Record<string, unknown>, string]> = [
      [{ supplier_owned_vehicle: true, supplier_settlement_mode: 'supplier_settlement_adjustment' }, 'ap_supplier_credit'],
      [{ source_type: 'fastag_import' }, 'wallet_fastag_credit'],
      [{ source_type: 'fleet_card_import' }, 'wallet_fuel_credit'],
      [{ vendor_bill_id: 'v' }, 'ap_vendor_credit'],
      [{ mechanic_work_order_id: 'w' }, 'ap_mechanic_credit'],
      [{ settlement_mode: 'cash_now' }, 'cash_credit'],
      [{}, 'suspense_credit'],
    ];
    for (const [over, refLeg] of cases) {
      const legs = projectExpense(expense(over));
      expect(legs[0]?.ref_source_key).toBe('expense:exp_1:expense_debit');
      expect(legs[1]?.ref_source_key).toBe(`expense:exp_1:${refLeg}`);
    }
  });

  it('flags is_supplier_settlement_recovery on the CREDIT leg only', () => {
    const legs = projectExpense(
      expense({ supplier_owned_vehicle: true, supplier_settlement_mode: 'supplier_settlement_adjustment' }),
    );
    expect(legs[0]?.is_supplier_settlement_recovery).toBe(false);
    expect(legs[1]?.is_supplier_settlement_recovery).toBe(true);
  });

  it('never flags any other branch', () => {
    for (const over of [{}, { vendor_bill_id: 'v' }, { source_type: 'fastag_import' }, { settlement_mode: 'cash_now' }]) {
      expect(projectExpense(expense(over)).every((l) => l.is_supplier_settlement_recovery === false)).toBe(true);
    }
  });

  it('forces party_type to supplier on a settlement recovery, overriding the document', () => {
    const legs = projectExpense(
      expense({
        supplier_owned_vehicle: true,
        supplier_settlement_mode: 'supplier_settlement_adjustment',
        party_type: 'vendor',
        party_id: 'ven_1',
        party_name: 'Some Vendor',
      }),
    );
    expect(legs.every((l) => l.party_type === 'supplier')).toBe(true);
    // ...but party_id and party_name are left exactly as denormalised.
    expect(legs[0]?.party_id).toBe('ven_1');
    expect(legs[0]?.party_name).toBe('Some Vendor');
  });

  it('keeps the document party_type on every other branch', () => {
    expect(projectExpense(expense({ party_type: 'vendor', vendor_bill_id: 'v' }))[0]?.party_type).toBe('vendor');
  });
});

describe('guards', () => {
  it.each([
    ['deleted', { is_deleted: true }],
    ['reversed', { is_reversed: true }],
    ['historical', { is_historical: true }],
    ['zero amount', { amount: 0 }],
    ['negative amount', { amount: -50 }],
    ['null amount', { amount: null }],
    ['missing amount', { amount: undefined }],
    ['amount rounding to zero', { amount: 0.004 }],
  ])('projects nothing for a %s expense', (_name, over) => {
    expect(projectExpense(expense(over))).toEqual([]);
  });

  it('still projects when the flags are falsy', () => {
    for (const over of [{ is_deleted: 0 }, { is_reversed: '' }, { is_historical: null }]) {
      expect(projectExpense(expense(over))).toHaveLength(2);
    }
  });
});

describe('narration and category', () => {
  it('falls back from narration to category to empty', () => {
    expect(projectExpense(expense({ narration: 'Explicit' }))[0]?.narration).toBe('Explicit');
    expect(projectExpense(expense({ narration: '', category: 'fuel' }))[0]?.narration).toBe('fuel');
    expect(projectExpense(expense({ narration: undefined, category: 'fuel' }))[0]?.narration).toBe('fuel');
    expect(projectExpense(expense({ narration: '', category: '' }))[0]?.narration).toBe('');
  });

  it('caps the narration at 400 but leaves the category field untouched', () => {
    const legs = projectExpense(expense({ narration: '', category: 'C'.repeat(500) }));
    expect(legs[0]?.narration).toHaveLength(400);
    // `category` is emitted raw — only the narration is sliced.
    expect(legs[0]?.category).toHaveLength(500);
  });
});

describe('denormalised fields', () => {
  it('carries source_key, which the party payments never set', () => {
    const legs = projectExpense(expense({ source_key: 'fastag:TXN123' }));
    expect(legs.every((l) => l.source_key === 'fastag:TXN123')).toBe(true);
  });

  it('empties absent fields rather than dropping the leg', () => {
    const legs = projectExpense(
      expense({
        source_key: undefined,
        party_id: undefined,
        party_name: undefined,
        vehicle_id: undefined,
        trip_id: undefined,
        date: undefined,
      }),
    );
    expect(legs).toHaveLength(2);
    expect([legs[0]?.source_key, legs[0]?.party_id, legs[0]?.vehicle_id, legs[0]?.txn_date]).toEqual([
      '',
      '',
      '',
      '',
    ]);
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
      expect(projectExpense(expense({ amount })).map((l) => l.amount)).toEqual([expected, expected]);
    }
  });
});

describe('registration', () => {
  it('joins the ported list', () => {
    expect([...PORTED_SOURCE_TYPES]).toContain('expense');
    // The exact remaining list lives in the NEWEST slice's tests, so porting
    // the next source type does not break this file.
    const unported = SUPPORTED_SOURCE_TYPES.filter(
      (t) => !(PORTED_SOURCE_TYPES as readonly string[]).includes(t),
    );
    expect(unported).not.toContain('expense');
  });
});
