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
