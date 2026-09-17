/**
 * TRUKVIA · Phase-3 · Gate-6x · MechanicPayment list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/mechanics/{mid}/payments
 *
 * Fake-DB write-forbid pattern inlined (mirrors Gate 6t/6u/6v/6w). `$ne`
 * matcher inlined with Mongo semantics (missing key returns TRUE for
 * `$ne:true`).
 * Gate 6x exercises:
 *   * Single soft-delete predicate `is_deleted: {$ne: true}`.
 *   * `activeCompanyId()` consumption (X-Company-Id changes rowset).
 *   * 5000-row cap.
 *   * date DESC ordering.
 *   * NO 404 branch: unknown mid / wrong-company mid → 200 [].
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
  mechanic_payments: Record<string, unknown>[];
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
      const opOnly = keys.length > 0 && keys.every((kk) => kk === '$gte' || kk === '$lte' || kk === '$ne');
      if (opOnly) {
        for (const [op, opv] of Object.entries(v)) {
          if (op === '$gte' && !(typeof dv === 'string' && typeof opv === 'string' && dv >= opv)) return false;
          if (op === '$lte' && !(typeof dv === 'string' && typeof opv === 'string' && dv <= opv)) return false;
          // $ne — MongoDB semantics: missing key ALSO matches (dv === undefined !== true).
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
    : name === 'mechanic_payments' ? state.mechanic_payments
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

// Descending date so DESC sort yields q1 > q2 > q3 > q4.
const D1 = '2026-05-04';
const D2 = '2026-05-03';
const D3 = '2026-05-02';
const D4 = '2026-05-01';

function mp(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'mp-x', user_id: 'u1', company_id: 'co-a',
    mechanic_id: 'mec-1',
    date: D1, amount: 1500, type: 'payment_out',
    mode: 'Bank', ref_no: 'MR-1', against: 'work_order',
    mechanic_work_order_id: 'wo-1', remarks: 'labour pay',
    is_deleted: false, is_reversed: false, correction_count: 0,
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
    mechanic_payments: [
      // Active co-a / mec-1 payments (is_deleted $ne:true).
      mp({ id: 'q1', date: D1, is_deleted: false }),
      mp({ id: 'q2', date: D2, is_deleted: false }),
      mp({ id: 'q3', date: D3 }), // is_deleted MISSING → included
      mp({ id: 'q4', date: D4, is_deleted: null }), // null → included
      // Soft-deleted → excluded.
      mp({ id: 'q-del', date: D1, is_deleted: true }),
      // Different mechanic same company — must NOT appear.
      mp({ id: 'q-mec2', mechanic_id: 'mec-2', date: D1 }),
      // Same mechanic different company (owned & unowned).
      mp({ id: 'q-alt',  company_id: 'co-a-alt', date: D1 }),
      mp({ id: 'q-u2',   user_id: 'u2', company_id: 'co-b', date: D1 }),
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

const MEC1_ACTIVE_IDS = ['q1', 'q2', 'q3', 'q4']; // DESC by date

describe('Gate-6x · MechanicPayment list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── HAPPY / EMPTY / MISS ──────────────────────────────────────────
  it('1 successful list · mec-1 · co-a · four active rows DESC by date', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(MEC1_ACTIVE_IDS);
  });

  it('2 empty list · different mechanic with no payments → 200 []', async () => {
    const r = await get('/api/mechanics/mec-empty/payments', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('3 unknown mechanic → 200 [] (no 404 mechanic-existence lookup)', async () => {
    const r = await get('/api/mechanics/does-not-exist/payments', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('4 wrong-company · u1 asks for u2/co-b mechanic → 200 []', async () => {
    // q-u2 exists but under u2 / co-b. u1 default co-a sees nothing for that mechanic_id.
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('q-u2');
  });

  it('5 cross-user isolation · u2 · mec-1 → [q-u2]', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u2' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['q-u2']);
  });

  it('6 different mechanic · mec-2 → [q-mec2]', async () => {
    const r = await get('/api/mechanics/mec-2/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['q-mec2']);
  });

  // ── X-COMPANY-ID SEMANTICS ────────────────────────────────────────
  it('7 owned X-Company-Id override · co-a-alt · mec-1 → [q-alt]', async () => {
    const r = await get('/api/mechanics/mec-1/payments', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['q-alt']);
  });

  it('8 unowned X-Company-Id (co-b for u1) → falls back to default co-a', async () => {
    const r = await get('/api/mechanics/mec-1/payments', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-b',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(MEC1_ACTIVE_IDS);
  });

  it('9 no X-Company-Id header · default co-a', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(MEC1_ACTIVE_IDS);
  });

  // ── SOFT-DELETE PREDICATE ($ne:true) ──────────────────────────────
  it('10 is_deleted:true excluded (q-del absent)', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('q-del');
  });

  it('11 is_deleted:false included (q1, q2)', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('q1');
    expect(ids).toContain('q2');
  });

  it('12 is_deleted missing → INCLUDED (q3)', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('q3');
  });

  it('13 is_deleted:null included (q4)', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('q4');
  });

  // ── PROJECTION / ORDERING / CAP ───────────────────────────────────
  it('14 projection strips _id and user_id', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('15 date DESC ordering · q1 > q2 > q3 > q4', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    const dates = (r.json() as Record<string, unknown>[]).map((x) => x['date']);
    expect(dates).toEqual([D1, D2, D3, D4]);
  });

  it('16 5000 cap · exactly 5000 returned when >5000 rows exist', async () => {
    state.mechanic_payments.length = 0;
    for (let i = 0; i < 5001; i++) {
      state.mechanic_payments.push(mp({
        id: 'z' + String(i).padStart(5, '0'),
        date: `2026-06-${String((i % 28) + 1).padStart(2, '0')}`,
        is_deleted: false,
      }));
    }
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    expect((r.json() as unknown[]).length).toBe(5000);
  });

  // ── AUTH (locked 401 literals) ─────────────────────────────────────
  it('17 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/mechanics/mec-1/payments');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('18 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('19 expired session → 401 Session expired', async () => {
    const r = await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── ZERO-WRITE AGGREGATE ───────────────────────────────────────────
  it('20 zero Node writes across every exercised branch', async () => {
    await get('/api/mechanics/mec-1/payments');
    await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer nope' });
    await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-expired' });
    await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanics/does-not-exist/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanics/mec-empty/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanics/mec-2/payments', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u2' });
    await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    await get('/api/mechanics/mec-1/payments', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-b' });
    expect(state.writes).toEqual([]);
  });
});
