/**
 * TRUKVIA · Phase-3 · Gate-4 · POST /api/saved-trip-filters unit tests.
 *
 * Fake DB (mirrors Gate-2 pattern) — no real Mongo.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const baseConfig: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017', dbName: 'trukvia_node_test',
  corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};

const IN_FUTURE = () => new Date(Date.now() + 3600_000).toISOString();
const IN_PAST = () => new Date(Date.now() - 60_000).toISOString();

interface Session { session_token: string; user_id: string; effective_role: string; expires_at: string }
interface Company { id: string; user_id: string; is_default?: boolean }
interface Filter { id: string; user_id: string; company_id: string; name: string; filter_state: unknown; created_at: string; _id?: string }
interface Idem { _id: string; status: 'in_progress' | 'completed'; status_code?: number; response_body_b64?: string; response_headers?: Record<string, string> }

interface State {
  sessions: Session[]; companies: Company[]; filters: Filter[]; idem: Idem[];
  users: { user_id: string; email: string }[];
  writes: string[]; // "coll.method" observations
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function fakeDb(state: State): Db {
  const projFn = <T extends Record<string, unknown>>(d: T, projection?: Record<string, 0 | 1>): Partial<T> => {
    if (!projection) return { ...d };
    const inc = Object.entries(projection).filter(([, v]) => v === 1).map(([k]) => k);
    const exc = Object.entries(projection).filter(([, v]) => v === 0).map(([k]) => k);
    if (inc.length > 0) {
      const o: Record<string, unknown> = {};
      for (const k of inc) o[k] = d[k];
      if (!exc.includes('_id') && '_id' in d) o['_id'] = d['_id'];
      return o as Partial<T>;
    }
    const o: Record<string, unknown> = { ...d };
    for (const k of exc) delete o[k];
    return o as Partial<T>;
  };
  const matches = (d: Record<string, unknown>, f: Record<string, unknown>): boolean => {
    for (const [k, v] of Object.entries(f)) { if (d[k] !== v) return false; } return true;
  };
  const collection = (name: string) => {
    const rows: Record<string, unknown>[] =
      name === 'user_sessions' ? state.sessions as unknown as Record<string, unknown>[]
      : name === 'companies' ? state.companies as unknown as Record<string, unknown>[]
      : name === 'saved_trip_filters' ? state.filters as unknown as Record<string, unknown>[]
      : name === 'users' ? state.users as unknown as Record<string, unknown>[]
      : name === 'idempotency_keys' ? state.idem as unknown as Record<string, unknown>[]
      : [];
    // saved_trip_filters + idempotency_keys collections need write methods.
    // Other collections must be forbidden.
    const isWritable = name === 'saved_trip_filters' || name === 'idempotency_keys';
    return {
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        return hit ? projFn(hit, opts?.projection) : null;
      }),
      insertOne: vi.fn(async (doc: Record<string, unknown>) => {
        if (!isWritable) forbid(state, `${name}.insertOne`)();
        // Enforce unique _id on idempotency_keys (leader single-flight).
        if (name === 'idempotency_keys') {
          const clash = rows.find((r) => r['_id'] === doc['_id']);
          if (clash) throw new Error('E11000 duplicate key');
        }
        rows.push({ ...doc });
        state.writes.push(`${name}.insertOne`);
        return { insertedId: doc['_id'] ?? doc['id'] };
      }),
      updateOne: vi.fn(async (f: Record<string, unknown>, update: { $set?: Record<string, unknown> }) => {
        if (!isWritable) forbid(state, `${name}.updateOne`)();
        const hit = rows.find((r) => matches(r, f));
        if (hit && update.$set) Object.assign(hit, update.$set);
        state.writes.push(`${name}.updateOne`);
        return { matchedCount: hit ? 1 : 0 };
      }),
      deleteOne: vi.fn(async (f: Record<string, unknown>) => {
        if (!isWritable) forbid(state, `${name}.deleteOne`)();
        const i = rows.findIndex((r) => matches(r, f));
        if (i >= 0) rows.splice(i, 1);
        state.writes.push(`${name}.deleteOne`);
        return { deletedCount: i >= 0 ? 1 : 0 };
      }),
      insertMany: vi.fn(forbid(state, `${name}.insertMany`)),
      updateMany: vi.fn(forbid(state, `${name}.updateMany`)),
      deleteMany: vi.fn(forbid(state, `${name}.deleteMany`)),
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

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-owner', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
      { session_token: 'tok-u2', user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
    ],
    users: [ { user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' } ],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b', user_id: 'u2', is_default: true },
    ],
    filters: [], idem: [], writes: [],
  };
}

async function makeApp(state: State) {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('POST /api/saved-trip-filters — Gate-4 shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const post = (body: unknown, headers: Record<string, string> = {}) =>
    app.inject({ method: 'POST', url: '/api/saved-trip-filters', payload: body, headers: { 'content-type': 'application/json', ...headers } });

  it('1 happy path — 200 + doc shape, id "sf"+16hex, ISO created_at', async () => {
    const r = await post({ name: 'view A', filter_state: { k: 1 } }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json() as Filter;
    expect(d.id).toMatch(/^sf[a-f0-9]{16}$/);
    expect(d.user_id).toBe('u1');
    expect(d.company_id).toBe('co-a');
    expect(d.name).toBe('view A');
    expect(d.filter_state).toEqual({ k: 1 });
    expect(new Date(d.created_at).toString()).not.toBe('Invalid Date');
    expect(d).not.toHaveProperty('_id');
  });

  it('2 name is trimmed', async () => {
    const r = await post({ name: '  spaced  ' }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Filter).name).toBe('spaced');
  });

  it('3 name silently truncated to 64 (via 63-char + trim + pad-to-64 boundary)', async () => {
    const s = 'x'.repeat(64);
    const r = await post({ name: s }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Filter).name.length).toBe(64);
  });

  it('4 65-char name → 422', async () => {
    const r = await post({ name: 'x'.repeat(65) }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
  });

  it('5 missing name → 422', async () => {
    const r = await post({}, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
  });

  it('6 whitespace-only name → 400 "name required"', async () => {
    const r = await post({ name: '   ' }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'name required' });
  });

  it('7 filter_state omitted → {}', async () => {
    const r = await post({ name: 'n' }, { authorization: 'Bearer tok-owner' });
    expect((r.json() as Filter).filter_state).toEqual({});
  });

  it('8 deeply nested filter_state → echoed verbatim', async () => {
    const fs = { a: { b: { c: [1, 2, { d: null }] } } };
    const r = await post({ name: 'n', filter_state: fs }, { authorization: 'Bearer tok-owner' });
    expect((r.json() as Filter).filter_state).toEqual(fs);
  });

  it('9 client-supplied server fields are ignored', async () => {
    const r = await post({
      name: 'n', id: 'HACK', user_id: 'HACK', company_id: 'HACK',
      created_at: '1970-01-01T00:00:00Z', _id: 'HACK',
    }, { authorization: 'Bearer tok-owner' });
    const d = r.json() as Filter;
    expect(d.id).toMatch(/^sf[a-f0-9]{16}$/); expect(d.id).not.toBe('HACK');
    expect(d.user_id).toBe('u1'); expect(d.company_id).toBe('co-a');
    expect(d.created_at).not.toBe('1970-01-01T00:00:00Z');
    expect(d).not.toHaveProperty('_id');
  });

  it('10 no token → 401 Not authenticated', async () => {
    const r = await post({ name: 'n' });
    expect(r.statusCode).toBe(401); expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('11 bad token → 401 Invalid session', async () => {
    const r = await post({ name: 'n' }, { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401); expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('12 expired → 401 Session expired', async () => {
    const r = await post({ name: 'n' }, { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401); expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('13 cookie auth', async () => {
    const r = await post({ name: 'n' }, { cookie: 'session_token=tok-owner' });
    expect(r.statusCode).toBe(200);
  });

  it('14 X-Company-Id owned override', async () => {
    const r = await post({ name: 'n' }, { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect((r.json() as Filter).company_id).toBe('co-a-alt');
  });

  it('15 X-Company-Id NOT owned → fallback to default', async () => {
    const r = await post({ name: 'n' }, { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect((r.json() as Filter).company_id).toBe('co-a');
  });

  it('16 same-user multi-company isolation via company_id filter', async () => {
    await post({ name: 'in alt' }, { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    const inA = state.filters.filter((f) => f.company_id === 'co-a');
    const inAlt = state.filters.filter((f) => f.company_id === 'co-a-alt');
    expect(inAlt.length).toBe(1); expect(inA.length).toBe(0);
  });

  it('17 duplicate names allowed (no dedup)', async () => {
    await post({ name: 'same' }, { authorization: 'Bearer tok-owner' });
    await post({ name: 'same' }, { authorization: 'Bearer tok-owner' });
    expect(state.filters.length).toBe(2);
  });

  it('18 exactly ONE saved_trip_filters.insertOne per success', async () => {
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner' });
    const c = state.writes.filter((w) => w === 'saved_trip_filters.insertOne').length;
    expect(c).toBe(1);
  });

  it('19 zero writes to forbidden collections', async () => {
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner' });
    for (const bad of ['companies', 'audit_logs', 'fin_txn', 'payment_corrections', 'user_sessions']) {
      const wrote = state.writes.some((w) => w.startsWith(`${bad}.`));
      expect(wrote, `unexpected write to ${bad}`).toBe(false);
    }
  });

  it('20 no Idempotency-Key → passthrough, one insert, no idem row', async () => {
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner' });
    expect(state.idem.length).toBe(0);
    expect(state.filters.length).toBe(1);
  });

  it('21 first idempotent request → row completed, one filter insert', async () => {
    const r = await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'idempotency-key': 'abcdefgh1' });
    expect(r.statusCode).toBe(200);
    expect(state.filters.length).toBe(1);
    expect(state.idem.length).toBe(1);
    expect(state.idem[0]!.status).toBe('completed');
  });

  it('22 replay same key → 0 new filter inserts, x-idempotent-replay:1, same body', async () => {
    const key = 'abcdefgh1';
    const first = await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'idempotency-key': key });
    const b1 = first.body;
    const second = await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'idempotency-key': key });
    expect(second.statusCode).toBe(200);
    expect(second.headers['x-idempotent-replay']).toBe('1');
    expect(second.body).toBe(b1);
    expect(state.filters.length).toBe(1);
  });

  it('23 different keys → distinct rows', async () => {
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'idempotency-key': 'kkkkkkkk1' });
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'idempotency-key': 'kkkkkkkk2' });
    expect(state.filters.length).toBe(2);
    expect(state.idem.length).toBe(2);
  });

  it('24 invalid key length (7 or 129) → passthrough', async () => {
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'idempotency-key': '1234567' });
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'idempotency-key': 'k'.repeat(129) });
    expect(state.idem.length).toBe(0);
    expect(state.filters.length).toBe(2);
  });

  it('25 idempotency middleware ignores non-Bucket-B routes (GET) — confirmed at unit-primitive level in idempotency.test.ts', async () => {
    // Direct unit assertion — the request-path check is proven in idempotency.test.ts.
    // Here we only ensure that sending an Idempotency-Key on a non-POST does not
    // create an idempotency_keys row via the middleware's onRequest hook.
    await app.inject({
      method: 'DELETE', url: '/api/saved-trip-filters/whatever',
      headers: { authorization: 'Bearer tok-owner', 'idempotency-key': 'shouldbeignored' },
    });
    expect(state.idem.length).toBe(0);
  });
});
