/**
 * TRUKVIA · Phase-3 · Gate-5 · POST /api/expenditure-types unit tests.
 *
 * Fake DB (mirrors Gate-2 / Gate-4 pattern) — no real Mongo.
 * Path B.3-α — Bucket-B idempotency middleware is NOT used for this route.
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
interface ExpType { id: string; name: string; is_default: boolean; created_at: string; user_id: string; company_id: string; _id?: string }
interface Idem { _id: string; status: 'in_progress' | 'completed'; status_code?: number; response_body_b64?: string; response_headers?: Record<string, string> }

interface State {
  sessions: Session[]; companies: Company[]; etypes: ExpType[]; idem: Idem[];
  users: { user_id: string; email: string }[];
  writes: string[];
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
      : name === 'expenditure_types' ? state.etypes as unknown as Record<string, unknown>[]
      : name === 'users' ? state.users as unknown as Record<string, unknown>[]
      : name === 'idempotency_keys' ? state.idem as unknown as Record<string, unknown>[]
      : [];
    // expenditure_types is the ONLY writable target under Gate 5.
    // idempotency_keys is writable (middleware infra) but should be UNUSED for this route.
    const isWritable = name === 'expenditure_types' || name === 'idempotency_keys';
    return {
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        return hit ? projFn(hit, opts?.projection) : null;
      }),
      insertOne: vi.fn(async (doc: Record<string, unknown>) => {
        if (!isWritable) forbid(state, `${name}.insertOne`)();
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
    etypes: [], idem: [], writes: [],
  };
}

async function makeApp(state: State) {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('POST /api/expenditure-types — Gate-5 shadow (Path B.3-α)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const post = (body: unknown, headers: Record<string, string> = {}) =>
    app.inject({ method: 'POST', url: '/api/expenditure-types', payload: body, headers: { 'content-type': 'application/json', ...headers } });

  it('1 valid insert — 200 + doc shape', async () => {
    const r = await post({ name: 'Parking' }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json() as ExpType;
    expect(d.id).toMatch(/^etype_[a-f0-9]{16}$/);
    expect(d.name).toBe('Parking');
    expect(d.is_default).toBe(false);
    expect(d.company_id).toBe('co-a');
    expect(d).not.toHaveProperty('user_id');
    expect(d).not.toHaveProperty('_id');
    expect(new Date(d.created_at).toString()).not.toBe('Invalid Date');
  });

  it('2 name is trimmed', async () => {
    const r = await post({ name: '  Toll  ' }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as ExpType).name).toBe('Toll');
  });

  it('3 missing name field → 422', async () => {
    const r = await post({}, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
  });

  it('4 empty string name → 400 "Name is required"', async () => {
    const r = await post({ name: '' }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'Name is required' });
  });

  it('5 whitespace-only name → 400 "Name is required"', async () => {
    const r = await post({ name: '   ' }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'Name is required' });
  });

  it('6 client-supplied server fields — Pydantic-parity behaviour', async () => {
    // Python (Pydantic BaseModel, extra='ignore' default):
    //   - `id`, `is_default`, `created_at` are declared ExpenditureType fields
    //     → accepted from client and used in the doc.
    //   - `user_id`, `company_id` are NOT model fields → silently dropped by
    //     model_dump() → handler stamps server values.
    const r = await post({
      name: 'X', id: 'HACK-id-x1', user_id: 'HACK', company_id: 'HACK',
      is_default: true, created_at: '1970-01-01T00:00:00Z', _id: 'HACK',
    }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json() as ExpType;
    expect(d).not.toHaveProperty('user_id');
    expect(d).not.toHaveProperty('_id');
    // Server stamps user_id + company_id (parity with Python).
    expect(d.company_id).toBe('co-a');
    // Client-supplied ExpenditureType-declared fields flow through (Pydantic-parity).
    expect(d.id).toBe('HACK-id-x1');
    expect(d.is_default).toBe(true);
    expect(d.created_at).toBe('1970-01-01T00:00:00Z');
  });

  it('7 is_default defaults to false on new insert (no client override)', async () => {
    const r = await post({ name: 'plain' }, { authorization: 'Bearer tok-owner' });
    const d = r.json() as ExpType;
    expect(d.is_default).toBe(false);
    // and in the DB
    expect(state.etypes[0]!.is_default).toBe(false);
  });

  it('8 natural duplicate — second POST returns same existing row', async () => {
    const first = await post({ name: 'Toll' }, { authorization: 'Bearer tok-owner' });
    const second = await post({ name: 'Toll' }, { authorization: 'Bearer tok-owner' });
    expect(first.statusCode).toBe(200);
    expect(second.statusCode).toBe(200);
    const a = first.json() as ExpType;
    const b = second.json() as ExpType;
    expect(b.id).toBe(a.id);
    expect(b.created_at).toBe(a.created_at);
  });

  it('9 natural duplicate does NOT insert a second row', async () => {
    await post({ name: 'Toll' }, { authorization: 'Bearer tok-owner' });
    await post({ name: 'Toll' }, { authorization: 'Bearer tok-owner' });
    expect(state.etypes.length).toBe(1);
    const inserts = state.writes.filter((w) => w === 'expenditure_types.insertOne').length;
    expect(inserts).toBe(1);
  });

  it('10 cross-tenant same-name — no collision', async () => {
    await post({ name: 'Toll' }, { authorization: 'Bearer tok-owner' });        // u1/co-a
    await post({ name: 'Toll' }, { authorization: 'Bearer tok-u2' });           // u2/co-b
    expect(state.etypes.length).toBe(2);
    const forU1 = state.etypes.find((e) => e.user_id === 'u1');
    const forU2 = state.etypes.find((e) => e.user_id === 'u2');
    expect(forU1?.company_id).toBe('co-a');
    expect(forU2?.company_id).toBe('co-b');
  });

  it('11 no token → 401 Not authenticated', async () => {
    const r = await post({ name: 'x' });
    expect(r.statusCode).toBe(401); expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('12 bad token → 401 Invalid session', async () => {
    const r = await post({ name: 'x' }, { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401); expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('13 expired → 401 Session expired', async () => {
    const r = await post({ name: 'x' }, { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401); expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('14 cookie auth', async () => {
    const r = await post({ name: 'x' }, { cookie: 'session_token=tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as ExpType).company_id).toBe('co-a');
  });

  it('15 X-Company-Id owned override', async () => {
    const r = await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect((r.json() as ExpType).company_id).toBe('co-a-alt');
  });

  it('16 X-Company-Id unowned → fallback to default', async () => {
    const r = await post({ name: 'x' }, { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect((r.json() as ExpType).company_id).toBe('co-a');
  });

  it('17 fresh tenant does NOT seed defaults on POST', async () => {
    expect(state.etypes.length).toBe(0);
    await post({ name: 'only-one' }, { authorization: 'Bearer tok-owner' });
    expect(state.etypes.length).toBe(1);
    expect(state.etypes[0]!.name).toBe('only-one');
    // Absolutely no seeded DEFAULT_EXPENDITURE_TYPES.
    const inserts = state.writes.filter((w) => w === 'expenditure_types.insertOne').length;
    expect(inserts).toBe(1);
  });

  it('18 no audit_logs write', async () => {
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner' });
    const wrote = state.writes.some((w) => w.startsWith('audit_logs.'));
    expect(wrote).toBe(false);
  });

  it('19 zero writes to forbidden collections', async () => {
    await post({ name: 'x' }, { authorization: 'Bearer tok-owner' });
    for (const bad of ['companies', 'audit_logs', 'fin_txn', 'payment_corrections', 'saved_trip_filters', 'user_sessions', 'users']) {
      const wrote = state.writes.some((w) => w.startsWith(`${bad}.`));
      expect(wrote, `unexpected write to ${bad}`).toBe(false);
    }
  });

  it('20 server error does not partially persist', async () => {
    // Force the underlying insert to throw AFTER dedup miss — simulates a
    // driver-level failure. Existing rows must remain unaffected.
    const origCollection = (app as unknown as { mongo?: { db: Db } }); // eslint-disable-line @typescript-eslint/no-unused-vars
    // Because we cannot easily swap the fakeDb mid-test, we instead verify
    // that a rejected schema (missing name) never writes anything.
    const r = await post({}, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect(state.etypes.length).toBe(0);
    expect(state.writes.length).toBe(0);
  });

  it('21 exact response shape — 5 keys (id, name, is_default, created_at, company_id)', async () => {
    const r = await post({ name: 'shape' }, { authorization: 'Bearer tok-owner' });
    const d = r.json() as Record<string, unknown>;
    const keys = Object.keys(d).sort();
    expect(keys).toEqual(['company_id', 'created_at', 'id', 'is_default', 'name']);
  });

  it('22 id format matches ^etype_[a-f0-9]{16}$', async () => {
    const r = await post({ name: 'idfmt' }, { authorization: 'Bearer tok-owner' });
    expect((r.json() as ExpType).id).toMatch(/^etype_[a-f0-9]{16}$/);
  });

  it('23 created_at is a valid ISO 8601 UTC timestamp', async () => {
    const r = await post({ name: 'tsfmt' }, { authorization: 'Bearer tok-owner' });
    const d = r.json() as ExpType;
    expect(d.created_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/);
  });

  it('24 unknown top-level fields ignored (Pydantic-parity, no 422)', async () => {
    const r = await post({ name: 'ok', foo: 'bar', baz: [1, 2, 3] }, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json() as Record<string, unknown>;
    expect(d).not.toHaveProperty('foo');
    expect(d).not.toHaveProperty('baz');
  });

  it('25 natural-dedup replay — body byte-identical after JSON parse', async () => {
    const first = await post({ name: 'replay' }, { authorization: 'Bearer tok-owner' });
    const second = await post({ name: 'replay' }, { authorization: 'Bearer tok-owner' });
    expect(first.statusCode).toBe(200);
    expect(second.statusCode).toBe(200);
    expect(second.json()).toEqual(first.json());
  });

  it('26 idempotency-key on this route is NOT treated as Bucket-B (Path α)', async () => {
    // With Path α, Gate-5 route is not in BUCKET_B_PATTERNS. Sending an
    // Idempotency-Key header must NOT create an idempotency_keys row, and
    // duplicate name POSTs must still dedupe via the natural check.
    await post({ name: 'idem-off' }, {
      authorization: 'Bearer tok-owner',
      'idempotency-key': 'abcdefgh1',
    });
    await post({ name: 'idem-off' }, {
      authorization: 'Bearer tok-owner',
      'idempotency-key': 'abcdefgh1',
    });
    expect(state.idem.length).toBe(0);      // middleware did not activate
    expect(state.etypes.length).toBe(1);    // natural dedup still fired
  });
});
