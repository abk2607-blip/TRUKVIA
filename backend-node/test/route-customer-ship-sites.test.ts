/**
 * TRUKVIA · Phase-3 · Gate-6g · Customer Ship-Sites read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/customers/{cid}/ship-sites
 *
 * Fake-DB write-forbid pattern reused from Gates 6c–6f.
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
  customers: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const cond = v as Record<string, unknown>;
      if ('$in' in cond) {
        if (!(cond['$in'] as unknown[]).some((x) => x === dv)) return false;
        continue;
      }
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(
  d: Record<string, unknown>,
  projection?: Record<string, 0 | 1>,
): Record<string, unknown> {
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
    : name === 'customers' ? state.customers
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    function makeCursor(
      f: Record<string, unknown>,
      opts?: { projection?: Record<string, 0 | 1> },
    ): {
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
              return ((av as string) < (bv as string) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
        skip(n: number) { hits = hits.slice(n); return cursor; },
        limit(n: number) { hits = hits.slice(0, n); return cursor; },
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

// ── Fixture helpers ─────────────────────────────────────────────────
function site(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 's-x', site_name: 'X', address: '', gstin: '',
    state: '', state_code: '', pincode: '',
    phone: '', contact_person: '', is_active: true,
    ...overrides,
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
    customers: [
      // Full site variety on cust-1 (default company)
      {
        id: 'cust-1', user_id: 'u1', company_id: 'co-a', name: 'Acme',
        ship_sites: [
          site({ id: 's-active-true', site_name: 'Active True', is_active: true }),
          site({ id: 's-active-false', site_name: 'Active False', is_active: false }),
          site({ id: 's-active-null', site_name: 'Active Null', is_active: null }),
          site({ id: 's-active-missing', site_name: 'Active Missing', is_active: undefined }),
          site({ id: 's-active-str', site_name: 'Active Str', is_active: 'anything' }),
          site({ id: 's-active-zero', site_name: 'Active Zero', is_active: 0 }),
          site({ id: 's-active-empty', site_name: 'Active Empty', is_active: '' }),
        ],
      },
      // Empty ship_sites
      { id: 'cust-empty', user_id: 'u1', company_id: 'co-a', name: 'Empty', ship_sites: [] },
      // Missing ship_sites entirely
      { id: 'cust-missing', user_id: 'u1', company_id: 'co-a', name: 'Missing' },
      // Same id under alt company (X-Company-Id override target)
      {
        id: 'cust-1', user_id: 'u1', company_id: 'co-a-alt', name: 'Acme-Alt',
        ship_sites: [site({ id: 's-alt', site_name: 'Alt' })],
      },
      // u2-owned customer for cross-tenant isolation test
      { id: 'cust-u2', user_id: 'u2', company_id: 'co-b', name: 'Beta',
        ship_sites: [site({ id: 's-u2', site_name: 'U2 Site' })] },
    ],
    writes: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6g · Customer Ship-Sites read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 happy path — returns items + total', async () => {
    const r = await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['total']).toBe(7);
    expect(d['items'].length).toBe(7);
    expect(d['items'][0]['site_name']).toBe('Active True');
  });

  it('2 empty ship_sites → items=[], total=0', async () => {
    const r = await get('/api/customers/cust-empty/ship-sites', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ items: [], total: 0 });
  });

  it('3 missing ship_sites field → items=[], total=0', async () => {
    const r = await get('/api/customers/cust-missing/ship-sites', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ items: [], total: 0 });
  });

  it('4 active_only omitted → defaults to false (all sites returned)', async () => {
    const r = await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-owner' });
    expect(r.json()['total']).toBe(7);
  });

  it('5 active_only=false → all sites returned', async () => {
    const r = await get('/api/customers/cust-1/ship-sites?active_only=false', { authorization: 'Bearer tok-owner' });
    expect(r.json()['total']).toBe(7);
  });

  it('6 active_only=true → removes ONLY literal is_active=false (6 remain)', async () => {
    const r = await get('/api/customers/cust-1/ship-sites?active_only=true', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['total']).toBe(6);
    const ids = d['items'].map((s: Record<string, unknown>) => s['id']);
    expect(ids).not.toContain('s-active-false');
    // All non-false variants remain
    for (const id of ['s-active-true', 's-active-null', 's-active-missing', 's-active-str', 's-active-zero', 's-active-empty']) {
      expect(ids).toContain(id);
    }
  });

  // FastAPI-compatible boolean coercion — TRUE tokens (case-insensitive)
  for (const token of ['true', 'True', 'TRUE', 'yes', 'YES', 'Yes', '1', 'on', 'ON', 't', 'T']) {
    it(`7.${token} active_only=${token} → filters is_active=false`, async () => {
      const r = await get(`/api/customers/cust-1/ship-sites?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      expect(r.json()['total']).toBe(6);
    });
  }

  // FastAPI-compatible boolean coercion — FALSE tokens (case-insensitive)
  for (const token of ['false', 'False', 'FALSE', 'no', 'NO', '0', 'off', 'OFF', 'f', 'F', 'n', 'N']) {
    it(`8.${token} active_only=${token} → no filter (all 7)`, async () => {
      const r = await get(`/api/customers/cust-1/ship-sites?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      expect(r.json()['total']).toBe(7);
    });
  }

  // Invalid boolean tokens → 422 (parity with FastAPI/Pydantic ValidationError)
  for (const token of ['maybe', '2', '1.0', 'yesplease', 'sure', '']) {
    it(`9.${JSON.stringify(token)} invalid boolean → 422`, async () => {
      const r = await get(`/api/customers/cust-1/ship-sites?active_only=${encodeURIComponent(token)}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(422);
    });
  }

  it('10 missing customer → 404 "Customer not found"', async () => {
    const r = await get('/api/customers/does-not-exist/ship-sites', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Customer not found' });
  });

  it('11 cross-user isolation → 404 (u1 cannot fetch u2 customer)', async () => {
    const r = await get('/api/customers/cust-u2/ship-sites', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Customer not found' });
  });

  it('12 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/customers/cust-1/ship-sites');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('13 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('14 expired session → 401 Session expired', async () => {
    const r = await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('15 owned X-Company-Id override → resolves customer under override company', async () => {
    const r = await get('/api/customers/cust-1/ship-sites', {
      authorization: 'Bearer tok-owner',
      'x-company-id': 'co-a-alt',
    });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    // Under co-a-alt, cust-1 has only s-alt (different from co-a)
    expect(d['total']).toBe(1);
    expect(d['items'][0]['id']).toBe('s-alt');
  });

  it('16 unowned X-Company-Id → falls back to default company (co-a)', async () => {
    const r = await get('/api/customers/cust-1/ship-sites', {
      authorization: 'Bearer tok-owner',
      'x-company-id': 'co-b', // owned by u2, not u1
    });
    expect(r.statusCode).toBe(200);
    expect(r.json()['total']).toBe(7);
  });

  it('17 no X-Company-Id header → default company', async () => {
    const r = await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()['total']).toBe(7);
  });

  it('18 raw ship_sites preserved (no GSTIN normalization, no state derivation)', async () => {
    // Inject a customer with dirty stored fields.
    state.customers.push({
      id: 'cust-raw', user_id: 'u1', company_id: 'co-a', name: 'Raw',
      ship_sites: [{
        id: 's-raw', site_name: '  Dirty  ',
        gstin: '  gst: 29abcde1234f1z5  ',
        state: '', state_code: '', pincode: '',
        is_active: true, extra_field: 'preserved',
      }],
    });
    const r = await get('/api/customers/cust-raw/ship-sites', { authorization: 'Bearer tok-owner' });
    const site0 = r.json()['items'][0];
    // Stored dirty GSTIN preserved (NOT normalized like Gate 6e)
    expect(site0['gstin']).toBe('  gst: 29abcde1234f1z5  ');
    expect(site0['site_name']).toBe('  Dirty  ');
    // Extra field passes through
    expect(site0['extra_field']).toBe('preserved');
  });

  it('19 zero Node business writes across every branch', async () => {
    await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-1/ship-sites?active_only=true', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-1/ship-sites?active_only=false', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-1/ship-sites?active_only=yes', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-1/ship-sites?active_only=maybe', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-empty/ship-sites', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-missing/ship-sites', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/does-not-exist/ship-sites', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-u2/ship-sites', { authorization: 'Bearer tok-owner' });
    await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/customers/cust-1/ship-sites');
    await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer nope' });
    await get('/api/customers/cust-1/ship-sites', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
