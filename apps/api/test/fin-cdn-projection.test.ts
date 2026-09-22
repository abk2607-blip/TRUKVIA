/**
 * Unit tests for slice 2c unit 5 — the `credit_debit_note` projection.
 *
 * Ledger values are compared against the real Python implementation in
 * scripts/fin-cdn-parity.ts. What is pinned here is everything that makes this
 * projection different from the four party payments, because those are the
 * places a reader coming from the earlier units would guess wrong.
 */
import { describe, expect, it } from 'vitest';
import {
  PORTED_SOURCE_TYPES,
  projectCreditDebitNote,
  projectDriverPayment,
} from '../src/fin/projection';
import { SUPPORTED_SOURCE_TYPES } from '../src/fin/fin-hook';

const note = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'cdn_1',
  kind: 'credit',
  status: 'issued',
  total_amount: 1000,
  note_date: '2026-09-02',
  customer_id: 'cust_1',
  note_number: 'CN-001',
  invoice_number_snapshot: 'INV-9',
  is_historical: false,
  ...over,
});

describe('credit note — reverses the receivable', () => {
  it('credits AR and debits SALES, in that order', () => {
    const legs = projectCreditDebitNote(note());
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['AR', 'out', 1000],
      ['SALES', 'in', 1000],
    ]);
    expect(legs.map((l) => l.counter_account_code)).toEqual(['SALES', 'AR']);
    expect(legs.every((l) => l.txn_type === 'credit_note_issue')).toBe(true);
    expect(legs.map((l) => l.ref_source_key)).toEqual([
      'credit_debit_note:cdn_1:ar_credit',
      'credit_debit_note:cdn_1:sales_debit',
    ]);
  });
});

describe('debit note — the exact mirror', () => {
  it('debits AR and credits SALES, in that order', () => {
    const legs = projectCreditDebitNote(note({ kind: 'debit' }));
    expect(legs.map((l) => [l.account_code, l.direction, l.amount])).toEqual([
      ['AR', 'in', 1000],
      ['SALES', 'out', 1000],
    ]);
    expect(legs.every((l) => l.txn_type === 'debit_note_issue')).toBe(true);
    expect(legs.map((l) => l.ref_source_key)).toEqual([
      'credit_debit_note:cdn_1:ar_debit',
      'credit_debit_note:cdn_1:sales_credit',
    ]);
  });
});

describe('kind resolution', () => {
  it.each([undefined, null, '', 0, false, []])('treats falsy kind %j as credit', (kind) => {
    // Python truthiness, including the empty list.
    expect(projectCreditDebitNote(note({ kind }))[0]?.txn_type).toBe('credit_note_issue');
  });

  it.each([5, true, ['x'], { a: 1 }])(
    'treats TRUTHY non-string kind %j as debit, as Python does',
    (kind) => {
      // `or "credit"` keeps the value, then `== "credit"` fails. Stringifying
      // it first would default it to credit and flip the sign of the note.
      expect(projectCreditDebitNote(note({ kind }))[0]?.txn_type).toBe('debit_note_issue');
      expect(projectCreditDebitNote(note({ kind }))[0]?.narration.startsWith('DN ')).toBe(true);
    },
  );

  it.each(['debit', 'weird', 'CREDIT', 'Credit', ' credit'])(
    'treats %j as debit, because the test is an exact === "credit"',
    (kind) => {
      expect(projectCreditDebitNote(note({ kind }))[0]?.txn_type).toBe('debit_note_issue');
    },
  );

  it('uses the resolved kind for the narration prefix too', () => {
    expect(projectCreditDebitNote(note({ kind: '' }))[0]?.narration.startsWith('CN ')).toBe(true);
    expect(projectCreditDebitNote(note({ kind: 'weird' }))[0]?.narration.startsWith('DN ')).toBe(true);
  });
});

