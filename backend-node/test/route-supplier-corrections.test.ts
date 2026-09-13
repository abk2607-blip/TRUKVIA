/**
 * TRUKVIA Node · Phase 3 · Gate 2 tests.
 *
 * Faithful behaviour parity for:
 *   GET /api/supplier-payments/:pid/corrections
 *
 * Python source of truth:
 *   backend/routers/supplier_ledger.py::list_supplier_payment_corrections
 *   backend/services_payment_corrections.py::list_corrections
 *
 * Tests cover categories A–H from the gate brief:
 *   A. happy path (sorted + projected)
 *   B. empty history
 *   C. not-found pid (Python-parity: returns 200 [] — NO 404)
 *   D. tenant isolation (cross-company)
 *   E. authorization: no-token / invalid / expired / cookie-auth
 *   F. path validation
 *   G. read-only guarantee: no write methods invoked
 *   H. response parity: no _id, no user_id in payload
 *
 * The DB is a purpose-built in-memory fake — no real Mongo is contacted.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

// -------------------- shared fixture setup --------------------

const baseConfig: AppConfig = {
  nodeEnv: 'test',
  logLevel: 'silent',
  port: 0,
  host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017',
  dbName: 'trukvia_node_test',
  corsOrigins: [],
  requestIdHeader: 'x-request-id',
  trustIncomingRequestId: false,
};

interface Session {
  session_token: string;
  user_id: string;
  effective_role: string;
  expires_at: string | Date;
}
interface Company { id: string; user_id: string; is_default?: boolean }
interface Correction {
  id: string;
  user_id: string;
  company_id: string;
  payment_type: string;
  payment_id: string;
  correction_index: number;
  kind: string;
  correction_reason: string;
  _id?: string; // simulated Mongo _id
}

interface DbState {
  sessions: Session[];
  companies: Company[];
  corrections: Correction[];
}

interface DbSpies {
  writeCalls: number;
  writeMethodsCalled: string[];
  findOneCalls: number;
  findCalls: number;
}

function buildFakeDb(state: DbState, spies: DbSpies): Db {
  const forbid = (name: string) => (): never => {
    spies.writeCalls += 1;
    spies.writeMethodsCalled.push(name);
    throw new Error(`READ-ONLY VIOLATION: ${name} was called`);
  };

  const applyProjection = <T extends Record<string, unknown>>(
    doc: T,
    projection: Record<string, 0 | 1> | undefined,
  ): Partial<T> => {
    if (!projection) return { ...doc };
    // include-mode: keys with 1
    const includes = Object.entries(projection).filter(([, v]) => v === 1).map(([k]) => k);
    const excludes = Object.entries(projection).filter(([, v]) => v === 0).map(([k]) => k);
    if (includes.length > 0 && excludes.every((k) => k === '_id')) {
      const out: Record<string, unknown> = {};
      for (const k of includes) out[k] = doc[k];
      if (!excludes.includes('_id') && '_id' in doc) out['_id'] = doc['_id'];
      return out as Partial<T>;
    }
    const out: Record<string, unknown> = { ...doc };
    for (const k of excludes) delete out[k];
    return out as Partial<T>;
  };

  const matches = (doc: Record<string, unknown>, filter: Record<string, unknown>): boolean => {
    for (const [k, v] of Object.entries(filter)) {
      if (doc[k] !== v) return false;
    }
    return true;
  };

  const collection = (name: string) => {
    const rows: Record<string, unknown>[] =
      name === 'user_sessions'
        ? (state.sessions as unknown as Record<string, unknown>[])
        : name === 'companies'
        ? (state.companies as unknown as Record<string, unknown>[])
        : name === 'payment_corrections'
        ? (state.corrections as unknown as Record<string, unknown>[])
        : [];
    return {
      findOne: vi.fn(async (filter: Record<string, unknown>, options?: { projection?: Record<string, 0 | 1> }) => {
        spies.findOneCalls += 1;
        const hit = rows.find((r) => matches(r, filter));
        return hit ? applyProjection(hit, options?.projection) : null;
      }),
      find: vi.fn((filter: Record<string, unknown>, options?: { projection?: Record<string, 0 | 1> }) => {
        spies.findCalls += 1;
        const matched = rows.filter((r) => matches(r, filter));
        return {
          sort: (spec: Record<string, 1 | -1>) => {
            const [[key, dir]] = Object.entries(spec);
            const sorted = [...matched].sort((a, b) => {
              const av = a[key!] as number;
              const bv = b[key!] as number;
              return av < bv ? -1 * dir! : av > bv ? 1 * dir! : 0;
            });
            return {
              toArray: async () => sorted.map((d) => applyProjection(d, options?.projection)),
            };
          },
        };
      }),
      // Any write method invoked here means the route violated the read-only
      // contract; each is a spy that increments spies.writeCalls and throws.
      insertOne: vi.fn(forbid('insertOne')),
      insertMany: vi.fn(forbid('insertMany')),
      updateOne: vi.fn(forbid('updateOne')),
      updateMany: vi.fn(forbid('updateMany')),
      deleteOne: vi.fn(forbid('deleteOne')),
      deleteMany: vi.fn(forbid('deleteMany')),
      replaceOne: vi.fn(forbid('replaceOne')),
      findOneAndUpdate: vi.fn(forbid('findOneAndUpdate')),
      findOneAndDelete: vi.fn(forbid('findOneAndDelete')),
      findOneAndReplace: vi.fn(forbid('findOneAndReplace')),
      bulkWrite: vi.fn(forbid('bulkWrite')),
    };
  };

  return { collection: vi.fn(collection) } as unknown as Db;
}

function buildMongo(db: Db): MongoConn {
  return {
    client: {} as MongoConn['client'],
    db,
    ping: async () => true,
    close: async () => undefined,
  };
}

async function makeApp(state: DbState): Promise<{
  app: Awaited<ReturnType<typeof buildApp>>;
  spies: DbSpies;
}> {
  const spies: DbSpies = {
    writeCalls: 0,
    writeMethodsCalled: [],
    findOneCalls: 0,
    findCalls: 0,
  };
  const db = buildFakeDb(state, spies);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const app = await buildApp({ config: baseConfig, logger, mongo: buildMongo(db) });
  return { app, spies };
}

// -------------------- fixtures --------------------

const IN_FUTURE = new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString();
const IN_PAST = new Date(Date.now() - 60 * 1000).toISOString();

const baseState = (): DbState => ({
  sessions: [
    { session_token: 'tok-owner', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE },
    { session_token: 'tok-viewer', user_id: 'u1', effective_role: 'viewer', expires_at: IN_FUTURE },
    { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST },
    { session_token: 'tok-tenant-b', user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE },
  ],
  companies: [
    { id: 'co-a', user_id: 'u1', is_default: true },
    { id: 'co-a-alt', user_id: 'u1' },
    { id: 'co-b', user_id: 'u2', is_default: true },
  ],
  corrections: [
    // u1 / co-a / sp_1 — three rows, deliberately inserted out-of-order to prove sort.
    { _id: 'mid-2', id: 'pcr_2', user_id: 'u1', company_id: 'co-a', payment_type: 'supplier', payment_id: 'sp_1',
      correction_index: 2, kind: 'amount_reversal_new', correction_reason: 'r2 padded to 10' },
    { _id: 'mid-1', id: 'pcr_1', user_id: 'u1', company_id: 'co-a', payment_type: 'supplier', payment_id: 'sp_1',
      correction_index: 1, kind: 'attribute', correction_reason: 'r1 padded to 10' },
    { _id: 'mid-3', id: 'pcr_3', user_id: 'u1', company_id: 'co-a', payment_type: 'supplier', payment_id: 'sp_1',
      correction_index: 3, kind: 'attribute', correction_reason: 'r3 padded to 10' },
    // u1 / co-a / sp_2 — one row
    { _id: 'mid-4', id: 'pcr_4', user_id: 'u1', company_id: 'co-a', payment_type: 'supplier', payment_id: 'sp_2',
      correction_index: 1, kind: 'attribute', correction_reason: 'r4 padded to 10' },
    // u2 / co-b / sp_x — cross-tenant fixture
    { _id: 'mid-5', id: 'pcr_5', user_id: 'u2', company_id: 'co-b', payment_type: 'supplier', payment_id: 'sp_x',
      correction_index: 1, kind: 'attribute', correction_reason: 'crossX pad to 10' },
    // u1 / co-a / vendor payment — must NOT appear in supplier query
    { _id: 'mid-6', id: 'pcr_6', user_id: 'u1', company_id: 'co-a', payment_type: 'vendor', payment_id: 'sp_1',
      correction_index: 9, kind: 'attribute', correction_reason: 'vendor_pad10' },
  ],
});

// -------------------- tests --------------------

describe('GET /api/supplier-payments/:pid/corrections — Phase-3 Gate-2 shadow', () => {
  let ctx: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => {
    ctx = await makeApp(baseState());
  });

  afterEach(async () => {
    await ctx.app.close();
  });

  // -------- A. happy path --------
  it('A · returns rows sorted by correction_index ASC and projects out _id and user_id', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(Array.isArray(body)).toBe(true);
    expect(body.map((r) => r['id'])).toEqual(['pcr_1', 'pcr_2', 'pcr_3']);
    for (const row of body) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
      expect(row['payment_type']).toBe('supplier');
      expect(row['company_id']).toBe('co-a');
    }
  });

  // -------- B. empty history --------
  it('B · returns [] when the payment has no corrections (existing pid)', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_never/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual([]);
  });

  // -------- C. not-found pid: Python parity (200 [], not 404) --------
  it('C · returns 200 [] for a non-existent pid (Python does NOT call _load_payment on GET)', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/does-not-exist-anywhere/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual([]);
  });

  // -------- D. tenant isolation --------
  it('D · cross-tenant read returns [] (u1 cannot see u2/co-b rows)', async () => {
    // u1's active company defaults to co-a. sp_x lives under u2/co-b.
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_x/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual([]);
  });

  it('D · vendor rows for the same pid are NOT returned by the supplier route', async () => {
    // Fixture has u1/co-a/vendor pcr_6 pointing at sp_1; supplier query MUST NOT return it.
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.every((r) => r.payment_type === 'supplier')).toBe(true);
    expect(body.map((r) => r.id)).not.toContain('pcr_6');
  });

  // -------- E. authorization parity with error-string-parity.md --------
  it('E · 401 "Not authenticated" when no token is supplied', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
    });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('E · 401 "Invalid session" for an unknown bearer token', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-nonexistent' },
    });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ detail: 'Invalid session' });
  });

  it('E · 401 "Session expired" for an expired session', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-expired' },
    });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ detail: 'Session expired' });
  });

  it('E · cookie-based session_token is accepted', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { cookie: 'session_token=tok-owner; something=else' },
    });
    expect(res.statusCode).toBe(200);
    expect((res.json()).length).toBe(3);
  });

  it('E · authenticated non-admin viewer role is allowed (Python GET does NOT enforce admin)', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-viewer' },
    });
    expect(res.statusCode).toBe(200);
    expect((res.json()).length).toBe(3);
  });

  // -------- Header override, default, and fallback semantics --------
  it('E · X-Company-Id header override is honoured when owned', async () => {
    // Move fixture data into co-a-alt to prove override selects that company.
    const state = baseState();
    for (const row of state.corrections) {
      if (row.user_id === 'u1' && row.payment_id === 'sp_1') row.company_id = 'co-a-alt';
    }
    const ctx2 = await makeApp(state);
    try {
      const res = await ctx2.app.inject({
        method: 'GET',
        url: '/api/supplier-payments/sp_1/corrections',
        headers: { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' },
      });
      expect(res.statusCode).toBe(200);
      expect((res.json()).length).toBe(3);
    } finally {
      await ctx2.app.close();
    }
  });

  it('E · X-Company-Id header pointing at a company the user does NOT own falls back to default', async () => {
    // u1 sends x-company-id: co-b (owned by u2) — should be ignored and fall back to co-a (default).
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    for (const row of body) expect(row.company_id).toBe('co-a');
  });

  it('E · user with no default company falls back to first-owned company', async () => {
    const state = baseState();
    for (const c of state.companies) c.is_default = false;
    const ctx2 = await makeApp(state);
    try {
      const res = await ctx2.app.inject({
        method: 'GET',
        url: '/api/supplier-payments/sp_1/corrections',
        headers: { authorization: 'Bearer tok-owner' },
      });
      expect(res.statusCode).toBe(200);
      // First-owned for u1 is co-a — expect the 3 rows.
      expect((res.json()).length).toBe(3);
    } finally {
      await ctx2.app.close();
    }
  });

  it('E · user with NO companies resolves cid="" and returns []', async () => {
    const state = baseState();
    state.companies = state.companies.filter((c) => c.user_id !== 'u1');
    const ctx2 = await makeApp(state);
    try {
      const res = await ctx2.app.inject({
        method: 'GET',
        url: '/api/supplier-payments/sp_1/corrections',
        headers: { authorization: 'Bearer tok-owner' },
      });
      expect(res.statusCode).toBe(200);
      expect(res.json()).toEqual([]);
    } finally {
      await ctx2.app.close();
    }
  });

  // -------- F. path validation --------
  it('F · pid with URL-safe punctuation is accepted (matches Python string-path semantics)', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1-weird.PID~123/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual([]);
  });

  // -------- G. read-only guarantee --------
  it('G · zero write methods invoked across the full happy-path request', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    expect(ctx.spies.writeCalls).toBe(0);
    expect(ctx.spies.writeMethodsCalled).toEqual([]);
    // Sanity: reads DID occur.
    expect(ctx.spies.findOneCalls).toBeGreaterThan(0);
    expect(ctx.spies.findCalls).toBeGreaterThan(0);
  });

  it('G · zero writes even on the unauthenticated failure path', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
    });
    expect(res.statusCode).toBe(401);
    expect(ctx.spies.writeCalls).toBe(0);
  });

  // -------- H. response parity: shape and headers --------
  it('H · response shape is a JSON array; every row carries the frozen keys', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.headers['content-type']).toMatch(/application\/json/);
    const body = res.json();
    expect(Array.isArray(body)).toBe(true);
    for (const row of body) {
      // Positive parity: keys observed in Python's payment_corrections doc.
      expect(row).toHaveProperty('id');
      expect(row).toHaveProperty('company_id');
      expect(row).toHaveProperty('payment_type');
      expect(row).toHaveProperty('payment_id');
      expect(row).toHaveProperty('correction_index');
      expect(row).toHaveProperty('kind');
      expect(row).toHaveProperty('correction_reason');
      // Negative parity: MUST project out _id and user_id.
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('H · x-request-id is echoed on the response (foundation invariant preserved)', async () => {
    const res = await ctx.app.inject({
      method: 'GET',
      url: '/api/supplier-payments/sp_1/corrections',
      headers: { authorization: 'Bearer tok-owner' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.headers['x-request-id']).toMatch(/^[0-9a-f-]{36}$/);
  });
});

// (per-test cleanup is registered inline in the describe block via afterEach)
