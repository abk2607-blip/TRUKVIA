/**
 * Unit tests for the Finance read slice (phase 6 · slice 2a).
 *
 * Each group covers a behaviour that live parity work actually caught, so a
 * regression here would have shown up as a byte difference against Python:
 *   • fin_txn has two key orders in production — the response must use the
 *     row's own order, not a canonical one;
 *   • money is repr(float), so 0 must render as 0.0 and 52400.0 keep its .0;
 *   • totals use round(), which is banker's rounding, not half-up;
 *   • day_closure snapshot/history are emitted verbatim from TEXT, because
 *     re-encoding them reorders keys and drops trailing .0;
 *   • limit parsing is Pydantic v2's, including the size-limit error type.
 *
 * Live Python-vs-NestJS comparison lives in scripts/fin-reads-parity.ts.
 */
import { describe, expect, it } from 'vitest';
import { pyDumps } from '../src/common/py-json';
import { closureToJson, roundHalfEven2, txnToJson, type ClosureRow } from '../src/fin/fin-reads.service';
import { parsePydanticInt } from '../src/fin/fin-reads.controller';
import type { finTxn } from '../src/db/schema';

type TxnRow = typeof finTxn.$inferSelect;

/** A row with every column populated, so key order is the only variable. */
function txnRow(over: Partial<TxnRow> = {}): TxnRow {
  return {
    id: 'ftx-1',
    mongoId: '000000000000000000000001',
    userId: 'u1',
    companyId: 'c1',
    refSourceKey: 'expense:e1',
    accountCode: 'EXPENSE_DEFAULT',
    accountId: 'acc-1',
    adjustmentGroupId: null,
    amount: '1200.50',
    category: 'fuel',
    counterAccountCode: 'CASH',
    counterAccountId: 'acc-2',
    createdAt: '2026-09-14T10:00:00+00:00',
    direction: 'out',
    isReversal: false,
    isSupplierSettlementRecovery: false,
    narration: 'Diesel',
    partyId: null,
    partyName: null,
    partyType: null,
    projectedAt: '2026-09-14T10:00:00+00:00',
    reconciledAt: null,
    reconciledRef: null,
    reversalOf: null,
    sourceId: 'e1',
    sourceKey: 'expense:e1',
    sourceType: 'expense',
    status: 'active',
    transferGroupId: null,
    tripId: 't1',
    txnDate: '2026-09-14',
    txnType: 'expense',
    vehicleId: 'v1',
    sourceShape: null,
    ...over,
  } as TxnRow;
}

describe('fin_txn key order', () => {
  it('emits fields in the row’s own recorded order', () => {
    const shape = ['id', 'amount', 'txn_date', 'company_id'];
    const out = pyDumps(txnToJson(txnRow({ sourceShape: shape })));
    expect(out).toBe('{"id":"ftx-1","amount":1200.5,"txn_date":"2026-09-14","company_id":"c1"}');
  });

  it('uses the default shape when the row records none', () => {
    const keys = Object.keys(txnToJson(txnRow({ sourceShape: null })));
    // The default order starts with company_id, not id — this is the 18,980-row shape.
    expect(keys[0]).toBe('company_id');
    expect(keys[1]).toBe('ref_source_key');
    expect(keys).toHaveLength(31);
  });

  it('handles the other production shape, where company_id and ref_source_key swap', () => {
    const shape = ['ref_source_key', 'company_id', 'id'];
    expect(Object.keys(txnToJson(txnRow({ sourceShape: shape })))).toEqual([
      'ref_source_key',
      'company_id',
      'id',
    ]);
  });

  it('strips _id and user_id, which the Python projection excludes', () => {
    const shape = ['_id', 'user_id', 'id'];
    expect(txnToJson(txnRow({ sourceShape: shape }))).toEqual({ id: 'ftx-1' });
  });

  it('skips keys with no column rather than emitting undefined', () => {
    const shape = ['id', 'not_a_column'];
    expect(pyDumps(txnToJson(txnRow({ sourceShape: shape })))).toBe('{"id":"ftx-1"}');
  });
});

