/**
 * Unit tests for the vendors slice.
 *
 * These cover the behaviours that parity work has historically got wrong, each
 * traceable to a real finding:
 *   • Pydantic boolean-string tokens (Gate 6j);
 *   • Python float rendering, 0.0 vs 0 (found on live data 2026-09-21);
 *   • timestamp rendering, including the +05:30 vs +00:00 break and the
 *     empty-string-means-absent convention (found 2026-09-21);
 *   • X-Company-Id first-raw-occurrence (Gate 9c);
 *   • auth identity: staff remap, missing user, missing email (Gate 9b).
 *
 * Live Python-vs-NestJS comparison lives in the parity harness, not here.
 */
import { describe, expect, it } from 'vitest';
import { coerceFastapiBool } from '../src/vendors/vendors.controller';
import { pyDumps, pyFloat, pyIsoTimestamp } from '../src/common/py-json';
import { readCompanyHeader } from '../src/common/identity';
import { toJson } from '../src/vendors/vendors.service';
import { billToJson } from '../src/vendors/vendor-bills.service';
import { correctionToJson, paymentToJson } from '../src/vendors/vendor-payments.service';

describe('Pydantic boolean-string coercion', () => {
  it.each(['1', 't', 'true', 'on', 'yes', 'TRUE', ' Yes '])('accepts %j as true', (v) => {
    expect(coerceFastapiBool(v)).toBe(true);
  });
  it.each(['0', 'f', 'false', 'off', 'n', 'no', 'FALSE'])('accepts %j as false', (v) => {
    expect(coerceFastapiBool(v)).toBe(false);
  });
  it.each(['maybe', '2', '', 'y e s', 'null'])('rejects %j', (v) => {
    expect(coerceFastapiBool(v)).toBe('invalid');
  });
  it('rejects non-strings', () => {
    expect(coerceFastapiBool(undefined)).toBe('invalid');
    expect(coerceFastapiBool(1)).toBe('invalid');
  });
});

describe('Python float rendering', () => {
  it('renders a whole number with .0, as repr(float) does', () => {
    expect(pyDumps(pyFloat('0.00'))).toBe('0.0');
    expect(pyDumps(pyFloat('29593.00'))).toBe('29593.0');
    expect(pyDumps(pyFloat(18000))).toBe('18000.0');
  });
  it('keeps the fraction when there is one', () => {
    expect(pyDumps(pyFloat('24.539334'))).toBe('24.539334');
    expect(pyDumps(pyFloat('0.50'))).toBe('0.5');
  });
  it('renders null for a null column', () => {
    expect(pyDumps(pyFloat(null))).toBe('null');
  });
});

describe('timestamp rendering', () => {
  it('converts a Postgres timestamptz to isoformat with +00:00', () => {
    expect(pyIsoTimestamp('2026-09-08 16:02:24.539334+00')).toBe(
      '2026-09-08T16:02:24.539334+00:00',
    );
  });
  it('pads microseconds to six digits, as isoformat does', () => {
    expect(pyIsoTimestamp('2026-09-08 16:02:24.5+00')).toBe('2026-09-08T16:02:24.500000+00:00');
  });
  it('omits the fraction when there is none', () => {
    expect(pyIsoTimestamp('2026-09-08 16:02:24+00')).toBe('2026-09-08T16:02:24+00:00');
  });
  it('preserves a non-UTC offset rather than silently shifting it', () => {
    // A +05:30 rendering was a real parity break: the fix is to force the
    // session timezone to UTC, not to rewrite the offset here.
    expect(pyIsoTimestamp('2026-09-08 21:32:24.539334+05:30')).toBe(
      '2026-09-08T21:32:24.539334+05:30',
    );
  });
  it('passes through null', () => {
    expect(pyIsoTimestamp(null)).toBeNull();
  });
});

describe('py-json serialization', () => {
  it('uses compact separators like json.dumps(separators=(",", ":"))', () => {
    expect(pyDumps({ a: 1, b: 'x' })).toBe('{"a":1,"b":"x"}');
    expect(pyDumps([1, 'a', true, null])).toBe('[1,"a",true,null]');
  });
  it('emits non-ASCII raw, like ensure_ascii=False', () => {
    expect(pyDumps({ name: 'Bharath ₹' })).toBe('{"name":"Bharath ₹"}');
  });
  it('drops undefined values, which json.dumps never sees', () => {
    expect(pyDumps({ a: 1, b: undefined })).toBe('{"a":1}');
  });
});

