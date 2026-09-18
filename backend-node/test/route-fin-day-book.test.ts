/**
 * TRUKVIA · Phase-3 · Gate-7s · Fin Day Book read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/fin/day-book
 *
 * Fake-DB write-forbid pattern (mirrors Gate 7r). Documents carry typed BSON
 * values as the driver returns them with `promoteValues:false`. Expected
 * bytes / totals are the ones the live Python server produced in the
 * Gate 7s parity run (542-byte-exact matrix), not derived.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Binary, Code, Decimal128, Double, Int32, Long, ObjectId, type Db } from 'mongodb';
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
  colls: Record<string, Row[]>;
  writes: string[];
  finds: { filter: Row; opts?: Row; sort?: unknown; limited?: boolean; read: number }[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

const isOps = (v: unknown): v is Row =>
  typeof v === 'object' && v !== null && !Array.isArray(v) && Object.keys(v).length > 0
  && Object.keys(v).every((k) => k.startsWith('$'));

function matches(d: Row, f: Row): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isOps(v)) {
      for (const [op, ov] of Object.entries(v)) {
        if (typeof dv !== 'string' || typeof ov !== 'string') return false;
        if (op === '$gte' && !(dv >= ov)) return false;
        if (op === '$lte' && !(dv <= ov)) return false;
      }
      continue;
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(d: Row, projection?: Record<string, 0 | 1>): Row {
  const o: Row = { ...d };
  if (projection) for (const [k, v] of Object.entries(projection)) if (v === 0) delete o[k];
  return o;
}

function fakeDb(state: State): Db {
  const collection = (name: string) => {
    const rows = state.colls[name] ?? [];
    return {
      find: vi.fn((f: Row, opts?: { projection?: Record<string, 0 | 1> } & Row) => {
        const rec: State['finds'][number] = { filter: f, opts, read: 0 };
        if (name === 'fin_txn') state.finds.push(rec);
        let hits = rows.filter((r) => matches(r, f));
        const cursor = {
          sort(spec: [string, 1 | -1][]) {
            rec.sort = spec;
            hits = hits.slice().sort((a, b) => {
              for (const [k, dir] of spec) {
                const av = String(a[k]); const bv = String(b[k]);
                if (av !== bv) return (av < bv ? -1 : 1) * dir;
              }
              return 0;
            });
            return cursor;
          },
          limit() { rec.limited = true; return cursor; },
          async close() { /* no-op */ },
          async *[Symbol.asyncIterator]() {
            for (const h of hits) { rec.read += 1; yield project(h, opts?.projection); }
          },
        };
        return cursor;
      }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        if (!hit) return null;
        const inc = Object.entries(opts?.projection ?? {}).filter(([, v]) => v === 1).map(([k]) => k);
        return inc.length ? Object.fromEntries(inc.filter((k) => k in hit).map((k) => [k, hit[k]])) : project(hit, opts?.projection);
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

const MISSING = Symbol('missing');
function leg(amount: unknown, direction: unknown = 'in', acct: unknown = 'AR', o: Row = {}): Row {
  const r: Row = { id: 'x', status: 'active', txn_date: '2026-04-30', created_at: '2026-04-30T10:00:00+00:00' };
  if (acct !== MISSING) r['account_code'] = acct;
  if (amount !== MISSING) r['amount'] = amount;
  if (direction !== MISSING) r['direction'] = direction;
  return { ...r, ...o };
}

