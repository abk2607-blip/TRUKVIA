/**
 * Unit tests for slice 2c unit 2 — the `mechanic_payment` projection.
 *
 * The ledger values themselves are compared against the real Python
 * implementation in scripts/fin-mechanic-parity.ts. What is worth pinning down
 * here is the shape of each leg and the guards, because those are the places a
 * later refactor of the shared party-payment helper would quietly change.
 */
import { describe, expect, it } from 'vitest';
import {
  projectMechanicPayment,
  projectVendorPayment,
  partyPaymentLegs,
  q2,
} from '../src/fin/projection';

const payment = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'mpay_1',
  mechanic_id: 'mech_1',
  date: '2026-09-02',
  amount: 1000,
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'MP-001',
  is_deleted: false,
  is_reversed: false,
  ...over,
});

describe('mechanic payment legs', () => {
  it('projects a balanced pair for payment_out', () => {
    const legs = projectMechanicPayment(payment());
    expect(legs).toHaveLength(2);
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['AP_MECHANIC', 'in', 1000],
      ['BANK_DEFAULT', 'out', 1000],
    ]);
    expect(legs.map((l) => l.counter_account_code)).toEqual(['BANK_DEFAULT', 'AP_MECHANIC']);
    expect(legs.every((l) => l.txn_type === 'mechanic_payment_out')).toBe(true);
  });

  it('reverses the direction for receipt_in', () => {
    const legs = projectMechanicPayment(payment({ type: 'receipt_in' }));
    expect(legs.map((l) => [l.account_code, l.direction])).toEqual([
      ['BANK_DEFAULT', 'in'],
      ['AP_MECHANIC', 'out'],
    ]);
    expect(legs.every((l) => l.txn_type === 'mechanic_receipt_in')).toBe(true);
  });

  it('treats any type other than payment_out as the receipt branch', () => {
    // Python compares `typ == "payment_out"` and falls through otherwise.
    expect(projectMechanicPayment(payment({ type: 'refund' }))[0]?.txn_type).toBe(
      'mechanic_receipt_in',
    );
  });

  it('defaults a missing or blank type to payment_out', () => {
    for (const type of [undefined, '']) {
      expect(projectMechanicPayment(payment({ type }))[0]?.txn_type).toBe('mechanic_payment_out');
    }
  });

  it('builds ref_source_key as source_type:source_id:leg', () => {
    expect(projectMechanicPayment(payment()).map((l) => l.ref_source_key)).toEqual([
      'mechanic_payment:mpay_1:ap_debit',
      'mechanic_payment:mpay_1:bank_credit',
    ]);
    expect(projectMechanicPayment(payment({ type: 'receipt_in' })).map((l) => l.ref_source_key)).toEqual([
      'mechanic_payment:mpay_1:bank_debit',
      'mechanic_payment:mpay_1:ap_credit',
    ]);
  });

  it('carries the mechanic as the party on every leg', () => {
    const legs = projectMechanicPayment(payment());
    expect(legs.every((l) => l.party_type === 'mechanic' && l.party_id === 'mech_1')).toBe(true);
  });

  it('leaves the party id empty when the document has none', () => {
    expect(projectMechanicPayment(payment({ mechanic_id: undefined }))[0]?.party_id).toBe('');
  });
});

describe('account resolution by mode', () => {
  it.each([
    ['Cash', 'CASH'],
    ['Bank', 'BANK_DEFAULT'],
    ['UPI', 'BANK_DEFAULT'],
    ['IMPS', 'BANK_DEFAULT'],
    ['NEFT', 'BANK_DEFAULT'],
    ['RTGS', 'BANK_DEFAULT'],
    ['Cheque', 'BANK_DEFAULT'],
    ['Other', 'BANK_DEFAULT'],
  ])('maps %s to %s', (mode, code) => {
    expect(projectMechanicPayment(payment({ mode }))[1]?.account_code).toBe(code);
  });

  it('falls back to BANK_DEFAULT for an unknown, blank or missing mode', () => {
    for (const mode of ['Crypto', '', undefined]) {
      expect(projectMechanicPayment(payment({ mode }))[1]?.account_code).toBe('BANK_DEFAULT');
    }
  });
});

