/**
 * TRUKVIA · Phase-3 · Gate-7n · Fin day-closure detail read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/fin/day-closures/:close_date
 *
 * Fake-DB write-forbid pattern inlined (mirrors Gate 7m). Exercises the
 * CPython 3.11 C `date.fromisoformat` acceptance axis, raw-segment 404
 * literal, and the encoded-slash 404 (Starlette decoded-path routing).
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
  lookups: { filter: Record<string, unknown>; projection?: Record<string, 0 | 1> }[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  return Object.entries(f).every(([k, v]) => d[k] === v);
}

function project(d: Record<string, unknown>, projection?: Record<string, 0 | 1>): Record<string, unknown> {
  const o: Record<string, unknown> = { ...d };
  if (!projection) return o;
  const inc = Object.entries(projection).filter(([, v]) => v === 1).map(([k]) => k);
  if (inc.length > 0) return Object.fromEntries(inc.filter((k) => k in d).map((k) => [k, d[k]]));
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
    return {
      find: vi.fn(() => { throw new Error(`unexpected find on ${name}`); }),
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        if (name === 'fin_day_closures') state.lookups.push({ filter: f, projection: opts?.projection });
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
    id: 'fdc-x', user_id: 'u1', company_id: 'co-a', close_date: '2026-05-01',
    status: 'closed', closed_at: '2026-05-02T00:00:00+00:00', closed_by: 'u1',
    snapshot: { AR: { in: 1000.0, out: 250.5, net: 749.5 } }, snapshot_source_count: 3,
    history: [{ event: 'closed', at: '2026-05-02T00:00:00+00:00', by: 'u1' }],
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
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a',     user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b',     user_id: 'u2', is_default: true },
    ],
    fin_day_closures: [
      fdc({ id: 'd1', close_date: '2026-05-01' }),
      fdc({ id: 'd-compact', close_date: '20260503' }),
      fdc({ id: 'd-week', close_date: '2026-W18-5' }),
      fdc({ id: 'd-alt', company_id: 'co-a-alt', close_date: '2026-05-02' }),
      fdc({ id: 'd-u2', user_id: 'u2', company_id: 'co-b', close_date: '2026-05-01' }),
    ],
    writes: [],
    lookups: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const U1 = { authorization: 'Bearer tok-u1' };
const BAD = { detail: 'close_date must be ISO YYYY-MM-DD' };
const url = (seg: string): string => `/api/fin/day-closures/${seg}`;
const enc = (raw: string): string => url(encodeURIComponent(raw));

describe('Gate-7n · Fin day-closure detail read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });

  // ── AUTH ───────────────────────────────────────────────────────────
  it.each([
    [{}, 'Not authenticated'],
    [{ authorization: 'Bearer nope' }, 'Invalid session'],
    [{ authorization: 'Bearer tok-expired' }, 'Session expired'],
  ])('1 auth failure %j → 401 %s', async (h, detail) => {
    const r = await get(url('2026-05-01'), h as Record<string, string>);
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail });
  });

  it('2 auth precedes date validation · no bearer + bad date → 401', async () => {
    const r = await get(url('not-a-date'));
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  // ── HIT ────────────────────────────────────────────────────────────
  it('3 hit · bare doc · _id and user_id stripped · exact findOne', async () => {
    const r = await get(url('2026-05-01'), U1);
    expect(r.statusCode).toBe(200);
    const body = r.json<Record<string, unknown>>();
    expect(body['id']).toBe('d1');
    expect(body).not.toHaveProperty('user_id');
    expect(body).not.toHaveProperty('_id');
    expect(body['snapshot']).toEqual({ AR: { in: 1000, out: 250.5, net: 749.5 } });
    expect(state.lookups).toEqual([{
      filter: { user_id: 'u1', company_id: 'co-a', close_date: '2026-05-01' },
      projection: { _id: 0, user_id: 0 },
    }]);
  });

  it('4 compact and ISO-week raw segments are queried verbatim', async () => {
    expect((await get(url('20260503'), U1)).json<Record<string, unknown>>()['id']).toBe('d-compact');
    expect((await get(url('2026-W18-5'), U1)).json<Record<string, unknown>>()['id']).toBe('d-week');
  });

  // ── 404 LITERAL (raw segment) ──────────────────────────────────────
  it.each(['2026-05-31', '20260501', '2026-W18', '2026W185', '2026050112', '2026-W53'])(
    '5 valid-but-missing %s → 404 raw literal', async (seg) => {
      const r = await get(url(seg), U1);
      expect(r.statusCode).toBe(404);
      expect(r.json()).toEqual({ detail: `No closure exists for ${seg}` });
    },
  );

  // ── 400 (C date.fromisoformat rejection) ───────────────────────────
  it.each([
    'not-a-date', '2026-5-1', '2026-02-29', '2026-13-01', '2026-00-10', '2026-05-00', '2026-05-32',
    '0000-01-01', '2026-0501', '202605-01', '2026W1852', '2026-W185', '2026W18-5', '2026-W00-1',
    '2026-W01-0', '2026-W01-8', '2015-W54', '2026-W01-12', ' 026-05-01', '+026-05-01',
    '２０２６-05-01', '2026-05-0١', '2026-05-01 ', '0000-W01-1',
    '9999-W52-6', '2026-05-01T00', 'x',
  ])('6 invalid %j → 400', async (raw) => {
    const r = await get(enc(raw), U1);
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual(BAD);
    expect(state.lookups).toEqual([]);
  });

  it.each(['2024-02-29', '0001-01-01', '9999-12-31', '2020-W53', '2015-W53-7', '9999-W52-5', '2026W01'])(
    '7 accepted edge %s → reaches findOne', async (raw) => {
      const r = await get(enc(raw), U1);
      expect(r.statusCode).toBe(404);
      expect(state.lookups).toHaveLength(1);
    },
  );

  // ── ENCODED SLASH ──────────────────────────────────────────────────
  it.each([[U1], [{}]])('8 encoded slash → 404 Not Found before auth (%j)', async (h) => {
    const r = await get(url('2026%2F05%2F01'), h);
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Not Found' });
  });

  // ── ISOLATION ──────────────────────────────────────────────────────
  it('9 cross-user · u2 sees own row for same date', async () => {
    const r = await get(url('2026-05-01'), { authorization: 'Bearer tok-u2' });
    expect(r.json<Record<string, unknown>>()['id']).toBe('d-u2');
  });

  it('10 default co-a cannot see co-a-alt row → 404', async () => {
    const r = await get(url('2026-05-02'), U1);
    expect(r.statusCode).toBe(404);
  });

  it('11 owned X-Company-Id co-a-alt → alt row visible', async () => {
    const r = await get(url('2026-05-02'), { ...U1, 'x-company-id': 'co-a-alt' });
    expect(r.json<Record<string, unknown>>()['id']).toBe('d-alt');
  });

  it('12 unowned X-Company-Id co-b → fallback co-a', async () => {
    const r = await get(url('2026-05-01'), { ...U1, 'x-company-id': 'co-b' });
    expect(r.json<Record<string, unknown>>()['id']).toBe('d1');
  });

  // ── ROUTE BOUNDARY ─────────────────────────────────────────────────
  it('13 late-entries sub-route not shadowed', async () => {
    const late = await get(url('2026-05-01/late-entries'), U1);
    expect(late.statusCode).toBe(404);
    expect(late.json()).not.toEqual({ detail: 'No closure exists for 2026-05-01' });
  });
});
