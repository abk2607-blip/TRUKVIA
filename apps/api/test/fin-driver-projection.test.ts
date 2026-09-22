/**
 * Unit tests for slice 2c unit 4 — the `driver_payment` projection.
 *
 * Ledger values are compared against the real Python implementation in
 * scripts/fin-driver-parity.ts, which also measures the routing. What is
 * pinned here is the shape: the payable account is DRIVER_OUTFLOW rather than
 * an AP_* code, and driver_payment must NOT pick up either of the
 * supplier-only behaviours that the shared helper can now switch on.
 */
import { describe, expect, it } from 'vitest';
import {
  PORTED_SOURCE_TYPES,
  projectDriverPayment,
  projectMechanicPayment,
  projectSupplierPayment,
} from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const payment = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'dpay_1',
  driver_id: 'drv_1',
  date: '2026-09-02',
  amount: 1000,
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'DP-001',
  is_deleted: false,
  is_reversed: false,
  ...over,
});

describe('driver payment legs', () => {
  it('projects DRIVER_OUTFLOW against the bank for payment_out', () => {
    const legs = projectDriverPayment(payment());
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['DRIVER_OUTFLOW', 'in', 1000],
      ['BANK_DEFAULT', 'out', 1000],
    ]);
    expect(legs.map((l) => l.counter_account_code)).toEqual(['BANK_DEFAULT', 'DRIVER_OUTFLOW']);
    expect(legs.every((l) => l.txn_type === 'driver_payment_out')).toBe(true);
  });

  it('reverses the direction for receipt_in', () => {
    const legs = projectDriverPayment(payment({ type: 'receipt_in' }));
    expect(legs.map((l) => [l.account_code, l.direction])).toEqual([
      ['BANK_DEFAULT', 'in'],
      ['DRIVER_OUTFLOW', 'out'],
    ]);
    expect(legs.every((l) => l.txn_type === 'driver_receipt_in')).toBe(true);
  });

  it('builds ref_source_key as source_type:source_id:leg', () => {
    expect(projectDriverPayment(payment()).map((l) => l.ref_source_key)).toEqual([
      'driver_payment:dpay_1:ap_debit',
      'driver_payment:dpay_1:bank_credit',
    ]);
    expect(projectDriverPayment(payment({ type: 'receipt_in' })).map((l) => l.ref_source_key)).toEqual([
      'driver_payment:dpay_1:bank_debit',
      'driver_payment:dpay_1:ap_credit',
    ]);
  });

  it('narrates "Driver <type> · <ref>" and strips a dangling separator', () => {
    expect(projectDriverPayment(payment())[0]?.narration).toBe('Driver payment_out · DP-001');
    for (const ref_no of ['', undefined]) {
      expect(projectDriverPayment(payment({ ref_no }))[0]?.narration).toBe('Driver payment_out');
    }
  });

  it('carries the driver as the party on every leg', () => {
    const legs = projectDriverPayment(payment());
    expect(legs.every((l) => l.party_type === 'driver' && l.party_id === 'drv_1')).toBe(true);
  });
});

describe('driver_payment must NOT inherit the supplier-only behaviours', () => {
  it('has no is_historical guard', () => {
    // Only project_supplier_payment skips historical documents. If the shared
    // helper ever turned that on by default, driver and mechanic rows would
    // silently disappear from the ledger.
    expect(projectDriverPayment(payment({ is_historical: true }))).toHaveLength(2);
    expect(projectMechanicPayment(payment({ mechanic_id: 'm1', is_historical: true }))).toHaveLength(2);
    expect(projectSupplierPayment(payment({ supplier_id: 's1', is_historical: true }))).toEqual([]);
  });

  it('never carries trip_id, even when the source document has one', () => {
    expect(projectDriverPayment(payment({ trip_id: 'trip_9' })).every((l) => l.trip_id === '')).toBe(true);
    expect(
      projectSupplierPayment(payment({ supplier_id: 's1', trip_id: 'trip_9' })).every(
        (l) => l.trip_id === 'trip_9',
      ),
    ).toBe(true);
  });
});

describe('shared behaviour', () => {
  it.each([
    ['Cash', 'CASH'],
    ['Bank', 'BANK_DEFAULT'],
    ['UPI', 'BANK_DEFAULT'],
    ['NEFT', 'BANK_DEFAULT'],
    ['Crypto', 'BANK_DEFAULT'],
    ['', 'BANK_DEFAULT'],
  ])('resolves mode %j to %s', (mode, code) => {
    expect(projectDriverPayment(payment({ mode }))[1]?.account_code).toBe(code);
  });

  it.each([
    ['deleted', { is_deleted: true }],
    ['reversed', { is_reversed: true }],
    ['zero amount', { amount: 0 }],
    ['negative amount', { amount: -50 }],
    ['null amount', { amount: null }],
    ['missing amount', { amount: undefined }],
    ['amount rounding to zero', { amount: 0.004 }],
  ])('projects nothing for a %s document', (_name, over) => {
    expect(projectDriverPayment(payment(over))).toEqual([]);
  });

  it('defaults a missing or blank type to payment_out', () => {
    for (const type of [undefined, '']) {
      expect(projectDriverPayment(payment({ type }))[0]?.txn_type).toBe('driver_payment_out');
    }
  });

  it('rounds half-to-even on the true binary value', () => {
    expect(projectDriverPayment(payment({ amount: 2.675 }))[0]?.amount).toBe(2.67);
    expect(projectDriverPayment(payment({ amount: 0.125 }))[0]?.amount).toBe(0.12);
    expect(projectDriverPayment(payment({ amount: '750.25' }))[0]?.amount).toBe(750.25);
  });

  it('truncates the narration at 400 characters', () => {
    expect(projectDriverPayment(payment({ ref_no: 'R'.repeat(500) }))[0]?.narration).toHaveLength(400);
  });
});

describe('registration', () => {
  it('is in the ported list alongside the rest', () => {
    expect([...PORTED_SOURCE_TYPES]).toContain('driver_payment');
    // The full list is asserted once, in the newest slice's test file, so
    // porting the next source type does not break this one.
  });

  it('is the LAST entry of the hook’s supported list, as Python appends it', () => {
    // services_fin_txn.py monkey-patches driver_payment onto the end of
    // SUPPORTED_SOURCE_TYPES at import time, and the hook renders that list
    // verbatim into its unsupported-type error.
    expect(SUPPORTED_SOURCE_TYPES[SUPPORTED_SOURCE_TYPES.length - 1]).toBe('driver_payment');
    expect(SUPPORTED_SOURCE_TYPES).toHaveLength(13);
  });

  it('leaves the remaining source types to Python', () => {
    const unported = SUPPORTED_SOURCE_TYPES.filter(
      (t) => !(PORTED_SOURCE_TYPES as readonly string[]).includes(t),
    );
    // Asserted as a SUBSET rule rather than an exact list: every unported type
    // must still be one Python owns, and none of the four party payments may
    // reappear here. The exact remaining list lives in the newest slice.
    expect(unported).not.toContain('driver_payment');
    expect(unported).not.toContain('mechanic_payment');
    expect(unported).not.toContain('supplier_payment');
    expect(unported.every((t) => SUPPORTED_SOURCE_TYPES.includes(t))).toBe(true);
  });
});
