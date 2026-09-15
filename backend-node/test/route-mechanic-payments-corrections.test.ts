/**
 * TRUKVIA · Phase-3 · Gate-6n · Mechanic payment corrections read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/mechanic-payments/{pid}/corrections
 *
 * Fake-DB write-forbid pattern reused inline (no shared/locked test
 * infrastructure touched). Gate-6n-only fixture surface adds a
 * `payment_corrections` rowset spanning mechanic / supplier /
 * vendor / driver payment types to prove cross-type isolation.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const baseConfig: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017', dbName: 'trukvia_node_test',
  corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};

const IN_FUTURE = (): string => new Date(Date.now() + 3600_000).toISOString();
const IN_PAST = (): string => new Date(Date.now() - 60_000).toISOString();

interface State {
  sessions: Record<string, unknown>[];
  users: Record<string, unknown>[];
  companies: Record<string, unknown>[];
  payment_corrections: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x) && !(x instanceof Date);
}

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isPlainObject(v)) {
      const keys = Object.keys(v);
      const hasOps = keys.length > 0 && keys.every((kk) => kk.startsWith('$'));
      if (hasOps) continue; // Gate-6n route uses no operator filters.
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(
  d: Record<string, unknown>,
  projection?: Record<string, 0 | 1>,
): Record<string, unknown> {
  if (!projection) return { ...d };
  const inc = Object.entries(projection).filter(([, v]) => v === 1).map(([k]) => k);
  const exc = Object.entries(projection).filter(([, v]) => v === 0).map(([k]) => k);
  if (inc.length > 0) {
    const o: Record<string, unknown> = {};
    for (const k of inc) if (k in d) o[k] = d[k];
    return o;
  }
  const o: Record<string, unknown> = { ...d };
  for (const k of exc) delete o[k];
  return o;
}

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Record<string, unknown>[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'payment_corrections' ? state.payment_corrections
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    function makeCursor(
      f: Record<string, unknown>,
      opts?: { projection?: Record<string, 0 | 1> },
    ): {
      sort: (s: [string, 1 | -1][]) => ReturnType<typeof makeCursor>;
      skip: (n: number) => ReturnType<typeof makeCursor>;
      limit: (n: number) => ReturnType<typeof makeCursor>;
      toArray: () => Promise<Record<string, unknown>[]>;
    } {
      let hits = rows.filter((r) => matches(r, f));
      const cursor = {
        sort(spec: [string, 1 | -1][]) {
          hits = hits.slice().sort((a, b) => {
            for (const [k, d] of spec) {
              const av = a[k]; const bv = b[k];
              if (av === bv) continue;
              if (av === undefined) return 1 * d;
              if (bv === undefined) return -1 * d;
              return ((av as number | string) < (bv as number | string) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
        skip(n: number) { hits = hits.slice(n); return cursor; },
        limit(n: number) { hits = hits.slice(0, n); return cursor; },
        async toArray(): Promise<Record<string, unknown>[]> {
          return hits.map((d) => project(d, opts?.projection));
        },
      };
      return cursor;
    }
    return {
      find: vi.fn((f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => makeCursor(f, opts)),
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        return hit ? project(hit, opts?.projection) : null;
      }),
      countDocuments: vi.fn(async (f: Record<string, unknown>) => rows.filter((r) => matches(r, f)).length),
      insertOne: vi.fn(forbid(state, `${name}.insertOne`)),
      updateOne: vi.fn(forbid(state, `${name}.updateOne`)),
      updateMany: vi.fn(forbid(state, `${name}.updateMany`)),
      deleteOne: vi.fn(forbid(state, `${name}.deleteOne`)),
      deleteMany: vi.fn(forbid(state, `${name}.deleteMany`)),
      insertMany: vi.fn(forbid(state, `${name}.insertMany`)),
      replaceOne: vi.fn(forbid(state, `${name}.replaceOne`)),
      findOneAndUpdate: vi.fn(forbid(state, `${name}.findOneAndUpdate`)),
      findOneAndDelete: vi.fn(forbid(state, `${name}.findOneAndDelete`)),
      findOneAndReplace: vi.fn(forbid(state, `${name}.findOneAndReplace`)),
      bulkWrite: vi.fn(forbid(state, `${name}.bulkWrite`)),
      createIndex: vi.fn(async () => 'ok'),
    };
  };
  return { collection: vi.fn(collection) } as unknown as Db;
}

// ── Fixtures ─────────────────────────────────────────────────────────
function corr(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'c-x', user_id: 'u1', company_id: 'co-a',
    payment_type: 'mechanic', payment_id: 'pay-1',
    correction_index: 1, kind: 'amount_reversal',
    correction_reason: '', before: {}, after: {}, diff: {},
    linked_reversal_id: '', linked_new_id: '',
    force_reconciled_override: false,
    corrected_by: 'u1', corrected_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-owner', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
      { session_token: 'tok-u2', user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
    ],
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b', user_id: 'u2', is_default: true },
    ],
    payment_corrections: [
      // pay-1 mechanic corrections under u1/co-a (three, out-of-order created)
      corr({ id: 'c-m3', payment_id: 'pay-1', correction_index: 3, correction_reason: 'third'  }),
      corr({ id: 'c-m1', payment_id: 'pay-1', correction_index: 1, correction_reason: 'first', extra_field: 'preserved' }),
      corr({ id: 'c-m2', payment_id: 'pay-1', correction_index: 2, correction_reason: 'second' }),
      // pay-1 same pid, DIFFERENT payment_types — must be excluded.
      corr({ id: 'c-supp',  payment_type: 'supplier', payment_id: 'pay-1', correction_index: 1, correction_reason: 'supplier-crumb' }),
      corr({ id: 'c-vend',  payment_type: 'vendor',   payment_id: 'pay-1', correction_index: 1, correction_reason: 'vendor-crumb'   }),
      corr({ id: 'c-driv',  payment_type: 'driver',   payment_id: 'pay-1', correction_index: 1, correction_reason: 'driver-crumb'   }),
      // pay-2 mechanic corrections — different pid.
      corr({ id: 'c-p2-m1', payment_id: 'pay-2', correction_index: 1, correction_reason: 'p2-first' }),
      // Alt-company row (co-a-alt) for X-Company-Id override.
      corr({ id: 'c-alt', company_id: 'co-a-alt', payment_id: 'pay-1', correction_index: 1, correction_reason: 'alt-first' }),
      // Cross-user row (u2).
      corr({ id: 'c-u2', user_id: 'u2', company_id: 'co-b', payment_id: 'pay-1', correction_index: 1, correction_reason: 'u2-first' }),
    ],
    writes: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6n · Mechanic payment corrections read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 happy list · returns only mechanic corrections for pid under u1/co-a', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.map((x) => x['id'])).toEqual(['c-m1', 'c-m2', 'c-m3']);
  });

  it('2 unknown pid → 200 []', async () => {
    const r = await get('/api/mechanic-payments/no-such-pid/corrections', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('3 cross-payment-type isolation · supplier/vendor/driver rows excluded', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('c-supp');
    expect(ids).not.toContain('c-vend');
    expect(ids).not.toContain('c-driv');
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row['payment_type']).toBe('mechanic');
    }
  });

  it('4 cross-user isolation · u2 rows never visible to u1', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('c-u2');
  });

  it('5 cross-company isolation · co-a-alt row not returned under default co-a', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('c-alt');
    expect(ids).toEqual(['c-m1', 'c-m2', 'c-m3']);
  });

  it('6 owned X-Company-Id override → alt-company row', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.map((x) => x['id'])).toEqual(['c-alt']);
  });

  it('7 unowned X-Company-Id → default fallback (co-a)', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['c-m1', 'c-m2', 'c-m3']);
  });

  it('8 no header → default company scope', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['c-m1', 'c-m2', 'c-m3']);
  });

  it('9 projection strips _id and user_id', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('10 sort by correction_index ASC', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    const idx = (r.json() as Record<string, unknown>[]).map((x) => x['correction_index']);
    expect(idx).toEqual([1, 2, 3]);
  });

  it('11 cap 1000 smoke', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBeLessThanOrEqual(1000);
  });

  it('12 pay-2 returns only its own mechanic corrections', async () => {
    const r = await get('/api/mechanic-payments/pay-2/corrections', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['c-p2-m1']);
  });

  it('13 extra fields preserved verbatim (no re-shaping)', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    const rows = r.json() as Record<string, unknown>[];
    const c1 = rows.find((x) => x['id'] === 'c-m1')!;
    expect(c1['extra_field']).toBe('preserved');
    expect(c1['correction_reason']).toBe('first');
  });

  it('14 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('15 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('16 expired session → 401 Session expired', async () => {
    const r = await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('17 zero Node business writes across every branch', async () => {
    await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanic-payments/pay-2/corrections', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanic-payments/no-such-pid/corrections', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-u2' });
    await get('/api/mechanic-payments/pay-1/corrections');
    await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer nope' });
    await get('/api/mechanic-payments/pay-1/corrections', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
