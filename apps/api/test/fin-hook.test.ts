/**
 * Unit tests for slice 2c unit 1 — the canonical projection hook.
 *
 * Only the parts that need no database live here. The failure-queue document
 * itself, the reopen rules and the reverse bridge are compared against the real
 * Python implementation in scripts/fin-hook-parity.ts, which drives both sides
 * through the same scenario list against two throwaway MongoDB databases.
 *
 * Constants below were read out of the running interpreter, not the source, so
 * the runtime monkey-patch at the bottom of services_fin_txn.py is accounted
 * for rather than assumed away.
 */
import { describe, expect, it } from 'vitest';
import {
  BACKOFF_BASE_SECONDS,
  BACKOFF_CAP_SECONDS,
  computeNextAttempt,
  FAILURE_STATUS_PENDING,
  FAILURE_STATUS_PERMANENTLY_FAILED,
  FAILURE_STATUS_RESOLVED,
  FAILURE_STATUS_RETRYING,
  MAX_RETRIES,
  NON_TERMINAL_STATUSES,
  SUPPORTED_SOURCE_TYPES,
} from '../src/fin/fin-hook';

const secondsFromNow = (retryCount: number): number => {
  const base = new Date('2026-09-21T12:00:00.000Z');
  return Math.round((Date.parse(computeNextAttempt(retryCount, base)) - base.getTime()) / 1000);
};

describe('retry policy', () => {
  it('matches Python: 60s doubling, capped at 24h', () => {
    // From the interpreter, retry_count 0..11.
    expect(Array.from({ length: 12 }, (_, n) => secondsFromNow(n))).toEqual([
      60, 120, 240, 480, 960, 1920, 3840, 7680, 15360, 30720, 61440, 86400,
    ]);
  });

  it('stays at the cap for every further attempt', () => {
    expect(secondsFromNow(20)).toBe(BACKOFF_CAP_SECONDS);
    expect(secondsFromNow(100)).toBe(BACKOFF_CAP_SECONDS);
  });

  it('keeps the constants Python uses', () => {
    expect(MAX_RETRIES).toBe(8);
    expect(BACKOFF_BASE_SECONDS).toBe(60);
    expect(BACKOFF_CAP_SECONDS).toBe(86_400);
  });

  it('emits the Python isoformat shape, with microseconds', () => {
    expect(computeNextAttempt(0, new Date('2026-09-21T12:00:00.000Z'))).toBe(
      '2026-09-21T12:01:00.000000+00:00',
    );
  });
});

describe('failure statuses', () => {
  it('uses Python’s literals', () => {
    expect([
      FAILURE_STATUS_PENDING,
      FAILURE_STATUS_RETRYING,
      FAILURE_STATUS_RESOLVED,
      FAILURE_STATUS_PERMANENTLY_FAILED,
    ]).toEqual(['pending', 'retrying', 'resolved', 'permanently_failed']);
  });

  it('treats exactly pending and retrying as non-terminal', () => {
    // The retry driver selects on this set; widening it would make it replay
    // rows that are already settled.
    expect([...NON_TERMINAL_STATUSES].sort()).toEqual(['pending', 'retrying']);
    expect(NON_TERMINAL_STATUSES).not.toContain(FAILURE_STATUS_RESOLVED);
    expect(NON_TERMINAL_STATUSES).not.toContain(FAILURE_STATUS_PERMANENTLY_FAILED);
  });
});

describe('supported source types', () => {
  it('has thirteen, in Python’s runtime order', () => {
    // Twelve come from the literal; driver_payment is appended by the Iter150I
    // monkey-patch at the bottom of services_fin_txn.py. Reading only the
    // literal gives the wrong list, and the hook renders it into its error.
    expect(SUPPORTED_SOURCE_TYPES).toEqual([
      'invoice',
      'credit_debit_note',
      'supplier_payment',
      'vendor_payment',
      'mechanic_payment',
      'expense',
      'vendor_bill',
      'mechanic_work_order',
      'trip_customer_receipt',
      'wallet_recharge',
      'wallet_transfer',
      'wallet_adjustment',
      'driver_payment',
    ]);
  });

  it('includes the two with a TypeScript projection', () => {
    expect(SUPPORTED_SOURCE_TYPES).toContain('vendor_payment');
    expect(SUPPORTED_SOURCE_TYPES).toContain('vendor_bill');
  });

  it('does not include reconciliation or account seeding as source types', () => {
    expect(SUPPORTED_SOURCE_TYPES).not.toContain('reconciliation');
    expect(SUPPORTED_SOURCE_TYPES).not.toContain('fin_account');
  });
});
