/**
 * Unit tests for slice 2c unit 12 — `invoice` and its `invoice_payment`
 * cascade, which are ONE projection.
 *
 * A single Python function emits both, so there is no separate payment
 * projection to test. What is pinned here is the ordering of the three leg
 * pairs and the four details that are easy to get wrong: a payment with no id
 * is dropped outright (no index fallback, unlike trip receipts), a
 * non-positive total kills the whole document including its payments, the
 * offset is double-rounded, and neither narration is stripped.
 */
import { describe, expect, it } from 'vitest';
import { PORTED_SOURCE_TYPES, projectInvoice } from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const inv = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'inv_1',
  total_amount: 1000,
  invoice_date: '2026-09-02',
  customer_id: 'cust_1',
  invoice_number: 'INV-9',
  is_historical: false,
  ...over,
});

const shape = (o: Record<string, unknown>): Array<[string, string, string, string]> =>
  projectInvoice(o).map((l) => [l.source_type, l.account_code, l.direction, l.txn_type]);

describe('the raise pair', () => {
  it('debits AR and credits SALES', () => {
    expect(shape(inv())).toEqual([
      ['invoice', 'AR', 'in', 'invoice_raise'],
      ['invoice', 'SALES', 'out', 'invoice_raise'],
    ]);
  });

  it('uses the invoice date and the customer', () => {
    const legs = projectInvoice(inv());
    expect(legs.every((l) => l.txn_date === '2026-09-02')).toBe(true);
    expect(legs.every((l) => l.party_type === 'customer' && l.party_id === 'cust_1')).toBe(true);
  });

  it('builds the ref legs', () => {
    expect(projectInvoice(inv()).map((l) => l.ref_source_key)).toEqual([
      'invoice:inv_1:ar_debit',
      'invoice:inv_1:sales_credit',
    ]);
  });
});

describe('the advance offset pair', () => {
  it('appears only when the deductions are positive', () => {
    expect(projectInvoice(inv())).toHaveLength(2);
    expect(projectInvoice(inv({ advance_deduction_total: 200 }))).toHaveLength(4);
    expect(projectInvoice(inv({ diesel_deduction_total: 150 }))).toHaveLength(4);
    expect(projectInvoice(inv({ advance_deduction_total: 0, diesel_deduction_total: 0 }))).toHaveLength(2);
    expect(projectInvoice(inv({ advance_deduction_total: -100 }))).toHaveLength(2);
  });

  it('sums the advance and diesel deductions', () => {
    const legs = projectInvoice(inv({ advance_deduction_total: 200, diesel_deduction_total: 50 }));
    expect(legs[2]?.amount).toBe(250);
    expect([legs[2]?.account_code, legs[2]?.direction, legs[2]?.txn_type]).toEqual([
      'CUSTOMER_ADVANCE',
      'in',
      'invoice_advance_offset',
    ]);
    expect(legs[3]?.ref_source_key).toBe('invoice:inv_1:sales_offset_credit');
  });

  it('DOUBLE-rounds: each deduction first, then their sum', () => {
    // q2(q2(0.005) + q2(0.005)) = q2(0.01 + 0.01) = 0.02.
    // Rounding the raw sum once would give q2(0.01) = 0.01 instead.
    expect(projectInvoice(inv({ advance_deduction_total: 0.005, diesel_deduction_total: 0.005 }))[2]?.amount).toBe(
      0.02,
    );
  });
});

