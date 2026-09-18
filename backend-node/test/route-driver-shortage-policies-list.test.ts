/**
 * TRUKVIA · Phase-3 · Gate-8d · Driver shortage-policy list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/driver-shortage-policies?q=&active_only=&limit=&offset=
 *
 * Fake-DB write-forbid pattern inlined. Records the exact countDocuments
 * filter and the find cursor shape (filter / projection / sort / skip /
 * limit), plus the raw Int64-skip find command used for skip > int32.
 * Mongo regex / tie semantics are proven live by the parity harness.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { BSONRegExp, Double, Long, ObjectId, type Db } from 'mongodb';
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

type Row = Record<string, unknown>;
interface FindCall { filter: Row; projection?: Row; sort?: Row; skip?: number; limit?: number }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; policies: Row[];
  writes: string[]; counts: Row[]; finds: FindCall[]; commands: Row[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function fieldMatches(v: unknown, c: unknown): boolean {
  if (c instanceof BSONRegExp) return typeof v === 'string' && new RegExp(c.pattern, 'i').test(v);
  return v === c;
}
function match(r: Row, f: Row): boolean {
  return Object.entries(f).every(([k, v]) => (k === '$or' ? (v as Row[]).some((s) => match(r, s)) : fieldMatches(r[k], v)));
}
const byDesc = (a: Row, b: Row): number =>
  String(b['effective_from']).localeCompare(String(a['effective_from'])) || Number(b['version']) - Number(a['version']);

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Row[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'driver_shortage_policies' ? state.policies
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      findOne: vi.fn(async (f: Row) => rows.find((r) => Object.entries(f).every(([k, v]) => r[k] === v)) ?? null),
      countDocuments: vi.fn(async (f: Row) => { state.counts.push(f); return rows.filter((r) => match(r, f)).length; }),
      find: vi.fn((f: Row, opts?: { projection?: Row }) => {
        const call: FindCall = { filter: f, projection: opts?.projection };
        state.finds.push(call);
        const cursor = {
          sort: (s: Row) => { call.sort = s; return cursor; },
          skip: (n: number) => { call.skip = n; return cursor; },
          limit: (n: number) => { call.limit = n; return cursor; },
          toArray: async () => rows.filter((r) => match(r, f)).sort(byDesc)
            .slice(call.skip ?? 0, (call.skip ?? 0) + (call.limit ?? rows.length))
            .map((r) => { const o = { ...r }; delete o['_id']; return o; }),
        };
        return cursor;
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
  const command = vi.fn(async (cmd: Row) => {
    state.commands.push(cmd);
    return { cursor: { id: Long.fromNumber(0), firstBatch: [] }, ok: 1 };
  });
  return { collection: vi.fn(collection), command } as unknown as Db;
}

const pol = (id: string, name: string, eff = '2026-01-01', version = 1, extra: Row = {}, uid = 'u1', cid = 'co-a'): Row => ({
  _id: `oid-${id}`, id, user_id: uid, company_id: cid, name, effective_from: eff, active: true, version, ...extra,
});

function makeState(): State {
  const policies: Row[] = [
    pol('b1', 'Bitumen Standard', '2026-02-01'), pol('b2', 'bitumen PREMIUM', '2026-02-02'),
    pol('meta', 'a.b*c+d?', '2026-02-03'), pol('rm', 'remarks hit', '2026-02-04', 1, { remarks: 'has BITUMEN' }),
    pol('inact', 'Bitumen inactive', '2026-02-05', 1, { active: false }),
    pol('ser', 'serialization', '2026-02-06', 1, { shortage_limit_kg: new Double(100), z: new Double(-0), nil: null }),
    pol('u2', 'Bitumen u2', '2026-09-09', 1, {}, 'u2', 'co-a'),
    pol('cob', 'Bitumen co-b', '2026-02-01', 1, {}, 'u1', 'co-b'),
    pol('nan', 'nan', '2026-02-01', 1, { shortage_limit_kg: new Double(NaN) }, 'u1', 'co-nan'),
    pol('oid', 'oid', '2026-02-01', 1, { ref: new ObjectId('65a000000000000000000001') }, 'u1', 'co-oid'),
  ];
  for (let i = 0; i < 60; i++) policies.push(pol(`t${String(i).padStart(2, '0')}`, `tie ${i}`, '2026-01-15', 7));
  return {
    sessions: ['u1', 'u2'].map((u) => ({ session_token: `tok-${u}`, user_id: u, effective_role: 'owner', expires_at: IN_FUTURE() })),
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      ...['co-b', 'co-nan', 'co-oid', 'co-empty'].map((id) => ({ id, user_id: 'u1', is_default: false })),
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    policies, writes: [], counts: [], finds: [], commands: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const P = '/api/driver-shortage-policies';
const as = (u: string, cid?: string): Record<string, string> =>
  cid === undefined ? { authorization: `Bearer tok-${u}` } : { authorization: `Bearer tok-${u}`, 'x-company-id': cid };
const err = (loc: string, type: string, msg: string, input: string): Row =>
  ({ type, loc: ['query', loc], msg, input, url: `https://errors.pydantic.dev/2.13/v/${type}` });
const INT_MSG = 'Input should be a valid integer, unable to parse string as an integer';
const BOOL_MSG = 'Input should be a valid boolean, unable to interpret input';

describe('Gate-8d · Driver shortage-policy list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (qs = '', headers: Record<string, string> = as('u1')): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: `${P}${qs}`, headers });
  const body = async (qs = '', headers?: Record<string, string>): Promise<{ items: Row[]; total: number; limit: number; offset: number }> =>
    JSON.parse((await get(qs, headers)).payload);

  it('defaults: count then find — exact filter, projection {_id:0}, sort, limit 50, no skip; wrapper', async () => {
    const r = await get();
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    const b = JSON.parse(r.payload) as { items: Row[]; total: number; limit: number; offset: number };
    expect([b.total, b.limit, b.offset, b.items.length]).toEqual([66, 50, 0, 50]);
    expect(Object.keys(b)).toEqual(['items', 'total', 'limit', 'offset']);
    expect(state.counts).toEqual([{ user_id: 'u1', company_id: 'co-a' }]);
    expect(state.finds).toEqual([{
      filter: { user_id: 'u1', company_id: 'co-a' }, projection: { _id: 0 },
      sort: { effective_from: -1, version: -1 }, limit: 50,
    }]);
  });

  it('empty company → {"items":[],"total":0,"limit":50,"offset":0}', async () => {
    expect((await get('', as('u1', 'co-empty'))).payload).toBe('{"items":[],"total":0,"limit":50,"offset":0}');
  });

  it('limit clamp: 0 → 50, -5 → 1, 501 → 500, 1.0 → 1, 1_0 → 10; offset: -3 → 0, 0 → no skip', async () => {
    for (const [qs, l] of [['?limit=0', 50], ['?limit=-5', 1], ['?limit=501', 500], ['?limit=1.0', 1], ['?limit=1_0', 10],
      ['?limit=%201%20', 1], ['?limit=%2B1', 1], ['?limit=99999999999999999999999', 500]] as const) {
      expect((await body(qs)).limit, qs).toBe(l);
    }
    expect((await body('?offset=-3')).offset).toBe(0);
    expect(state.finds.at(-1)?.skip).toBeUndefined();
    await get('?offset=25&limit=10');
    expect(state.finds.at(-1)).toMatchObject({ skip: 25, limit: 10 });
  });

  it('offset > int32 → raw find with exact Int64 skip; > int64 → 500 after the count only', async () => {
    const r = await get('?offset=9007199254740993');
    expect(r.payload).toBe('{"items":[],"total":66,"limit":50,"offset":9007199254740993}');
    const cmd = state.commands[0] as Row;
    expect(cmd['find']).toBe('driver_shortage_policies');
    expect((cmd['skip'] as Long).toString()).toBe('9007199254740993');
    expect(cmd['limit']).toBe(50);
    state.counts = []; state.finds = [];
    const big = await get('?offset=9223372036854775808');
    expect(big.statusCode).toBe(500);
    expect(big.payload).toBe('Internal Server Error');
    expect(state.counts).toHaveLength(1);
    expect(state.finds).toEqual([]);
  });

  it('422 envelope: errors in declaration order (active_only, limit, offset) regardless of query order', async () => {
    for (const qs of ['?active_only=x&limit=y&offset=z', '?offset=z&limit=y&active_only=x']) {
      const r = await get(qs);
      expect(r.statusCode).toBe(422);
      expect(JSON.parse(r.payload)).toEqual({ detail: [
        err('active_only', 'bool_parsing', BOOL_MSG, 'x'), err('limit', 'int_parsing', INT_MSG, 'y'),
        err('offset', 'int_parsing', INT_MSG, 'z'),
      ] });
    }
    expect(state.finds).toEqual([]);
  });

  it('integer rejects: "", 1.5, 1e3, fullwidth / Arabic-Indic digits, 1__0, 0x10; >4300 digits → int_parsing_size', async () => {
    for (const v of ['', '1.5', '1e3', '%EF%BC%91', '%D9%A3', '1__0', '0x10', 'abc']) {
      const r = await get(`?limit=${v}`);
      expect(r.statusCode, v).toBe(422);
      expect((JSON.parse(r.payload) as { detail: Row[] }).detail[0]?.['type']).toBe('int_parsing');
    }
    const r = await get(`?limit=${'1'.repeat(4301)}`);
    expect((JSON.parse(r.payload) as { detail: Row[] }).detail[0]?.['type']).toBe('int_parsing_size');
  });

  it('bool: case-insensitive 1/0/true/false/t/f/yes/no/y/n/on/off; no trimming; others → bool_parsing', async () => {
    for (const v of ['true', 'TRUE', 'tRuE', '1', 'yes', 'on', 't', 'y']) {
      await get(`?active_only=${v}`);
      expect(state.counts.at(-1), v).toEqual({ user_id: 'u1', company_id: 'co-a', active: true });
    }
    for (const v of ['false', 'FALSE', '0', 'no', 'off', 'f', 'n']) {
      await get(`?active_only=${v}`);
      expect(state.counts.at(-1), v).toEqual({ user_id: 'u1', company_id: 'co-a' });
    }
    for (const v of ['', '%20true', '2', '1.0', 'none', 'truee']) expect((await get(`?active_only=${v}`)).statusCode, v).toBe(422);
    await get('?active_only=true&active_only=false');
    expect(state.counts.at(-1)).toEqual({ user_id: 'u1', company_id: 'co-a' });
  });

  it('search: CPython re.escape(q.strip()) as BSON regex options "iu" over name / remarks / product_category', async () => {
    await get('?q=%20a.b*c%2Bd%3F%20');
    const f = state.counts.at(-1) as Row;
    const or = f['$or'] as Row[];
    expect(or.map((o) => Object.keys(o)[0])).toEqual(['name', 'remarks', 'product_category']);
    const pat = or[0]?.['name'] as BSONRegExp;
    expect(pat).toBeInstanceOf(BSONRegExp);
    expect(pat.pattern).toBe('a\\.b\\*c\\+d\\?');
    expect(pat.options).toBe('iu');
    await get('?q=%28%29%5B%5D%7B%7D%5C%5E%24%7C-%26~%23+x');
    expect(((state.counts.at(-1) as Row)['$or'] as Row[])[0]?.['name']).toEqual(
      new BSONRegExp('\\(\\)\\[\\]\\{\\}\\\\\\^\\$\\|\\-\\&\\~\\#\\ x', 'iu'));
    expect((await body('?q=bitumen')).items.map((i) => i['id'])).toEqual(['inact', 'rm', 'b2', 'b1']);
    for (const q of ['', '%20%20', '%09%0A', '%E2%80%83']) {
      await get(`?q=${q}`);
      expect(state.counts.at(-1), q).toEqual({ user_id: 'u1', company_id: 'co-a' });
    }
    await get('?q=x&q=bitumen');
    expect((((state.counts.at(-1) as Row)['$or'] as Row[])[0]?.['name'] as BSONRegExp).pattern).toBe('bitumen');
  });

  it('isolation: other user never leaks; owned alternate; unowned / unknown / empty header → default', async () => {
    expect((await body('?q=bitumen', as('u1', 'co-b'))).items.map((i) => i['id'])).toEqual(['cob']);
    for (const cid of ['co-z', 'co-nope', '']) expect((await body('?q=bitumen', as('u1', cid))).total, cid).toBe(4);
    expect((await body('?q=bitumen', as('u2', 'co-a'))).total).toBe(0);
  });

  it('serialisation: whole doubles, -0.0, null kept, _id removed; NaN / ObjectId → 500 text/plain', async () => {
    const r = await get('?q=serialization');
    expect(r.payload).toContain('"shortage_limit_kg":100.0,"z":-0.0,"nil":null}]');
    expect(r.payload).not.toContain('"_id"');
    for (const cid of ['co-nan', 'co-oid']) {
      const e = await get('', as('u1', cid));
      expect(e.statusCode, cid).toBe(500);
      expect(e.headers['content-type']).toBe('text/plain; charset=utf-8');
    }
  });

  it('401 precedes 422 and reads', async () => {
    for (const qs of ['', '?limit=abc']) {
      const r = await get(qs, {});
      expect(r.statusCode).toBe(401);
    }
    expect(state.counts).toEqual([]);
  });

  it('HEAD → 405 allow: GET before auth; static /resolve still wins; only GET registered here', async () => {
    for (const headers of [as('u1'), {}]) {
      const r = await app.inject({ method: 'HEAD', url: P, headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-length']).toBe('31');
    }
    const res = await app.inject({ method: 'GET', url: `${P}/resolve?trip_date=2026-05-10`, headers: as('u1') });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload)).toHaveProperty('trip_date', '2026-05-10');
    expect(app.hasRoute({ method: 'GET', url: P })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: P })).toBe(false);
    expect(app.hasRoute({ method: 'GET', url: `${P}/:pid` })).toBe(false);
  });
});
