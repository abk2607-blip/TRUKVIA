/**
 * TRUKVIA · Phase-3 · Gate-8e · Reports supplier list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/reports/suppliers
 *
 * Fake-DB write-forbid pattern inlined. Records every distinct / findOne in
 * order. The fake evaluates the UNESCAPED `^name$` pattern with a JS RegExp
 * (case-insensitive) and throws for an invalid pattern, standing in for the
 * MongoDB OperationFailure; real PCRE semantics are proven by the harness.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Double, Int32, type Db } from 'mongodb';
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
interface Op { kind: 'distinct' | 'findOne'; coll: string; key?: string; filter: Row; projection?: Row }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; trips: Row[]; vehicles: Row[];
  distinctValues: Record<string, unknown[]>; writes: string[]; ops: Op[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function scoped(r: Row, f: Row): boolean {
  return Object.entries(f).every(([k, v]) => {
    if (v !== null && typeof v === 'object' && '$regex' in (v as Row)) {
      const re = new RegExp((v as { $regex: string }).$regex, 'i');
      return typeof r[k] === 'string' && re.test(r[k] as string);
    }
    return r[k] === v;
  });
}

// MongoDB rejects an invalid pattern up front (OperationFailure), before scanning.
function compileRegexes(f: Row): void {
  for (const v of Object.values(f)) {
    if (v !== null && typeof v === 'object' && '$regex' in (v as Row)) new RegExp((v as { $regex: string }).$regex, 'i');
  }
}

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Row[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'trips' ? state.trips
    : name === 'vehicles' ? state.vehicles
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      distinct: vi.fn(async (key: string, f: Row) => {
        state.ops.push({ kind: 'distinct', coll: name, key, filter: f });
        const override = state.distinctValues[`${name}:${String(f['company_id'])}`];
        if (override) return override;
        const out: unknown[] = [];
        for (const r of rows.filter((x) => scoped(x, f))) {
          const vals = Array.isArray(r[key]) ? (r[key] as unknown[]) : [r[key]];
          for (const v of vals) if (v !== undefined && !out.includes(v)) out.push(v);
        }
        return out.sort((a, b) => String(a).localeCompare(String(b)));
      }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Row }) => {
        if (name === 'vehicles') state.ops.push({ kind: 'findOne', coll: name, filter: f, projection: opts?.projection });
        compileRegexes(f);
        const hit = rows.find((r) => scoped(r, f));
        if (!hit) return null;
        if (!opts?.projection || name !== 'vehicles') return { ...hit };
        const o: Row = {};
        for (const [k, v] of Object.entries(opts.projection)) if (v === 1 && k in hit) o[k] = hit[k];
        return o;
      }),
      find: vi.fn(() => { throw new Error(`unexpected find on ${name}`); }),
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

const trip = (name: unknown, cid = 'co-a', uid = 'u1', vtype = 'supplier'): Row =>
  ({ user_id: uid, company_id: cid, vehicle_type: vtype, supplier_name: name });
const veh = (name: unknown, extra: Row = {}, cid = 'co-a', uid = 'u1', vtype = 'supplier'): Row =>
  ({ _id: `oid-${String(name)}-${cid}-${uid}`, user_id: uid, company_id: cid, vehicle_type: vtype, supplier_name: name, ...extra });

function makeState(): State {
  return {
    sessions: ['u1', 'u2'].map((u) => ({ session_token: `tok-${u}`, user_id: u, effective_role: 'owner', expires_at: IN_FUTURE() })),
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      ...['co-b', 'co-empty', 'co-bad', 'co-rx', 'co-mob', 'co-uni'].map((id) => ({ id, user_id: 'u1', is_default: false })),
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    trips: [
      trip('Zeta'), trip(' Sharma Roads '), trip('sharma roads'), trip('alpha'), trip('a.b'), trip('a+b'),
      trip('Own Fleet', 'co-a', 'u1', 'own'), trip('U2 Leak', 'co-a', 'u2'), trip('Co-B Only', 'co-b'),
      trip('(unclosed', 'co-rx'), trip('Good', 'co-rx'),
      trip('Mob Bad', 'co-mob'),
    ],
    vehicles: [
      veh('Zeta', { supplier_mobile: ' 98765 ' }), veh('SHARMA ROADS', { supplier_mobile: '', owner_phone: '111' }),
      veh('alpha', { supplier_mobile: new Int32(0), owner_phone: '222' }),
      veh('axb', { supplier_mobile: 'REGEX-DOT' }), veh('aab', { supplier_mobile: 'REGEX-PLUS' }),
      veh('a+b', { supplier_mobile: 'LITERAL-PLUS' }),
      veh('Vehicle Only', { owner_phone: '333' }), veh('Zeta', { supplier_mobile: 'OTHER-USER' }, 'co-a', 'u2'),
      veh('Mob Bad', { supplier_mobile: new Double(5) }, 'co-mob'),
    ],
    distinctValues: {
      // Python-falsy values skipped; a truthy non-str mid-stream → 500 after earlier lookups.
      'trips:co-bad': [null, '', new Int32(0), false, {}, 'First Ok', new Int32(7), 'Never Reached'],
      'trips:co-uni': ['\u{1D504}xy', 'ａbc', 'ΑΣ', 'É', 'e'],
    },
    writes: [], ops: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const P = '/api/reports/suppliers';
const as = (u: string, cid?: string): Record<string, string> =>
  cid === undefined ? { authorization: `Bearer tok-${u}` } : { authorization: `Bearer tok-${u}`, 'x-company-id': cid };
const SCOPE = { user_id: 'u1', company_id: 'co-a', vehicle_type: 'supplier' };

describe('Gate-8e · Reports supplier list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (headers: Record<string, string> = as('u1'), qs = ''): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: `${P}${qs}`, headers });
  const names = async (headers?: Record<string, string>): Promise<string[]> =>
    (JSON.parse((await get(headers)).payload) as Row[]).map((r) => r['name'] as string);

  it('normal result: exact bytes, content-type, de-dupe (first wins), strip, mobile fallbacks, Python sort', async () => {
    const r = await get();
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    // Vehicle-master supplier names (aab, axb, …) are listed too; `a+b` resolves its mobile via
    // the UNESCAPED ^a+b$ (matches "aab"), `a.b` via ^a.b$ (matches "axb").
    expect(r.payload).toBe(
      '[{"name":"a+b","mobile":"REGEX-PLUS"},{"name":"a.b","mobile":"REGEX-DOT"},{"name":"aab","mobile":"REGEX-PLUS"},'
      + '{"name":"alpha","mobile":"222"},{"name":"axb","mobile":"REGEX-DOT"},{"name":"Sharma Roads","mobile":"111"},'
      + '{"name":"Vehicle Only","mobile":"333"},{"name":"Zeta","mobile":"98765"}]',
    );
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(r.payload)));
  });

  it('exact read sequence: distinct(trips) → distinct(vehicles) → one findOne per new name, unescaped ^name$ / i', async () => {
    await get();
    const seq = state.ops.map((o) => `${o.kind}:${o.coll}`);
    expect(seq.slice(0, 2)).toEqual(['distinct:trips', 'distinct:vehicles']);
    expect(state.ops[0]).toMatchObject({ key: 'supplier_name', filter: SCOPE });
    expect(state.ops[1]).toMatchObject({ key: 'supplier_name', filter: SCOPE });
    const lookups = state.ops.slice(2);
    expect(lookups.every((o) => o.kind === 'findOne' && o.coll === 'vehicles')).toBe(true);
    const patterns = lookups.map((o) => (o.filter['supplier_name'] as { $regex: string }).$regex);
    // exactly one lookup per NEW (stripped, case-folded) name — 8 names, no repeats
    expect(patterns).toHaveLength(8);
    expect(new Set(patterns)).toEqual(new Set(
      ['^Sharma Roads$', '^Zeta$', '^a+b$', '^a.b$', '^alpha$', '^aab$', '^axb$', '^Vehicle Only$']));
    for (const o of lookups) {
      expect(JSON.stringify(Object.keys(o.filter))).toBe(JSON.stringify(['user_id', 'company_id', 'vehicle_type', 'supplier_name']));
      expect((o.filter['supplier_name'] as Row)['$options']).toBe('i');
      expect(o.projection).toEqual({ _id: 0, supplier_mobile: 1, owner_phone: 1 });
    }
    expect(patterns).toContain('^a+b$'); // NOT escaped
    // a case-duplicate never triggers a second lookup
    expect(patterns.filter((p) => /sharma/i.test(p))).toHaveLength(1);
  });

  it('empty company → [] with exactly the two distinct reads', async () => {
    const r = await get(as('u1', 'co-empty'));
    expect(r.payload).toBe('[]');
    expect(state.ops.map((o) => o.kind)).toEqual(['distinct', 'distinct']);
  });

  it('falsy names skipped; a truthy non-string mid-stream → 500 after the earlier lookup only', async () => {
    const r = await get(as('u1', 'co-bad'));
    expect(r.statusCode).toBe(500);
    expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
    expect(r.payload).toBe('Internal Server Error');
    const lookups = state.ops.filter((o) => o.kind === 'findOne');
    expect(lookups.map((o) => (o.filter['supplier_name'] as { $regex: string }).$regex)).toEqual(['^First Ok$']);
  });

  it('invalid unescaped regex → 500 (after the valid earlier lookup)', async () => {
    const r = await get(as('u1', 'co-rx'));
    expect(r.statusCode).toBe(500);
    expect(r.payload).toBe('Internal Server Error');
  });

  it('truthy non-string mobile → 500', async () => {
    expect((await get(as('u1', 'co-mob'))).statusCode).toBe(500);
  });

  it('sort = code-point order on Python lower(): fullwidth (U+FF41) before astral (U+1D504); É/e; final sigma', async () => {
    expect(await names(as('u1', 'co-uni'))).toEqual(['e', 'É', 'ΑΣ', 'ａbc', '\u{1D504}xy']);
  });

  it('isolation: other user never leaks; owned alternate; unowned / unknown / empty header → default', async () => {
    expect(await names(as('u1', 'co-b'))).toEqual(['Co-B Only']);
    const base = await names();
    for (const cid of ['co-z', 'co-nope', '']) expect(await names(as('u1', cid)), cid).toEqual(base);
    expect(base).not.toContain('U2 Leak');
    expect(await names(as('u2', 'co-a'))).toEqual([]);
  });

  it('query parameters are ignored', async () => {
    const base = (await get()).payload;
    for (const qs of ['?x=1&x=2', '?', '?%zz=%C3']) expect((await get(as('u1'), qs)).payload, qs).toBe(base);
  });

  it('401 before any read', async () => {
    for (const headers of [{}, { authorization: 'Bearer nope' }]) {
      const r = await get(headers);
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
    expect(state.ops).toEqual([]);
  });

  it('HEAD → 405 allow: GET before auth; only GET registered', async () => {
    for (const headers of [as('u1'), {}]) {
      const r = await app.inject({ method: 'HEAD', url: P, headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-length']).toBe('31');
    }
    expect(app.hasRoute({ method: 'GET', url: P })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: P })).toBe(false);
    expect(state.ops).toEqual([]);
  });
});
