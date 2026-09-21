/**
 * Unit tests for slice 2c unit 3 — the `supplier_payment` projection.
 *
 * Ledger values are compared against the real Python implementation in
 * scripts/fin-supplier-parity.ts. What matters here is the pair of behaviours
 * that make supplier_payment genuinely different from `_party_payment_legs`,
 * because they are the only places the shared helper could quietly get it
 * wrong — in EITHER direction:
 *
 *   1. supplier skips historical documents; vendor and mechanic do not;
 *   2. supplier carries trip_id on every leg; vendor and mechanic do not.
 *
 * Both are asserted positively for supplier and negatively for the others.
 */
import { describe, expect, it } from 'vitest';
import {
  projectMechanicPayment,
  projectSupplierPayment,
  projectVendorPayment,
} from '../src/fin/projection';

const payment = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'sp_1',
  supplier_id: 'sup_1',
  date: '2026-09-02',
  amount: 1000,
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'SP-001',
  trip_id: 'trip_1',
  is_deleted: false,
  is_reversed: false,
  is_historical: false,
  ...over,
});

describe('supplier payment legs', () => {
  it('projects AP_SUPPLIER against the bank for payment_out', () => {
    const legs = projectSupplierPayment(payment());
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['AP_SUPPLIER', 'in', 1000],
      ['BANK_DEFAULT', 'out', 1000],
    ]);
    expect(legs.map((l) => l.counter_account_code)).toEqual(['BANK_DEFAULT', 'AP_SUPPLIER']);
    expect(legs.every((l) => l.txn_type === 'supplier_payment_out')).toBe(true);
  });

  it('reverses the direction for receipt_in', () => {
    const legs = projectSupplierPayment(payment({ type: 'receipt_in' }));
    expect(legs.map((l) => [l.account_code, l.direction])).toEqual([
      ['BANK_DEFAULT', 'in'],
      ['AP_SUPPLIER', 'out'],
    ]);
    expect(legs.every((l) => l.txn_type === 'supplier_receipt_in')).toBe(true);
  });

  it('builds ref_source_key as source_type:source_id:leg', () => {
    expect(projectSupplierPayment(payment()).map((l) => l.ref_source_key)).toEqual([
      'supplier_payment:sp_1:ap_debit',
      'supplier_payment:sp_1:bank_credit',
    ]);
    expect(projectSupplierPayment(payment({ type: 'receipt_in' })).map((l) => l.ref_source_key)).toEqual([
      'supplier_payment:sp_1:bank_debit',
      'supplier_payment:sp_1:ap_credit',
    ]);
  });

  it('narrates "Supplier <type> · <ref>" and strips a dangling separator', () => {
    // Python uses a literal "Supplier"; the shared helper title-cases
    // party_type. For "supplier" the two are the same string.
    expect(projectSupplierPayment(payment())[0]?.narration).toBe('Supplier payment_out · SP-001');
    for (const ref_no of ['', undefined]) {
      expect(projectSupplierPayment(payment({ ref_no }))[0]?.narration).toBe('Supplier payment_out');
    }
  });

  it('truncates the narration at 400 characters', () => {
    expect(projectSupplierPayment(payment({ ref_no: 'R'.repeat(500) }))[0]?.narration).toHaveLength(400);
  });

  it('never flags is_supplier_settlement_recovery — that is project_expense', () => {
    expect(projectSupplierPayment(payment()).every((l) => l.is_supplier_settlement_recovery === false)).toBe(
      true,
    );
  });
});

describe('difference 1 — the is_historical guard is supplier-only', () => {
  it('skips a historical supplier payment entirely', () => {
    expect(projectSupplierPayment(payment({ is_historical: true }))).toEqual([]);
    expect(projectSupplierPayment(payment({ is_historical: true, type: 'receipt_in' }))).toEqual([]);
  });

  it('still projects when is_historical is falsy or absent', () => {
    for (const is_historical of [false, 0, '', null, undefined]) {
      expect(projectSupplierPayment(payment({ is_historical }))).toHaveLength(2);
    }
  });

  it('does NOT apply to mechanic or vendor payments', () => {
    // _party_payment_legs has no such guard; adding one to the shared helper
    // would silently drop ledger rows for two already-verified source types.
    expect(projectMechanicPayment(payment({ is_historical: true, mechanic_id: 'm1' }))).toHaveLength(2);
    expect(projectVendorPayment(payment({ is_historical: true, vendor_id: 'v1' }))).toHaveLength(2);
  });
});

describe('difference 2 — trip_id is supplier-only', () => {
  it('carries trip_id on every leg', () => {
    expect(projectSupplierPayment(payment()).every((l) => l.trip_id === 'trip_1')).toBe(true);
  });

  it('turns a blank or absent trip_id into an empty string', () => {
    for (const trip_id of ['', undefined, null]) {
      expect(projectSupplierPayment(payment({ trip_id })).every((l) => l.trip_id === '')).toBe(true);
    }
  });

  it('leaves mechanic and vendor legs with an empty trip_id', () => {
    expect(projectMechanicPayment(payment({ mechanic_id: 'm1' })).every((l) => l.trip_id === '')).toBe(true);
    expect(projectVendorPayment(payment({ vendor_id: 'v1' })).every((l) => l.trip_id === '')).toBe(true);
  });
});

describe('shared behaviour — unchanged from the verified helper', () => {
  it.each([
    ['Cash', 'CASH'],
    ['Bank', 'BANK_DEFAULT'],
    ['UPI', 'BANK_DEFAULT'],
    ['Cheque', 'BANK_DEFAULT'],
    ['Crypto', 'BANK_DEFAULT'],
    ['', 'BANK_DEFAULT'],
  ])('resolves mode %j to %s', (mode, code) => {
    expect(projectSupplierPayment(payment({ mode }))[1]?.account_code).toBe(code);
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
    expect(projectSupplierPayment(payment(over))).toEqual([]);
  });

  it('defaults a missing or blank type to payment_out', () => {
    for (const type of [undefined, '']) {
      expect(projectSupplierPayment(payment({ type }))[0]?.txn_type).toBe('supplier_payment_out');
    }
  });

  it('treats any other type as the receipt branch', () => {
    expect(projectSupplierPayment(payment({ type: 'refund' }))[0]?.txn_type).toBe('supplier_receipt_in');
  });

  it('rounds half-to-even on the true binary value', () => {
    expect(projectSupplierPayment(payment({ amount: 2.675 }))[0]?.amount).toBe(2.67);
    expect(projectSupplierPayment(payment({ amount: 0.125 }))[0]?.amount).toBe(0.12);
    expect(projectSupplierPayment(payment({ amount: 0.375 }))[0]?.amount).toBe(0.38);
    expect(projectSupplierPayment(payment({ amount: '750.25' }))[0]?.amount).toBe(750.25);
  });

  it('empties a missing supplier id and date rather than dropping the leg', () => {
    const legs = projectSupplierPayment(payment({ supplier_id: undefined, date: undefined }));
    expect(legs).toHaveLength(2);
    expect(legs[0]?.party_id).toBe('');
    expect(legs[0]?.txn_date).toBe('');
  });
});
