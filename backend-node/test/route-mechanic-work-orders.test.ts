/**
 * TRUKVIA · Phase-3 · Gate-6u · MechanicWorkOrder read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/mechanic-work-orders?mechanic_id=&vehicle_id=&repair_event_id=&trip_id=
 *   GET /api/mechanic-work-orders/{wid}
 *
 * Fake-DB write-forbid pattern inlined (mirrors Gate 6t). `$ne` matcher
 * inlined with Mongo semantics (missing key returns TRUE for `$ne:true`).
 * Gate 6u exercises:
 *   * Soft-delete predicate on both endpoints.
 *   * `activeCompanyId()` consumption (X-Company-Id changes rowset).
 *   * 5000-row cap on LIST.
 *   * work_date DESC ordering.
 *   * 404 literal parity on DETAIL for miss/wrong-company/soft-deleted.
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
  mechanic_work_orders: Record<string, unknown>[];
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
    : name === 'mechanic_work_orders' ? state.mechanic_work_orders
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

// Descending work_date so DESC sort yields w1 > w2 > w3 > w4.
const D1 = '2026-05-04';
const D2 = '2026-05-03';
const D3 = '2026-05-02';
const D4 = '2026-05-01';

function wo(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'wo-x', user_id: 'u1', company_id: 'co-a',
    mechanic_id: 'mec-1', vehicle_id: 'veh-1',
    repair_event_id: 're-1', trip_id: 'trp-1',
    work_date: D1, amount: 1000, is_deleted: false,
    mechanic_name: 'Alpha Garage', narration: 'body work',
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
    mechanic_work_orders: [
      wo({ id: 'w1', work_date: D1, is_deleted: false }),
      wo({ id: 'w2', work_date: D2, is_deleted: false, mechanic_id: 'mec-2', vehicle_id: 'veh-2', repair_event_id: 're-2', trip_id: 'trp-2' }),
      wo({ id: 'w3', work_date: D3 }), // is_deleted MISSING → must be INCLUDED
      wo({ id: 'w4', work_date: D4, is_deleted: null }), // null → included
      wo({ id: 'w-sd', work_date: D1, is_deleted: true }), // soft-deleted → excluded
      wo({ id: 'w-alt', company_id: 'co-a-alt', work_date: D1, is_deleted: false }),
      wo({ id: 'w-u2', user_id: 'u2', company_id: 'co-b', work_date: D1, is_deleted: false }),
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

const CO_A_ACTIVE_IDS = ['w1', 'w2', 'w3', 'w4']; // sorted DESC by work_date

describe('Gate-6u · MechanicWorkOrder read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── LIST ──────────────────────────────────────────────────────────
  it('1 happy list · u1 · co-a · four active rows DESC by work_date', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('2 empty list · vehicle_id filter yields no rows → 200 []', async () => {
    const r = await get('/api/mechanic-work-orders?vehicle_id=no-such', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('3 cross-user isolation · u2 never sees u1 rows', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u2' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['w-u2']);
  });

  it('4 cross-company isolation · co-a-alt row not visible in default co-a scope', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('w-alt');
  });

  it('5 is_deleted:true excluded', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('w-sd');
  });

  it('6 is_deleted:false included (w1, w2)', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('w1');
    expect(ids).toContain('w2');
  });

  it('7 missing is_deleted → INCLUDED ($ne:true matches missing key)', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('w3');
  });

  it('8 null is_deleted → included', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('w4');
  });

  it('9 mechanic_id filter · mec-2 → w2', async () => {
    const r = await get('/api/mechanic-work-orders?mechanic_id=mec-2', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['w2']);
  });

  it('10 vehicle_id filter · veh-2 → w2', async () => {
    const r = await get('/api/mechanic-work-orders?vehicle_id=veh-2', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['w2']);
  });

  it('11 repair_event_id filter · re-2 → w2', async () => {
    const r = await get('/api/mechanic-work-orders?repair_event_id=re-2', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['w2']);
  });

  it('12 trip_id filter · trp-2 → w2', async () => {
    const r = await get('/api/mechanic-work-orders?trip_id=trp-2', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['w2']);
  });

  it('13 combined mechanic_id + vehicle_id + repair_event_id + trip_id', async () => {
    const r = await get('/api/mechanic-work-orders?mechanic_id=mec-2&vehicle_id=veh-2&repair_event_id=re-2&trip_id=trp-2', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['w2']);
  });

  it('14 empty-string filters omitted (truthy-gate) · returns all active co-a rows', async () => {
    const r = await get('/api/mechanic-work-orders?mechanic_id=&vehicle_id=&repair_event_id=&trip_id=', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('15 5000 cap · exactly 5000 returned when >5000 rows exist', async () => {
    state.mechanic_work_orders.length = 0;
    for (let i = 0; i < 5001; i++) {
      state.mechanic_work_orders.push(wo({
        id: 'z' + String(i).padStart(5, '0'),
        work_date: `2026-06-${String((i % 28) + 1).padStart(2, '0')}`,
        is_deleted: false,
      }));
    }
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    expect((r.json() as unknown[]).length).toBe(5000);
  });

  it('16 projection strips _id and user_id (LIST)', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('17 extra fields preserved (LIST) · mechanic_name/narration/amount', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    const first = (r.json() as Record<string, unknown>[])[0];
    expect(first['mechanic_name']).toBe('Alpha Garage');
    expect(first['narration']).toBe('body work');
    expect(first['amount']).toBe(1000);
  });

  it('18 owned X-Company-Id override · co-a-alt → w-alt only', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['w-alt']);
  });

  it('19 unowned X-Company-Id → falls back to default co-a', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-b' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('20 no X-Company-Id header · default company', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  // ── DETAIL ────────────────────────────────────────────────────────
  it('21 detail happy · w1', async () => {
    const r = await get('/api/mechanic-work-orders/w1', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const body = r.json() as Record<string, unknown>;
    expect(body['id']).toBe('w1');
    expect(body).not.toHaveProperty('_id');
    expect(body).not.toHaveProperty('user_id');
  });

  it('22 unknown wid → 404 exact literal', async () => {
    const r = await get('/api/mechanic-work-orders/does-not-exist', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'MechanicWorkOrder not found' });
  });

  it('23 wrong-company wid → same 404 (w-u2 belongs to co-b)', async () => {
    const r = await get('/api/mechanic-work-orders/w-u2', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'MechanicWorkOrder not found' });
  });

  it('24 soft-deleted wid → same 404 (w-sd is_deleted:true)', async () => {
    const r = await get('/api/mechanic-work-orders/w-sd', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'MechanicWorkOrder not found' });
  });

  it('25 detail projection strips _id and user_id + extra fields preserved', async () => {
    const r = await get('/api/mechanic-work-orders/w3', { authorization: 'Bearer tok-u1' });
    const body = r.json() as Record<string, unknown>;
    expect(body['id']).toBe('w3');
    expect(body['mechanic_name']).toBe('Alpha Garage');
    expect(body['amount']).toBe(1000);
    expect(body).not.toHaveProperty('_id');
    expect(body).not.toHaveProperty('user_id');
  });

  // ── AUTH (locked 401 literals) ─────────────────────────────────────
  it('26 LIST no auth → 401 Not authenticated', async () => {
    const r = await get('/api/mechanic-work-orders');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('27 LIST invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('28 LIST expired session → 401 Session expired', async () => {
    const r = await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('29 DETAIL no auth → 401 Not authenticated', async () => {
    const r = await get('/api/mechanic-work-orders/w1');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('30 DETAIL invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/mechanic-work-orders/w1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('31 DETAIL expired session → 401 Session expired', async () => {
    const r = await get('/api/mechanic-work-orders/w1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── ZERO-WRITE AGGREGATE ───────────────────────────────────────────
  it('32 zero Node writes across every exercised branch', async () => {
    await get('/api/mechanic-work-orders');
    await get('/api/mechanic-work-orders', { authorization: 'Bearer nope' });
    await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-expired' });
    await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders?mechanic_id=mec-2', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders?vehicle_id=veh-2', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders?repair_event_id=re-2', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders?trip_id=trp-2', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders?mechanic_id=mec-2&vehicle_id=veh-2&repair_event_id=re-2&trip_id=trp-2', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    await get('/api/mechanic-work-orders', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-b' });
    await get('/api/mechanic-work-orders/w1', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders/does-not-exist', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders/w-u2', { authorization: 'Bearer tok-u1' });
    await get('/api/mechanic-work-orders/w-sd', { authorization: 'Bearer tok-u1' });
    expect(state.writes).toEqual([]);
  });
});
