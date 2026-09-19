/**
 * TRUKVIA · Phase-3 · Gate-7d · PolicyChanges list read-only shadow — Vitest.
 *
 *   GET /api/policy-changes
 *
 * NEW parity axes exercised: Pydantic int_parsing 422 envelope, server
 * clamp 1..200, wrapped {items,total} response, projection retains
 * user_id, sort by created_at DESC.
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

const IN_FUTURE = (): string => new Date(Date.now() + 3600_000).toISOString();
const IN_PAST = (): string => new Date(Date.now() - 60_000).toISOString();

interface State {
  sessions: Record<string, unknown>[];
  users: Record<string, unknown>[];
  companies: Record<string, unknown>[];
  policy_change_events: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x) && !(x instanceof Date);
}

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isPlainObject(v)) {
      // No $ne/$gte/$lte used by Gate 7d — plain equality only.
      return false;
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(d: Record<string, unknown>, projection?: Record<string, 0 | 1>): Record<string, unknown> {
  if (!projection) return { ...d };
  const inc = Object.entries(projection).filter(([, v]) => v === 1).map(([k]) => k);
  const exc = Object.entries(projection).filter(([, v]) => v === 0).map(([k]) => k);
  if (inc.length > 0) {
    const o: Record<string, unknown> = {};
    for (const k of inc) if (k in d) o[k] = d[k];
    return o;
  }
  const o: Record<string, unknown> = { ...d };
  for (const k of exc) delete o[k];
  return o;
}

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Record<string, unknown>[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'policy_change_events' ? state.policy_change_events
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    function makeCursor(f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }): {
      sort: (s: [string, 1 | -1][]) => ReturnType<typeof makeCursor>;
      skip: (n: number) => ReturnType<typeof makeCursor>;
      limit: (n: number) => ReturnType<typeof makeCursor>;
      toArray: () => Promise<Record<string, unknown>[]>;
    } {
      let hits = rows.filter((r) => matches(r, f));
      const cursor = {
        sort(spec: [string, 1 | -1][]) {
          hits = hits.slice().sort((a, b) => {
            for (const [k, d] of spec) {
              const av = a[k]; const bv = b[k];
              if (av === bv) continue;
              if (av === undefined) return 1 * d;
              if (bv === undefined) return -1 * d;
              return ((av as string | number) < (bv as string | number) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
        skip(n: number) { hits = hits.slice(n); return cursor; },
        // Gate 9e: routes read Motor-style (async iteration, no server-side limit).
        async *[Symbol.asyncIterator]() { yield* await cursor.toArray(); },
        hasNext: (): Promise<boolean> => cursor.toArray().then((a) => a.length > 0),
        close: (): Promise<void> => Promise.resolve(),
        limit(n: number) { hits = hits.slice(0, Math.max(0, n)); return cursor; },
        async toArray(): Promise<Record<string, unknown>[]> {
          return hits.map((d) => project(d, opts?.projection));
        },
      };
      return cursor;
    }
    return {
      find: vi.fn((f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => makeCursor(f, opts)),
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        return hit ? project(hit, opts?.projection) : null;
      }),
      countDocuments: vi.fn(async (f: Record<string, unknown>) => rows.filter((r) => matches(r, f)).length),
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

// Distinct timestamps to avoid tie-order ambiguity (Python/Mongo do not
// guarantee stable single-key tie order).
const T1 = '2026-05-04T10:00:00+00:00';
const T2 = '2026-05-03T10:00:00+00:00';
const T3 = '2026-05-02T10:00:00+00:00';
const T4 = '2026-05-01T10:00:00+00:00';

function pce(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'pce-x', user_id: 'u1', company_id: 'co-a',
    customer_id: 'cust-1', old_policy: {}, new_policy: {},
    status: 'applied', created_by: 'u1', created_at: T1,
    reason: 'annual review',
    ...overrides,
  };
}

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-u1',      user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
    ],
    users: [
      { user_id: 'u1', email: 'u1@x' },
      { user_id: 'u2', email: 'u2@x' },
    ],
    companies: [
      { id: 'co-a',     user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b',     user_id: 'u2', is_default: true },
    ],
    policy_change_events: [
      pce({ id: 'e1', customer_id: 'cust-1', created_at: T1 }),
      pce({ id: 'e2', customer_id: 'cust-2', created_at: T2 }),
      pce({ id: 'e3', customer_id: 'cust-1', created_at: T3 }),
      pce({ id: 'e4', customer_id: 'cust-3', created_at: T4 }),
      pce({ id: 'e-alt', customer_id: 'cust-1', company_id: 'co-a-alt', created_at: T1 }),
      pce({ id: 'e-u2',  customer_id: 'cust-1', user_id: 'u2', company_id: 'co-b', created_at: T1 }),
    ],
    writes: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof makeApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const CO_A_ACTIVE_IDS = ['e1', 'e2', 'e3', 'e4']; // DESC by created_at

const int422 = (input: string): Record<string, unknown> => ({
  detail: [{
    type: 'int_parsing',
    loc: ['query', 'limit'],
    msg: 'Input should be a valid integer, unable to parse string as an integer',
    input,
    url: 'https://errors.pydantic.dev/2.13/v/int_parsing',
  }],
});

describe('Gate-7d · PolicyChanges list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 default limit=50 · four active rows DESC by created_at', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    const ids = body.items.map((x) => x['id']);
    expect(ids).toEqual(CO_A_ACTIVE_IDS);
    expect(body.total).toBe(4);
  });

  it('2 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/policy-changes');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('3 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('4 expired session → 401 Session expired', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('5 auth precedence · no bearer + limit=abc → 401 (not 422)', async () => {
    const r = await get('/api/policy-changes?limit=abc');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('6 limit=1 returns exactly 1 row (top of DESC)', async () => {
    const r = await get('/api/policy-changes?limit=1', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.map((x) => x['id'])).toEqual(['e1']);
    expect(body.total).toBe(1);
  });

  it('7 limit=200 · returns all active rows', async () => {
    const r = await get('/api/policy-changes?limit=200', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.length).toBe(4);
    expect(body.total).toBe(4);
  });

  it('8 limit=0 → clamped to 1', async () => {
    const r = await get('/api/policy-changes?limit=0', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.length).toBe(1);
    expect(body.total).toBe(1);
  });

  it('9 limit=-5 → clamped to 1', async () => {
    const r = await get('/api/policy-changes?limit=-5', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.length).toBe(1);
    expect(body.total).toBe(1);
  });

  it('10 limit=201 → clamped to 200 (returns all 4 active)', async () => {
    const r = await get('/api/policy-changes?limit=201', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.length).toBe(4);
    expect(body.total).toBe(4);
  });

  it('11 limit=999 → clamped to 200', async () => {
    const r = await get('/api/policy-changes?limit=999', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.length).toBe(4);
    expect(body.total).toBe(4);
  });

  it('12 limit=+1 → parsed as 1', async () => {
    const r = await get('/api/policy-changes?limit=%2B1', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.length).toBe(1);
  });

  it('13 limit surrounded by whitespace → parsed', async () => {
    // "%20%201%20%20" = "  1  "
    const r = await get('/api/policy-changes?limit=%20%201%20%20', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.length).toBe(1);
  });

  it('14 limit=abc → 422 int_parsing envelope', async () => {
    const r = await get('/api/policy-changes?limit=abc', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual(int422('abc'));
  });

  it('15 limit="" (blank) → 422 int_parsing envelope', async () => {
    const r = await get('/api/policy-changes?limit=', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual(int422(''));
  });

  it('16 limit=1.5 → 422 int_parsing envelope', async () => {
    const r = await get('/api/policy-changes?limit=1.5', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual(int422('1.5'));
  });

  it('17 limit=null → 422 int_parsing envelope', async () => {
    const r = await get('/api/policy-changes?limit=null', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual(int422('null'));
  });

  it('18 limit=None → 422 int_parsing envelope', async () => {
    const r = await get('/api/policy-changes?limit=None', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual(int422('None'));
  });

  it('19 customer_id omitted → all customers', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[] };
    const cids = new Set(body.items.map((x) => x['customer_id']));
    expect(cids.has('cust-1')).toBe(true);
    expect(cids.has('cust-2')).toBe(true);
    expect(cids.has('cust-3')).toBe(true);
  });

  it('20 customer_id="" blank → omitted', async () => {
    const r = await get('/api/policy-changes?customer_id=', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[] };
    expect(body.items.length).toBe(4);
  });

  it('21 customer_id=cust-1 · only cust-1 rows', async () => {
    const r = await get('/api/policy-changes?customer_id=cust-1', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.map((x) => x['id'])).toEqual(['e1', 'e3']);
    expect(body.total).toBe(2);
  });

  it('22 customer_id=unknown → 200 { items:[], total:0 }', async () => {
    const r = await get('/api/policy-changes?customer_id=cust-does-not-exist', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ items: [], total: 0 });
  });

  it('23 projection strips _id ONLY · user_id preserved', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[] };
    expect(body.items.length).toBeGreaterThan(0);
    for (const row of body.items) {
      expect(row).not.toHaveProperty('_id');
      expect(row['user_id']).toBe('u1');
    }
  });

  it('24 created_at DESC · e1 > e2 > e3 > e4', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[] };
    const ts = body.items.map((x) => x['created_at']);
    expect(ts).toEqual([T1, T2, T3, T4]);
  });

  it('25 wrapped response · exact { items, total } shape', async () => {
    const r = await get('/api/policy-changes?limit=1', { authorization: 'Bearer tok-u1' });
    const body = r.json() as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(['items', 'total']);
    expect(Array.isArray(body['items'])).toBe(true);
    expect(typeof body['total']).toBe('number');
  });

  it('26 empty result · far-future customer → total 0', async () => {
    state.policy_change_events.length = 0;
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-u1' });
    expect(r.json()).toEqual({ items: [], total: 0 });
  });

  it('27 owned X-Company-Id · co-a-alt → [e-alt]', async () => {
    const r = await get('/api/policy-changes', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt',
    });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.map((x) => x['id'])).toEqual(['e-alt']);
    expect(body.total).toBe(1);
  });

  it('28 unowned X-Company-Id → fallback default co-a', async () => {
    const r = await get('/api/policy-changes', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-b',
    });
    const body = r.json() as { items: Record<string, unknown>[]; total: number };
    expect(body.items.map((x) => x['id'])).toEqual(CO_A_ACTIVE_IDS);
  });

  it('29 no X-Company-Id · default company', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-u1' });
    const body = r.json() as { items: Record<string, unknown>[] };
    expect(body.items.map((x) => x['id'])).toEqual(CO_A_ACTIVE_IDS);
  });

  it('30 cross-user isolation · u2 sees only own', async () => {
    const r = await get('/api/policy-changes', { authorization: 'Bearer tok-u2' });
    const body = r.json() as { items: Record<string, unknown>[] };
    expect(body.items.map((x) => x['id'])).toEqual(['e-u2']);
  });

  it('31 zero Node writes across every exercised branch', async () => {
    await get('/api/policy-changes');
    await get('/api/policy-changes', { authorization: 'Bearer nope' });
    await get('/api/policy-changes', { authorization: 'Bearer tok-expired' });
    await get('/api/policy-changes?limit=abc', { authorization: 'Bearer tok-u1' });
    await get('/api/policy-changes?limit=', { authorization: 'Bearer tok-u1' });
    await get('/api/policy-changes?limit=1', { authorization: 'Bearer tok-u1' });
    await get('/api/policy-changes?limit=999', { authorization: 'Bearer tok-u1' });
    await get('/api/policy-changes?customer_id=cust-1', { authorization: 'Bearer tok-u1' });
    await get('/api/policy-changes', { authorization: 'Bearer tok-u2' });
    await get('/api/policy-changes', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    expect(state.writes).toEqual([]);
  });
});
