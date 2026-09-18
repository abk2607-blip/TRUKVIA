/**
 * TRUKVIA · Phase-3 · Gate-7o · Fin day-status read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/fin/day-status
 *
 * Fake-DB write-forbid pattern inlined (mirrors Gate 7n). Exercises the
 * required-`date` 422, the two 400 literals, Python truthiness on the
 * projected closure / fin_txn probe, and missing-vs-null response fields.
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
  sessions: Row[]; users: Row[]; companies: Row[];
  fin_day_closures: Row[]; fin_txn: Row[];
  writes: string[];
  lookups: { coll: string; filter: Row; projection?: Record<string, 0 | 1> }[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function isOps(v: unknown): v is Row {
  return typeof v === 'object' && v !== null && !Array.isArray(v) && Object.keys(v).every((k) => k.startsWith('$'));
}

function matches(d: Row, f: Row): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isOps(v)) {
      for (const [op, ov] of Object.entries(v)) {
        if (typeof dv !== 'string' || typeof ov !== 'string') return false;
        if (op === '$lte' && !(dv <= ov)) return false;
        if (op === '$gt' && !(dv > ov)) return false;
      }
      continue;
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(d: Row, projection?: Record<string, 0 | 1>): Row {
  if (!projection) return { ...d };
  const inc = Object.entries(projection).filter(([, v]) => v === 1).map(([k]) => k);
  if (inc.length > 0) return Object.fromEntries(inc.filter((k) => k in d).map((k) => [k, d[k]]));
  const o: Row = { ...d };
  for (const [k, v] of Object.entries(projection)) if (v === 0) delete o[k];
  return o;
}

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Row[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'fin_day_closures' ? state.fin_day_closures
    : name === 'fin_txn' ? state.fin_txn
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      find: vi.fn(() => { throw new Error(`unexpected find on ${name}`); }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        if (name === 'fin_day_closures' || name === 'fin_txn') {
          state.lookups.push({ coll: name, filter: f, projection: opts?.projection });
        }
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

const CLOSED_AT = '2026-05-10T18:00:00+00:00';

function fdc(close_date: string, overrides: Row = {}): Row {
  return {
    id: `fdc-${close_date}`, user_id: 'u1', company_id: 'co-a', close_date,
    status: 'closed', closed_at: CLOSED_AT, closed_by: 'u1',
    reopened_at: '', reopened_by: '', snapshot: {},
    ...overrides,
  };
}

function txn(id: string | undefined, overrides: Row = {}): Row {
  const t: Row = {
    user_id: 'u1', company_id: 'co-a', status: 'active',
    txn_date: '2026-05-01', created_at: '2026-05-11T00:00:00+00:00', ...overrides,
  };
  if (id !== undefined) t['id'] = id;
  return t;
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
      fdc('2026-05-01'),                                                   // closed, late txn exists
      fdc('2026-04-01'),                                                   // closed, no late txn
      fdc('2026-05-02', { status: 'reopened', reopened_at: '2026-05-11T09:00:00+00:00', reopened_by: 'u1' }),
      fdc('2026-05-03', { closed_at: '' }),                                // closed, falsy closed_at
      { id: 'bare', user_id: 'u1', company_id: 'co-a', close_date: '2026-05-04' }, // projects to {}
      { id: 'partial', user_id: 'u1', company_id: 'co-a', close_date: '2026-05-05',
        status: 'closed', closed_at: CLOSED_AT, closed_by: null },          // missing reopened_*; null closed_by
      fdc('2026-05-06'),                                                   // late txn lacks `id`
      fdc('2026-05-07', { company_id: 'co-a-alt' }),
      fdc('2026-05-01', { id: 'u2-row', user_id: 'u2', company_id: 'co-b', status: 'reopened' }),
    ],
    fin_txn: [
      txn('tx-late', { txn_date: '2026-04-30' }),                          // late for 2026-05-01
      txn('tx-early', { txn_date: '2026-03-01', created_at: '2026-05-01T00:00:00+00:00' }),
      txn(undefined, { txn_date: '2026-05-06', created_at: '2026-05-12T00:00:00+00:00', company_id: 'co-z' }),
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
const P = '/api/fin/day-status';
const q = (date: string): string => `${P}?date=${encodeURIComponent(date)}`;

describe('Gate-7o · Fin day-status read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });

  // ── AUTH / VALIDATION ORDER ────────────────────────────────────────
  it.each([
    [{}, 'Not authenticated'],
    [{ authorization: 'Bearer nope' }, 'Invalid session'],
    [{ authorization: 'Bearer tok-expired' }, 'Session expired'],
  ])('1 auth failure %j → 401 %s', async (h, detail) => {
    const r = await get(q('2026-05-01'), h as Record<string, string>);
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail });
  });

  it.each([P, `${P}?date=`, q('bad')])('2 auth precedes validation · %s without bearer → 401', async (u) => {
    const r = await get(u);
    expect(r.statusCode).toBe(401);
  });

  it('3 missing date → 422 Pydantic `missing` envelope', async () => {
    const r = await get(P, U1);
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({ detail: [{
      type: 'missing', loc: ['query', 'date'], msg: 'Field required', input: null,
      url: 'https://errors.pydantic.dev/2.13/v/missing',
    }] });
  });

  it.each([`${P}?date=`, `${P}?date`])('4 blank date %s → 400 required literal', async (u) => {
    const r = await get(u, U1);
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'date is required (YYYY-MM-DD)' });
  });

  it.each(['bad', '2026-5-1', '2026-02-29', '0000-01-01', ' ', '2026-05-01T00'])(
    '5 invalid %j → 400 ISO literal · no reads', async (d) => {
      const r = await get(q(d), U1);
      expect(r.statusCode).toBe(400);
      expect(r.json()).toEqual({ detail: 'date must be ISO YYYY-MM-DD' });
      expect(state.lookups).toEqual([]);
    },
  );

  // ── RESPONSE SHAPES ────────────────────────────────────────────────
  it('6 no closure → {date, is_closed:false} only', async () => {
    const r = await get(q('2026-06-01'), U1);
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ date: '2026-06-01', is_closed: false });
  });

  it('7 closed + late txn → full shape, key order, has_late_entries true', async () => {
    const r = await get(q('2026-05-01'), U1);
    const body = r.json<Row>();
    expect(Object.keys(body)).toEqual([
      'date', 'is_closed', 'status', 'closed_at', 'closed_by', 'reopened_at', 'reopened_by', 'has_late_entries',
    ]);
    expect(body).toEqual({
      date: '2026-05-01', is_closed: true, status: 'closed', closed_at: CLOSED_AT, closed_by: 'u1',
      reopened_at: '', reopened_by: '', has_late_entries: true,
    });
  });

  it('8 exact reads · closure inclusion projection · fin_txn late probe', async () => {
    await get(q('2026-05-01'), U1);
    expect(state.lookups).toEqual([
      { coll: 'fin_day_closures',
        filter: { user_id: 'u1', company_id: 'co-a', close_date: '2026-05-01' },
        projection: { _id: 0, status: 1, closed_at: 1, closed_by: 1, reopened_at: 1, reopened_by: 1 } },
      { coll: 'fin_txn',
        filter: { user_id: 'u1', company_id: 'co-a', status: 'active',
                  txn_date: { $lte: '2026-05-01' }, created_at: { $gt: CLOSED_AT } },
        projection: { _id: 0, id: 1 } },
    ]);
  });

  it('9 closed without late txn → has_late_entries false', async () => {
    const r = await get(q('2026-04-01'), U1);
    expect(r.json<Row>()['has_late_entries']).toBe(false);
  });

  it('10 reopened → is_closed false · no fin_txn probe', async () => {
    const r = await get(q('2026-05-02'), U1);
    expect(r.json<Row>()).toMatchObject({ is_closed: false, status: 'reopened', has_late_entries: false });
    expect(state.lookups.map((l) => l.coll)).toEqual(['fin_day_closures']);
  });

  it('11 closed with falsy closed_at → no fin_txn probe', async () => {
    const r = await get(q('2026-05-03'), U1);
    expect(r.json<Row>()).toMatchObject({ is_closed: true, closed_at: '', has_late_entries: false });
    expect(state.lookups.map((l) => l.coll)).toEqual(['fin_day_closures']);
  });

  it('12 closure projecting to {} → treated as not found (Python `if not doc`)', async () => {
    const r = await get(q('2026-05-04'), U1);
    expect(r.json()).toEqual({ date: '2026-05-04', is_closed: false });
  });

  it('13 missing reopened_* → "" · present null closed_by stays null', async () => {
    const r = await get(q('2026-05-05'), U1);
    expect(r.json<Row>()).toMatchObject({ closed_by: null, reopened_at: '', reopened_by: '' });
  });

  it('14 late txn projecting to {} (no id) → has_late_entries false', async () => {
    state.fin_txn = [{ ...(state.fin_txn[2] as Row), company_id: 'co-a' }];
    const r = await get(q('2026-05-06'), U1);
    expect(r.json<Row>()['has_late_entries']).toBe(false);
    expect(state.lookups.map((l) => l.coll)).toEqual(['fin_day_closures', 'fin_txn']);
  });

  // ── ISOLATION / QUERY ──────────────────────────────────────────────
  it('15 cross-user u2 sees own reopened row', async () => {
    const r = await get(q('2026-05-01'), { authorization: 'Bearer tok-u2' });
    expect(r.json<Row>()).toMatchObject({ is_closed: false, status: 'reopened' });
  });

  it('16 default hides alt · owned header shows · unowned falls back', async () => {
    expect((await get(q('2026-05-07'), U1)).json()).toEqual({ date: '2026-05-07', is_closed: false });
    expect((await get(q('2026-05-07'), { ...U1, 'x-company-id': 'co-a-alt' })).json<Row>()['is_closed']).toBe(true);
    expect((await get(q('2026-05-07'), { ...U1, 'x-company-id': 'co-b' })).json<Row>()['is_closed']).toBe(false);
  });

  it('17 repeated date → last occurrence wins', async () => {
    const r = await get(`${P}?date=bad&date=2026-05-01`, U1);
    expect(r.json<Row>()['is_closed']).toBe(true);
  });
});