describe('vendor row -> JSON contract', () => {
  const row = {
    id: 'ven_1',
    sourceId: '6aa568d7453166811caadd33',
    userId: 'user_1',
    companyId: 'co_1',
    name: 'Acme',
    contactPerson: '',
    mobile: '',
    altMobile: '',
    address: '',
    state: '',
    city: '',
    gstIn: '',
    pan: '',
    msmeNumber: '',
    bankName: '',
    accountNumber: '',
    ifsc: '',
    branch: '',
    paymentTerms: '',
    openingBalance: '0.00',
    openingBalanceType: 'payable',
    remarks: '',
    isActive: true,
    isHistorical: false,
    importedFrom: '',
    importedRef: '',
    importedBatch: '',
    createdBy: 'user_1',
    createdAt: '2026-09-08 16:02:24.539334+00',
    modifiedBy: '',
    modifiedAt: null,
    deactivatedBy: '',
    deactivatedAt: null,
    deactivationReason: '',
  };

  it('omits user_id, because the Python projection strips it', () => {
    expect(Object.keys(toJson(row))).not.toContain('user_id');
  });

  it('keeps the document field order the Python response has', () => {
    expect(Object.keys(toJson(row)).slice(0, 6)).toEqual([
      'id',
      'name',
      'contact_person',
      'mobile',
      'alt_mobile',
      'address',
    ]);
    expect(Object.keys(toJson(row)).at(-1)).toBe('company_id');
  });

  it('renders an absent timestamp as "", which is how the source stores it', () => {
    const json = toJson(row);
    expect(json.modified_at).toBe('');
    expect(json.deactivated_at).toBe('');
    expect(json.created_at).toBe('2026-09-08T16:02:24.539334+00:00');
  });

  it('renders money Python-style', () => {
    expect(pyDumps(toJson(row).opening_balance)).toBe('0.0');
  });
});

describe('X-Company-Id header (Gate 9c)', () => {
  const req = (rawHeaders: string[]) => ({ rawHeaders }) as never;

  it('takes the first raw occurrence when the header is duplicated', () => {
    expect(readCompanyHeader(req(['X-Company-Id', 'co-a', 'X-Company-Id', 'co-b']))).toBe('co-a');
  });
  it('matches the header name case-insensitively', () => {
    expect(readCompanyHeader(req(['x-COMPANY-id', 'co-a']))).toBe('co-a');
  });
  it('keeps a single comma-containing value literal', () => {
    expect(readCompanyHeader(req(['X-Company-Id', 'co-b, co-a']))).toBe('co-b, co-a');
  });
  it('returns "" when absent', () => {
    expect(readCompanyHeader(req(['Host', 'x']))).toBe('');
  });
});

describe('vendor bill -> JSON contract', () => {
  const bill = {
    id: 'vbl_1',
    sourceId: '6a1',
    userId: 'user_1',
    companyId: 'co_1',
    vendorId: 'ven_1',
    vendorName: 'Acme',
    billNumber: 'B-1',
    billDate: '2026-08-05',
    billAmount: '18000.00',
    vehicleId: '',
    vehicleNumber: '',
    tripId: '',
    repairEventId: '',
    narration: '',
    remarks: '',
    fileIds: [],
    isDeleted: false,
    deletedBy: '',
    deletedAt: null,
    deletionReason: '',
    createdBy: 'user_1',
    createdAt: '2026-08-05 10:00:00.123456+00',
    modifiedBy: '',
    modifiedAt: null,
  };

  it('keeps the source key order and strips user_id', () => {
    const keys = Object.keys(billToJson(bill));
    expect(keys.slice(0, 6)).toEqual([
      'id',
      'vendor_id',
      'vendor_name',
      'bill_number',
      'bill_date',
      'bill_amount',
    ]);
    expect(keys).not.toContain('user_id');
    expect(keys.at(-1)).toBe('company_id');
  });

  it('renders money Python-style and absent timestamps as ""', () => {
    const json = billToJson(bill);
    expect(pyDumps(json.bill_amount)).toBe('18000.0');
    expect(json.modified_at).toBe('');
    expect(json.created_at).toBe('2026-08-05T10:00:00.123456+00:00');
  });
});

