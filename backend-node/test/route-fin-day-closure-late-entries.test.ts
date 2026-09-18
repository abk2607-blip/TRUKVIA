/**
 * TRUKVIA · Phase-3 · Gate-7r · Fin day-closure late-entries read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/fin/day-closures/:close_date/late-entries
 *
 * Fake-DB write-forbid pattern (mirrors Gate 7q). Documents carry typed BSON
 * values exactly as the driver returns them with `promoteValues:false`.
 * Every expected number / byte below was observed on the live Python server
 * (Gate 7r parity harness), not derived.
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
const CLOSED_AT = '2026-05-10T18:00:00+00:00';

type Row = Record<string, unknown>;
interface State {
  colls: Record<string, Row[]>;
  writes: string[];
  calls: { coll: string; kind: string; filter: Row; opts?: Row; sort?: unknown; limited?: boolean }[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

const isOps = (v: unknown): v is Row =>
  typeof v === 'object' && v !== null && !Array.isArray(v) && Object.keys(v).length > 0
  && Object.keys(v).every((k) => k.startsWith('$'));

// Mongo semantics used here: string range ops; an array field matches when any element does.
function opOk(dv: unknown, op: string, ov: unknown): boolean {
  if (Array.isArray(dv)) return dv.some((x) => opOk(x, op, ov));
  if (typeof dv !== 'string' || typeof ov !== 'string') return false;
  return op === '$lte' ? dv <= ov : dv > ov;
}

function matches(d: Row, f: Row): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isOps(v)) {
      for (const [op, ov] of Object.entries(v)) if (!opOk(dv, op, ov)) return false;
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
  const collection = (name: string) => {
    const rows = state.colls[name] ?? [];
    const track = name === 'fin_day_closures' || name === 'fin_txn';
    return {
      find: vi.fn((f: Row, opts?: { projection?: Record<string, 0 | 1> } & Row) => {
        const rec: State['calls'][number] = { coll: name, kind: 'find', filter: f, opts };
        if (track) state.calls.push(rec);
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
            for (const h of hits) yield project(h, opts?.projection);
          },
        };
        return cursor;
      }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        if (track) state.calls.push({ coll: name, kind: 'findOne', filter: f, opts });
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

// Per-test company "cx": one closure + the given legs. MISSING omits a field
// (JS default parameters would turn `undefined` into the default).
const MISSING = Symbol('missing');
function leg(amount: unknown, direction: unknown = 'in', stype: unknown = 'invoice', o: Row = {}): Row {
  const r: Row = { id: 'x', status: 'active', txn_date: '2026-04-30', created_at: '2026-05-11T00:00:00+00:00' };
  if (amount !== MISSING) r['amount'] = amount;
  if (direction !== MISSING) r['direction'] = direction;
  if (stype !== MISSING) r['source_type'] = stype;
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
      fin_day_closures: [
        { id: 'c1', user_id: 'u1', company_id: 'co-a', close_date: '2026-05-01', status: 'closed', closed_at: CLOSED_AT },
        { id: 'c-alt', user_id: 'u1', company_id: 'co-a-alt', close_date: '2026-05-01', status: 'closed', closed_at: CLOSED_AT },
        { id: 'cx', user_id: 'u1', company_id: 'cx', close_date: '2026-05-01', status: 'closed', closed_at: CLOSED_AT },
        { id: 'c-u2', user_id: 'u2', company_id: 'co-b', close_date: '2026-05-01', status: 'reopened', closed_at: CLOSED_AT },
        { id: 'c-noclosed', user_id: 'u1', company_id: 'co-a', close_date: '2026-03-01', status: 'closed' },
      ],
      fin_txn: [
        { ...leg(new Double(100.125), 'in', 'invoice'), id: 't-a1', user_id: 'u1', company_id: 'co-a' },
        { ...leg(new Double(40), 'out', 'expense', { txn_date: '2026-03-01' }), id: 't-a2', user_id: 'u1', company_id: 'co-a' },
        { ...leg(new Double(7.5), 'in', 'wallet_recharge'), id: 't-alt', user_id: 'u1', company_id: 'co-a-alt' },
        { ...leg(new Double(3.25), 'in', 'invoice'), id: 't-u2', user_id: 'u2', company_id: 'co-b' },
      ],
    },
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
const CX = { ...U1, 'x-company-id': 'cx' };
const url = (d: string): string => `/api/fin/day-closures/${d}/late-entries`;
const totalsOf = (body: string): string => body.slice(body.indexOf('"totals":'), body.indexOf(',"by_source_type"'));

describe('Gate-7r · Fin day-closure late-entries read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });
  const withLegs = async (legs: Row[]): Promise<Awaited<ReturnType<typeof get>>> => {
    state.colls['fin_txn'] = legs.map((l, i) => ({ ...l, id: `t${i}`, user_id: 'u1', company_id: 'cx' }));
    return get(url('2026-05-01'), CX);
  };

  // ── AUTH / VALIDATION / 404 ────────────────────────────────────────
  it.each([
    [{}, 'Not authenticated'],
    [{ authorization: 'Bearer nope' }, 'Invalid session'],
    [{ authorization: 'Bearer tok-expired' }, 'Session expired'],
  ])('1 auth failure %j → 401 %s', async (h, detail) => {
    const r = await get(url('2026-05-01'), h as Record<string, string>);
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail });
    expect(state.calls).toEqual([]);
  });

  it('2 auth precedes date validation', async () => {
    expect((await get(url('bad'))).statusCode).toBe(401);
  });

  it.each(['bad', '2026-13-01', '2026-5-1'])('3 invalid close_date %s → 400', async (d) => {
    const r = await get(url(d), U1);
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'close_date must be ISO YYYY-MM-DD' });
  });

  it('4 no closure → 404 raw echo', async () => {
    const r = await get(url('20260501'), U1);
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'No closure exists for 20260501' });
  });

  it('5 closure without closed_at → 404 (projection {} is falsy)', async () => {
    const r = await get(url('2026-03-01'), U1);
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'No closure exists for 2026-03-01' });
    expect(state.calls.map((c) => c.coll)).toEqual(['fin_day_closures']);
  });

  it.each([['/api/fin/day-closures/2026%2F05/late-entries'], ['/api/fin/day-closures//late-entries']])(
    '6 %s → 404 Not Found before auth', async (p) => {
      const r = await get(p);
      expect(r.statusCode).toBe(404);
      expect(r.json()).toEqual({ detail: 'Not Found' });
    },
  );

  // ── EXACT READS / SHAPE ────────────────────────────────────────────
  it('7 exact reads · no server-side limit · typed values', async () => {
    await get(url('2026-05-01'), U1);
    expect(state.calls[0]).toEqual({ coll: 'fin_day_closures', kind: 'findOne',
      filter: { user_id: 'u1', company_id: 'co-a', close_date: '2026-05-01' },
      opts: { projection: { _id: 0, closed_at: 1 } } });
    expect(state.calls[1]).toMatchObject({ coll: 'fin_txn', kind: 'find',
      filter: { user_id: 'u1', company_id: 'co-a', status: 'active',
        txn_date: { $lte: '2026-05-01' }, created_at: { $gt: CLOSED_AT } },
      opts: { projection: { _id: 0, user_id: 0 }, promoteValues: false },
      sort: [['txn_date', -1]] });
    expect(state.calls[1]?.limited).toBeUndefined();
  });

  it('8 normal result · Python-exact bytes', async () => {
    const r = await get(url('2026-05-01'), U1);
    expect(r.statusCode).toBe(200);
    // Python sends pplication/json; Fastify appends ; charset=utf-8 (header-only, all Node routes).
    expect(String(r.headers['content-type']).split(';')[0]).toBe('application/json');
    expect(r.body).toBe(
      '{"close_date":"2026-05-01","count":2,"totals":{"in":100.12,"out":40.0,"net":60.12},'
      + '"by_source_type":{"invoice":1,"expense":1},'
      + '"by_days_late_bucket":{"0-7":1,"8-30":0,"31-90":1,"90+":0},'
      + '"rows":[{"id":"t-a1","status":"active","txn_date":"2026-04-30","created_at":"2026-05-11T00:00:00+00:00",'
      + '"amount":100.125,"direction":"in","source_type":"invoice","company_id":"co-a","days_late":1},'
      + '{"id":"t-a2","status":"active","txn_date":"2026-03-01","created_at":"2026-05-11T00:00:00+00:00",'
      + '"amount":40.0,"direction":"out","source_type":"expense","company_id":"co-a","days_late":61}]}',
    );
  });

  it('9 empty result', async () => {
    const r = await withLegs([]);
    expect(r.body).toBe('{"close_date":"2026-05-01","count":0,"totals":{"in":0.0,"out":0.0,"net":0.0},'
      + '"by_source_type":{},"by_days_late_bucket":{"0-7":0,"8-30":0,"31-90":0,"90+":0},"rows":[]}');
  });

  // ── ROUND-HALF-EVEN (live Python results) ──────────────────────────
  it.each([
    [0.125, '0.12'], [0.375, '0.38'], [0.625, '0.62'], [0.875, '0.88'], [2.675, '2.67'], [1.005, '1.0'],
    [1.115, '1.11'], [0.285, '0.28'], [1.255, '1.25'], [8.345, '8.35'], [10.125, '10.12'],
    [1234567.125, '1234567.12'], [0.005, '0.01'], [0.015, '0.01'], [0.025, '0.03'], [0.035, '0.04'],
    [0.045, '0.04'], [-0.125, '-0.12'], [-2.675, '-2.67'], [0.1250000000000001, '0.13'],
    [0.12499999999999999, '0.12'], [2.5, '2.5'], [5e-324, '0.0'], [0.30000000000000004, '0.3'],
  ])('10 round(%d, 2) → %s (differs from toFixed where noted)', async (x, want) => {
    const r = await withLegs([leg(new Double(x))]);
    expect(totalsOf(r.body)).toBe(`"totals":{"in":${want},"out":0.0,"net":${want}}`);
  });

  it('11 toFixed / Math.round would disagree on the half-way cases', () => {
    expect((0.125).toFixed(2)).toBe('0.13');
    expect(Math.round(0.625 * 100) / 100).toBe(0.63);
  });

  it('12 net = round(round(in) - round(out)) · accumulation order', async () => {
    const a = await withLegs([leg(new Double(0.125)), leg(new Double(0.005), 'out')]);
    expect(totalsOf(a.body)).toBe('"totals":{"in":0.12,"out":0.01,"net":0.11}');
    const b = await withLegs(Array.from({ length: 10 }, () => leg(new Double(0.1))));
    expect(totalsOf(b.body)).toBe('"totals":{"in":1.0,"out":0.0,"net":1.0}');
  });

  it('13 zero / negative / decimal amounts', async () => {
    const r = await withLegs([leg(new Double(0)), leg(new Int32(0), 'out'), leg(new Double(-0)),
      leg(new Double(-12.345)), leg(new Double(-0.125), 'out')]);
    expect(totalsOf(r.body)).toBe('"totals":{"in":-12.35,"out":-0.12,"net":-12.23}');
  });

  // ── float() CONVERSION ─────────────────────────────────────────────
  it.each<[string, unknown, string]>([
    ['str 12.5', '12.5', '12.5'], ['str underscores', '1_000.25', '1000.25'],
    ['str arabic digits + spaces', ' ١٢.5 ', '12.5'], ['str NBSP', ' 7.5', '7.5'],
    ['str exponent', '1e3', '1000.0'], ['str +.5', '+.5', '0.5'], ['str -5.', '-5.', '-5.0'],
    ['str empty (falsy)', '', '0.0'], ['int32', new Int32(7), '7.0'], ['bool true', true, '1.0'],
    ['bool false', false, '0.0'], ['null', null, '0.0'], ['int64 big', Long.fromString('9007199254740993'), '9007199254740992.0'],
    ['Binary bytes', new Binary(Buffer.from('2.5')), '2.5'], ['Code str-subclass', new Code('1.5'), '1.5'],
    ['empty list', [], '0.0'], ['empty dict', {}, '0.0'],
  ])('14 amount %s → in %s', async (_n, amount, want) => {
    const r = await withLegs([leg(amount)]);
    expect(r.statusCode).toBe(200);
    expect(totalsOf(r.body)).toBe(`"totals":{"in":${want},"out":0.0,"net":${want}}`);
  });

  it.each<[string, unknown]>([
    ['str abc', 'abc'], ['str 1,5', '1,5'], ['str 0x10', '0x10'], ['str 1__0', '1__0'], ['str \\x1c1', '1'],
    ['str BOM', '﻿1'], ['str inf', 'inf'], ['str -Infinity', '-Infinity'], ['str nan', 'nan'],
    ['str 1e400', '1e400'], ['double NaN', new Double(NaN)], ['double +inf', new Double(Infinity)],
    ['double -inf', new Double(-Infinity)], ['Decimal128', Decimal128.fromString('1.5')],
    ['datetime', new Date('2026-01-01T00:00:00Z')], ['ObjectId', new ObjectId('65f000000000000000000001')],
    ['list [1]', [new Int32(1)]], ['dict {a:1}', { a: new Int32(1) }], ['Binary invalid', new Binary(Buffer.from([0xff]))],
  ])('15 amount %s → 500 Internal Server Error (text/plain)', async (_n, amount) => {
    const r = await withLegs([leg(amount)]);
    expect(r.statusCode).toBe(500);
    expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
    expect(r.body).toBe('Internal Server Error');
  });

  it('16 totals overflow / inf-inf → 500', async () => {
    expect((await withLegs([leg(new Double(1.7976931348623157e308)), leg(new Double(1.7976931348623157e308))])).statusCode).toBe(500);
    expect((await withLegs([leg(new Double(Infinity)), leg(new Double(Infinity), 'out')])).statusCode).toBe(500);
  });

  it('17 direction: only exact "in" counts as in', async () => {
    const r = await withLegs([leg(new Double(1), 'IN'), leg(new Double(2), MISSING), leg(new Double(4), 'out'),
      leg(new Double(8), null), leg(new Double(16), 'in')]);
    expect(totalsOf(r.body)).toBe('"totals":{"in":16.0,"out":15.0,"net":1.0}');
  });

  // ── by_source_type DICT SEMANTICS ──────────────────────────────────
  it.each<[string, unknown[], string]>([
    ['insertion order b,a,c', ['b', 'a', 'b', 'c'], '{"b":2,"a":1,"c":1}'],
    ['numeric-looking strings keep order', ['10', '2', 'a', '1'], '{"10":1,"2":1,"a":1,"1":1}'],
    ['int 1, True, "1" → duplicate JSON keys', [new Int32(1), true, '1'], '{"1":2,"1":1}'],
    ['True then 1.0', [true, new Double(1)], '{"true":2}'],
    ['double keys repr', [new Double(5), new Double(1e16), new Double(0.1)], '{"5.0":1,"1e+16":1,"0.1":1}'],
    ['int64 big', [Long.fromString('9007199254740993')], '{"9007199254740993":1}'],
    ['falsy → ""', [MISSING, null, '', new Int32(0), new Double(-0), [], {}], '{"":7}'],
    ['bytes + str collide in jsonable_encoder', [new Binary(Buffer.from('hello')), 'hello'], '{"hello":1}'],
    ['datetime key isoformat', [new Date('2026-01-02T03:04:05.123Z')], '{"2026-01-02T03:04:05.123000":1}'],
  ])('18 source keys: %s', async (_n, keys, want) => {
    const r = await withLegs(keys.map((k) => leg(new Double(1), 'in', k)));
    expect(r.statusCode).toBe(200);
    expect(r.body.slice(r.body.indexOf('"by_source_type":') + 17, r.body.indexOf(',"by_days_late_bucket"'))).toBe(want);
  });

  it.each<[string, unknown]>([
    ['list', [new Int32(1)]], ['dict', { a: new Int32(1) }], ['Code', new Code('x')],
    ['ObjectId', new ObjectId('65f000000000000000000002')], ['Decimal128', Decimal128.fromString('1')],
    ['NaN', new Double(NaN)], ['inf', new Double(Infinity)],
  ])('19 source key %s → 500', async (_n, k) => {
    expect((await withLegs([leg(new Double(1), 'in', k)])).statusCode).toBe(500);
  });

  // ── days_late ──────────────────────────────────────────────────────
  it('20 buckets 0,7,8,30,31,90,91,400', async () => {
    const r = await withLegs(['2026-05-01', '2026-04-24', '2026-04-23', '2026-04-01', '2026-03-31', '2026-01-31',
      '2026-01-30', '2025-03-27'].map((d) => leg(new Double(1), 'in', 'x', { txn_date: d })));
    expect(r.body).toContain('"by_days_late_bucket":{"0-7":2,"8-30":2,"31-90":2,"90+":2}');
  });

  it('21 unparsable / array / astral txn_date → 0 days · existing days_late keeps position', async () => {
    const r = await withLegs([
      leg(new Double(1), 'in', 'x', { txn_date: '2026-04-3x' }),
      leg(new Double(1), 'in', 'x', { txn_date: ['2026-04-01'] }),
      leg(new Double(1), 'in', 'x', { txn_date: '2026-04-0\u{1d7cf}', days_late: new Int32(999), zz: 'tail' }),
    ]);
    expect(r.body).toContain('"days_late":0,"zz":"tail"');
    expect(r.body).toContain('"count":3,');
    expect(r.body).toContain('"by_days_late_bucket":{"0-7":3,"8-30":0,"31-90":0,"90+":0}');
  });

  it('22 ISO-week close_date resolves to the real date', async () => {
    state.colls['fin_day_closures']?.push({ id: 'cw', user_id: 'u1', company_id: 'cx', close_date: '2026-W18-5', closed_at: CLOSED_AT });
    state.colls['fin_txn'] = [{ ...leg(new Double(1), 'in', 'x', { txn_date: '2026-04-01' }), id: 'tw', user_id: 'u1', company_id: 'cx' }];
    const r = await get(url('2026-W18-5'), CX);
    expect(r.body).toContain('"days_late":30');
  });

  // ── ROW SERIALISATION ──────────────────────────────────────────────
  it('23 row field types serialise like FastAPI', async () => {
    const r = await withLegs([leg(new Double(1), 'in', 'x', {
      x_dt: new Date('2026-01-02T03:04:05.123Z'), x_dt0: new Date('2026-01-02T00:00:00Z'),
      x_bin: new Binary(Buffer.from('hello')), x_code: new Code('c', { s: 1 }), x_i64: Long.fromString('9007199254740993'),
      x_d: [new Double(5), new Double(1e16), new Double(1e15), new Double(1e-5), new Double(1e-4), new Double(-0),
        new Double(123456789.123), new Double(5e-324)],
      x_nested: { a: [new Int32(1), new Double(2), { b: null, c: 'q"\\\n\t é₹' }] },
    })]);
    expect(r.body).toContain('"x_dt":"2026-01-02T03:04:05.123000","x_dt0":"2026-01-02T00:00:00","x_bin":"hello",'
      + '"x_code":"c","x_i64":9007199254740993,'
      + '"x_d":[5.0,1e+16,1000000000000000.0,1e-05,0.0001,-0.0,123456789.123,5e-324],'
      + '"x_nested":{"a":[1,2.0,{"b":null,"c":"q\\"\\\\\\n\\t\\u0001 é₹"}]}');
  });

  it.each<[string, unknown]>([
    ['ObjectId', new ObjectId('65f000000000000000000003')], ['Decimal128', Decimal128.fromString('2.5')],
    ['nested NaN', { a: [new Double(NaN)] }], ['Binary invalid utf-8', new Binary(Buffer.from([0xfe]))],
  ])('24 row field %s → 500', async (_n, v) => {
    expect((await withLegs([leg(new Double(1), 'in', 'x', { x: v })])).statusCode).toBe(500);
  });

  // ── CAP / ISOLATION ────────────────────────────────────────────────
  it('25 cap 5000 read from an unlimited cursor', async () => {
    const r = await withLegs(Array.from({ length: 5002 }, () => leg(new Double(0.01))));
    expect(r.body.startsWith('{"close_date":"2026-05-01","count":5000,"totals":{"in":50.0,')).toBe(true);
  });

  it('26 cross-user u2 · reopened closure still served', async () => {
    const r = await get(url('2026-05-01'), { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(200);
    expect(r.body).toContain('"count":1');
    expect(r.body).toContain('"id":"t-u2"');
  });

  it('27 owned X-Company-Id alt · unowned falls back', async () => {
    expect((await get(url('2026-05-01'), { ...U1, 'x-company-id': 'co-a-alt' })).body).toContain('"id":"t-alt"');
    expect((await get(url('2026-05-01'), { ...U1, 'x-company-id': 'co-b' })).body).toContain('"id":"t-a1"');
  });
});
