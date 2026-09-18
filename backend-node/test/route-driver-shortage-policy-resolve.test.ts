/**
 * TRUKVIA · Phase-3 · Gate-8c · Driver shortage-policy resolve read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/driver-shortage-policies/resolve?trip_date=...&product_category=...
 *
 * Fake-DB write-forbid pattern inlined. The fake findOne records every
 * driver_shortage_policies call (filter incl. key order, projection, sort)
 * and evaluates the exact Mongo operators used by Python ($lte / $gte on
 * strings, $exists, null-matches-missing, $or / $and, array element
 * equality). Live Mongo semantics are proven by the parity harness.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Double, Int32, Long, ObjectId, type Db } from 'mongodb';
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
const REQUIRED = '{"detail":"trip_date required (YYYY-MM-DD)"}';

type Row = Record<string, unknown>;
interface Call { filter: Row; projection?: Row; sort?: Row }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; policies: Row[];
  writes: string[]; calls: Call[]; companyReads: number;
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

// Minimal Mongo matcher for the operators this route uses.
function cond(dv: unknown, has: boolean, c: unknown): boolean {
  if (c !== null && typeof c === 'object' && !Array.isArray(c)) {
    return Object.entries(c as Row).every(([op, v]) => {
      if (op === '$exists') return has === v;
      if (op === '$lte') return typeof dv === 'string' && typeof v === 'string' && dv <= v;
      if (op === '$gte') return typeof dv === 'string' && typeof v === 'string' && dv >= v;
      throw new Error(`unsupported ${op}`);
    });
  }
  if (c === null) return !has || dv === null;
  if (Array.isArray(dv)) return dv.includes(c);
  return dv === c;
}
function match(r: Row, f: Row): boolean {
  return Object.entries(f).every(([k, v]) => {
    if (k === '$or') return (v as Row[]).some((s) => match(r, s));
    if (k === '$and') return (v as Row[]).every((s) => match(r, s));
    return cond(r[k], Object.prototype.hasOwnProperty.call(r, k), v);
  });
}
const num = (v: unknown): number => (v === null || v === undefined ? -Infinity : Number(v));

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
      find: vi.fn(() => { throw new Error(`unexpected find on ${name}`); }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Row; sort?: Row }) => {
        if (name === 'companies') state.companyReads++;
        let hit = rows.filter((r) => (name === 'driver_shortage_policies' ? match(r, f) : Object.entries(f).every(([k, v]) => r[k] === v)));
        if (name === 'driver_shortage_policies') {
          state.calls.push({ filter: f, projection: opts?.projection, sort: opts?.sort });
          hit = [...hit].sort((a, b) =>
            String(b['effective_from']).localeCompare(String(a['effective_from'])) || num(b['version']) - num(a['version']));
        }
        const h = hit[0];
        if (!h) return null;
        const o: Row = { ...h };
        for (const [k, v] of Object.entries(opts?.projection ?? {})) if (v === 0) delete o[k];
        return o;
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

const pol = (id: string, from: unknown, extra: Row = {}, uid = 'u1', cid = 'co-a'): Row => ({
  _id: `oid-${id}`, id, user_id: uid, company_id: cid, name: `p ${id}`, effective_from: from, active: true, version: 1, ...extra,
});

function makeState(): State {
  return {
    sessions: ['u1', 'u2'].map((u) => ({ session_token: `tok-${u}`, user_id: u, effective_role: 'owner', expires_at: IN_FUTURE() })),
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false },
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    policies: [
      pol('ca-old', '2026-01-01'),                                                  // category + effective_to missing
      pol('ca-null', '2026-04-01', { product_category: null, effective_to: null }),
      pol('ca-empty-v2', '2026-04-01', { product_category: '', version: 2 }),
      pol('ca-expired', '2026-04-10', { effective_to: '2026-04-30', version: 9 }),
      pol('ca-inactive', '2026-05-05', { active: false }),
      pol('ca-active-int', '2026-05-06', { active: new Int32(1) }),
      pol('ca-space', '2026-05-08', { product_category: ' ' }),
      pol('ca-effto-empty', '2026-05-09', { effective_to: '' }),
      pol('bit-v1', '2026-05-01', { product_category: 'BITUMEN', version: 1 }),
      pol('bit-v2', '2026-05-01', { product_category: 'BITUMEN', version: 2 }),
      pol('emu-expired', '2026-01-01', { product_category: 'EMULSION', effective_to: '2026-02-01' }),
      pol('crmb-array', '2026-02-01', { product_category: ['CRMB', 'PMB'] }),
      pol('num-cat', '2026-02-01', { product_category: new Int32(5) }),
      pol('ser', '2026-02-03', {
        product_category: 'SER', shortage_limit_kg: new Double(100), big: Long.fromString('9007199254740993'),
        z: new Double(-0), nil: null,
      }),
      pol('nan', '2026-02-03', { product_category: 'NAN', shortage_limit_kg: new Double(NaN) }),
      pol('oid', '2026-02-03', { product_category: 'OID', ref: new ObjectId('65a000000000000000000001') }),
      pol('u2-in-co-a', '2026-05-09', { product_category: 'BITUMEN', version: 99 }, 'u2', 'co-a'),
      pol('u2-own', '2026-01-01', {}, 'u2', 'co-z'),
      pol('u1-co-b', '2026-02-01', {}, 'u1', 'co-b'),
    ],
    writes: [], calls: [], companyReads: 0,
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const P = '/api/driver-shortage-policies/resolve';
const as = (u: string, cid?: string): Record<string, string> =>
  cid === undefined ? { authorization: `Bearer tok-${u}` } : { authorization: `Bearer tok-${u}`, 'x-company-id': cid };
const Q_BASE = (cid: string, d: string): Row => ({
  user_id: 'u1', company_id: cid, active: true, effective_from: { $lte: d },
  $or: [{ effective_to: { $exists: false } }, { effective_to: null }, { effective_to: { $gte: d } }],
});
const CATCH_ALL = { $and: [{ $or: [{ product_category: { $exists: false } }, { product_category: null }, { product_category: '' }] }] };

describe('Gate-8c · Driver shortage-policy resolve read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (qs: string, headers: Record<string, string> = as('u1')): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: `${P}${qs}`, headers });
  const policyId = async (qs: string, headers?: Record<string, string>): Promise<unknown> =>
    (JSON.parse((await get(qs, headers)).payload) as { policy: Row | null }).policy?.['id'] ?? null;

  it('missing / empty / bare / repeated-empty trip_date → exact 400 before company resolution', async () => {
    for (const qs of ['', '?', '?trip_date=', '?trip_date', '?product_category=BITUMEN', '?trip_date=2026-05-10&trip_date=',
      '?trip_date%5B%5D=2026-05-10']) {
      const r = await get(qs);
      expect(r.statusCode, qs).toBe(400);
      expect(r.headers['content-type']).toBe('application/json');
      expect(r.payload).toBe(REQUIRED);
    }
    expect(state.companyReads).toBe(0);
    expect(state.calls).toEqual([]);
  });

  it('catch-all only (no category): exactly ONE read — READ #2 filter / sort / no projection, key order kept', async () => {
    const r = await get('?trip_date=2026-05-10');
    expect(r.statusCode).toBe(200);
    expect(state.calls).toHaveLength(1);
    const c = state.calls[0] as Call;
    expect(JSON.stringify(c.filter)).toBe(JSON.stringify({ ...Q_BASE('co-a', '2026-05-10'), ...CATCH_ALL }));
    expect(c.sort).toEqual({ effective_from: -1, version: -1 });
    expect(c.projection).toBeUndefined();
  });

  it('specific hit: ONE read (READ #1) with product_category appended after q_base; version tie-break', async () => {
    expect(await policyId('?trip_date=2026-05-10&product_category=BITUMEN')).toBe('bit-v2');
    expect(state.calls).toHaveLength(1);
    expect(JSON.stringify((state.calls[0] as Call).filter))
      .toBe(JSON.stringify({ ...Q_BASE('co-a', '2026-05-10'), product_category: 'BITUMEN' }));
  });

  it('specific miss → READ #1 then READ #2 fallback; neither → policy null', async () => {
    expect(await policyId('?trip_date=2026-05-10&product_category=EMULSION')).toBe('ca-empty-v2');
    expect(state.calls).toHaveLength(2);
    expect((await get('?trip_date=2025-12-31&product_category=NOPE')).payload).toBe('{"policy":null,"trip_date":"2025-12-31"}');
  });

  it('$or / $exists / null semantics: catch-all includes missing / null / ""; excludes " ", inactive, active:1, expired, effective_to ""', async () => {
    expect(await policyId('?trip_date=2026-05-10')).toBe('ca-empty-v2');
    expect(await policyId('?trip_date=2026-04-15')).toBe('ca-expired');
    expect(await policyId('?trip_date=2026-01-01')).toBe('ca-old');
    expect(await policyId('?trip_date=2026-05-10&product_category=%20')).toBe('ca-space');
  });

  it('type edge cases: array category matches an element; numeric stored category ≠ "5"; case-sensitive', async () => {
    expect(await policyId('?trip_date=2026-05-10&product_category=CRMB')).toBe('crmb-array');
    expect(await policyId('?trip_date=2026-05-10&product_category=5')).toBe('ca-empty-v2');
    expect(await policyId('?trip_date=2026-05-10&product_category=bitumen')).toBe('ca-empty-v2');
  });

  it('trip_date is a raw string: " " is truthy, no trimming, echoed verbatim; repeated → last; empty category → catch-all', async () => {
    expect((await get('?trip_date=+')).payload).toBe('{"policy":null,"trip_date":" "}');
    const r = JSON.parse((await get('?trip_date=x&trip_date=2026-05-10%20&product_category=')).payload) as Row;
    expect(r['trip_date']).toBe('2026-05-10 ');
    expect(await policyId('?trip_date=2026-05-10&product_category=X&product_category=BITUMEN')).toBe('bit-v2');
  });

  it('exact response: _id popped, user_id kept, key order, Python number formatting', async () => {
    const r = await get('?trip_date=2026-05-10&product_category=SER');
    expect(r.payload).toBe(
      '{"policy":{"id":"ser","user_id":"u1","company_id":"co-a","name":"p ser","effective_from":"2026-02-03",'
      + '"active":true,"version":1,"product_category":"SER","shortage_limit_kg":100.0,"big":9007199254740993,'
      + '"z":-0.0,"nil":null},"trip_date":"2026-05-10"}',
    );
  });

  it('NaN / ObjectId in the selected policy → 500 Internal Server Error text/plain', async () => {
    for (const cat of ['NAN', 'OID']) {
      const r = await get(`?trip_date=2026-05-10&product_category=${cat}`);
      expect(r.statusCode, cat).toBe(500);
      expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
      expect(r.payload).toBe('Internal Server Error');
    }
  });

  it('isolation: other user never leaks; owned alternate company; unowned / unknown / empty header → default', async () => {
    expect(await policyId('?trip_date=2026-05-10&product_category=BITUMEN', as('u1', 'co-b'))).toBe('u1-co-b');
    for (const cid of ['co-z', 'co-nope', '']) {
      expect(await policyId('?trip_date=2026-05-10&product_category=BITUMEN', as('u1', cid)), cid).toBe('bit-v2');
    }
    expect(await policyId('?trip_date=2026-05-10', as('u2'))).toBe('u2-own');
    expect(await policyId('?trip_date=2026-05-10&product_category=BITUMEN', as('u2', 'co-a'))).toBe('u2-own');
  });

  it('401 before validation and reads', async () => {
    for (const qs of ['', '?trip_date=2026-05-10']) {
      const r = await get(qs, {});
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
    expect(state.calls).toEqual([]);
  });

  it('HEAD → 405 allow: PUT (Starlette first partial match) before auth; only GET registered', async () => {
    for (const headers of [as('u1'), {}]) {
      const r = await app.inject({ method: 'HEAD', url: `${P}?trip_date=2026-05-10`, headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('PUT');
      expect(r.headers['content-length']).toBe('31');
    }
    expect(app.hasRoute({ method: 'GET', url: P })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: P })).toBe(false);
    expect(state.calls).toEqual([]);
  });
});
