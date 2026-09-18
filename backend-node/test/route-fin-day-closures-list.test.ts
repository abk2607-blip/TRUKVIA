/**
 * TRUKVIA · Phase-3 · Gate-7m · Fin day-closures list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/fin/day-closures
 *
 * Fake-DB write-forbid pattern inlined (mirrors Gate 7a). `$gte` / `$lte`
 * matcher inlined with Mongo semantics (missing key does NOT match).
 * Gate 7m exercises the `limit: int` coercion axis (pydantic-core 2.46.4
 * `str_as_int`) plus the handler-side clamp int(max(1, min(limit, 5000))).
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
  fin_day_closures: Record<string, unknown>[];
  writes: string[];
  finds: { filter: Record<string, unknown>; projection?: Record<string, 0 | 1>; sort?: unknown; limit?: number }[];
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
      if (keys.length > 0 && keys.every((kk) => kk === '$gte' || kk === '$lte')) {
        for (const [op, opv] of Object.entries(v)) {
          if (op === '$gte' && !(typeof dv === 'string' && typeof opv === 'string' && dv >= opv)) return false;
          if (op === '$lte' && !(typeof dv === 'string' && typeof opv === 'string' && dv <= opv)) return false;
        }
        continue;
      }
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(d: Record<string, unknown>, projection?: Record<string, 0 | 1>): Record<string, unknown> {
  const o: Record<string, unknown> = { ...d };
  if (!projection) return o;
  for (const [k, v] of Object.entries(projection)) if (v === 0) delete o[k];
  return o;
}

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Record<string, unknown>[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'fin_day_closures' ? state.fin_day_closures
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    function makeCursor(f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }): {
      sort: (s: [string, 1 | -1][]) => ReturnType<typeof makeCursor>;
      limit: (n: number) => ReturnType<typeof makeCursor>;
      toArray: () => Promise<Record<string, unknown>[]>;
    } {
      const rec: State['finds'][number] = { filter: f, projection: opts?.projection };
      if (name === 'fin_day_closures') state.finds.push(rec);
      let hits = rows.filter((r) => matches(r, f));
      const cursor = {
        sort(spec: [string, 1 | -1][]) {
          rec.sort = spec;
          hits = hits.slice().sort((a, b) => {
            for (const [k, d] of spec) {
              const av = a[k]; const bv = b[k];
              if (av === bv) continue;
              if (av === undefined) return 1 * d;
              if (bv === undefined) return -1 * d;
              return ((av as string) < (bv as string) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
        limit(n: number) { rec.limit = n; hits = hits.slice(0, Math.max(0, n)); return cursor; },
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

function fdc(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'fdc-x', user_id: 'u1', company_id: 'co-a',
    close_date: '2026-05-01', status: 'closed',
    closed_at: '2026-05-02T00:00:00+00:00', closed_by: 'u1',
    snapshot: { AR: { in: 1000.0, out: 250.5, net: 749.5 } },
    snapshot_source_count: 3, history: [],
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
    fin_day_closures: [
      fdc({ id: 'd2', close_date: '2026-05-02', status: 'reopened' }),
      fdc({ id: 'd4', close_date: '2026-05-04' }),
      fdc({ id: 'd1', close_date: '2026-05-01' }),
      fdc({ id: 'd3', close_date: '2026-05-03' }),
      fdc({ id: 'd-alt', company_id: 'co-a-alt', close_date: '2026-05-09' }),
      fdc({ id: 'd-u2', user_id: 'u2', company_id: 'co-b', close_date: '2026-05-09' }),
    ],
    writes: [],
    finds: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const U1 = { authorization: 'Bearer tok-u1' };
const ALL_DESC = ['d4', 'd3', 'd2', 'd1'];

function intErr(type: 'int_parsing' | 'int_parsing_size', input: string): Record<string, unknown> {
  return {
    detail: [{
      type,
      loc: ['query', 'limit'],
      msg: type === 'int_parsing'
        ? 'Input should be a valid integer, unable to parse string as an integer'
        : 'Unable to parse input string as an integer, exceeded maximum size',
      input,
      url: `https://errors.pydantic.dev/2.13/v/${type}`,
    }],
  };
}

describe('Gate-7m · Fin day-closures list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });
  const ids = (body: unknown): unknown[] => ((body as { rows: Record<string, unknown>[] }).rows).map((r) => r['id']);

  // ── AUTH ───────────────────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    const r = await get('/api/fin/day-closures');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/fin/day-closures', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    const r = await get('/api/fin/day-closures', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('4 auth precedes query validation · no bearer + limit=abc → 401', async () => {
    const r = await get('/api/fin/day-closures?limit=abc');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  // ── DEFAULT READ ───────────────────────────────────────────────────
  it('5 default · wrapper {rows, count} · close_date DESC · _id+user_id stripped', async () => {
    const r = await get('/api/fin/day-closures', U1);
    expect(r.statusCode).toBe(200);
    const body = r.json<{ rows: Record<string, unknown>[]; count: number }>();
    expect(Object.keys(body)).toEqual(['rows', 'count']);
    expect(ids(body)).toEqual(ALL_DESC);
    expect(body.count).toBe(4);
    for (const row of body.rows) {
      expect(row).not.toHaveProperty('user_id');
      expect(row).not.toHaveProperty('_id');
      expect(row['company_id']).toBe('co-a');
    }
  });

  it('6 exact Mongo call · filter / projection / sort / default limit 500', async () => {
    await get('/api/fin/day-closures', U1);
    expect(state.finds).toEqual([{
      filter: { user_id: 'u1', company_id: 'co-a' },
      projection: { _id: 0, user_id: 0 },
      sort: [['close_date', -1]],
      limit: 500,
    }]);
  });

  it('7 empty result → {rows: [], count: 0}', async () => {
    const r = await get('/api/fin/day-closures?status=nomatch', U1);
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ rows: [], count: 0 });
  });

  // ── DATE RANGE / STATUS ────────────────────────────────────────────
  it('8 date_from only → close_date {$gte}', async () => {
    const r = await get('/api/fin/day-closures?date_from=2026-05-03', U1);
    expect(ids(r.json())).toEqual(['d4', 'd3']);
    expect(state.finds[0]?.filter).toEqual({ user_id: 'u1', company_id: 'co-a', close_date: { $gte: '2026-05-03' } });
  });

  it('9 date_to only → close_date {$lte}', async () => {
    const r = await get('/api/fin/day-closures?date_to=2026-05-02', U1);
    expect(ids(r.json())).toEqual(['d2', 'd1']);
    expect(state.finds[0]?.filter).toEqual({ user_id: 'u1', company_id: 'co-a', close_date: { $lte: '2026-05-02' } });
  });

  it('10 both bounds inclusive', async () => {
    const r = await get('/api/fin/day-closures?date_from=2026-05-02&date_to=2026-05-03', U1);
    expect(ids(r.json())).toEqual(['d3', 'd2']);
  });

  it('11 blank date_from / date_to / status are falsy → no predicate', async () => {
    await get('/api/fin/day-closures?date_from=&date_to=&status=', U1);
    expect(state.finds[0]?.filter).toEqual({ user_id: 'u1', company_id: 'co-a' });
  });

  it('12 status exact equality · filter key order after close_date', async () => {
    const r = await get('/api/fin/day-closures?status=reopened&date_from=2026-05-01', U1);
    expect(ids(r.json())).toEqual(['d2']);
    expect(Object.keys(state.finds[0]?.filter ?? {})).toEqual(['user_id', 'company_id', 'close_date', 'status']);
  });

  it('13 repeated key → last occurrence wins', async () => {
    const r = await get('/api/fin/day-closures?status=reopened&status=closed', U1);
    expect(ids(r.json())).toEqual(['d4', 'd3', 'd1']);
  });

  // ── LIMIT CLAMP ────────────────────────────────────────────────────
  it.each([
    ['2', 2], ['0', 1], ['-5', 1], ['5000', 5000], ['5001', 5000],
    ['99999999999999999999', 5000], ['-99999999999999999999', 1],
  ])('14 limit=%s → clamped cap %i', async (raw, cap) => {
    const r = await get(`/api/fin/day-closures?limit=${encodeURIComponent(raw)}`, U1);
    expect(r.statusCode).toBe(200);
    expect(state.finds[0]?.limit).toBe(cap);
  });

  // ── LIMIT COERCION (pydantic 2.13.4 ground truth) ──────────────────
  it.each([
    ['+5', 5], [' 5 ', 5], ['\t5\n', 5], ['05', 5], ['1.0', 1], ['1.00', 1], ['0.0', 1],
    ['1_000', 1000], ['1_000.0', 1000], ['-00.00', 1], ['0_0', 1], [' 5', 5],
    ['5', 5], ['　5', 5], ['0005000', 5000], ['+1.0', 1],
  ])('15 limit=%j accepted by pydantic → cap %i', async (raw, cap) => {
    const r = await get(`/api/fin/day-closures?limit=${encodeURIComponent(raw)}`, U1);
    expect(r.statusCode).toBe(200);
    expect(state.finds[0]?.limit).toBe(cap);
  });

  it.each([
    'abc', '', ' ', '1.5', '1e3', '0x10', '1_', '_1', '1__0', '+-5', '--5', '1.', '.0',
    '1.0_0', '+_1', '5﻿', '​5', '١٢', '+ 5', '1.01', '-', '+', '_',
  ])('16 limit=%j → 422 int_parsing', async (raw) => {
    const r = await get(`/api/fin/day-closures?limit=${encodeURIComponent(raw)}`, U1);
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual(intErr('int_parsing', raw));
    expect(state.finds).toEqual([]);
  });

  it('17 int_parsing_size thresholds (jiter 4300-byte digit run incl. sign)', async () => {
    const cases: [string, number | 'int_parsing' | 'int_parsing_size'][] = [
      ['1'.repeat(4300), 5000],
      ['1'.repeat(4301), 'int_parsing_size'],
      [`-${'1'.repeat(4299)}`, 1],
      [`-${'1'.repeat(4300)}`, 'int_parsing_size'],
      [`+${'1'.repeat(4300)}`, 5000],
      [`+${'1'.repeat(4301)}`, 'int_parsing'],
      [`${'1'.repeat(4301)} `, 'int_parsing_size'],
      [`${'1'.repeat(4301)}.0`, 'int_parsing_size'],
      [`${'0'.repeat(4300)}5`, 5],
    ];
    for (const [raw, want] of cases) {
      state.finds = [];
      const r = await get(`/api/fin/day-closures?limit=${encodeURIComponent(raw)}`, U1);
      if (typeof want === 'number') {
        expect(r.statusCode).toBe(200);
        expect(state.finds[0]?.limit).toBe(want);
      } else {
        expect(r.statusCode).toBe(422);
        expect(r.json()).toEqual(intErr(want, raw));
      }
    }
  });

  // ── ISOLATION ──────────────────────────────────────────────────────
  it('18 cross-user · u2 sees only own co-b rows', async () => {
    const r = await get('/api/fin/day-closures', { authorization: 'Bearer tok-u2' });
    expect(ids(r.json())).toEqual(['d-u2']);
  });

  it('19 owned X-Company-Id co-a-alt → alt rows only', async () => {
    const r = await get('/api/fin/day-closures', { ...U1, 'x-company-id': 'co-a-alt' });
    expect(ids(r.json())).toEqual(['d-alt']);
  });

  it('20 unowned X-Company-Id co-b → fallback default co-a', async () => {
    const r = await get('/api/fin/day-closures', { ...U1, 'x-company-id': 'co-b' });
    expect(ids(r.json())).toEqual(ALL_DESC);
  });

  // ── ROUTE BOUNDARY ─────────────────────────────────────────────────
  it('21 only GET list is mounted · detail path + POST not shadowed', async () => {
    const detail = await get('/api/fin/day-closures/2026-05-01', U1);
    expect(detail.statusCode).toBe(404);
    const post = await app.inject({ method: 'POST', url: '/api/fin/day-closures', headers: U1, payload: {} });
    expect(post.statusCode).toBe(404);
  });
});
