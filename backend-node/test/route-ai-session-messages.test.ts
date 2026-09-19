/**
 * TRUKVIA · Phase-3 · Gate-8a · AI chat session messages read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/ai/sessions/{sid}/messages
 *
 * Fake-DB write-forbid pattern inlined. Two distinct reads, in order:
 *   READ #1 chat_sessions.findOne({id, user_id, company_id}, {_id:0})
 *   READ #2 chat_messages.find({session_id}, {_id:0}).sort({created_at:1}) — NO
 *           user/company filter (Python contract copied), NO server limit,
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
const SESSION_NOT_FOUND = '{"detail":"Chat session not found"}';

type Row = Record<string, unknown>;
interface Op { coll: string; kind: 'findOne' | 'find'; filter: Row; projection?: Row; sort?: Row; limit?: number;
  yielded?: number; closed?: boolean }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; chats: Row[]; msgs: Row[];
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
    : name === 'chat_sessions' ? state.chats
    : name === 'chat_messages' ? state.msgs
    : [];
  const route = (name: string): boolean => name === 'chat_sessions' || name === 'chat_messages';
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      findOne: vi.fn(async (f: Row, opts?: { projection?: Row }) => {
        if (route(name)) state.ops.push({ coll: name, kind: 'findOne', filter: f, projection: opts?.projection });
        const hit = rows.find((r) => matches(r, f));
        return hit ? project(hit, opts?.projection) : null;
      }),
      find: vi.fn((f: Row, opts?: { projection?: Row }) => {
        if (name !== 'chat_messages') throw new Error(`unexpected find on ${name}`);
        const op: Op = { coll: name, kind: 'find', filter: f, projection: opts?.projection, yielded: 0, closed: false };
        state.ops.push(op);
        const cursor = {
          sort: (s: Row) => { op.sort = s; return cursor; },
          limit: (n: number) => { op.limit = n; return cursor; },
          close: async () => { op.closed = true; },
          async *[Symbol.asyncIterator]() {
            const hit = rows.filter((r) => matches(r, f)).map((r) => project(r, op.projection));
            hit.sort((a, b) => String(a['created_at'] ?? '').localeCompare(String(b['created_at'] ?? '')));
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
const sess = (id: string, uid: string, cid: string): Row =>
  ({ _id: `oid-${id}-${uid}`, id, title: `chat ${id}`, created_at: ts(0), user_id: uid, company_id: cid });
const msg = (sid: string, n: number, created_at: unknown, uid = 'u1', cid = 'co-a', extra: Row = {}): Row => ({
  _id: `oid-${sid}-${uid}-${n}`, id: `m-${sid}-${uid}-${n}`, session_id: sid, role: n % 2 ? 'assistant' : 'user',
  content: `m${n}`, created_at, user_id: uid, company_id: cid, ...extra,
});

function makeState(): State {
  const msgs: Row[] = [
    msg('s1', 1, ts(2)), msg('s1', 0, ts(1)), msg('s1', 2, ts(3)),
    msg('s1', 90, ts(4), 'u2', 'co-z'),                 // same sid, other user — Python returns it
    msg('s1', 91, ts(5), 'u1', 'co-b'),                 // same sid, other company — Python returns it
    { _id: 'oid-orphan', session_id: 's1', content: 'orphan', created_at: ts(6) },
    msg('s-b', 0, ts(1), 'u1', 'co-b'),
    msg('s-u2', 0, ts(1), 'u2', 'co-z'),
    msg('s-nosession', 0, ts(1)),
    msg('s-ser', 0, ts(1), 'u1', 'co-a', {
      score: new Double(5), n: new Int32(7), big: Long.fromString('9007199254740993'), z: new Double(-0), nil: null,
    }),
    msg('s-nan', 0, ts(1), 'u1', 'co-a', { score: new Double(NaN) }),
    msg('s-oid', 0, ts(1), 'u1', 'co-a', { ref: new ObjectId('65a000000000000000000001') }),
    msg('s-dec', 0, ts(1), 'u1', 'co-a', { amt: Decimal128.fromString('12.50') }),
  ];
  for (let n = 0; n < 600; n++) msgs.push(msg('s-big', n, ts(n)));
  for (let n = 0; n < 60; n++) msgs.push(msg('s-tie', n, ts(0)));
  return {
    sessions: ['u1', 'u2'].map((u) => ({ session_token: `tok-${u}`, user_id: u, effective_role: 'owner', expires_at: IN_FUTURE() })),
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false },
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    chats: [
      sess('s1', 'u1', 'co-a'), sess('s-empty', 'u1', 'co-a'), sess('s-b', 'u1', 'co-b'), sess('s-u2', 'u2', 'co-z'),
      sess('s-big', 'u1', 'co-a'), sess('s-tie', 'u1', 'co-a'), sess('s-ser', 'u1', 'co-a'),
      sess('s-nan', 'u1', 'co-a'), sess('s-oid', 'u1', 'co-a'), sess('s-dec', 'u1', 'co-a'), sess('sé', 'u1', 'co-a'),
    ],
    msgs, writes: [], ops: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const url = (sid: string, qs = ''): string => `/api/ai/sessions/${sid}/messages${qs}`;
const as = (u: string, cid?: string): Record<string, string> =>
  cid === undefined ? { authorization: `Bearer tok-${u}` } : { authorization: `Bearer tok-${u}`, 'x-company-id': cid };

describe('Gate-8a · AI chat session messages read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = as('u1')): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });
  const ids = async (u: string, headers?: Record<string, string>): Promise<unknown[]> =>
    (JSON.parse((await get(u, headers)).payload) as Row[]).map((r) => r['id'] ?? null);

  it('A/Q/R/S owned session: created_at ASC, exact bytes / status / content-type', async () => {
    const r = await get(url('s-b'), as('u1', 'co-b'));
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.payload).toBe(
      `[{"id":"m-s-b-u1-0","session_id":"s-b","role":"user","content":"m0","created_at":"${ts(1)}",`
      + '"user_id":"u1","company_id":"co-b"}]',
    );
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(r.payload)));
  });

  it('I/J exact two reads in order: READ #1 user+company scoped, READ #2 session_id ONLY, no limit', async () => {
    await get(url('s1'));
    expect(state.ops.map((o) => [o.coll, o.kind])).toEqual([['chat_sessions', 'findOne'], ['chat_messages', 'find']]);
    const [r1, r2] = state.ops as [Op, Op];
    expect(r1.filter).toEqual({ id: 's1', user_id: 'u1', company_id: 'co-a' });
    expect(r1.projection).toEqual({ _id: 0 });
    expect(r2.filter).toEqual({ session_id: 's1' });
    expect(r2.projection).toEqual({ _id: 0 });
    expect(r2.sort).toEqual({ created_at: 1 });
    expect(r2.limit).toBeUndefined();
    expect(r2.closed).toBe(true);
  });

  it('C/G/H multiple messages incl. same-sid other user / other company / orphan (Python exposure copied)', async () => {
    expect(await ids(url('s1'))).toEqual(['m-s1-u1-0', 'm-s1-u1-1', 'm-s1-u1-2', 'm-s1-u2-90', 'm-s1-u1-91', null]);
  });

  it('B zero messages → []', async () => {
    const r = await get(url('s-empty'));
    expect(r.statusCode).toBe(200);
    expect(r.payload).toBe('[]');
  });

  it('D/E/F 404 Chat session not found: nonexistent, another user, another company, messages without session', async () => {
    for (const [u, h] of [[url('nope'), as('u1')], [url('s-u2'), as('u1')], [url('s-b'), as('u1')],
      [url('s1'), as('u1', 'co-b')], [url('s-nosession'), as('u1')], [url('s1'), as('u2')], [url('s1'), as('u2', 'co-a')]] as const) {
      const r = await get(u, h);
      expect(r.statusCode, u).toBe(404);
      expect(r.headers['content-type']).toBe('application/json');
      expect(r.payload).toBe(SESSION_NOT_FOUND);
    }
    expect(state.ops.filter((o) => o.coll === 'chat_messages')).toEqual([]);
  });

  it('M company header: owned alternate; unowned / unknown / empty → default', async () => {
    expect(await ids(url('s-b'), as('u1', 'co-b'))).toEqual(['m-s-b-u1-0']);
    for (const cid of ['co-z', 'co-nope', '']) expect((await ids(url('s1'), as('u1', cid))).length, cid).toBe(6);
    expect(await ids(url('s-u2'), as('u2'))).toEqual(['m-s-u2-u2-0']);
  });

  it('K 600 messages → first 500 of the unlimited sorted cursor; 60 ties → all 60', async () => {
    const big = await ids(url('s-big'));
    expect(big).toHaveLength(500);
    expect(big[0]).toBe('m-s-big-u1-0');
    expect(big[499]).toBe('m-s-big-u1-499');
    expect(state.ops.at(-1)?.yielded).toBe(500);
    expect(await ids(url('s-tie'))).toHaveLength(60);
  });

  it('T serialisation: whole doubles, int32/int64, -0.0, null kept', async () => {
    const r = await get(url('s-ser'));
    expect(r.payload).toContain('"score":5.0,"n":7,"big":9007199254740993,"z":-0.0,"nil":null}]');
  });

  it('T NaN / ObjectId / Decimal128 in a message → 500 Internal Server Error text/plain', async () => {
    for (const sid of ['s-nan', 's-oid', 's-dec']) {
      const r = await get(url(sid));
      expect(r.statusCode, sid).toBe(500);
      expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
      expect(r.payload).toBe('Internal Server Error');
    }
  });

  it('L 401 before any route read', async () => {
    for (const headers of [{}, { authorization: 'Bearer nope' }]) {
      const r = await get(url('s1'), headers);
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
    expect(state.ops).toEqual([]);
  });

  it('O path: encoded Unicode sid decoded; empty / encoded-slash sid → 404 Not Found before auth; query ignored', async () => {
    expect((await get(url('s%C3%A9'))).statusCode).toBe(200);
    for (const sid of ['', 'a%2Fb']) {
      const r = await get(url(sid), {});
      expect(r.statusCode, sid).toBe(404);
      expect(r.payload).toBe('{"detail":"Not Found"}');
    }
    expect((await get(url('s1', '?x=1&x=2&limit=5'))).payload).toBe((await get(url('s1'))).payload);
  });

  it('P HEAD → 405 allow: GET before auth; trailing slash is not this route', async () => {
    for (const headers of [as('u1'), {}]) {
      const r = await app.inject({ method: 'HEAD', url: url('s1'), headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-length']).toBe('31');
    }
    // Gate 9d: Starlette redirect_slashes → 307 to the slash-less path (verified live).
    const slash = await get(`${url('s1')}/`);
    expect(slash.statusCode).toBe(307);
    expect(slash.headers['location']).toBe(`http://localhost:80${url('s1')}`);
    expect(state.ops).toEqual([]);
  });

  it('U only GET (+ explicit HEAD) registered — no writer; 7x list route untouched', () => {
    const p = '/api/ai/sessions/:sid/messages';
    expect(app.hasRoute({ method: 'GET', url: p })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: p })).toBe(false);
    expect(app.hasRoute({ method: 'GET', url: '/api/ai/sessions' })).toBe(true);
    expect(app.hasRoute({ method: 'POST', url: '/api/ai/chat' })).toBe(false);
  });
});
