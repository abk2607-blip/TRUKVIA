/**
 * TRUKVIA · Phase-3 · Gate-7x · AI chat sessions list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/ai/sessions
 *
 * Fake-DB write-forbid pattern inlined. The fake `find` records the exact
 * cursor shape and asserts NO server-side limit is requested (Motor
 * `to_list(50)` sends an unlimited find); the handler must stop at 50 while
 * iterating. Live tie order is proven by the parity harness.
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

type Row = Record<string, unknown>;
interface FindCall {
  filter: Row; projection?: Row; promoteValues?: boolean; sort?: Row; limit?: number;
  yielded: number; closed: boolean;
}
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; chats: Row[];
  writes: string[]; finds: FindCall[];
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
    : name === 'chat_sessions' ? state.chats
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      findOne: vi.fn(async (f: Row, opts?: { projection?: Row }) => {
        const hit = rows.find((r) => matches(r, f));
        return hit ? project(hit, opts?.projection) : null;
      }),
      find: vi.fn((f: Row, opts?: { projection?: Row; promoteValues?: boolean }) => {
        if (name !== 'chat_sessions') throw new Error(`unexpected find on ${name}`);
        const call: FindCall = { filter: f, projection: opts?.projection, promoteValues: opts?.promoteValues,
          yielded: 0, closed: false };
        state.finds.push(call);
        const cursor = {
          sort: (s: Row) => { call.sort = s; return cursor; },
          limit: (n: number) => { call.limit = n; return cursor; },
          close: async () => { call.closed = true; },
          async *[Symbol.asyncIterator]() {
            const hit = rows.filter((r) => matches(r, f)).map((r) => project(r, call.projection));
            hit.sort((a, b) => String(b['created_at'] ?? '').localeCompare(String(a['created_at'] ?? '')));
            for (const h of call.limit === undefined ? hit : hit.slice(0, call.limit)) {
              call.yielded++;
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

const ts = (i: number): string => new Date(Date.UTC(2026, 4, 1, 0, i)).toISOString().replace('Z', '+00:00');

function cs(n: number, uid: string, cid: string, created_at: unknown, extra: Row = {}): Row {
  return { _id: `oid-${cid}-${uid}-${n}`, id: `chat_${cid}_${uid}_${n}`, title: `${cid} ${n}`, created_at,
    user_id: uid, company_id: cid, ...extra };
}

function makeState(): State {
  const chats: Row[] = [];
  for (let n = 0; n < 49; n++) chats.push(cs(n, 'u1', 'co-49', ts(n)));
  for (let n = 0; n < 50; n++) chats.push(cs(n, 'u1', 'co-50', ts(n)));
  for (let n = 0; n < 51; n++) chats.push(cs(n, 'u1', 'co-51', ts(n)));
  for (let n = 0; n < 70; n++) chats.push(cs(n, 'u1', 'co-tie', ts(0)));
  chats.push(cs(0, 'u1', 'co-a', ts(1)), cs(1, 'u1', 'co-a', ts(3)), cs(2, 'u1', 'co-a', ts(2)));
  chats.push(cs(0, 'u2', 'co-a', ts(9)), cs(0, 'u2', 'co-z', ts(1)));
  chats.push(cs(0, 'u1', 'co-typed', ts(1), {
    f: new Double(5), i32: new Int32(7), i64: Long.fromString('9007199254740993'), z: new Double(-0), nil: null,
  }));
  chats.push({ _id: 'oid-min', id: 'chat_min', user_id: 'u1', company_id: 'co-typed' });
  chats.push(cs(0, 'u1', 'co-nan', ts(1), { x: new Double(NaN) }));
  chats.push(cs(0, 'u1', 'co-oid', ts(1), { ref: new ObjectId('65a000000000000000000001') }));
  return {
    sessions: [
      { session_token: 'tok-u1', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2', user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
    ],
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      ...['co-49', 'co-50', 'co-51', 'co-tie', 'co-empty', 'co-typed', 'co-nan', 'co-oid']
        .map((id) => ({ id, user_id: 'u1', is_default: false })),
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    chats, writes: [], finds: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const P = '/api/ai/sessions';
const U1 = { authorization: 'Bearer tok-u1' };
const as = (cid: string, tok = 'tok-u1'): Record<string, string> => ({ authorization: `Bearer ${tok}`, 'x-company-id': cid });

describe('Gate-7x · AI chat sessions list read-only shadow', () => {
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

  it('normal result: default company, created_at DESC, user_id dropped, exact bytes / content-type', async () => {
    const r = await get();
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.payload).toBe(
      `[{"id":"chat_co-a_u1_1","title":"co-a 1","created_at":"${ts(3)}","company_id":"co-a"},`
      + `{"id":"chat_co-a_u1_2","title":"co-a 2","created_at":"${ts(2)}","company_id":"co-a"},`
      + `{"id":"chat_co-a_u1_0","title":"co-a 0","created_at":"${ts(1)}","company_id":"co-a"}]`,
    );
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(r.payload)));
  });

  it('exact cursor: filter, projection {_id:0,user_id:0}, sort created_at -1, NO server limit', async () => {
    await get();
    expect(state.finds).toHaveLength(1);
    const f = state.finds[0] as FindCall;
    expect(f.filter).toEqual({ user_id: 'u1', company_id: 'co-a' });
    expect(f.projection).toEqual({ _id: 0, user_id: 0 });
    expect(f.promoteValues).toBe(false);
    expect(f.sort).toEqual({ created_at: -1 });
    expect(f.limit).toBeUndefined();
  });

  it('empty company → []', async () => {
    const r = await get(as('co-empty'));
    expect(r.statusCode).toBe(200);
    expect(r.payload).toBe('[]');
  });

  it('49 / 50 / 51 rows → 49 / 50 / 50, newest first; iteration stops at 50 and the cursor is closed', async () => {
    expect(await ids(as('co-49'))).toHaveLength(49);
    expect(await ids(as('co-50'))).toHaveLength(50);
    const r51 = await ids(as('co-51'));
    expect(r51).toHaveLength(50);
    expect(r51[0]).toBe('chat_co-51_u1_50');
    expect(r51).not.toContain('chat_co-51_u1_0');
    const last = state.finds.at(-1) as FindCall;
    expect(last.yielded).toBe(50);
    expect(last.closed).toBe(true);
  });

  it('70 tied rows → first 50 of the unlimited sorted cursor (exact selection and order)', async () => {
    const got = await ids(as('co-tie'));
    expect(got).toEqual(Array.from({ length: 50 }, (_, n) => `chat_co-tie_u1_${n}`));
    expect(state.finds.at(-1)?.limit).toBeUndefined();
  });

  it('isolation: other user rows never leak; unowned header → default company', async () => {
    const own = ['chat_co-a_u1_1', 'chat_co-a_u1_2', 'chat_co-a_u1_0'];
    expect(await ids(U1)).toEqual(own);
    expect(await ids(as('co-z'))).toEqual(own);
    expect(await ids(as(''))).toEqual(own);
    expect(await ids({ authorization: 'Bearer tok-u2' })).toEqual(['chat_co-z_u2_0']);
    expect(await ids(as('co-a', 'tok-u2'))).toEqual(['chat_co-z_u2_0']);
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

  it('Python serialisation and field presence: whole doubles, int32/int64, -0.0, null kept, missing stays missing', async () => {
    const r = await get(as('co-typed'));
    expect(r.payload).toBe(
      `[{"id":"chat_co-typed_u1_0","title":"co-typed 0","created_at":"${ts(1)}","company_id":"co-typed",`
      + '"f":5.0,"i32":7,"i64":9007199254740993,"z":-0.0,"nil":null},'
      + '{"id":"chat_min","company_id":"co-typed"}]',
    );
  });

  it('NaN / ObjectId in a document → 500 Internal Server Error text/plain', async () => {
    for (const cid of ['co-nan', 'co-oid']) {
      const r = await get(as(cid));
      expect(r.statusCode, cid).toBe(500);
      expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
      expect(r.payload).toBe('Internal Server Error');
    }
  });

  it('401 before any company / session read', async () => {
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

  it('only GET (+ explicit HEAD) is registered on the path — no writer', () => {
    expect(app.hasRoute({ method: 'GET', url: P })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: P })).toBe(false);
  });
});