function makeState(): State {
  return {
    colls: {
      user_sessions: [
        { session_token: 'tok-u1',      user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
        { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
        { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
      ],
      users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
      companies: [
        { id: 'co-a',     user_id: 'u1', is_default: true },
        { id: 'co-a-alt', user_id: 'u1', is_default: false },
        { id: 'cx',       user_id: 'u1', is_default: false },
        { id: 'co-b',     user_id: 'u2', is_default: true },
      ],
      fin_txn: [
        { ...leg(new Double(100.125), 'in', 'AR'), id: 't-a1', user_id: 'u1', company_id: 'co-a' },
        { ...leg(new Double(40), 'out', 'BANK', { txn_date: '2026-03-01' }), id: 't-a2', user_id: 'u1', company_id: 'co-a' },
        { ...leg(new Double(9), 'in', 'AR', { status: 'void' }), id: 't-a3', user_id: 'u1', company_id: 'co-a' },
        { ...leg(new Double(7.5), 'in', 'CASH'), id: 't-alt', user_id: 'u1', company_id: 'co-a-alt' },
        { ...leg(new Double(3.25), 'in', 'AR'), id: 't-u2', user_id: 'u2', company_id: 'co-b' },
        { ...leg(new Double(999), 'in', 'LEAK'), id: 't-leak', user_id: 'u2', company_id: 'co-a' },
      ],
    },
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
const CX = { ...U1, 'x-company-id': 'cx' };
const WIN = 'date_from=2026-01-01&date_to=2026-12-31';
const P = '/api/fin/day-book';
const totalsOf = (body: string): string => body.slice(body.indexOf('"totals":') + 9, body.lastIndexOf(',"count"'));
const missing = (name: string): Row => ({ type: 'missing', loc: ['query', name], msg: 'Field required', input: null,
  url: 'https://errors.pydantic.dev/2.13/v/missing' });

describe('Gate-7s · Fin Day Book read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });
  const withLegs = async (legs: Row[], q = WIN): Promise<Awaited<ReturnType<typeof get>>> => {
    state.colls['fin_txn'] = legs.map((l, i) => ({ id: `t${i}`, ...l, user_id: 'u1', company_id: 'cx' }));
    return get(`${P}?${q}`, CX);
  };

  // ── AUTH / VALIDATION ORDER / CONTENT-TYPE ─────────────────────────
  it.each([
    [{}, 'Not authenticated'],
    [{ authorization: 'Bearer nope' }, 'Invalid session'],
    [{ authorization: 'Bearer tok-expired' }, 'Session expired'],
  ])('1 auth failure %j → 401 %s · exact application/json', async (h, detail) => {
    const r = await get(`${P}?${WIN}`, h as Record<string, string>);
    expect(r.statusCode).toBe(401);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.body).toBe(JSON.stringify({ detail }));
  });

  it.each([P, `${P}?limit=abc`, `${P}?date_from=&date_to=`])('2 auth precedes validation · %s → 401', async (u) => {
    expect((await get(u)).statusCode).toBe(401);
  });

  it('3 missing both dates + bad limit → one 422 list in declaration order', async () => {
    const r = await get(`${P}?limit=abc`, U1);
    expect(r.statusCode).toBe(422);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.json()).toEqual({ detail: [missing('date_from'), missing('date_to'), {
      type: 'int_parsing', loc: ['query', 'limit'],
      msg: 'Input should be a valid integer, unable to parse string as an integer', input: 'abc',
      url: 'https://errors.pydantic.dev/2.13/v/int_parsing' }] });
  });

  it.each([
    [`${P}?date_to=x`, [missing('date_from')]],
    [`${P}?date_from=x`, [missing('date_to')]],
  ])('4 %s → 422 single missing', async (u, detail) => {
    const r = await get(u, U1);
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({ detail });
  });

  it('5 limit int_parsing_size', async () => {
    const r = await get(`${P}?${WIN}&limit=${'1'.repeat(4301)}`, U1);
    expect(r.statusCode).toBe(422);
    expect(r.json<{ detail: Row[] }>().detail[0]?.['type']).toBe('int_parsing_size');
  });

  it.each([`${P}?date_from=&date_to=x`, `${P}?date_from=x&date_to=`, `${P}?date_from&date_to`])(
    '6 empty date %s → 400 literal after company resolution', async (u) => {
      const r = await get(u, U1);
      expect(r.statusCode).toBe(400);
      expect(r.headers['content-type']).toBe('application/json');
      expect(r.body).toBe('{"detail":"date_from and date_to are required (YYYY-MM-DD)"}');
      expect(state.finds).toEqual([]);
    },
  );

  it('7 empty dates + bad limit → 422 (FastAPI validation before handler 400)', async () => {
    expect((await get(`${P}?date_from=&date_to=&limit=x`, U1)).statusCode).toBe(422);
  });

  // ── EXACT READ / SHAPE ─────────────────────────────────────────────
  it('8 exact find · sort · no server limit · typed values', async () => {
    await get(`${P}?${WIN}`, U1);
    expect(state.finds[0]).toMatchObject({
      filter: { user_id: 'u1', company_id: 'co-a', txn_date: { $gte: '2026-01-01', $lte: '2026-12-31' }, status: 'active' },
      opts: { projection: { _id: 0, user_id: 0 }, promoteValues: false },
      sort: [['txn_date', -1], ['created_at', -1]],
    });
    expect(state.finds[0]?.limited).toBeUndefined();
  });

  it('9 normal result · Python-exact bytes · key order date_from,date_to,rows,totals,count', async () => {
    const r = await get(`${P}?${WIN}`, U1);
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.body).toBe(
      '{"date_from":"2026-01-01","date_to":"2026-12-31","rows":['
      + '{"id":"t-a1","status":"active","txn_date":"2026-04-30","created_at":"2026-04-30T10:00:00+00:00",'
      + '"account_code":"AR","amount":100.125,"direction":"in","company_id":"co-a"},'
      + '{"id":"t-a2","status":"active","txn_date":"2026-03-01","created_at":"2026-04-30T10:00:00+00:00",'
      + '"account_code":"BANK","amount":40.0,"direction":"out","company_id":"co-a"}],'
      + '"totals":{"AR":{"in":100.12,"out":0.0,"net":100.12},"BANK":{"in":0.0,"out":40.0,"net":-40.0}},"count":2}',
    );
  });

  it('10 empty result', async () => {
    const r = await withLegs([]);
    expect(r.body).toBe('{"date_from":"2026-01-01","date_to":"2026-12-31","rows":[],"totals":{},"count":0}');
  });

  it('11 multi accounts in sorted-row insertion order · duplicate aggregation', async () => {
    const r = await withLegs([
      leg(new Double(1), 'in', 'BANK', { txn_date: '2026-04-30' }), leg(new Double(2), 'in', 'AR', { txn_date: '2026-04-29' }),
      leg(new Double(3), 'out', 'BANK', { txn_date: '2026-04-28' }), leg(new Double(4), 'in', 'CASH', { txn_date: '2026-04-27' }),
      leg(new Double(1.5), 'in', 'AR', { txn_date: '2026-04-26' }), leg(new Double(0.25), 'out', 'AR', { txn_date: '2026-04-25' }),
    ]);
    expect(totalsOf(r.body)).toBe('{"BANK":{"in":1.0,"out":3.0,"net":-2.0},"AR":{"in":3.5,"out":0.25,"net":3.25},'
      + '"CASH":{"in":4.0,"out":0.0,"net":4.0}}');
  });

  // ── ROUND-HALF-EVEN PER ACCOUNT ────────────────────────────────────
  it.each([
    [0.125, '0.12'], [0.375, '0.38'], [0.625, '0.62'], [0.875, '0.88'], [2.675, '2.67'], [1.005, '1.0'],
    [0.015, '0.01'], [0.025, '0.03'], [-0.125, '-0.12'], [-2.675, '-2.67'], [0.1250000000000001, '0.13'],
    [0.12499999999999999, '0.12'], [2.675000000000001, '2.68'], [2.6749999999999994, '2.67'], [10.125, '10.12'],
    [1234567.125, '1234567.12'], [5e-324, '0.0'], [2.2250738585072014e-308, '0.0'], [0.30000000000000004, '0.3'],
    [1.7976931348623157e308, '1.7976931348623157e+308'],
  ])('12 round(%d, 2) → %s', async (x, want) => {
    const r = await withLegs([leg(new Double(x))]);
    expect(totalsOf(r.body)).toBe(`{"AR":{"in":${want},"out":0.0,"net":${want}}}`);
  });

  it('13 net = round(round(in) - round(out)) per account · repeated additions', async () => {
    const a = await withLegs([leg(new Double(0.125)), leg(new Double(0.005), 'out'),
      leg(new Double(2.675), 'in', 'X'), leg(new Double(1.005), 'out', 'X')]);
    expect(totalsOf(a.body)).toBe('{"AR":{"in":0.12,"out":0.01,"net":0.11},"X":{"in":2.67,"out":1.0,"net":1.67}}');
    const b = await withLegs(Array.from({ length: 10 }, () => leg(new Double(0.1))));
    expect(totalsOf(b.body)).toBe('{"AR":{"in":1.0,"out":0.0,"net":1.0}}');
  });

  it('14 large+small ordering follows sort order', async () => {
    const r = await withLegs([leg(new Double(1e16), 'in', 'AR', { txn_date: '2026-04-30' }),
      leg(new Double(1), 'in', 'AR', { txn_date: '2026-04-29' }), leg(new Double(-1e16), 'in', 'AR', { txn_date: '2026-04-28' })]);
    expect(totalsOf(r.body)).toBe('{"AR":{"in":0.0,"out":0.0,"net":0.0}}');
  });

  it('15 zero / negative / decimal', async () => {
    const r = await withLegs([leg(new Double(0)), leg(new Double(-0), 'out'), leg(new Double(-12.345)),
      leg(new Double(0.1), 'out'), leg(new Double(0.2), 'out')]);
    expect(totalsOf(r.body)).toBe('{"AR":{"in":-12.35,"out":0.3,"net":-12.65}}');
  });

  // ── float() CONVERSION ─────────────────────────────────────────────
  it.each<[string, unknown, string]>([
    ['str 12.5', '12.5', '12.5'], ['str underscores', '1_000.25', '1000.25'], ['str arabic digits', ' ١٢.5 ', '12.5'],
    ['str exponent', '1e3', '1000.0'], ['str empty', '', '0.0'], ['int32', new Int32(7), '7.0'], ['bool true', true, '1.0'],
    ['int64 big', Long.fromString('9007199254740993'), '9007199254740992.0'], ['Binary', new Binary(Buffer.from('2.5')), '2.5'],
    ['Code', new Code('1.5'), '1.5'], ['null', null, '0.0'], ['empty list', [], '0.0'],
  ])('16 amount %s → in %s', async (_n, amount, want) => {
    const r = await withLegs([leg(amount)]);
    expect(totalsOf(r.body)).toBe(`{"AR":{"in":${want},"out":0.0,"net":${want}}}`);
  });

  it.each<[string, unknown]>([
    ['str abc', 'abc'], ['str 0x10', '0x10'], ['str BOM', '﻿1'], ['str inf', 'inf'], ['str nan', 'nan'],
    ['str 1e400', '1e400'], ['double NaN', new Double(NaN)], ['double -inf', new Double(-Infinity)],
    ['Decimal128', Decimal128.fromString('1.5')], ['datetime', new Date('2026-01-01T00:00:00Z')],
    ['ObjectId', new ObjectId('65f000000000000000000001')], ['list [1]', [new Int32(1)]],
  ])('17 amount %s → 500 text/plain', async (_n, amount) => {
    const r = await withLegs([leg(amount)]);
    expect(r.statusCode).toBe(500);
    expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
    expect(r.body).toBe('Internal Server Error');
  });

  it('18 non-finite totals → 500 (overflow, inf-inf, inf in another account)', async () => {
    expect((await withLegs([leg(new Double(1.7976931348623157e308)), leg(new Double(1.7976931348623157e308))])).statusCode).toBe(500);
    expect((await withLegs([leg(new Double(Infinity)), leg(new Double(Infinity), 'out')])).statusCode).toBe(500);
    expect((await withLegs([leg(new Double(1), 'in', 'OK'), leg(new Double(-Infinity), 'in', 'BAD')])).statusCode).toBe(500);
  });

  it('19 direction: only exact "in" counts as in', async () => {
    const r = await withLegs([leg(new Double(1), 'IN'), leg(new Double(2), MISSING), leg(new Double(4), null),
      leg(new Double(8), 'out'), leg(new Double(16), 'in')]);
    expect(totalsOf(r.body)).toBe('{"AR":{"in":16.0,"out":15.0,"net":1.0}}');
  });

  // ── TOTALS KEY SEMANTICS ───────────────────────────────────────────
  it.each<[string, unknown[], string]>([
    ['int 1, True, "1" → duplicate JSON keys', [new Int32(1), true, '1'],
      '{"1":{"in":2.0,"out":0.0,"net":2.0},"1":{"in":1.0,"out":0.0,"net":1.0}}'],
    ['True then 1.0 merge (first text)', [true, new Double(1)], '{"true":{"in":2.0,"out":0.0,"net":2.0}}'],
    ['double keys repr', [new Double(5), new Double(1e16)], '{"5.0":{"in":1.0,"out":0.0,"net":1.0},"1e+16":{"in":1.0,"out":0.0,"net":1.0}}'],
    ['falsy keys → ""', [MISSING, null, '', new Int32(0), new Double(-0), [], {}], '{"":{"in":7.0,"out":0.0,"net":7.0}}'],
  ])('20 keys: %s', async (_n, keys, want) => {
    const r = await withLegs(keys.map((k, i) => leg(new Double(1), 'in', k, { txn_date: `2026-04-${String(30 - i).padStart(2, '0')}` })));
    expect(r.statusCode).toBe(200);
    expect(totalsOf(r.body)).toBe(want);
  });

  it('21 bytes vs str collision: first position, LAST value', async () => {
    const a = await withLegs([leg(new Double(1), 'in', new Binary(Buffer.from('AR')), { txn_date: '2026-04-30' }),
      leg(new Double(5), 'in', 'AR', { txn_date: '2026-04-29' })]);
    expect(totalsOf(a.body)).toBe('{"AR":{"in":5.0,"out":0.0,"net":5.0}}');
    const b = await withLegs([leg(new Double(5), 'in', 'AR', { txn_date: '2026-04-30' }),
      leg(new Double(1), 'in', new Binary(Buffer.from('AR')), { txn_date: '2026-04-29' })]);
    expect(totalsOf(b.body)).toBe('{"AR":{"in":1.0,"out":0.0,"net":1.0}}');
  });

  it.each<[string, unknown]>([
    ['list', [new Int32(1)]], ['dict', { a: new Int32(1) }], ['Code', new Code('x')],
    ['ObjectId', new ObjectId('65f000000000000000000002')], ['Decimal128', Decimal128.fromString('1')], ['NaN', new Double(NaN)],
  ])('22 account_code %s → 500', async (_n, k) => {
    expect((await withLegs([leg(new Double(1), 'in', k)])).statusCode).toBe(500);
  });

  // ── ROW SERIALISATION ──────────────────────────────────────────────
  it('23 row field types serialise like FastAPI', async () => {
    const r = await withLegs([leg(new Double(1), 'in', 'AR', {
      x_dt: new Date('2026-01-02T03:04:05.123Z'), x_bin: new Binary(Buffer.from('hello')), x_i64: Long.fromString('9007199254740993'),
      x_d: [new Double(5), new Double(1e16), new Double(1e-5), new Double(-0)],
    })]);
    expect(r.body).toContain('"x_dt":"2026-01-02T03:04:05.123000","x_bin":"hello","x_i64":9007199254740993,"x_d":[5.0,1e+16,1e-05,-0.0]');
  });

  it.each<[string, unknown]>([
    ['ObjectId', new ObjectId('65f000000000000000000003')], ['nested NaN', { a: [new Double(NaN)] }],
  ])('24 row field %s → 500', async (_n, v) => {
    expect((await withLegs([leg(new Double(1), 'in', 'AR', { x: v })])).statusCode).toBe(500);
  });

  // ── FILTERS / LIMIT / TIES ─────────────────────────────────────────
  it('25 optional filters: truthy only, in Python order, repeated key last wins', async () => {
    await get(`${P}?${WIN}&trip_id=t&account_code=&party_id=p&source_type=s&account_id=a&vehicle_id=v&account_code=AR`, U1);
    expect(Object.keys(state.finds[0]?.filter ?? {})).toEqual(
      ['user_id', 'company_id', 'txn_date', 'status', 'account_code', 'account_id', 'source_type', 'party_id', 'vehicle_id', 'trip_id']);
    expect(state.finds[0]?.filter['account_code']).toBe('AR');
  });

  it.each([['1', 1], ['0', 1], ['-5', 1], ['2', 2], ['1.0', 1], ['+2', 2], ['1_0', 10], ['99999', 25]])(
    '26 limit=%s reads %i of 25 rows from an unlimited cursor', async (lim, n) => {
      const r = await withLegs(Array.from({ length: 25 }, (_, i) => leg(new Double(1), 'in', 'AR', { tag: new Int32(i) })),
        `${WIN}&limit=${encodeURIComponent(lim)}`);
      expect(r.body.endsWith(`"count":${n}}`)).toBe(true);
      expect(state.finds[0]?.limited).toBeUndefined();
      expect(state.finds[0]?.read).toBe(n);
    },
  );

  it('27 ties: created_at breaks txn_date ties DESC', async () => {
    const r = await withLegs(Array.from({ length: 4 }, (_, i) => leg(new Double(1), 'in', 'AR',
      { id: `k${i}`, created_at: `2026-04-30T0${i}:00:00+00:00` })));
    const ids = (JSON.parse(r.body) as { rows: Row[] }).rows.map((x) => x['id']);
    expect(ids).toEqual(['k3', 'k2', 'k1', 'k0']);
  });

  // ── ISOLATION ──────────────────────────────────────────────────────
  it('28 cross-user u2 · owned alt · unowned fallback · leak hidden', async () => {
    expect((await get(`${P}?${WIN}`, { authorization: 'Bearer tok-u2' })).body).toContain('"id":"t-u2"');
    expect((await get(`${P}?${WIN}`, { ...U1, 'x-company-id': 'co-a-alt' })).body).toContain('"id":"t-alt"');
    const fb = await get(`${P}?${WIN}`, { ...U1, 'x-company-id': 'co-b' });
    expect(fb.body).toContain('"id":"t-a1"');
    expect(fb.body).not.toContain('t-leak');
  });
});
