/**
 * TRUKVIA · Phase-3 · Gate-6b · GET /api/trips unit tests.
 * Read-only route — fake DB verifies zero writes on every path.
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

interface State {
  sessions: Record<string, unknown>[];
  users: Record<string, unknown>[];
  companies: Record<string, unknown>[];
  trips: Record<string, unknown>[];
  customers: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    if (k === '$and') {
      for (const clause of v as Record<string, unknown>[]) if (!matches(d, clause)) return false;
      continue;
    }
    if (k === '$or') {
      const anyOk = (v as Record<string, unknown>[]).some((c) => matches(d, c));
      if (!anyOk) return false;
      continue;
    }
    const dv = d[k];
    if (v instanceof RegExp) { if (typeof dv !== 'string' || !v.test(dv)) return false; continue; }
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const cond = v as Record<string, unknown>;
      if ('$gt' in cond) { if (!(typeof dv === 'number' && dv > (cond['$gt'] as number))) return false; continue; }
      if ('$gte' in cond || '$lte' in cond) {
        if (typeof dv !== 'string') return false;
        if ('$gte' in cond && dv < (cond['$gte'] as string)) return false;
        if ('$lte' in cond && dv > (cond['$lte'] as string)) return false;
        continue;
      }
      if ('$in' in cond) { if (!(cond['$in'] as unknown[]).some((x) => x === dv || (x === null && dv === undefined))) return false; continue; }
      if ('$exists' in cond) { const has = k in d; if (has !== cond['$exists']) return false; continue; }
    }
    if (dv !== v) return false;
  }
  return true;
}

function fakeDb(state: State): Db {
  const projFn = (d: Record<string, unknown>, projection?: Record<string, 0 | 1>): Record<string, unknown> => {
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
  };
  const collection = (name: string) => {
    const rows: Record<string, unknown>[] =
      name === 'user_sessions' ? state.sessions
      : name === 'companies' ? state.companies
      : name === 'trips' ? state.trips
      : name === 'customers' ? state.customers
      : name === 'users' ? state.users : [];

    function makeCursor(f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) {
      let hits = rows.filter((r) => matches(r, f));
      const cursor = {
        sort(spec: [string, 1 | -1][]) {
          hits = hits.slice().sort((a, b) => {
            for (const [k, d] of spec) {
              const av = a[k], bv = b[k];
              if (av === bv) continue;
              return ((av as string) < (bv as string) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
        skip(n: number) { hits = hits.slice(n); return cursor; },
        limit(n: number) { hits = hits.slice(0, n); return cursor; },
        async toArray() { return hits.map((d) => projFn(d, opts?.projection)); },
      };
      return cursor;
    }

    return {
      find: vi.fn((f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => makeCursor(f, opts)),
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        return hit ? projFn(hit, opts?.projection) : null;
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

function trip(o: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 't0', company_id: 'co-a', user_id: 'u1',
    customer_id: 'cust-1', date: '2026-02-01', vehicle_number: 'AB01AA0000',
    vehicle_id: 'v1', vehicle_type: 'own',
    supplier_id: '', supplier_name: '', driver_name: '',
    lr_number: '', from_location: '', to_location: '',
    external_invoice_no: '', customer_invoice_no: '', waybill_no: '',
    customer_reference_number: '',
    freight_amount: 30000, halting_amount: 0,
    supplier_diesel_entries: [], supplier_advance_entries: [],
    status: 'posted', is_historical: false,
    created_at: '2026-02-01T00:00:00.000Z',
    ...o,
  };
}

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-owner', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
      { session_token: 'tok-u2', user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
    ],
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b', user_id: 'u2', is_default: true },
    ],
    customers: [{ id: 'cust-1', user_id: 'u1', company_id: 'co-a', name: 'Acme Traders' }],
    trips: [
      trip({ id: 't1', vehicle_number: 'AB01AA0001', date: '2026-02-05', created_at: '2026-02-05T10:00:00Z' }),
      trip({ id: 't2', vehicle_number: 'AB01AA0002', date: '2026-02-03', created_at: '2026-02-03T09:00:00Z' }),
      trip({ id: 't3', vehicle_number: 'ZZ99ZZ9999', date: '2026-02-01', created_at: '2026-02-01T08:00:00Z',
        customer_id: 'cust-1', halting_amount: 500, customer_reference_number: '' }),
      trip({ id: 't4', vehicle_number: 'AB01AA0004', date: '2026-01-15',
        company_id: 'co-a-alt', supplier_id: 'sup-1', status: 'invoiced' }),
      trip({ id: 't5', vehicle_number: 'AB01AA0005', date: '2026-02-02',
        user_id: 'u2', company_id: 'co-b', customer_id: 'cust-2' }),
      trip({ id: 't6', vehicle_number: 'AB01AA0006', date: '2026-02-04',
        customer_reference_number: 'CRN-123' }),  // NOT missing_cust_ref
      trip({ id: 't7', vehicle_number: 'AB01AA0007', date: '2026-01-30',
        is_historical: true, status: 'archived_historical' }),
    ],
    writes: [],
  };
}

async function makeApp(state: State) {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('GET /api/trips — Gate-6b list shadow (read-only)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}) =>
    app.inject({ method: 'GET', url, headers });

  it('1 happy: no filters returns u1/co-a trips sorted (date desc, created_at desc)', async () => {
    const r = await get('/api/trips', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const arr = r.json();
    // u1/co-a trips: t1(02-05), t2(02-03), t3(02-01), t6(02-04), t7(01-30)
    expect(arr.map((d: Record<string, unknown>) => d['id'])).toEqual(['t1', 't6', 't2', 't3', 't7']);
    expect(r.headers['x-total-count']).toBe('5');
    expect(r.headers['x-has-more']).toBe('false');
    expect(r.headers['access-control-expose-headers']).toBe('X-Total-Count, X-Has-More');
  });

  it('2 empty result → [] with X-Total-Count:0 X-Has-More:false', async () => {
    const r = await get('/api/trips?customer_id=nope', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
    expect(r.headers['x-total-count']).toBe('0');
    expect(r.headers['x-has-more']).toBe('false');
  });

  it('3 limit=1 offset=0', async () => {
    const r = await get('/api/trips?limit=1&offset=0', { authorization: 'Bearer tok-owner' });
    expect(r.json().length).toBe(1);
    expect(r.headers['x-total-count']).toBe('5');
    expect(r.headers['x-has-more']).toBe('true');
  });

  it('4 limit=1 offset=1', async () => {
    const r = await get('/api/trips?limit=1&offset=1', { authorization: 'Bearer tok-owner' });
    const arr = r.json();
    expect(arr.length).toBe(1);
    expect(arr[0]['id']).toBe('t6');
    expect(r.headers['x-has-more']).toBe('true');
  });

  it('5 offset beyond result set → [] X-Has-More:false', async () => {
    const r = await get('/api/trips?limit=10&offset=100', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
    expect(r.headers['x-has-more']).toBe('false');
  });

  it('6 customer_id filter', async () => {
    const r = await get('/api/trips?customer_id=cust-1', { authorization: 'Bearer tok-owner' });
    const ids = r.json().map((d: Record<string, unknown>) => d['id']);
    expect(ids).toContain('t3');
  });

  it('7 vehicle_id filter', async () => {
    const r = await get('/api/trips?vehicle_id=v1', { authorization: 'Bearer tok-owner' });
    expect(r.json().length).toBeGreaterThan(0);
  });

  it('8 supplier_id filter (owned override to co-a-alt)', async () => {
    const r = await get('/api/trips?supplier_id=sup-1',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    const arr = r.json();
    expect(arr.length).toBe(1);
    expect(arr[0]['id']).toBe('t4');
  });

  it('9 status filter (invoiced only in co-a-alt)', async () => {
    const r = await get('/api/trips?status=invoiced',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(r.json().length).toBe(1);
  });

  it('10 exact date filter', async () => {
    const r = await get('/api/trips?date=2026-02-01', { authorization: 'Bearer tok-owner' });
    expect(r.json().map((d: Record<string, unknown>) => d['id'])).toEqual(['t3']);
  });

  it('11 date_from/date_to range', async () => {
    const r = await get('/api/trips?date_from=2026-02-03&date_to=2026-02-05',
      { authorization: 'Bearer tok-owner' });
    expect(r.json().map((d: Record<string, unknown>) => d['id'])).toEqual(['t1', 't6', 't2']);
  });

  it('12 q matches vehicle_number', async () => {
    const r = await get('/api/trips?q=ZZ99', { authorization: 'Bearer tok-owner' });
    expect(r.json().map((d: Record<string, unknown>) => d['id'])).toEqual(['t3']);
  });

  it('13 q matches customer.name secondary lookup', async () => {
    const r = await get('/api/trips?q=Acme', { authorization: 'Bearer tok-owner' });
    // t3 has customer_id=cust-1 which name matches "Acme Traders"
    const ids = r.json().map((d: Record<string, unknown>) => d['id']);
    expect(ids).toContain('t3');
  });

  it('14 halting_only=true', async () => {
    const r = await get('/api/trips?halting_only=true', { authorization: 'Bearer tok-owner' });
    expect(r.json().map((d: Record<string, unknown>) => d['id'])).toEqual(['t3']);
  });

  it('15 missing_cust_ref=true excludes trips with a stored ref', async () => {
    const r = await get('/api/trips?missing_cust_ref=true', { authorization: 'Bearer tok-owner' });
    const ids = r.json().map((d: Record<string, unknown>) => d['id']);
    expect(ids).not.toContain('t6');  // t6 has customer_reference_number set
  });

  it('16 ids=a,b,c short-circuit — no pagination headers', async () => {
    const r = await get('/api/trips?ids=t1,t2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json().map((d: Record<string, unknown>) => d['id']).sort()).toEqual(['t1', 't2']);
    expect(r.headers['x-total-count']).toBeUndefined();
    expect(r.headers['x-has-more']).toBeUndefined();
  });

  it('17 ids="" empty → falls through to normal list (Python-parity: falsy)', async () => {
    const r = await get('/api/trips?ids=', { authorization: 'Bearer tok-owner' });
    // Python: `if ids:` empty string is falsy → normal listing + headers.
    expect(r.statusCode).toBe(200);
    expect(r.headers['x-total-count']).toBe('5');
    expect(r.headers['x-has-more']).toBe('false');
  });

  it('18 unauthenticated → 401', async () => {
    const r = await get('/api/trips');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('19 invalid session → 401', async () => {
    const r = await get('/api/trips', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('20 expired → 401', async () => {
    const r = await get('/api/trips', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('21 owned X-Company-Id override (co-a-alt)', async () => {
    const r = await get('/api/trips',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    const arr = r.json();
    expect(arr.length).toBe(1);
    expect(arr[0]['id']).toBe('t4');
  });

  it('22 unowned X-Company-Id → default fallback (co-a)', async () => {
    const r = await get('/api/trips',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    // fallback returns co-a trips
    expect(r.json().length).toBe(5);
  });

  it('23 cross-tenant isolation: u2 sees only own trips', async () => {
    const r = await get('/api/trips', { authorization: 'Bearer tok-u2' });
    const arr = r.json();
    expect(arr.length).toBe(1);
    expect(arr[0]['id']).toBe('t5');
  });

  it('24 invalid limit → 422', async () => {
    const r = await get('/api/trips?limit=0', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
  });

  it('25 historical trip included in default list', async () => {
    const r = await get('/api/trips', { authorization: 'Bearer tok-owner' });
    const ids = r.json().map((d: Record<string, unknown>) => d['id']);
    expect(ids).toContain('t7');
  });

  it('26 Node write observation — zero writes across every path', async () => {
    await get('/api/trips', { authorization: 'Bearer tok-owner' });
    await get('/api/trips?ids=t1,t2', { authorization: 'Bearer tok-owner' });
    await get('/api/trips?q=Acme', { authorization: 'Bearer tok-owner' });
    await get('/api/trips');
    await get('/api/trips', { authorization: 'Bearer nope' });
    await get('/api/trips?limit=0', { authorization: 'Bearer tok-owner' });
    await get('/api/trips?halting_only=true&missing_cust_ref=true',
      { authorization: 'Bearer tok-owner' });
    expect(state.writes).toEqual([]);
  });

  it('27 date takes precedence over date_from/date_to', async () => {
    const r = await get('/api/trips?date=2026-02-01&date_from=2026-01-01&date_to=2026-12-31',
      { authorization: 'Bearer tok-owner' });
    expect(r.json().map((d: Record<string, unknown>) => d['id'])).toEqual(['t3']);
  });

  it('28 response projection excludes _id and user_id', async () => {
    const r = await get('/api/trips', { authorization: 'Bearer tok-owner' });
    for (const d of r.json()) {
      expect(d).not.toHaveProperty('_id');
      expect(d).not.toHaveProperty('user_id');
    }
  });
});
