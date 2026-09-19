/**
 * TRUKVIA · Phase-3 · Gate-8b · Vehicle status-audit read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/vehicles/{vid}/status-audit
 *
 * Fake-DB write-forbid pattern inlined. Two distinct reads, in order:
 *   READ #1 vehicles.findOne({id, user_id, company_id}, {_id:0, user_id:0})
 *   READ #2 vehicle_status_audit_log.find({user_id, company_id, vehicle_id},
 *           {_id:0, user_id:0}).sort({changed_at:-1}) — NO server limit,
 *           iteration stops at 500.
 * Live tie order is proven by the parity harness.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Decimal128, Double, Int32, Long, ObjectId, type Db } from 'mongodb';
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
const VEHICLE_NOT_FOUND = '{"detail":"Vehicle not found"}';

type Row = Record<string, unknown>;
interface Op { coll: string; kind: 'findOne' | 'find'; filter: Row; projection?: Row; sort?: Row; limit?: number;
  yielded?: number; closed?: boolean }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; vehicles: Row[]; audit: Row[];
  writes: string[]; ops: Op[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

const matches = (r: Row, f: Row): boolean => Object.entries(f).every(([k, v]) => r[k] === v);

function project(r: Row, projection: Row = {}): Row {
  const o: Row = { ...r };
  for (const [k, v] of Object.entries(projection)) if (v === 0) delete o[k];
  return o;
}

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Row[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'vehicles' ? state.vehicles
    : name === 'vehicle_status_audit_log' ? state.audit
    : [];
  const route = (name: string): boolean => name === 'vehicles' || name === 'vehicle_status_audit_log';
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      findOne: vi.fn(async (f: Row, opts?: { projection?: Row }) => {
        if (route(name)) state.ops.push({ coll: name, kind: 'findOne', filter: f, projection: opts?.projection });
        const hit = rows.find((r) => matches(r, f));
        return hit ? project(hit, opts?.projection) : null;
      }),
      find: vi.fn((f: Row, opts?: { projection?: Row }) => {
        if (name !== 'vehicle_status_audit_log') throw new Error(`unexpected find on ${name}`);
        const op: Op = { coll: name, kind: 'find', filter: f, projection: opts?.projection, yielded: 0, closed: false };
        state.ops.push(op);
        const cursor = {
          sort: (s: Row) => { op.sort = s; return cursor; },
          limit: (n: number) => { op.limit = n; return cursor; },
          close: async () => { op.closed = true; },
          async *[Symbol.asyncIterator]() {
            const hit = rows.filter((r) => matches(r, f)).map((r) => project(r, op.projection));
            hit.sort((a, b) => String(b['changed_at'] ?? '').localeCompare(String(a['changed_at'] ?? '')));
            for (const h of op.limit === undefined ? hit : hit.slice(0, op.limit)) {
              op.yielded = (op.yielded ?? 0) + 1;
              yield h;
            }
          },
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
  return { collection: vi.fn(collection) } as unknown as Db;
}

const ts = (i: number): string => new Date(Date.UTC(2026, 4, 1, 0, 0, i)).toISOString().replace('Z', '+00:00');
const veh = (id: unknown, uid = 'u1', cid = 'co-a', extra: Row = {}): Row =>
  ({ _id: `oid-veh-${String(id)}-${uid}-${cid}`, id, user_id: uid, company_id: cid, vehicle_number: `MH-${String(id)}`, ...extra });
const aud = (vid: string, n: number, changedAt: unknown, uid = 'u1', cid = 'co-a', extra: Row = {}): Row => ({
  _id: `oid-aud-${vid}-${uid}-${cid}-${n}`, id: `vsa-${vid}-${uid}-${cid}-${n}`, user_id: uid, company_id: cid,
  vehicle_id: vid, action: 'deactivated', changed_at: changedAt, ...extra,
});

function makeState(): State {
  const audit: Row[] = [
    aud('v1', 1, ts(2)), aud('v1', 0, ts(1)), aud('v1', 2, ts(3)),
    aud('v1', 90, ts(9), 'u2', 'co-a'), aud('v1', 91, ts(9), 'u1', 'co-b'),
    { _id: 'oid-orphan', vehicle_id: 'v1', changed_at: ts(9) }, aud('v-other', 0, ts(9)),
    aud('v-b', 0, ts(1), 'u1', 'co-b'),
    aud('v-ser', 0, ts(1), 'u1', 'co-a', {
      score: new Double(5), n: new Int32(7), big: Long.fromString('9007199254740993'), z: new Double(-0), nil: null,
    }),
    aud('v-nan', 0, ts(1), 'u1', 'co-a', { score: new Double(NaN) }),
    aud('v-oid', 0, ts(1), 'u1', 'co-a', { ref: new ObjectId('65a000000000000000000001') }),
    aud('v-dec', 0, ts(1), 'u1', 'co-a', { amt: Decimal128.fromString('12.50') }),
  ];
  for (let n = 0; n < 600; n++) audit.push(aud('v-big', n, ts(1000 - n)));
  for (const [vid, count] of [['v-49', 49], ['v-50', 50], ['v-51', 51]] as const) {
    for (let n = 0; n < count; n++) audit.push(aud(vid, n, ts(n)));
  }
  return {
    sessions: ['u1', 'u2'].map((u) => ({ session_token: `tok-${u}`, user_id: u, effective_role: 'owner', expires_at: IN_FUTURE() })),
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false },
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    vehicles: [
      veh('v1'), veh('v-empty'), veh('v-b', 'u1', 'co-b'), veh('v2', 'u2', 'co-z'),
      veh('v-ser'), veh('v-nan'), veh('v-oid'), veh('v-dec'), veh('v-big'), veh('v-49'), veh('v-50'), veh('v-51'),
      veh('v-false', 'u1', 'co-a', { is_active: false }), veh('v-zero', 'u1', 'co-a', { is_active: new Int32(0) }),
      veh('v-null', 'u1', 'co-a', { is_active: null }), veh('v-str', 'u1', 'co-a', { is_active: 'false' }),
      { _id: 'oid-nonum', id: 'v-nonum', user_id: 'u1', company_id: 'co-a' },
      veh('v-numflt', 'u1', 'co-a', { vehicle_number: new Double(5) }),
      veh('v-vehnan', 'u1', 'co-a', { notes_score: new Double(NaN) }),
    ],
    audit, writes: [], ops: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const url = (vid: string, qs = ''): string => `/api/vehicles/${vid}/status-audit${qs}`;
const as = (u: string, cid?: string): Record<string, string> =>
  cid === undefined ? { authorization: `Bearer tok-${u}` } : { authorization: `Bearer tok-${u}`, 'x-company-id': cid };

describe('Gate-8b · Vehicle status-audit read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = as('u1')): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });
  const body = async (u: string, headers?: Record<string, string>): Promise<{ vehicle: Row; items: Row[]; total: number }> =>
    JSON.parse((await get(u, headers)).payload);

  it('normal vehicle: exact wrapper bytes, changed_at DESC, status / content-type', async () => {
    const r = await get(url('v-b'), as('u1', 'co-b'));
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.payload).toBe(
      '{"vehicle":{"id":"v-b","vehicle_number":"MH-v-b","is_active":true},'
      + `"items":[{"id":"vsa-v-b-u1-co-b-0","company_id":"co-b","vehicle_id":"v-b","action":"deactivated","changed_at":"${ts(1)}"}],`
      + '"total":1}',
    );
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(r.payload)));
  });

  it('exact two reads in order: READ #1 id+user+company, READ #2 user+company+vehicle, no limit', async () => {
    await get(url('v1'));
    expect(state.ops.map((o) => [o.coll, o.kind])).toEqual([['vehicles', 'findOne'], ['vehicle_status_audit_log', 'find']]);
    const [r1, r2] = state.ops as [Op, Op];
    expect(r1.filter).toEqual({ id: 'v1', user_id: 'u1', company_id: 'co-a' });
    expect(r1.projection).toEqual({ _id: 0, user_id: 0 });
    expect(r2.filter).toEqual({ user_id: 'u1', company_id: 'co-a', vehicle_id: 'v1' });
    expect(r2.projection).toEqual({ _id: 0, user_id: 0 });
    expect(r2.sort).toEqual({ changed_at: -1 });
    expect(r2.limit).toBeUndefined();
    expect(r2.closed).toBe(true);
  });

  it('multiple rows newest first; conflicting user / company / orphan / other-vehicle rows excluded', async () => {
    const b = await body(url('v1'));
    expect(b.items.map((i) => i['id'])).toEqual(['vsa-v1-u1-co-a-2', 'vsa-v1-u1-co-a-1', 'vsa-v1-u1-co-a-0']);
    expect(b.total).toBe(3);
  });

  it('zero audit rows → items [] and total 0', async () => {
    expect((await get(url('v-empty'))).payload).toBe('{"vehicle":{"id":"v-empty","vehicle_number":"MH-v-empty","is_active":true},"items":[],"total":0}');
  });

  it('404 Vehicle not found: missing / another user / another company / unowned header → default', async () => {
    for (const [u, h] of [[url('nope'), as('u1')], [url('v-other'), as('u1')], [url('v2'), as('u1')], [url('v-b'), as('u1')],
      [url('v-b'), as('u1', 'co-z')], [url('v1'), as('u2')], [url('v1'), as('u2', 'co-a')]] as const) {
      const r = await get(u, h);
      expect(r.statusCode, u).toBe(404);
      expect(r.payload).toBe(VEHICLE_NOT_FOUND);
    }
    expect(state.ops.filter((o) => o.coll === 'vehicle_status_audit_log')).toEqual([]);
  });

  it('company header: owned alternate; unowned / unknown / empty → default company', async () => {
    expect((await body(url('v-b'), as('u1', 'co-b'))).total).toBe(1);
    for (const cid of ['co-z', 'co-nope', '']) expect((await body(url('v1'), as('u1', cid))).total, cid).toBe(3);
  });

  it('is_active is `is not False`: only boolean false → false; missing / 0 / null / "false" → true', async () => {
    expect((await body(url('v-false'))).vehicle['is_active']).toBe(false);
    for (const vid of ['v1', 'v-zero', 'v-null', 'v-str']) expect((await body(url(vid))).vehicle['is_active'], vid).toBe(true);
  });

  it('vehicle_number: missing → null; numeric kept with Python formatting; NaN in an unreturned field ignored', async () => {
    expect((await get(url('v-nonum'))).payload).toBe('{"vehicle":{"id":"v-nonum","vehicle_number":null,"is_active":true},"items":[],"total":0}');
    expect((await get(url('v-numflt'))).payload).toContain('"vehicle_number":5.0');
    expect((await get(url('v-vehnan'))).statusCode).toBe(200);
  });

  it('limit: 49 / 50 / 51 → 49 / 50 / 51; 600 → first 500 of the unlimited cursor (total 500)', async () => {
    for (const [vid, n] of [['v-49', 49], ['v-50', 50], ['v-51', 51]] as const) expect((await body(url(vid))).total, vid).toBe(n);
    const big = await body(url('v-big'));
    expect(big.total).toBe(500);
    expect(big.items).toHaveLength(500);
    expect(big.items[0]?.['id']).toBe('vsa-v-big-u1-co-a-0');
    expect(state.ops.at(-1)?.yielded).toBe(500);
  });

  it('serialisation: whole doubles, int32/int64, -0.0, null kept', async () => {
    expect((await get(url('v-ser'))).payload).toContain('"score":5.0,"n":7,"big":9007199254740993,"z":-0.0,"nil":null}]');
  });

  it('NaN / ObjectId / Decimal128 in an audit row → 500 Internal Server Error text/plain', async () => {
    for (const vid of ['v-nan', 'v-oid', 'v-dec']) {
      const r = await get(url(vid));
      expect(r.statusCode, vid).toBe(500);
      expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
      expect(r.payload).toBe('Internal Server Error');
    }
  });

  it('401 before any route read; empty / encoded-slash vid → 404 Not Found before auth; query ignored', async () => {
    for (const headers of [{}, { authorization: 'Bearer nope' }]) {
      const r = await get(url('v1'), headers);
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
    for (const vid of ['', 'a%2Fb']) {
      const r = await get(url(vid), {});
      expect(r.statusCode, vid).toBe(404);
      expect(r.payload).toBe('{"detail":"Not Found"}');
    }
    expect(state.ops).toEqual([]);
    expect((await get(url('v1', '?x=1&x=2'))).payload).toBe((await get(url('v1'))).payload);
  });

  it('HEAD → 405 allow: GET before auth; only GET (+ explicit HEAD) registered — no writer', async () => {
    for (const headers of [as('u1'), {}]) {
      const r = await app.inject({ method: 'HEAD', url: url('v1'), headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-length']).toBe('31');
    }
    const p = '/api/vehicles/:vid/status-audit';
    expect(app.hasRoute({ method: 'GET', url: p })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: p })).toBe(false);
    expect(app.hasRoute({ method: 'PATCH', url: '/api/vehicles/:vid/status' })).toBe(false);
    // Gate 9d: Starlette redirect_slashes → 307 to the slash-less path (verified live).
    const slash = await get(`${url('v1')}/`);
    expect(slash.statusCode).toBe(307);
    expect(slash.headers['location']).toBe(`http://localhost:80${url('v1')}`);
  });
});
