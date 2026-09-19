/**
 * TRUKVIA · Phase-3 · Gate-7w · Saved trip filters list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/saved-trip-filters
 *
 * Fake-DB write-forbid pattern inlined. The fake `find` records the exact
 * cursor shape (filter / projection / sort / limit) and emulates a stable
 * sort + server-side limit; live tie order is proven by the parity harness.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Double, Int32, Long, type Db } from 'mongodb';
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
interface FindCall { filter: Row; projection?: Row; promoteValues?: boolean; sort?: Row; limit?: number }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; filters: Row[];
  writes: string[]; finds: FindCall[];
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
    : name === 'saved_trip_filters' ? state.filters
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      findOne: vi.fn(async (f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        if (!hit) return null;
        const o: Row = { ...hit };
        for (const [k, v] of Object.entries(opts?.projection ?? {})) if (v === 0) delete o[k];
        return o;
      }),
      find: vi.fn((f: Row, opts?: { projection?: Row; promoteValues?: boolean }) => {
        if (name !== 'saved_trip_filters') throw new Error(`unexpected find on ${name}`);
        const call: FindCall = { filter: f, projection: opts?.projection, promoteValues: opts?.promoteValues };
        state.finds.push(call);
        const cursor = {
          sort: (s: Row) => { call.sort = s; return cursor; },
          limit: (n: number) => { call.limit = n; return cursor; },
          toArray: async () => {
            const hit = rows.filter((r) => matches(r, f)).map((r) => {
              const o: Row = { ...r };
              delete o['_id'];
              return o;
            });
            // stable DESC on created_at (strings only in this fake)
            hit.sort((a, b) => String(b['created_at'] ?? '').localeCompare(String(a['created_at'] ?? '')));
            return call.limit === undefined ? hit : hit.slice(0, call.limit);
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

const ts = (i: number): string => new Date(Date.UTC(2026, 4, 1, 0, i)).toISOString().replace('Z', '+00:00');

function sf(n: number, uid: string, cid: string, created_at: unknown, extra: Row = {}): Row {
  return { _id: `oid-${cid}-${uid}-${n}`, id: `sf-${cid}-${uid}-${n}`, user_id: uid, company_id: cid,
    name: `${cid} ${n}`, filter_state: { n }, created_at, ...extra };
}

function makeState(): State {
  const filters: Row[] = [];
  for (let n = 0; n < 49; n++) filters.push(sf(n, 'u1', 'co-49', ts(n)));
  for (let n = 0; n < 50; n++) filters.push(sf(n, 'u1', 'co-50', ts(n)));
  for (let n = 0; n < 51; n++) filters.push(sf(n, 'u1', 'co-51', ts(n)));
  for (let n = 0; n < 60; n++) filters.push(sf(n, 'u1', 'co-tie', ts(0)));
  filters.push(sf(0, 'u1', 'co-a', ts(1)), sf(1, 'u1', 'co-a', ts(3)), sf(2, 'u1', 'co-a', ts(2)));
  filters.push(sf(0, 'u2', 'co-a', ts(9)), sf(0, 'u2', 'co-z', ts(1)));
  filters.push(sf(0, 'u1', 'co-typed', ts(1), {
    filter_state: { f: new Double(5), i32: new Int32(7), i64: Long.fromString('9007199254740993'), z: new Double(-0) },
    extra: 'kept',
  }));
  filters.push(sf(0, 'u1', 'co-nan', ts(1), { filter_state: { x: new Double(NaN) } }));
  return {
    sessions: [
      { session_token: 'tok-u1', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2', user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
    ],
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      ...['co-49', 'co-50', 'co-51', 'co-tie', 'co-empty', 'co-typed', 'co-nan']
        .map((id) => ({ id, user_id: 'u1', is_default: false })),
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    filters, writes: [], finds: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const P = '/api/saved-trip-filters';
const U1 = { authorization: 'Bearer tok-u1' };
const as = (cid: string, tok = 'tok-u1'): Record<string, string> => ({ authorization: `Bearer ${tok}`, 'x-company-id': cid });

describe('Gate-7w · Saved trip filters list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (headers: Record<string, string> = U1, qs = ''): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: P + qs, headers });
  const ids = async (headers: Record<string, string>): Promise<string[]> =>
    (JSON.parse((await get(headers)).payload) as Row[]).map((r) => r['id'] as string);

  it('normal result: default company, created_at DESC, exact bytes / content-type', async () => {
    const r = await get();
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.payload).toBe(
      `[{"id":"sf-co-a-u1-1","user_id":"u1","company_id":"co-a","name":"co-a 1","filter_state":{"n":1},"created_at":"${ts(3)}"},`
      + `{"id":"sf-co-a-u1-2","user_id":"u1","company_id":"co-a","name":"co-a 2","filter_state":{"n":2},"created_at":"${ts(2)}"},`
      + `{"id":"sf-co-a-u1-0","user_id":"u1","company_id":"co-a","name":"co-a 0","filter_state":{"n":0},"created_at":"${ts(1)}"}]`,
    );
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(r.payload)));
  });

  it('exact cursor: filter {user_id, company_id}, projection {_id:0}, sort created_at -1, SERVER limit 50', async () => {
    await get();
    expect(state.finds).toEqual([{
      filter: { user_id: 'u1', company_id: 'co-a' }, projection: { _id: 0 }, promoteValues: false,
      sort: { created_at: -1 }, limit: 50,
    }]);
  });

  it('empty company → []', async () => {
    const r = await get(as('co-empty'));
    expect(r.statusCode).toBe(200);
    expect(r.payload).toBe('[]');
  });

  it('49 / 50 / 51 rows → 49 / 50 / 50 (newest first)', async () => {
    expect(await ids(as('co-49'))).toHaveLength(49);
    expect(await ids(as('co-50'))).toHaveLength(50);
    const r51 = await ids(as('co-51'));
    expect(r51).toHaveLength(50);
    expect(r51[0]).toBe('sf-co-51-u1-50');
    expect(r51).not.toContain('sf-co-51-u1-0');
  });

  it('60 tied rows → 50 with the limit sent to the server', async () => {
    expect(await ids(as('co-tie'))).toHaveLength(50);
    expect(state.finds.at(-1)?.limit).toBe(50);
  });

  it('isolation: other user rows never leak; unowned header → default company', async () => {
    expect(await ids(U1)).toEqual(['sf-co-a-u1-1', 'sf-co-a-u1-2', 'sf-co-a-u1-0']);
    expect(await ids(as('co-z'))).toEqual(['sf-co-a-u1-1', 'sf-co-a-u1-2', 'sf-co-a-u1-0']);
    expect(await ids({ authorization: 'Bearer tok-u2' })).toEqual(['sf-co-z-u2-0']);
    expect(await ids(as('co-a', 'tok-u2'))).toEqual(['sf-co-z-u2-0']);
  });

  it('owned alternate company via X-Company-Id', async () => {
    expect(await ids(as('co-49'))).toHaveLength(49);
    expect(state.finds.at(-1)?.filter).toEqual({ user_id: 'u1', company_id: 'co-49' });
  });

  it('query parameters are ignored (no 422/400 surface)', async () => {
    const base = (await get()).payload;
    for (const qs of ['?limit=5', '?company_id=co-49', '?x=1&x=2', '?', '?%zz=%C3']) {
      const r = await get(U1, qs);
      expect(r.statusCode, qs).toBe(200);
      expect(r.payload, qs).toBe(base);
    }
  });

  it('Python serialisation: whole doubles, int32/int64, -0.0, extra fields preserved', async () => {
    const r = await get(as('co-typed'));
    expect(r.payload).toContain('"filter_state":{"f":5.0,"i32":7,"i64":9007199254740993,"z":-0.0}');
    expect(r.payload).toContain('"extra":"kept"');
  });

  it('NaN in a document → 500 Internal Server Error text/plain', async () => {
    const r = await get(as('co-nan'));
    expect(r.statusCode).toBe(500);
    expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
    expect(r.payload).toBe('Internal Server Error');
  });

  it('401 before any company / filter read', async () => {
    for (const headers of [{}, { authorization: 'Bearer nope' }]) {
      const r = await get(headers);
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
    expect(state.finds).toEqual([]);
  });

  it('HEAD → 405 allow: GET before auth; trailing slash is not this route', async () => {
    for (const headers of [U1, {}]) {
      const r = await app.inject({ method: 'HEAD', url: P, headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-length']).toBe('31');
    }
    // Gate 9d: Starlette redirect_slashes → 307 to the slash-less path (verified live).
    const slash = await app.inject({ method: 'GET', url: `${P}/`, headers: U1 });
    expect(slash.statusCode).toBe(307);
    expect(slash.headers['location']).toBe(`http://localhost:80${P}`);
    expect(state.finds).toEqual([]);
  });

  it('parked Gate-4 POST writer is still registered on the same path (unchanged)', () => {
    expect(app.hasRoute({ method: 'POST', url: P })).toBe(true);
    expect(app.hasRoute({ method: 'GET', url: P })).toBe(true);
  });
});
