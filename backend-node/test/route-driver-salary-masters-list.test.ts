/**
 * TRUKVIA · Phase-3 · Gate-7p · Driver salary-masters list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/drivers/:did/salary-masters
 *
 * Fake-DB write-forbid pattern inlined (mirrors Gate 6y / 7n). Exercises the
 * driver pre-check 404, `{_id:0}`-only projection (user_id preserved), the
 * two-key DESC sort, the 500 cap and the encoded-slash 404.
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

type Row = Record<string, unknown>;
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; drivers: Row[]; driver_salary_masters: Row[];
  writes: string[];
  calls: { coll: string; kind: string; filter: Row; projection?: Record<string, 0 | 1>; sort?: unknown; limit?: number }[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

const matches = (d: Row, f: Row): boolean => Object.entries(f).every(([k, v]) => d[k] === v);

function project(d: Row, projection?: Record<string, 0 | 1>): Row {
  const o: Row = { ...d };
  if (!projection) return o;
  for (const [k, v] of Object.entries(projection)) if (v === 0) delete o[k];
  return o;
}

// Mongo ordering for the value kinds used here: missing/null < numbers < strings.
function rank(v: unknown): number {
  if (v === undefined || v === null) return 0;
  if (typeof v === 'number') return 1;
  return 2;
}
function cmp(a: unknown, b: unknown): number {
  const ra = rank(a); const rb = rank(b);
  if (ra !== rb) return ra - rb;
  if (ra === 0) return 0;
  return (a as string | number) < (b as string | number) ? -1 : (a === b ? 0 : 1);
}

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Row[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'drivers' ? state.drivers
    : name === 'driver_salary_masters' ? state.driver_salary_masters
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    const track = name === 'drivers' || name === 'driver_salary_masters';
    return {
      find: vi.fn((f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        const rec: State['calls'][number] = { coll: name, kind: 'find', filter: f, projection: opts?.projection };
        if (track) state.calls.push(rec);
        let hits = rows.filter((r) => matches(r, f));
        const cursor = {
          sort(spec: [string, 1 | -1][]) {
            rec.sort = spec;
            hits = hits.slice().sort((a, b) => {
              for (const [k, dir] of spec) {
                const c = cmp(a[k], b[k]);
                if (c !== 0) return c * dir;
              }
              return 0;
            });
            return cursor;
          },
          // Gate 9e: routes read Motor-style (async iteration, no server-side limit).
          async *[Symbol.asyncIterator]() { yield* await cursor.toArray(); },
          hasNext: (): Promise<boolean> => cursor.toArray().then((a) => a.length > 0),
          close: (): Promise<void> => Promise.resolve(),
          limit(n: number) { rec.limit = n; hits = hits.slice(0, n); return cursor; },
          async toArray(): Promise<Row[]> { return hits.map((h) => project(h, opts?.projection)); },
        };
        return cursor;
      }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        if (track) state.calls.push({ coll: name, kind: 'findOne', filter: f, projection: opts?.projection });
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
      countDocuments: vi.fn(forbid(state, `${name}.countDocuments`)),
      findOneAndUpdate: vi.fn(forbid(state, `${name}.findOneAndUpdate`)),
      findOneAndDelete: vi.fn(forbid(state, `${name}.findOneAndDelete`)),
      findOneAndReplace: vi.fn(forbid(state, `${name}.findOneAndReplace`)),
      bulkWrite: vi.fn(forbid(state, `${name}.bulkWrite`)),
      createIndex: vi.fn(async () => 'ok'),
    };
  };
  return { collection: vi.fn(collection) } as unknown as Db;
}

function dsm(id: string, effective_from: string | undefined, version: number, o: Row = {}): Row {
  const d: Row = {
    id, user_id: 'u1', company_id: 'co-a', driver_id: 'd1', version,
    monthly_salary: 15000.0, effective_to: null, remarks: null,
    created_at: '2026-01-01T00:00:00+00:00', created_by: 'u1', ...o,
  };
  if (effective_from !== undefined) d['effective_from'] = effective_from;
  return d;
}

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-u1',      user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
    ],
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a',     user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b',     user_id: 'u2', is_default: true },
    ],
    drivers: [
      { id: 'd1', user_id: 'u1', company_id: 'co-a', name: 'Ravi' },
      { id: 'd-empty', user_id: 'u1', company_id: 'co-a', name: 'No Masters' },
      { id: 'd-alt', user_id: 'u1', company_id: 'co-a-alt', name: 'Alt' },
      { id: 'd-u2', user_id: 'u2', company_id: 'co-b', name: 'U2' },
    ],
    driver_salary_masters: [
      dsm('m1', '2026-01-01', 1),
      dsm('m3', '2026-04-01', 3),
      dsm('m2', '2026-04-01', 2),          // tie on effective_from → version DESC
      dsm('m-nofrom', undefined, 9),       // missing effective_from → last
      dsm('m-alt', '2026-02-01', 1, { company_id: 'co-a-alt', driver_id: 'd-alt' }),
      dsm('m-u2', '2026-02-01', 1, { user_id: 'u2', company_id: 'co-b', driver_id: 'd-u2' }),
      dsm('m-orphan', '2026-02-01', 1, { driver_id: 'd-gone' }),
    ],
    writes: [],
    calls: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const U1 = { authorization: 'Bearer tok-u1' };
const url = (did: string): string => `/api/drivers/${did}/salary-masters`;
const ids = (b: unknown): unknown[] => (b as { items: Row[] }).items.map((r) => r['id']);

describe('Gate-7p · Driver salary-masters list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });

  it.each([
    [{}, 'Not authenticated'],
    [{ authorization: 'Bearer nope' }, 'Invalid session'],
    [{ authorization: 'Bearer tok-expired' }, 'Session expired'],
  ])('1 auth failure %j → 401 %s', async (h, detail) => {
    const r = await get(url('d1'), h as Record<string, string>);
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail });
    expect(state.calls).toEqual([]);
  });

  it('2 wrapper {items} · effective_from DESC then version DESC · missing last', async () => {
    const r = await get(url('d1'), U1);
    expect(r.statusCode).toBe(200);
    expect(Object.keys(r.json<Row>())).toEqual(['items']);
    expect(ids(r.json())).toEqual(['m3', 'm2', 'm1', 'm-nofrom']);
  });

  it('3 user_id PRESERVED in items · _id stripped', async () => {
    const r = await get(url('d1'), U1);
    for (const it of r.json<{ items: Row[] }>().items) {
      expect(it['user_id']).toBe('u1');
      expect(it).not.toHaveProperty('_id');
    }
  });

  it('4 exact reads · driver pre-check then list', async () => {
    await get(url('d1'), U1);
    expect(state.calls).toEqual([
      { coll: 'drivers', kind: 'findOne',
        filter: { id: 'd1', user_id: 'u1', company_id: 'co-a' }, projection: { _id: 0, user_id: 0 } },
      { coll: 'driver_salary_masters', kind: 'find',
        filter: { user_id: 'u1', company_id: 'co-a', driver_id: 'd1' }, projection: { _id: 0 },
        // Gate 9e: Motor `to_list(500)` sends NO server-side limit (reads stop at 500).
        sort: [['effective_from', -1], ['version', -1]] },
    ]);
  });

  it('5 driver with no masters → {items: []}', async () => {
    const r = await get(url('d-empty'), U1);
    expect(r.json()).toEqual({ items: [] });
  });

  it.each([
    ['unknown driver', 'd-gone', U1],
    ['cross-user driver', 'd-u2', U1],
    ['other-company driver under default', 'd-alt', U1],
  ])('6 %s → 404 Driver not found · no list read', async (_n, did, h) => {
    const r = await get(url(did), h);
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Driver not found' });
    expect(state.calls.map((c) => c.coll)).toEqual(['drivers']);
  });

  it('7 owned X-Company-Id co-a-alt → alt driver masters', async () => {
    const r = await get(url('d-alt'), { ...U1, 'x-company-id': 'co-a-alt' });
    expect(ids(r.json())).toEqual(['m-alt']);
  });

  it('8 unowned X-Company-Id co-b → fallback co-a', async () => {
    const r = await get(url('d1'), { ...U1, 'x-company-id': 'co-b' });
    expect(ids(r.json())).toEqual(['m3', 'm2', 'm1', 'm-nofrom']);
  });

  it('9 cross-user u2 own driver', async () => {
    const r = await get(url('d-u2'), { authorization: 'Bearer tok-u2' });
    expect(ids(r.json())).toEqual(['m-u2']);
  });

  it('10 cap 500 of 502 masters', async () => {
    state.driver_salary_masters = Array.from({ length: 502 }, (_, i) =>
      dsm(`b${String(i).padStart(3, '0')}`, `2020-01-${String((i % 28) + 1).padStart(2, '0')}`, i));
    const r = await get(url('d1'), U1);
    expect(r.json<{ items: Row[] }>().items).toHaveLength(500);
  });

  it.each([
    ['/api/drivers/d1%2Fx/salary-masters', U1], ['/api/drivers/d1%2Fx/salary-masters', {}],
    ['/api/drivers//salary-masters', U1], ['/api/drivers//salary-masters', {}],
  ])('11 encoded slash / empty did %s → 404 Not Found before auth (%j)', async (path, h) => {
    const r = await get(path, h);
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Not Found' });
    expect(state.calls).toEqual([]);
  });
});