describe('guards', () => {
  it.each(['draft', 'cancelled', '', 'ISSUED', 'Issued'])('skips status %j', (status) => {
    expect(projectCreditDebitNote(note({ status }))).toEqual([]);
  });

  it('skips a missing status', () => {
    expect(projectCreditDebitNote(note({ status: undefined }))).toEqual([]);
  });

  it('skips a historical note but not a falsy flag', () => {
    expect(projectCreditDebitNote(note({ is_historical: true }))).toEqual([]);
    for (const is_historical of [false, 0, '', null, undefined]) {
      expect(projectCreditDebitNote(note({ is_historical }))).toHaveLength(2);
    }
  });

  it.each([
    ['zero', 0],
    ['negative', -500],
    ['null', null],
    ['missing', undefined],
    ['rounding to zero', 0.004],
  ])('skips a %s total_amount', (_name, total_amount) => {
    expect(projectCreditDebitNote(note({ total_amount }))).toEqual([]);
  });

  it('has NO is_deleted or is_reversed guard, unlike the party payments', () => {
    // Those fields do not exist on the CreditDebitNote model; a withdrawn note
    // carries status "cancelled", which the status guard already rejects.
    expect(projectCreditDebitNote(note({ is_deleted: true }))).toHaveLength(2);
    expect(projectCreditDebitNote(note({ is_reversed: true }))).toHaveLength(2);
    // The party payments do the opposite.
    expect(projectDriverPayment({ id: 'd', amount: 1, is_deleted: true })).toEqual([]);
  });
});

describe('fields', () => {
  it('reads total_amount, never a stray amount field', () => {
    expect(projectCreditDebitNote(note({ amount: 9999, total_amount: 250 }))[0]?.amount).toBe(250);
  });

  it('reads note_date, never a stray date field', () => {
    expect(projectCreditDebitNote(note({ date: '2020-01-01', note_date: '2026-09-02' }))[0]?.txn_date).toBe(
      '2026-09-02',
    );
  });

  it('empties a missing customer id and date rather than dropping the leg', () => {
    const legs = projectCreditDebitNote(note({ customer_id: undefined, note_date: undefined }));
    expect(legs).toHaveLength(2);
    expect(legs[0]?.party_id).toBe('');
    expect(legs[0]?.txn_date).toBe('');
  });

  it('carries the customer as the party, with no trip or vehicle', () => {
    const legs = projectCreditDebitNote(note({ trip_id: 'trip_9', vehicle_id: 'veh_9' }));
    expect(legs.every((l) => l.party_type === 'customer' && l.party_id === 'cust_1')).toBe(true);
    expect(legs.every((l) => l.trip_id === '' && l.vehicle_id === '' && l.category === '')).toBe(true);
  });
});

describe('narration — NOT stripped, unlike every earlier projection', () => {
  it('keeps the dangling separator when both references are empty', () => {
    // Python has no .strip(" ·") here. Trimming would be a silent difference
    // in a field that reaches the day-book.
    expect(projectCreditDebitNote(note({ note_number: '', invoice_number_snapshot: '' }))[0]?.narration).toBe(
      'CN  · Inv ',
    );
  });

  it('treats absent references the same as empty ones', () => {
    expect(
      projectCreditDebitNote(note({ note_number: undefined, invoice_number_snapshot: undefined }))[0]
        ?.narration,
    ).toBe('CN  · Inv ');
  });

  it('builds the full form when both are present', () => {
    expect(projectCreditDebitNote(note())[0]?.narration).toBe('CN CN-001 · Inv INV-9');
    expect(projectCreditDebitNote(note({ kind: 'debit' }))[0]?.narration).toBe('DN CN-001 · Inv INV-9');
  });

  it('still truncates at 400 characters', () => {
    expect(projectCreditDebitNote(note({ note_number: 'N'.repeat(500) }))[0]?.narration).toHaveLength(400);
  });
});

describe('rounding', () => {
  it('rounds half-to-even on the true binary value', () => {
    expect(projectCreditDebitNote(note({ total_amount: 2.675 }))[0]?.amount).toBe(2.67);
    expect(projectCreditDebitNote(note({ total_amount: 0.125 }))[0]?.amount).toBe(0.12);
    expect(projectCreditDebitNote(note({ total_amount: 0.375 }))[0]?.amount).toBe(0.38);
    expect(projectCreditDebitNote(note({ total_amount: 1.005 }))[0]?.amount).toBe(1.0);
    expect(projectCreditDebitNote(note({ total_amount: '750.25' }))[0]?.amount).toBe(750.25);
  });
});

describe('registration', () => {
  it('joins the ported list', () => {
    expect([...PORTED_SOURCE_TYPES]).toContain('credit_debit_note');
  });

  it('is one of the ported types, and none of them is still unported', () => {
    // The exact remaining list lives in the NEWEST slice's tests, so porting
    // the next source type does not break this file.
    const unported = SUPPORTED_SOURCE_TYPES.filter(
      (t) => !(PORTED_SOURCE_TYPES as readonly string[]).includes(t),
    );
    expect(unported).not.toContain('credit_debit_note');
  });
});