describe('vendor payment shapes', () => {
  const base = {
    id: 'vpay_1',
    sourceId: '6b1',
    userId: 'u',
    companyId: 'co_1',
    vendorId: 'ven_1',
    vendorBillId: '',
    paymentDate: '2026-08-05',
    amount: '7500.00',
    type: '',
    mode: 'Bank',
    accountId: '',
    refNo: '',
    against: '',
    remarks: '',
    fileIds: [],
    correctedBy: null,
    correctedAt: null,
    correctionCount: null,
    latestCorrectionId: null,
    isReversed: null,
    reversedBy: null,
    reversedAt: null,
    reversalReason: null,
    reversalOf: null,
    reconciledAt: null,
    reconciledRef: null,
    bankAccountId: null,
    bankSnapshot: null,
    companyBankAccountId: null,
    sourceBankSnapshot: null,
    isDeleted: false,
    deletedBy: '',
    deletedAt: null,
    deletionReason: '',
    createdBy: 'u',
    createdAt: '2026-08-05 10:00:00+00',
    modifiedBy: '',
    modifiedAt: null,
    sourceShape: null,
    bankSnapshotText: null,
    sourceBankSnapshotText: null,
  };

  it('omits fields the source document did not have', () => {
    // 23 of 2,040 production payments carry no correction block at all.
    const json = paymentToJson({ ...base, sourceShape: ['id', 'vendor_id', 'amount'] });
    expect(Object.keys(json)).toEqual(['id', 'vendor_id', 'amount']);
    expect('correction_count' in json).toBe(false);
  });

  it('reproduces the source key order, not a canonical one', () => {
    const json = paymentToJson({
      ...base,
      sourceShape: ['id', 'bank_account_id', 'vendor_id', 'date'],
      bankAccountId: '',
      bankSnapshotText: '{}',
    });
    expect(Object.keys(json)).toEqual(['id', 'bank_account_id', 'vendor_id', 'date']);
  });

  it('drops _id and user_id even when the recorded shape lists them', () => {
    const json = paymentToJson({ ...base, sourceShape: ['_id', 'user_id', 'id'] });
    expect(Object.keys(json)).toEqual(['id']);
  });

  it('falls back to the canonical shape when none was recorded', () => {
    const json = paymentToJson(base);
    expect(Object.keys(json)[0]).toBe('id');
    expect(Object.keys(json).at(-1)).toBe('company_id');
    expect('bank_account_id' in json).toBe(false);
  });

  it('emits a stored snapshot verbatim, preserving key order and 7500.0', () => {
    const text = '{"date":"2029-09-07","amount":7500.0,"mode":"Bank"}';
    const json = paymentToJson({
      ...base,
      sourceShape: ['id', 'bank_snapshot'],
      bankSnapshotText: text,
    });
    expect(pyDumps(json)).toBe(`{"id":"vpay_1","bank_snapshot":${text}}`);
  });

  it('renders money Python-style', () => {
    expect(pyDumps(paymentToJson(base).amount)).toBe('7500.0');
  });
});

describe('payment correction -> JSON contract', () => {
  it('emits before/after/diff verbatim in source key order', () => {
    const json = correctionToJson({
      id: 'pcr_1',
      sourceId: '6c1',
      userId: 'u',
      companyId: 'co_1',
      paymentType: 'vendor',
      paymentId: 'vpay_1',
      correctionIndex: 1,
      kind: 'attribute',
      correctionReason: 'typed wrong vendor by mistake',
      before: null,
      after: null,
      diff: null,
      linkedReversalId: null,
      linkedNewId: null,
      forceReconciledOverride: false,
      correctedBy: 'u',
      correctedAt: '2026-09-11 10:00:00+00',
      beforeText: '{"account_id":"","amount":7500.0}',
      afterText: '{"account_id":"x","amount":7500.0}',
      diffText: '{"account_id":["","x"]}',
    });
    expect(pyDumps(json.before)).toBe('{"account_id":"","amount":7500.0}');
    expect(Object.keys(json).slice(0, 5)).toEqual([
      'id',
      'company_id',
      'payment_type',
      'payment_id',
      'correction_index',
    ]);
    expect(json.linked_reversal_id).toBe('');
  });
});
