/**
 * TRUKVIA · Phase-3 · Gate-7c · WalletRecharges list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/wallet-recharges
 *
 * Contract IDENTICAL LINE-FOR-LINE to Gate 7a wallet-adjustments except
 * for the collection name. Fake-DB write-forbid pattern + $ne/$gte/$lte
 * matcher inlined route-locally.
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
  wallet_recharges: Record<string, unknown>[];
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
          if (op === '$gte') {
            if (!(typeof dv === 'string' && typeof opv === 'string' && dv >= opv)) return false;
          }
          if (op === '$lte') {
            if (!(typeof dv === 'string' && typeof opv === 'string' && dv <= opv)) return false;
          }
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
    : name === 'wallet_recharges' ? state.wallet_recharges
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
        // Gate 9e: routes read Motor-style (async iteration, no server-side limit).
        async *[Symbol.asyncIterator]() { yield* await cursor.toArray(); },
        hasNext: (): Promise<boolean> => cursor.toArray().then((a) => a.length > 0),
        close: (): Promise<void> => Promise.resolve(),
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

const D1 = '2026-05-04';
const D2 = '2026-05-03';
const D3 = '2026-05-02';
const D4 = '2026-05-01';

function wr(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'wr-x', user_id: 'u1', company_id: 'co-a',
    wallet_code: 'WALLET_FUEL', funding_mode: 'Bank',
    amount: 1000.0, date: D1, reference: 'RN-1',
    created_by: 'u1', created_at: '2026-05-04T00:00:00+00:00',
    is_deleted: false,
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
    wallet_recharges: [
      wr({ id: 'r1', wallet_code: 'WALLET_FUEL',   date: D1, is_deleted: false }),
      wr({ id: 'r2', wallet_code: 'WALLET_FASTAG', date: D2, is_deleted: false }),
      wr({ id: 'r3', wallet_code: 'WALLET_FUEL',   date: D3 }),                       // is_deleted MISSING
      wr({ id: 'r4', wallet_code: 'WALLET_FUEL',   date: D4, is_deleted: null }),     // null
      wr({ id: 'r-del', wallet_code: 'WALLET_FUEL', date: D1, is_deleted: true }),
      wr({ id: 'r-alt', wallet_code: 'WALLET_FUEL', company_id: 'co-a-alt', date: D1 }),
      wr({ id: 'r-u2',  wallet_code: 'WALLET_FUEL', user_id: 'u2', company_id: 'co-b', date: D1 }),
    ],
    writes: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof makeApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const CO_A_ACTIVE_IDS = ['r1', 'r2', 'r3', 'r4'];

describe('Gate-7c · WalletRecharges list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 default include_deleted=false · four active rows DESC', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('2 omitted include_deleted === false · deleted excluded', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('r-del');
  });

  it('3 include_deleted=true · deleted included', async () => {
    const r = await get('/api/wallet-recharges?include_deleted=true', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('r-del');
  });

  it('4 include_deleted=false · deleted excluded', async () => {
    const r = await get('/api/wallet-recharges?include_deleted=false', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('5 True token variants', async () => {
    for (const t of ['true', 'True', 'TRUE', '1', 'yes', 'Yes', 'YES', 'on', 'On', 'ON']) {
      const r = await get(`/api/wallet-recharges?include_deleted=${t}`, { authorization: 'Bearer tok-u1' });
      expect(r.statusCode).toBe(200);
      expect((r.json() as Record<string, unknown>[]).map((x) => x['id'])).toContain('r-del');
    }
  });

  it('6 False token variants', async () => {
    for (const t of ['false', 'False', 'FALSE', '0', 'no', 'No', 'NO', 'off', 'Off', 'OFF']) {
      const r = await get(`/api/wallet-recharges?include_deleted=${t}`, { authorization: 'Bearer tok-u1' });
      expect(r.statusCode).toBe(200);
      expect((r.json() as Record<string, unknown>[]).map((x) => x['id'])).not.toContain('r-del');
    }
  });

  it('7 invalid include_deleted="" → 422 Pydantic envelope', async () => {
    const r = await get('/api/wallet-recharges?include_deleted=', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({
      detail: [{
        type: 'bool_parsing',
        loc: ['query', 'include_deleted'],
        msg: 'Input should be a valid boolean, unable to interpret input',
        input: '',
        url: 'https://errors.pydantic.dev/2.13/v/bool_parsing',
      }],
    });
  });

  it('8 invalid include_deleted=FOO → 422 Pydantic envelope', async () => {
    const r = await get('/api/wallet-recharges?include_deleted=FOO', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({
      detail: [{
        type: 'bool_parsing',
        loc: ['query', 'include_deleted'],
        msg: 'Input should be a valid boolean, unable to interpret input',
        input: 'FOO',
        url: 'https://errors.pydantic.dev/2.13/v/bool_parsing',
      }],
    });
  });

  it('9a no auth → 401 Not authenticated', async () => {
    const r = await get('/api/wallet-recharges');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('9b invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('9c expired session → 401 Session expired', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('10 auth precedence · no bearer + invalid include_deleted → 401', async () => {
    const r = await get('/api/wallet-recharges?include_deleted=FOO');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('11 wallet_code omitted → all wallet codes', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1' });
    const codes = new Set((r.json() as Record<string, unknown>[]).map((x) => x['wallet_code']));
    expect(codes.has('WALLET_FUEL')).toBe(true);
    expect(codes.has('WALLET_FASTAG')).toBe(true);
  });

  it('12 wallet_code="" blank → omitted', async () => {
    const r = await get('/api/wallet-recharges?wallet_code=', { authorization: 'Bearer tok-u1' });
    const codes = new Set((r.json() as Record<string, unknown>[]).map((x) => x['wallet_code']));
    expect(codes.has('WALLET_FUEL')).toBe(true);
    expect(codes.has('WALLET_FASTAG')).toBe(true);
  });

  it('13 wallet_code=WALLET_FUEL exact filter', async () => {
    const r = await get('/api/wallet-recharges?wallet_code=WALLET_FUEL', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['r1', 'r3', 'r4']); // DESC by date, FASTAG r2 excluded
  });

  it('14 date_from only · rows >= 2026-05-03', async () => {
    const r = await get('/api/wallet-recharges?date_from=2026-05-03', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['r1', 'r2']);
  });

  it('15 date_to only · rows <= 2026-05-02', async () => {
    const r = await get('/api/wallet-recharges?date_to=2026-05-02', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['r3', 'r4']);
  });

  it('16 both bounds · inclusive range', async () => {
    const r = await get('/api/wallet-recharges?date_from=2026-05-02&date_to=2026-05-03', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['r2', 'r3']);
  });

  it('17 blank date bounds omitted', async () => {
    const r = await get('/api/wallet-recharges?date_from=&date_to=', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('18 projection strips _id and user_id', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1' });
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('19 date DESC · r1 > r2 > r3 > r4', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1' });
    const dates = (r.json() as Record<string, unknown>[]).map((x) => x['date']);
    expect(dates).toEqual([D1, D2, D3, D4]);
  });

  it('20 5000 cap · exactly 5000 returned when >5000 rows exist', async () => {
    state.wallet_recharges.length = 0;
    for (let i = 0; i < 5001; i++) {
      state.wallet_recharges.push(wr({
        id: 'z' + String(i).padStart(5, '0'),
        date: `2026-06-${String((i % 28) + 1).padStart(2, '0')}`,
        is_deleted: false,
      }));
    }
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1' });
    expect((r.json() as unknown[]).length).toBe(5000);
  });

  it('21 empty result · date_from far future → 200 []', async () => {
    const r = await get('/api/wallet-recharges?date_from=2099-01-01', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('22 cross-user/company isolation · u2 sees own only', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u2' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['r-u2']);
  });

  it('23 owned X-Company-Id override · co-a-alt → r-alt only', async () => {
    const r = await get('/api/wallet-recharges', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['r-alt']);
  });

  it('24 unowned X-Company-Id → fallback default co-a', async () => {
    const r = await get('/api/wallet-recharges', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-b',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('25 no X-Company-Id · default company', async () => {
    const r = await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
  });

  it('26 no 404 branch · unknown wallet_code → 200 []', async () => {
    const r = await get('/api/wallet-recharges?wallet_code=NON_EXISTENT', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('27 zero Node writes across every exercised branch', async () => {
    await get('/api/wallet-recharges');
    await get('/api/wallet-recharges', { authorization: 'Bearer nope' });
    await get('/api/wallet-recharges', { authorization: 'Bearer tok-expired' });
    await get('/api/wallet-recharges?include_deleted=FOO', { authorization: 'Bearer tok-u1' });
    await get('/api/wallet-recharges?include_deleted=true', { authorization: 'Bearer tok-u1' });
    await get('/api/wallet-recharges?wallet_code=WALLET_FUEL', { authorization: 'Bearer tok-u1' });
    await get('/api/wallet-recharges?date_from=2026-05-02&date_to=2026-05-03', { authorization: 'Bearer tok-u1' });
    await get('/api/wallet-recharges', { authorization: 'Bearer tok-u2' });
    await get('/api/wallet-recharges', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    expect(state.writes).toEqual([]);
  });
});