describe('guards — these must project nothing at all', () => {
  it.each([
    ['deleted', { is_deleted: true }],
    ['reversed', { is_reversed: true }],
    ['zero amount', { amount: 0 }],
    ['negative amount', { amount: -50 }],
    ['null amount', { amount: null }],
    ['missing amount', { amount: undefined }],
  ])('%s', (_name, over) => {
    expect(projectMechanicPayment(payment(over))).toEqual([]);
  });
});

describe('narration', () => {
  it('is "Mechanic <type> · <ref>"', () => {
    expect(projectMechanicPayment(payment())[0]?.narration).toBe('Mechanic payment_out · MP-001');
  });

  it('strips the dangling separator when there is no ref', () => {
    // Python: .strip(" ·") removes any leading/trailing space or "·".
    for (const ref_no of ['', undefined]) {
      expect(projectMechanicPayment(payment({ ref_no }))[0]?.narration).toBe('Mechanic payment_out');
    }
  });

  it('truncates at 400 characters, as _leg does', () => {
    const n = projectMechanicPayment(payment({ ref_no: 'R'.repeat(500) }))[0]?.narration ?? '';
    expect(n).toHaveLength(400);
  });

  it('titles the party name the way Python’s str.title() does here', () => {
    expect(projectVendorPayment(payment({ vendor_id: 'v1' }))[0]?.narration).toBe(
      'Vendor payment_out · MP-001',
    );
  });
});

describe('the shared helper is genuinely shared', () => {
  it('produces the vendor projection from the same code path', () => {
    const viaHelper = partyPaymentLegs(payment({ vendor_id: 'v1' }), {
      apCode: 'AP_VENDOR',
      partyType: 'vendor',
      partyIdKey: 'vendor_id',
      srcType: 'vendor_payment',
      txnTypePrefix: 'vendor',
    });
    expect(viaHelper).toEqual(projectVendorPayment(payment({ vendor_id: 'v1' })));
  });

  it('differs from the mechanic projection only in the parameterised fields', () => {
    const v = projectVendorPayment(payment({ vendor_id: 'v1' }))[0];
    const m = projectMechanicPayment(payment())[0];
    expect([v?.account_code, v?.party_type, v?.txn_type]).toEqual([
      'AP_VENDOR',
      'vendor',
      'vendor_payment_out',
    ]);
    expect([m?.account_code, m?.party_type, m?.txn_type]).toEqual([
      'AP_MECHANIC',
      'mechanic',
      'mechanic_payment_out',
    ]);
    expect(v?.amount).toBe(m?.amount);
    expect(v?.direction).toBe(m?.direction);
  });
});

describe('_q2 money rounding', () => {
  it('rounds half-to-even against the true binary value', () => {
    // Caught by the 2c parity run: a mechanic payment of 2.675 projected as
    // 2.68 where Python gives 2.67 — a one-paisa error in a real ledger leg.
    expect(q2(2.675)).toBe(2.67);
    expect(q2(0.125)).toBe(0.12);
    expect(q2(0.375)).toBe(0.38);
    expect(q2(1.005)).toBe(1.0);
  });

  it('reaches the legs, not just the helper', () => {
    expect(projectMechanicPayment(payment({ amount: 2.675 }))[0]?.amount).toBe(2.67);
  });

  it('accepts a numeric string, as float() does', () => {
    expect(q2('750.25')).toBe(750.25);
  });

  it('treats falsy and non-finite input as zero', () => {
    expect(q2(null)).toBe(0);
    expect(q2(undefined)).toBe(0);
    expect(q2('')).toBe(0);
    expect(q2(NaN)).toBe(0);
  });
});
