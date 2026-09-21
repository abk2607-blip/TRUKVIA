/**
 * Unit tests for the two Finance reads deferred out of slice 2a:
 * GET /api/fin/day-status and GET /api/fin/day-closures/{d}/late-entries.
 *
 * The date parser gets most of the attention because it is where the real
 * bugs were. CPython 3.11's `date.fromisoformat` accepts more than
 * YYYY-MM-DD — the basic form and ISO week dates — and a regex guard silently
 * 400s inputs Python answers 200 to. Every expected value below came from
 * running the interpreter, including the ordinals.
 *
 * Live comparison against Python lives in scripts/fin-status-parity.ts.
 */
import { describe, expect, it } from 'vitest';
import { pyIsoDateOrdinal, pyIsoDateValid } from '../src/common/py-date';
import { bucket } from '../src/fin/fin-status-reads.service';

describe('CPython date.fromisoformat — acceptance and ordinal', () => {
  // [input, Python's toordinal()]
  it.each([
    ['2026-02-14', 739661],
    ['20260214', 739661], // basic form — a regex guard rejects this
    ['2026-W07-6', 739661], // ISO week date, same day
    ['2026-W07', 739656], // week with no day means Monday
    ['2026-W53-1', 739978],
    ['2020-W53-7', 737793], // week 53 spilling into the next year
    ['9999-12-31', 3652059],
    ['0001-01-01', 1],
    ['2024-02-29', 738945], // leap day
  ])('accepts %j with ordinal %d', (input, ordinal) => {
    expect(pyIsoDateOrdinal(input as string)).toBe(ordinal);
  });

  it.each([
    '2026-W99-1', // week 99 does not exist
    '2026-02-30',
    '2026-13-01',
    '0000-01-01', // year 0 is out of range
    '2026-2-14', // single-digit month is not ISO
    '26-02-14',
    '2026-02-14T00:00', // a datetime, not a date
    '',
    '2023-02-29', // 2023 is not a leap year
    '2026-02-14 ', // trailing space
    'not-a-date',
  ])('rejects %j', (input) => {
    expect(pyIsoDateOrdinal(input)).toBeNull();
    expect(pyIsoDateValid(input)).toBe(false);
  });

  it('gives (a - b).days by subtraction, which is what days_late needs', () => {
    const a = pyIsoDateOrdinal('2026-02-14') as number;
    const b = pyIsoDateOrdinal('2026-01-01') as number;
    expect(a - b).toBe(44);
  });

  it('agrees across the three spellings of one day', () => {
    const ords = ['2026-02-14', '20260214', '2026-W07-6'].map(pyIsoDateOrdinal);
    expect(new Set(ords).size).toBe(1);
  });

  it('orders the basic form correctly, which string comparison does not', () => {
    // '20260903' > '2026-09-21' as TEXT, because '0' (0x30) beats '-' (0x2d).
    // That read a past date as a future one and 422'd it.
    expect('20260903' > '2026-09-21').toBe(true);
    const past = pyIsoDateOrdinal('20260903') as number;
    const today = pyIsoDateOrdinal('2026-09-21') as number;
    expect(past).toBeLessThan(today);
  });
});

describe('late-entries day bucket', () => {
  it.each([
    [0, '0-7'],
    [7, '0-7'],
    [8, '8-30'],
    [30, '8-30'],
    [31, '31-90'],
    [90, '31-90'],
    [91, '90+'],
    [10000, '90+'],
  ])('puts %d days in %s', (days, expected) => {
    expect(bucket(days as number)).toBe(expected);
  });

  it('treats a clamped negative as 0 days, the first bucket', () => {
    // days_late is max(0, …), so a txn dated after the close lands in 0-7.
    expect(bucket(Math.max(0, -5))).toBe('0-7');
  });
});