describe('amount rendering', () => {
  it('keeps a whole amount as a float, not an int', () => {
    const out = pyDumps(txnToJson(txnRow({ sourceShape: ['amount'], amount: '52400.00' })));
    expect(out).toBe('{"amount":52400.0}');
  });

  it('renders zero as 0.0', () => {
    const out = pyDumps(txnToJson(txnRow({ sourceShape: ['amount'], amount: '0.00' })));
    expect(out).toBe('{"amount":0.0}');
  });

  it('keeps a null amount null', () => {
    const out = pyDumps(txnToJson(txnRow({ sourceShape: ['amount'], amount: null })));
    expect(out).toBe('{"amount":null}');
  });
});

describe("totals rounding — Python's round() is half-to-even", () => {
  it.each([
    [0.125, 0.12],
    [0.135, 0.14],
    [2.675, 2.68],
    [1.005, 1.0],
  ])('rounds %d to %d', (input, expected) => {
    expect(roundHalfEven2(input)).toBe(expected);
  });

  it('leaves values that need no rounding alone', () => {
    expect(roundHalfEven2(1200.5)).toBe(1200.5);
    expect(roundHalfEven2(0)).toBe(0);
    expect(roundHalfEven2(-42.25)).toBe(-42.25);
  });
});

describe('day closure snapshot and history', () => {
  const base: ClosureRow = {
    id: 'dc-1',
    mongoId: '000000000000000000000002',
    userId: 'u1',
    companyId: 'c1',
    closeDate: '2026-02-14',
    status: 'closed',
    closedAt: '2026-02-14T18:00:00+00:00',
    closedBy: 'u1',
    closeNotes: null,
    snapshot: null,
    snapshotSourceCount: 3,
    reopenedAt: null,
    reopenedBy: null,
    reopenReason: null,
    history: null,
    createdAt: '2026-02-14T18:00:00+00:00',
    modifiedAt: '2026-02-14T18:00:00+00:00',
    snapshotText: null,
    historyText: null,
  } as ClosureRow;

  it('emits the stored JSON text verbatim, preserving key order and 52400.0', () => {
    const text = '{"CASH":52400.0,"AR":0.0}';
    const out = pyDumps(closureToJson({ ...base, snapshotText: text }));
    expect(out).toContain('"snapshot":{"CASH":52400.0,"AR":0.0}');
  });

  it('keeps a null snapshot null rather than emitting the string "null"', () => {
    const out = pyDumps(closureToJson(base));
    expect(out).toContain('"snapshot":null');
    expect(out).toContain('"history":null');
  });

  it('emits the closure fields in Python’s key order', () => {
    expect(Object.keys(closureToJson(base))).toEqual([
      'id',
      'company_id',
      'close_date',
      'status',
      'closed_at',
      'closed_by',
      'close_notes',
      'snapshot',
      'snapshot_source_count',
      'reopened_at',
      'reopened_by',
      'reopen_reason',
      'history',
      'created_at',
      'modified_at',
    ]);
  });

  it('does not leak user_id or the tie-break column', () => {
    const out = closureToJson(base);
    expect(out).not.toHaveProperty('user_id');
    expect(out).not.toHaveProperty('mongo_id');
    expect(out).not.toHaveProperty('snapshotText');
  });
});

describe('limit parsing — Pydantic v2', () => {
  it.each(['1', '0', '-5', '20000', ' 42 '])('accepts %j', (v) => {
    const r = parsePydanticInt(v);
    expect(r.ok).toBe(true);
  });

  it.each(['abc', '', '1.5', '1e3', '0x10', '1,000'])('rejects %j as int_parsing', (v) => {
    const r = parsePydanticInt(v);
    expect(r).toEqual({ ok: false, type: 'int_parsing' });
  });

  it('reports a distinct error type past the parser size limit', () => {
    expect(parsePydanticInt('9'.repeat(4301))).toEqual({ ok: false, type: 'int_parsing_size' });
    expect(parsePydanticInt('9'.repeat(4300)).ok).toBe(true);
  });

  it('parses values beyond Number.MAX_SAFE_INTEGER without loss', () => {
    const r = parsePydanticInt('99999999999999999999');
    expect(r.ok && r.value).toBe(99999999999999999999n);
  });
});