describe('embedded payments', () => {
  it('projects each payment under its own source_type and compound id', () => {
    const legs = projectInvoice(inv({ payments: [{ id: 'p1', amount: 300, mode: 'Cash' }] }));
    expect(shape(inv({ payments: [{ id: 'p1', amount: 300, mode: 'Cash' }] }))).toEqual([
      ['invoice', 'AR', 'in', 'invoice_raise'],
      ['invoice', 'SALES', 'out', 'invoice_raise'],
      ['invoice_payment', 'CASH', 'in', 'invoice_receipt'],
      ['invoice_payment', 'AR', 'out', 'invoice_receipt'],
    ]);
    expect(legs[2]?.source_id).toBe('inv_1:p1');
    expect(legs[2]?.ref_source_key).toBe('invoice_payment:inv_1:p1:bank_in');
    expect(legs[3]?.ref_source_key).toBe('invoice_payment:inv_1:p1:ar_credit');
  });

  it('adds one pair per payment, after any offset', () => {
    expect(
      projectInvoice(inv({ advance_deduction_total: 100, payments: [{ id: 'p1', amount: 1 }, { id: 'p2', amount: 2 }] })),
    ).toHaveLength(8);
  });

  it('DROPS a payment with no id — there is no index fallback', () => {
    // trip_customer_receipt falls back to idx0; this one does not.
    for (const p of [{ amount: 300 }, { id: '', amount: 300 }, { id: null, amount: 300 }]) {
      expect(projectInvoice(inv({ payments: [p] }))).toHaveLength(2);
    }
  });

  it('drops a payment with a non-positive amount', () => {
    for (const amount of [0, -5, null, undefined, 0.004]) {
      expect(projectInvoice(inv({ payments: [{ id: 'p1', amount }] }))).toHaveLength(2);
    }
  });

  it('keeps the valid payments of a mixed array', () => {
    const legs = projectInvoice(
      inv({ payments: [{ amount: 1 }, { id: 'good', amount: 20 }, { id: 'z', amount: 0 }] }),
    );
    expect(legs).toHaveLength(4);
    expect(legs[2]?.source_id).toBe('inv_1:good');
  });

  it('takes the payment date, falling back to the INVOICE date', () => {
    expect(projectInvoice(inv({ payments: [{ id: 'p', amount: 1, date: '2026-09-09' }] }))[2]?.txn_date).toBe(
      '2026-09-09',
    );
    expect(projectInvoice(inv({ payments: [{ id: 'p', amount: 1 }] }))[2]?.txn_date).toBe('2026-09-02');
  });

  it.each([
    ['Cash', 'CASH'],
    ['UPI', 'BANK_DEFAULT'],
    ['Crypto', 'BANK_DEFAULT'],
    ['', 'BANK_DEFAULT'],
  ])('resolves payment mode %j to %s', (mode, code) => {
    expect(projectInvoice(inv({ payments: [{ id: 'p', amount: 1, mode }] }))[2]?.account_code).toBe(code);
  });
});

describe('invoice-level guards', () => {
  it('projects nothing for a historical invoice, payments included', () => {
    expect(projectInvoice(inv({ is_historical: true, payments: [{ id: 'p', amount: 300 }] }))).toEqual([]);
  });

  it('lets a non-positive total kill the WHOLE document', () => {
    // This is the one most likely to surprise: real payments do not project
    // when the invoice total is zero or negative.
    for (const total_amount of [0, -100, null, undefined, 0.004]) {
      expect(projectInvoice(inv({ total_amount, payments: [{ id: 'p', amount: 300 }] }))).toEqual([]);
    }
  });

  it('has NO is_deleted guard', () => {
    expect(projectInvoice(inv({ is_deleted: true }))).toHaveLength(2);
  });
});

describe('narration — neither is stripped', () => {
  it('names the invoice number', () => {
    expect(projectInvoice(inv())[0]?.narration).toBe('Invoice INV-9');
  });

  it('leaves the trailing space when the number is blank', () => {
    expect(projectInvoice(inv({ invoice_number: '' }))[0]?.narration).toBe('Invoice ');
    expect(projectInvoice(inv({ invoice_number: undefined }))[0]?.narration).toBe('Invoice ');
  });

  it('interpolates a null invoice number as the literal "None"', () => {
    expect(projectInvoice(inv({ invoice_number: null }))[0]?.narration).toBe('Invoice None');
  });

  it('names the receipt reference and the invoice on a payment leg', () => {
    expect(projectInvoice(inv({ payments: [{ id: 'p', amount: 1, reference: 'R1' }] }))[2]?.narration).toBe(
      'Receipt R1 · Inv INV-9',
    );
    expect(projectInvoice(inv({ payments: [{ id: 'p', amount: 1, reference: null }] }))[2]?.narration).toBe(
      'Receipt None · Inv INV-9',
    );
    expect(projectInvoice(inv({ payments: [{ id: 'p', amount: 1, reference: '' }] }))[2]?.narration).toBe(
      'Receipt  · Inv INV-9',
    );
  });

  it('caps at 400 characters', () => {
    expect(projectInvoice(inv({ invoice_number: 'N'.repeat(500) }))[0]?.narration).toHaveLength(400);
  });
});

describe('rounding', () => {
  it('rounds half-to-even on the true binary value', () => {
    for (const [total_amount, expected] of [
      [2.675, 2.67],
      [0.125, 0.12],
      [0.375, 0.38],
      [1.005, 1.0],
      ['750.25', 750.25],
    ] as Array<[unknown, number]>) {
      expect(projectInvoice(inv({ total_amount })).map((l) => l.amount)).toEqual([expected, expected]);
    }
  });
});

describe('registration — every source type is now ported', () => {
  it('leaves nothing with Python', () => {
    const unported = SUPPORTED_SOURCE_TYPES.filter(
      (t) => !(PORTED_SOURCE_TYPES as readonly string[]).includes(t),
    );
    expect(unported).toEqual([]);
  });

  it('covers all thirteen supported source types', () => {
    expect([...PORTED_SOURCE_TYPES].sort()).toEqual([...SUPPORTED_SOURCE_TYPES].sort());
    expect(PORTED_SOURCE_TYPES).toHaveLength(13);
  });
});
