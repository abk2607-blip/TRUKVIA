/**
 * TRUKVIA · Phase-3 · Gate-7y · Reminder digest read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/reminders/digest
 *
 * Fake-DB write-forbid pattern inlined. USER-ONLY scope: the route must
 * never touch `companies` (Python does not call `_active_company_id`), so
 * any companies access is recorded and asserted empty. The fake findOne
 * records the exact filter / projection / sort; live tie order is proven by
 * the parity harness.
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
const NO_DIGEST =
  '{"digest":null,"message":"No digest yet — cron runs at 18:00 IST daily. Try /reminders/digest/run to generate now."}';

type Row = Record<string, unknown>;
interface FindOneCall { filter: Row; projection?: Row; sort?: Row; promoteValues?: boolean }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; digests: Row[];
  writes: string[]; companyReads: number; lookups: FindOneCall[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

const matches = (r: Row, f: Row): boolean => Object.entries(f).every(([k, v]) => r[k] === v);

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Row[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'reminder_digests' ? state.digests
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      find: vi.fn(() => { throw new Error(`unexpected find on ${name}`); }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Row; sort?: Row; promoteValues?: boolean }) => {
        if (name === 'companies') state.companyReads++;
        let hit = rows.filter((r) => matches(r, f));
        if (name === 'reminder_digests') {
          state.lookups.push({ filter: f, projection: opts?.projection, sort: opts?.sort, promoteValues: opts?.promoteValues });
          hit = [...hit].sort((a, b) => String(b['generated_at'] ?? '').localeCompare(String(a['generated_at'] ?? '')));
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

const gen = (day: number): string => `2026-05-${String(day).padStart(2, '0')}T12:30:00+00:00`;

function dg(uid: string, day: number, extra: Row = {}): Row {
  return { _id: `oid-${uid}-${day}`, user_id: uid, date: `2026-05-${String(day).padStart(2, '0')}`,
    generated_at: gen(day), entries: [], total_customers: 0, total_outstanding: new Double(0), ...extra };
}

function makeState(): State {
  const users = ['u1', 'u2', 'u3', 'u5', 'u7', 'u8', 'u10'];
  return {
    sessions: users.map((u) => ({ session_token: `tok-${u}`, user_id: u, effective_role: 'owner', expires_at: IN_FUTURE() })),
    users: users.map((u) => ({ user_id: u, email: `${u}@x` })),
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false },
      { id: 'co-z', user_id: 'u2', is_default: true },
      { id: 'co-u3a', user_id: 'u3', is_default: false },
    ],
    digests: [
      dg('u1', 2), dg('u1', 3, { marker: 'latest-u1' }), dg('u1', 1),
      dg('u2', 9, { marker: 'u2-only', entries: [{ company_id: 'co-a', balance: new Double(10) }] }),
      dg('u3', 4, { marker: 'u3' }),
      dg('u7', 2, {
        entries: [{ company_id: 'co-a', customer_id: 'c', balance: new Double(1500), invoices: new Int32(2),
          big: Long.fromString('9007199254740993'), z: new Double(-0), nil: null }],
        total_customers: new Int32(1), total_outstanding: new Double(1500),
      }),
      dg('u8', 2, { total_outstanding: new Double(NaN) }),
      dg('u10', 2, { ref: new ObjectId('65a000000000000000000001') }),
    ],
    writes: [], companyReads: 0, lookups: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const P = '/api/reminders/digest';
const as = (u: string, cid?: string): Record<string, string> =>
  cid === undefined ? { authorization: `Bearer tok-${u}` } : { authorization: `Bearer tok-${u}`, 'x-company-id': cid };

describe('Gate-7y · Reminder digest read-only shadow (user-only scope)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    expect(state.companyReads).toBe(0);
    await app.close();
  });

  const get = (headers: Record<string, string>, qs = ''): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: P + qs, headers });
  const marker = async (headers: Record<string, string>): Promise<unknown> =>
    (JSON.parse((await get(headers)).payload) as { digest: Row | null }).digest?.['marker'];

  it('digest branch: latest by generated_at, user_id kept, _id dropped, exact bytes / content-type', async () => {
    const r = await get(as('u1'));
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.payload).toBe(
      `{"digest":{"user_id":"u1","date":"2026-05-03","generated_at":"${gen(3)}","entries":[],`
      + '"total_customers":0,"total_outstanding":0.0,"marker":"latest-u1"}}',
    );
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(r.payload)));
  });

  it('exact find_one: filter {user_id} ONLY, projection {_id:0}, sort generated_at -1', async () => {
    await get(as('u1', 'co-b'));
    expect(state.lookups).toEqual([{
      filter: { user_id: 'u1' }, projection: { _id: 0 }, sort: { generated_at: -1 }, promoteValues: false,
    }]);
  });

  it('null branch: no digest → exact {"digest":null,"message":...}', async () => {
    for (const headers of [as('u5'), as('u5', 'co-a')]) {
      const r = await get(headers);
      expect(r.statusCode).toBe(200);
      expect(r.headers['content-type']).toBe('application/json');
      expect(r.payload).toBe(NO_DIGEST);
    }
  });

  it('user-only: X-Company-Id (owned / unowned / unknown / empty) never changes the result', async () => {
    for (const cid of [undefined, 'co-a', 'co-b', 'co-z', 'co-nope', '']) {
      expect(await marker(as('u1', cid)), String(cid)).toBe('latest-u1');
    }
  });

  it('isolation: another user sees only their own digest, even with the first user\'s company header', async () => {
    expect(await marker(as('u2'))).toBe('u2-only');
    expect(await marker(as('u2', 'co-a'))).toBe('u2-only');
  });

  it('user with no default company still gets their digest (no company resolution)', async () => {
    expect(await marker(as('u3'))).toBe('u3');
  });

  it('query parameters are ignored', async () => {
    const base = (await get(as('u1'))).payload;
    for (const qs of ['?user_id=u2', '?x=1&x=2', '?', '?%zz=%C3']) {
      expect((await get(as('u1'), qs)).payload, qs).toBe(base);
    }
  });

  it('Python serialisation: whole doubles, int32/int64, -0.0, null kept', async () => {
    const r = await get(as('u7'));
    expect(r.payload).toContain(
      '"entries":[{"company_id":"co-a","customer_id":"c","balance":1500.0,"invoices":2,"big":9007199254740993,"z":-0.0,"nil":null}]',
    );
    expect(r.payload).toContain('"total_customers":1,"total_outstanding":1500.0}');
  });

  it('NaN / ObjectId in the digest → 500 Internal Server Error text/plain', async () => {
    for (const u of ['u8', 'u10']) {
      const r = await get(as(u));
      expect(r.statusCode, u).toBe(500);
      expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
      expect(r.payload).toBe('Internal Server Error');
    }
  });

  it('401 before any digest read', async () => {
    for (const headers of [{}, { authorization: 'Bearer nope' }]) {
      const r = await get(headers);
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
    expect(state.lookups).toEqual([]);
  });

  it('HEAD → 405 allow: GET before auth; trailing slash is not this route', async () => {
    for (const headers of [as('u1'), {}]) {
      const r = await app.inject({ method: 'HEAD', url: P, headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-length']).toBe('31');
    }
    // Gate 9d: Starlette redirect_slashes → 307 to the slash-less path (verified live).
    const slash = await app.inject({ method: 'GET', url: `${P}/`, headers: as('u1') });
    expect(slash.statusCode).toBe(307);
    expect(slash.headers['location']).toBe(`http://localhost:80${P}`);
    expect(state.lookups).toEqual([]);
  });

  it('only GET (+ explicit HEAD) registered — the POST /run writer is NOT migrated', () => {
    expect(app.hasRoute({ method: 'GET', url: P })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: P })).toBe(false);
    expect(app.hasRoute({ method: 'POST', url: `${P}/run` })).toBe(false);
  });
});
