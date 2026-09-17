/**
 * TRUKVIA · Phase-3 · Gate-6y · DriverPayment list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/drivers/{did}/payments
 *
 * New parity dimensions vs Gate 6w/6x:
 *   * Cross-collection `drivers.findOne` pre-check with EXACT 404 literal.
 *   * Projection strips ONLY `_id` — `user_id` remains in response.
 *   * NO `.limit(5000)` cap — unbounded async cursor.
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
  drivers: Record<string, unknown>[];
  driver_payments: Record<string, unknown>[];
  writes: string[];
  reads: string[];
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
      const opOnly = keys.length > 0 && keys.every((kk) => kk === '$gte' || kk === '$lte' || kk === '$ne');
      if (opOnly) {
        for (const [op, opv] of Object.entries(v)) {
          if (op === '$gte' && !(typeof dv === 'string' && typeof opv === 'string' && dv >= opv)) return false;
          if (op === '$lte' && !(typeof dv === 'string' && typeof opv === 'string' && dv <= opv)) return false;
          if (op === '$ne' && dv === opv) return false;
        }
        continue;
      }
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(d: Record<string, unknown>, projection?: Record<string, 0 | 1>): Record<string, unknown> {
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
    : name === 'drivers' ? state.drivers
    : name === 'driver_payments' ? state.driver_payments
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    function makeCursor(f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }): {
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
              return ((av as string | number) < (bv as string | number) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
        skip(n: number) { hits = hits.slice(n); return cursor; },
        limit(n: number) { hits = hits.slice(0, Math.max(0, n)); return cursor; },
        async toArray(): Promise<Record<string, unknown>[]> {
          state.reads.push(`${name}.find`);
          return hits.map((d) => project(d, opts?.projection));
        },
      };
      return cursor;
    }
    return {
      find: vi.fn((f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => makeCursor(f, opts)),
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        state.reads.push(`${name}.findOne`);
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

const D1 = '2026-05-04';
const D2 = '2026-05-03';
const D3 = '2026-05-02';
const D4 = '2026-05-01';

function dp(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'dp-x', user_id: 'u1', company_id: 'co-a',
    driver_id: 'drv-1', date: D1, amount: 1000, type: 'payment_out',
    mode: 'Bank', ref_no: 'DR-1', against: 'advance',
    remarks: 'shift pay', is_deleted: false, is_reversed: false,
    ...overrides,
  };
}

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-u1',      user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
    ],
    users: [
      { user_id: 'u1', email: 'u1@x' },
      { user_id: 'u2', email: 'u2@x' },
    ],
    companies: [
      { id: 'co-a',     user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b',     user_id: 'u2', is_default: true },
    ],
    drivers: [
      { id: 'drv-1', user_id: 'u1', company_id: 'co-a',     name: 'Alpha' },
      { id: 'drv-1', user_id: 'u1', company_id: 'co-a-alt', name: 'Alpha Alt' },
      { id: 'drv-u2', user_id: 'u2', company_id: 'co-b',    name: 'Beta' },
      { id: 'drv-empty', user_id: 'u1', company_id: 'co-a', name: 'No Payments' },
    ],
    driver_payments: [
      dp({ id: 'x1', date: D1, is_deleted: false }),
      dp({ id: 'x2', date: D2, is_deleted: false }),
      dp({ id: 'x3', date: D3 }), // is_deleted MISSING → included
      dp({ id: 'x4', date: D4, is_deleted: null }), // null → included
      dp({ id: 'x-del', date: D1, is_deleted: true }),
      // Different company (owned alt + unowned other tenant).
      dp({ id: 'x-alt', company_id: 'co-a-alt', date: D1 }),
      dp({ id: 'x-u2',  user_id: 'u2', company_id: 'co-b', driver_id: 'drv-u2', date: D1 }),
    ],
    writes: [],
    reads: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const DRV1_ACTIVE_IDS = ['x1', 'x2', 'x3', 'x4']; // DESC by date

describe('Gate-6y · DriverPayment list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── HAPPY / EMPTY / 404 ───────────────────────────────────────────
  it('1 valid driver with payments · four active rows DESC by date', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(DRV1_ACTIVE_IDS);
  });

  it('2 valid driver with no payments → 200 []', async () => {
    const r = await get('/api/drivers/drv-empty/payments', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('3 unknown driver → 404 exact "Driver not found"', async () => {
    const r = await get('/api/drivers/does-not-exist/payments', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Driver not found' });
  });

  it('4 wrong-company driver → same 404 "Driver not found"', async () => {
    // drv-u2 belongs to u2/co-b; u1 in default co-a cannot see it.
    const r = await get('/api/drivers/drv-u2/payments', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Driver not found' });
  });

  it('5 cross-user isolation · u2 sees drv-u2', async () => {
    const r = await get('/api/drivers/drv-u2/payments', { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['x-u2']);
  });

  // ── X-COMPANY-ID SEMANTICS ────────────────────────────────────────
  it('6 owned X-Company-Id override · co-a-alt · drv-1 → [x-alt]', async () => {
    const r = await get('/api/drivers/drv-1/payments', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['x-alt']);
  });

  it('7 unowned X-Company-Id (co-b for u1) → falls back to default co-a', async () => {
    const r = await get('/api/drivers/drv-1/payments', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-b',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(DRV1_ACTIVE_IDS);
  });

  it('8 no X-Company-Id header · default co-a', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(DRV1_ACTIVE_IDS);
  });

  // ── SOFT-DELETE PREDICATE ($ne:true) ──────────────────────────────
  it('9 is_deleted:true excluded (x-del absent)', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('x-del');
  });

  it('10 is_deleted:false included (x1, x2)', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('x1'); expect(ids).toContain('x2');
  });

  it('11 is_deleted missing → INCLUDED (x3)', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('x3');
  });

  it('12 is_deleted:null included (x4)', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('x4');
  });

  // ── PROJECTION / ORDERING (NO CAP) ────────────────────────────────
  it('13 payment projection strips ONLY _id (user_id REMAINS)', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row['user_id']).toBe('u1');
    }
  });

  it('14 user_id present in returned payment · byte-parity requirement', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const first = (r.json() as Record<string, unknown>[])[0];
    expect(first['user_id']).toBe('u1');
  });

  it('15 date DESC ordering · x1 > x2 > x3 > x4', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const dates = (r.json() as Record<string, unknown>[]).map((x) => x['date']);
    expect(dates).toEqual([D1, D2, D3, D4]);
  });

  // ── AUTH (locked 401 literals) ─────────────────────────────────────
  it('16 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/drivers/drv-1/payments');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('17 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('18 expired session → 401 Session expired', async () => {
    const r = await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── CROSS-COLLECTION PRE-CHECK ORDER ──────────────────────────────
  it('19 drivers.findOne pre-check runs BEFORE driver_payments.find', async () => {
    state.reads = [];
    await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    const bizReads = state.reads.filter((r) => r === 'drivers.findOne' || r === 'driver_payments.find');
    expect(bizReads).toEqual(['drivers.findOne', 'driver_payments.find']);
  });

  it('20 on 404 · payment query is NEVER executed', async () => {
    state.reads = [];
    await get('/api/drivers/does-not-exist/payments', { authorization: 'Bearer tok-u1' });
    expect(state.reads).toContain('drivers.findOne');
    expect(state.reads).not.toContain('driver_payments.find');
  });

  // ── ZERO-WRITE AGGREGATE ───────────────────────────────────────────
  it('21 zero Node writes across every exercised branch', async () => {
    await get('/api/drivers/drv-1/payments');
    await get('/api/drivers/drv-1/payments', { authorization: 'Bearer nope' });
    await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-expired' });
    await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/drivers/does-not-exist/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/drivers/drv-u2/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/drivers/drv-empty/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u2' });
    await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    await get('/api/drivers/drv-1/payments', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-b' });
    expect(state.writes).toEqual([]);
  });
});
