import { describe, it, expect } from 'vitest';
import { matchesBucketB, compositeId } from '../src/idempotency.js';
import { createHash } from 'node:crypto';

describe('idempotency · unit primitives', () => {
  it('allowlist matches POST /api/saved-trip-filters only', () => {
    expect(matchesBucketB('POST', '/api/saved-trip-filters')).toBe(true);
    expect(matchesBucketB('post', '/api/saved-trip-filters')).toBe(true);
    expect(matchesBucketB('GET', '/api/saved-trip-filters')).toBe(false);
    expect(matchesBucketB('DELETE', '/api/saved-trip-filters/abc')).toBe(false);
    expect(matchesBucketB('POST', '/api/supplier-payments/x/corrections')).toBe(false);
    expect(matchesBucketB('POST', '/api/saved-trip-filters/abc')).toBe(false);
    expect(matchesBucketB('POST', '/api/trips')).toBe(false);
  });

  it('composite-id is sha256(user|company_or_"_"|METHOD|path|key) — Python-parity vector', () => {
    const expected = createHash('sha256')
      .update('u1|co-a|POST|/api/saved-trip-filters|k123', 'utf8').digest('hex');
    expect(compositeId('u1', 'co-a', 'POST', '/api/saved-trip-filters', 'k123')).toBe(expected);

    const emptyCo = createHash('sha256')
      .update('u1|_|POST|/api/saved-trip-filters|k123', 'utf8').digest('hex');
    expect(compositeId('u1', '', 'POST', '/api/saved-trip-filters', 'k123')).toBe(emptyCo);

    // Different user or company yields different id.
    const other = compositeId('u2', 'co-a', 'POST', '/api/saved-trip-filters', 'k123');
    expect(other).not.toBe(expected);
  });
});
