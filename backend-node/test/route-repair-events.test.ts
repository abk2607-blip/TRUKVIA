/**
 * TRUKVIA · Phase-3 · Gate-6t · RepairEvent read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/repair-events?vehicle_id=&trip_id=&status=
 *   GET /api/repair-events/{rid}
 *
 * Fake-DB write-forbid pattern inlined. `$ne` handling reused from
 * Gate 6s matcher (missing key returns TRUE for `$ne:true`, matching
 * MongoDB semantics). Gate 6t exercises:
 *   * Soft-delete predicate on both endpoints.
 *   * `activeCompanyId()` consumption (X-Company-Id changes rowset).
 *   * 5000-row cap on LIST.
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
  repair_events: Record<string, unknown>[];
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
    : name === 'repair_events' ? state.repair_events
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

// Descending event_date so DESC sort yields e1 > e2 > e3 > e4.
const D1 = '2026-05-04';
const D2 = '2026-05-03';
const D3 = '2026-05-02';
const D4 = '2026-05-01';

function ev(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'ev-x', user_id: 'u1', company_id: 'co-a',
    vehicle_id: 'veh-1', trip_id: 'trp-1', status: 'open',
    event_date: D1, is_deleted: false,
    workshop_name: 'Alpha', ...overrides,
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
    repair_events: [
      ev({ id: 'e1', event_date: D1, is_deleted: false }),
      ev({ id: 'e2', event_date: D2, is_deleted: false, vehicle_id: 'veh-2', trip_id: 'trp-2', status: 'closed' }),
      ev({ id: 'e3', event_date: D3 }), // is_deleted MISSING → must be INCLUDED
      ev({ id: 'e4', event_date: D4, is_deleted: null }), // null → included
      ev({ id: 'e-sd', event_date: D1, is_deleted: true }), // soft-deleted → excluded
      ev({ id: 'e-alt', company_id: 'co-a-alt', event_date: D1, is_deleted: false }),
      ev({ id: 'e-u2', user_id: 'u2', company_id: 'co-b', event_date: D1, is_deleted: false }),
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

const CO_A_ACTIVE_IDS = ['e1', 'e2', 'e3', 'e4']; // sorted DESC by event_date

describe('Gate-6t · RepairEvent read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── LIST ──────────────────────────────────────────────────────────
  it('1 happy list · u1 · co-a · four active rows DESC by event_date', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('2 empty list · vehicle_id filter yields no rows → 200 []', async () => {
    const r = await get('/api/repair-events?vehicle_id=no-such', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('3 cross-user isolation · u2 never sees u1 rows', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u2' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-u2']);
  });

  it('4 cross-company isolation · co-a-alt row not visible in default co-a scope', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('e-alt');
  });

  it('5 is_deleted:true excluded', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('e-sd');
  });

  it('6 is_deleted:false included (e1, e2)', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('e1');
    expect(ids).toContain('e2');
  });

  it('7 missing is_deleted → INCLUDED ($ne:true matches missing key)', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('e3');
  });

  it('8 null is_deleted → included', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('e4');
  });

  it('9 vehicle_id filter · veh-2 → e2', async () => {
    const r = await get('/api/repair-events?vehicle_id=veh-2', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e2']);
  });

  it('10 trip_id filter · trp-2 → e2', async () => {
    const r = await get('/api/repair-events?trip_id=trp-2', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e2']);
  });

  it('11 status filter · closed → e2', async () => {
    const r = await get('/api/repair-events?status=closed', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e2']);
  });

  it('12 combined vehicle_id + trip_id + status', async () => {
    const r = await get('/api/repair-events?vehicle_id=veh-2&trip_id=trp-2&status=closed', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e2']);
  });

  it('13 empty-string filters omitted (truthy-gate) · returns all active co-a rows', async () => {
    const r = await get('/api/repair-events?vehicle_id=&trip_id=&status=', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('14 5000 cap · exactly 5000 returned when >5000 rows exist', async () => {
    state.repair_events.length = 0;
    for (let i = 0; i < 5001; i++) {
      state.repair_events.push(ev({
        id: 'z' + String(i).padStart(5, '0'),
        event_date: `2026-06-${String((i % 28) + 1).padStart(2, '0')}`,
        is_deleted: false,
      }));
    }
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    expect((r.json() as unknown[]).length).toBe(5000);
  });

  it('15 projection strips _id and user_id (LIST)', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('16 owned X-Company-Id override · co-a-alt → e-alt only', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-alt']);
  });

  it('17 unowned X-Company-Id → falls back to default co-a', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-b' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('18 no X-Company-Id header · default company', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  // ── DETAIL ────────────────────────────────────────────────────────
  it('19 detail happy · e1', async () => {
    const r = await get('/api/repair-events/e1', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const body = r.json() as Record<string, unknown>;
    expect(body['id']).toBe('e1');
    expect(body).not.toHaveProperty('_id');
    expect(body).not.toHaveProperty('user_id');
  });

  it('20 unknown rid → 404 exact literal', async () => {
    const r = await get('/api/repair-events/does-not-exist', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'RepairEvent not found' });
  });

  it('21 wrong-company rid → same 404 (e-u2 belongs to co-b)', async () => {
    const r = await get('/api/repair-events/e-u2', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'RepairEvent not found' });
  });

  it('22 soft-deleted rid → same 404 (e-sd is_deleted:true)', async () => {
    const r = await get('/api/repair-events/e-sd', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'RepairEvent not found' });
  });

  it('23 detail projection strips _id and user_id', async () => {
    const r = await get('/api/repair-events/e3', { authorization: 'Bearer tok-u1' });
    const body = r.json() as Record<string, unknown>;
    expect(body['id']).toBe('e3');
    expect(body).not.toHaveProperty('_id');
    expect(body).not.toHaveProperty('user_id');
  });

  // ── AUTH (locked 401 literals) ─────────────────────────────────────
  it('24 LIST no auth → 401 Not authenticated', async () => {
    const r = await get('/api/repair-events');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('25 LIST invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('26 LIST expired session → 401 Session expired', async () => {
    const r = await get('/api/repair-events', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('27 DETAIL no auth → 401 Not authenticated', async () => {
    const r = await get('/api/repair-events/e1');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('28 DETAIL invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/repair-events/e1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('29 DETAIL expired session → 401 Session expired', async () => {
    const r = await get('/api/repair-events/e1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── ZERO-WRITE AGGREGATE ───────────────────────────────────────────
  it('30 zero Node writes across every exercised branch', async () => {
    await get('/api/repair-events');
    await get('/api/repair-events', { authorization: 'Bearer nope' });
    await get('/api/repair-events', { authorization: 'Bearer tok-expired' });
    await get('/api/repair-events', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events?vehicle_id=veh-2', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events?trip_id=trp-2', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events?status=closed', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events?vehicle_id=veh-2&trip_id=trp-2&status=closed', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    await get('/api/repair-events', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-b' });
    await get('/api/repair-events/e1', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events/does-not-exist', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events/e-u2', { authorization: 'Bearer tok-u1' });
    await get('/api/repair-events/e-sd', { authorization: 'Bearer tok-u1' });
    expect(state.writes).toEqual([]);
  });
});
