/**
 * Unit tests for slice 2c unit 7 — the `mechanic_work_order` projection.
 *
 * This is an ORPHAN-ONLY projection: it posts legs solely when no paired
 * expense exists, because in the canonical flow the Expense carries the real
 * cost and projecting both would double-count AP_MECHANIC.
 *
 * The pairing lookup itself is a database query, so it is exercised in
 * scripts/fin-workorder-parity.ts against the real collection. What is pinned
 * here is the projection given a pairing answer — including the guards this
 * function does NOT have, which is where it differs from every unit before it.
 */
import { describe, expect, it } from 'vitest';
import { PORTED_SOURCE_TYPES, projectMechanicWorkOrder } from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const wo = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'wo_1',
  amount: 500,
  work_date: '2026-09-02',
  mechanic_id: 'mech_1',
  mechanic_name: 'Ravi',
  vehicle_id: 'veh_1',
  trip_id: 'trip_1',
  is_deleted: false,
  ...over,
});

const unpaired = (over: Record<string, unknown> = {}) => projectMechanicWorkOrder(wo(over), false);

describe('the orphan leg shape', () => {
  it('parks the cost in SUSPENSE against AP_MECHANIC', () => {
    const legs = unpaired();
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['SUSPENSE', 'in', 500],
      ['AP_MECHANIC', 'out', 500],
    ]);
    expect(legs.map((l) => l.counter_account_code)).toEqual(['AP_MECHANIC', 'SUSPENSE']);
    expect(legs.every((l) => l.txn_type === 'mechanic_wo_orphan')).toBe(true);
  });

  it('uses suspense_debit and ap_credit as the ref legs', () => {
    expect(unpaired().map((l) => l.ref_source_key)).toEqual([
      'mechanic_work_order:wo_1:suspense_debit',
      'mechanic_work_order:wo_1:ap_credit',
    ]);
  });

  it('carries the mechanic as the party, with the vehicle and trip', () => {
    const legs = unpaired();
    expect(legs.every((l) => l.party_type === 'mechanic')).toBe(true);
    expect([legs[0]?.party_id, legs[0]?.party_name, legs[0]?.vehicle_id, legs[0]?.trip_id]).toEqual([
      'mech_1',
      'Ravi',
      'veh_1',
      'trip_1',
    ]);
  });

  it('sets no source_key and no category', () => {
    expect(unpaired().every((l) => l.source_key === '' && l.category === '')).toBe(true);
  });

  it('never flags is_supplier_settlement_recovery', () => {
    expect(unpaired().every((l) => l.is_supplier_settlement_recovery === false)).toBe(true);
  });
});

describe('pairing', () => {
  it('projects nothing when a paired expense exists', () => {
    expect(projectMechanicWorkOrder(wo(), true)).toEqual([]);
  });

  it('projects normally when none does', () => {
    expect(projectMechanicWorkOrder(wo(), false)).toHaveLength(2);
  });

  it('checks is_deleted BEFORE the pairing, and pairing before the amount', () => {
    // All three return [], so the order is not observable in the output — but
    // it is the order Python evaluates in, and a reordering that introduced a
    // throw would surface here.
    expect(projectMechanicWorkOrder(wo({ is_deleted: true, amount: 0 }), true)).toEqual([]);
    expect(projectMechanicWorkOrder(wo({ amount: 0 }), true)).toEqual([]);
  });
});

describe('the guards this projection does NOT have', () => {
  it('still projects a REVERSED work order', () => {
    // Every other ported projection skips is_reversed. This one has no such
    // guard — adding one would silently drop orphan costs from the ledger.
    expect(projectMechanicWorkOrder(wo({ is_reversed: true }), false)).toHaveLength(2);
  });

  it('still projects a HISTORICAL work order', () => {
    expect(projectMechanicWorkOrder(wo({ is_historical: true }), false)).toHaveLength(2);
  });

  it('does skip a deleted one, and only on a truthy flag', () => {
    expect(projectMechanicWorkOrder(wo({ is_deleted: true }), false)).toEqual([]);
    for (const is_deleted of [false, 0, '', null, undefined]) {
      expect(projectMechanicWorkOrder(wo({ is_deleted }), false)).toHaveLength(2);
    }
    // Python truthiness: a non-empty string is truthy.
    expect(projectMechanicWorkOrder(wo({ is_deleted: 'false' }), false)).toEqual([]);
  });
});

describe('amount guards', () => {
  it.each([
    ['zero', 0],
    ['negative', -50],
    ['null', null],
    ['missing', undefined],
    ['rounding to zero', 0.004],
  ])('projects nothing for a %s amount', (_name, amount) => {
    expect(projectMechanicWorkOrder(wo({ amount }), false)).toEqual([]);
  });

  it('rounds half-to-even on the true binary value, on both legs', () => {
    for (const [amount, expected] of [
      [2.675, 2.67],
      [0.125, 0.12],
      [0.375, 0.38],
      [1.005, 1.0],
      ['750.25', 750.25],
    ] as Array<[unknown, number]>) {
      expect(unpaired({ amount }).map((l) => l.amount)).toEqual([expected, expected]);
    }
  });
});

describe('fields', () => {
  it('takes the date from work_date, never from a stray date field', () => {
    expect(unpaired({ date: '2020-01-01', work_date: '2026-09-02' })[0]?.txn_date).toBe('2026-09-02');
  });

  it('empties an absent work_date rather than dropping the leg', () => {
    const legs = unpaired({ work_date: undefined });
    expect(legs).toHaveLength(2);
    expect(legs[0]?.txn_date).toBe('');
  });

  it('empties absent mechanic, vehicle and trip fields', () => {
    const legs = unpaired({
      mechanic_id: undefined,
      mechanic_name: undefined,
      vehicle_id: undefined,
      trip_id: undefined,
    });
    expect([legs[0]?.party_id, legs[0]?.party_name, legs[0]?.vehicle_id, legs[0]?.trip_id]).toEqual([
      '',
      '',
      '',
      '',
    ]);
  });
});

describe('narration', () => {
  it('is the fixed orphan form, with no fallback and no strip', () => {
    expect(unpaired()[0]?.narration).toBe('WO wo_1 (orphan)');
    // Unlike the expense projection there is no narration-or-category chain:
    // a narration field on the document is ignored entirely.
    expect(unpaired({ narration: 'ignored', category: 'ignored' })[0]?.narration).toBe('WO wo_1 (orphan)');
  });

  it('caps at 400 characters when the id is long', () => {
    expect(unpaired({ id: 'W'.repeat(500) })[0]?.narration).toHaveLength(400);
  });
});

describe('registration', () => {
  it('joins the ported list', () => {
    expect([...PORTED_SOURCE_TYPES]).toContain('mechanic_work_order');
    // The exact remaining list lives in the NEWEST slice's tests, so porting
    // the next source type does not break this file.
    const unported = SUPPORTED_SOURCE_TYPES.filter(
      (t) => !(PORTED_SOURCE_TYPES as readonly string[]).includes(t),
    );
    expect(unported).not.toContain('mechanic_work_order');
  });
});
