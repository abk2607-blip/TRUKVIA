/**
 * Slice 2c step 6 — the narration f-string semantics of the four party
 * payments and of vendor_bill.
 *
 * These were ported with `str()`, which maps BOTH an absent key and a present
 * `None` to `""`. Python does not: `p.get('ref_no', '')` defaults only when
 * the key is ABSENT, so a present `None` is interpolated as the literal text
 * `"None"` and — because it ends in a letter — survives `.strip(" ·")`.
 *
 * The divergence was found by scripts/fin-vendorpay-bridge-parity.ts against
 * the real Python implementation, not reasoned about, and it is a wrong
 * narration on a real ledger row rather than a cosmetic difference. This file
 * pins the corrected behaviour for all five projections, because they share
 * one helper and a regression in it would be silent.
 */
import { describe, expect, it } from 'vitest';
import {
  projectDriverPayment,
  projectMechanicPayment,
  projectSupplierPayment,
  projectVendorBill,
  projectVendorPayment,
} from '../src/fin/projection';

type Doc = Record<string, unknown>;

const base: Doc = {
  id: 'p1',
  amount: 100,
  date: '2026-09-02',
  mode: 'Bank',
  type: 'payment_out',
  ref_no: 'R-1',
};

/** The four party payments, each with the party key its projection reads. */
const PARTIES: Array<[string, string, (d: Doc) => Array<{ narration: string }>]> = [
  ['Vendor', 'vendor_id', projectVendorPayment],
  ['Mechanic', 'mechanic_id', projectMechanicPayment],
  ['Driver', 'driver_id', projectDriverPayment],
  ['Supplier', 'supplier_id', projectSupplierPayment],
];

describe.each(PARTIES)('%s payment narration', (title, partyKey, project) => {
  const doc = (over: Doc = {}): Doc => ({ ...base, [partyKey]: 'party_1', ...over });
  const narrationOf = (over: Doc = {}): string => project(doc(over))[0]?.narration ?? '<no legs>';

  it('names the party, the type and the reference', () => {
    expect(narrationOf()).toBe(`${title} payment_out · R-1`);
  });

  it('interpolates a PRESENT null reference as the literal "None"', () => {
    // The regression this file exists for.
    expect(narrationOf({ ref_no: null })).toBe(`${title} payment_out · None`);
  });

  it('treats an ABSENT reference as the "" default', () => {
    expect(narrationOf({ ref_no: undefined })).toBe(`${title} payment_out`);
  });

  it('strips a blank or all-middot reference back to the type', () => {
    expect(narrationOf({ ref_no: '' })).toBe(`${title} payment_out`);
    expect(narrationOf({ ref_no: ' · · ' })).toBe(`${title} payment_out`);
  });

  it('strips ALL trailing middots and spaces, not one suffix', () => {
    expect(narrationOf({ ref_no: 'R-1 ·· ' })).toBe(`${title} payment_out · R-1`);
  });

  it('keeps a reference that merely CONTAINS a middot', () => {
    expect(narrationOf({ ref_no: 'A·B' })).toBe(`${title} payment_out · A·B`);
  });

  it('defaults a falsy type to payment_out', () => {
    for (const type of [undefined, null, '', 0, false]) {
      expect(narrationOf({ type })).toBe(`${title} payment_out · R-1`);
    }
  });

  it('interpolates a truthy non-string type as Python renders it', () => {
    // `typ = p.get("type") or "payment_out"` keeps the RAW value, so a number
    // reaches the f-string as a number and a bool as True/False.
    expect(narrationOf({ type: 5 })).toBe(`${title} 5 · R-1`);
    expect(narrationOf({ type: true })).toBe(`${title} True · R-1`);
  });

  it('sends any type that is not literally "payment_out" down the receipt branch', () => {
    // The comparison is against the RAW value, so a non-string can never match.
    expect(project(doc({ type: 5 }))[0]).toMatchObject({ narration: `${title} 5 · R-1` });
    const legs = project(doc({ type: 5 })) as unknown as Array<{ txn_type: string }>;
    expect(legs.every((l) => l.txn_type.endsWith('_receipt_in'))).toBe(true);
  });

  it('puts the same narration on BOTH legs', () => {
    const legs = project(doc({ ref_no: null }));
    expect(legs).toHaveLength(2);
    expect(legs[0]?.narration).toBe(legs[1]?.narration);
  });
});

describe('vendor_bill narration', () => {
  const vb = (over: Doc = {}): Doc => ({
    id: 'vb1',
    vendor_id: 'vend_1',
    bill_amount: 100,
    bill_date: '2026-09-02',
    bill_number: 'VB-1',
    ...over,
  });
  const narrationOf = (over: Doc = {}): string =>
    projectVendorBill(vb(over), false)[0]?.narration ?? '<no legs>';

  it('names the bill number', () => {
    expect(narrationOf()).toBe('VendorBill VB-1 (orphan)');
  });

  it('interpolates a PRESENT null number as the literal "None"', () => {
    expect(narrationOf({ bill_number: null })).toBe('VendorBill None (orphan)');
  });

  it('leaves the DOUBLE space for a blank or absent number — there is no strip here', () => {
    expect(narrationOf({ bill_number: '' })).toBe('VendorBill  (orphan)');
    expect(narrationOf({ bill_number: undefined })).toBe('VendorBill  (orphan)');
  });

  it('does not strip a number that ends in a middot', () => {
    expect(narrationOf({ bill_number: 'VB-1 ·' })).toBe('VendorBill VB-1 · (orphan)');
  });

  it('projects nothing at all when an expense is paired', () => {
    expect(projectVendorBill(vb(), true)).toEqual([]);
  });
});

describe('the party name field is NOT an f-string', () => {
  it('maps an absent or null vendor_name to an empty string', () => {
    // Python: `vb.get("vendor_name") or ""` — a different construct from the
    // narration, and it really does flatten both to "".
    for (const vendor_name of [undefined, null, '']) {
      const legs = projectVendorBill(
        { id: 'vb1', vendor_id: 'v', bill_amount: 100, bill_date: '2026-09-02', vendor_name },
        false,
      );
      expect(legs[0]?.party_name).toBe('');
    }
  });
});
