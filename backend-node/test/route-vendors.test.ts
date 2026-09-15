/**
 * TRUKVIA · Phase-3 · Gate-6j · Vendor master read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/vendors
 *   GET /api/vendors/{vid}
 *
 * Fake-DB write-forbid pattern reused from Gates 6c–6i.
 * Gate-6j-only fake-DB extension: `$regex` + `$or` support added
 * INLINE in this file. Shared / locked test infrastructure is NOT
 * touched.
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
  vendors: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

// ── Gate-6j-only operator support (inline; no shared infra touched) ──
// Supported operators (subset sufficient for Gate-6j contract):
//   $regex + $options — Mongo-style case-insensitive regex on strings
//   $in — membership
function matchOperator(dv: unknown, cond: Record<string, unknown>): boolean {
  if ('$regex' in cond) {
    if (typeof dv !== 'string') return false;
    const flags = typeof cond['$options'] === 'string' ? (cond['$options'] as string) : '';
    const pattern = cond['$regex'] as string;
    return new RegExp(pattern, flags).test(dv);
  }
  if ('$in' in cond) {
    const arr = cond['$in'] as unknown[];
    return arr.some((x) => x === dv);
  }
  return false;
}

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x) && !(x instanceof Date);
}

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    if (k === '$or') {
      const branches = v as Record<string, unknown>[];
      if (!branches.some((br) => matches(d, br))) return false;
      continue;
    }
    const dv = d[k];
    if (isPlainObject(v)) {
      const keys = Object.keys(v);
      const hasOps = keys.length > 0 && keys.every((kk) => kk.startsWith('$'));
      if (hasOps) {
        if (!matchOperator(dv, v)) return false;
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
    : name === 'vendors' ? state.vendors
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
              if (av === undefined) return 1 * d;
              if (bv === undefined) return -1 * d;
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
function ven(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'v-x', user_id: 'u1', company_id: 'co-a',
    name: 'Vendor X', mobile: '9999999999', contact_person: 'PersonX',
    address: '', gstin: '', pan: '', state: '',
    opening_balance: 0.0, is_active: true,
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
    vendors: [
      ven({ id: 'v-alpha',   name: 'Alpha Parts',      mobile: '9111111111', contact_person: 'Alice',   is_active: true }),
      ven({ id: 'v-beta',    name: 'Beta Tools',       mobile: '9222222222', contact_person: 'Bob',     is_active: true, extra_field: 'preserved' }),
      ven({ id: 'v-gamma',   name: 'Gamma Workshop',   mobile: '9333333333', contact_person: 'Charlie', is_active: false }),
      ven({ id: 'v-delta',   name: 'Delta Enterprise', mobile: '9444444444', contact_person: 'Dave',    is_active: true }),
      // Same-user alt company (must NOT surface under default scope)
      ven({ id: 'v-alt', user_id: 'u1', company_id: 'co-a-alt', name: 'Alt Vendor', mobile: '9555555555', contact_person: 'Eve' }),
      // Cross-user isolation
      ven({ id: 'v-u2', user_id: 'u2', company_id: 'co-b', name: 'U2 Vendor', mobile: '9666666666', contact_person: 'Frank' }),
    ],
    writes: [],
  };
}

const VISIBLE_UNDER_CO_A = 4;      // alpha, beta, gamma, delta
const ACTIVE_UNDER_CO_A = 3;       // alpha, beta, delta (gamma is inactive)

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6j · Vendor master read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ─────────────────────────────── LIST ──────────────────────────────

  it('1 happy path — returns all visible vendors under default company', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('2 active_only=true → filters inactive (only 3 remain)', async () => {
    const r = await get('/api/vendors?active_only=true', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids.length).toBe(ACTIVE_UNDER_CO_A);
    expect(ids).not.toContain('v-gamma');
    for (const id of ['v-alpha', 'v-beta', 'v-delta']) expect(ids).toContain(id);
  });

  it('3 active_only=false → all vendors returned', async () => {
    const r = await get('/api/vendors?active_only=false', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('3b active_only omitted → all vendors returned (default false)', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  // Boolean TRUE tokens
  for (const token of ['true', 'True', 'TRUE', 'yes', 'YES', '1', 'on', 'ON', 't', 'T']) {
    it(`4.${token} active_only=${token} → filters inactive`, async () => {
      const r = await get(`/api/vendors?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      expect((r.json() as unknown[]).length).toBe(ACTIVE_UNDER_CO_A);
    });
  }

  // Boolean FALSE tokens
  for (const token of ['false', 'False', 'FALSE', 'no', 'NO', '0', 'off', 'OFF', 'f', 'F', 'n', 'N']) {
    it(`5.${token} active_only=${token} → all vendors returned`, async () => {
      const r = await get(`/api/vendors?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
    });
  }

  // Invalid boolean → 422
  for (const token of ['maybe', '2', '1.0', 'yesplease', 'sure', '']) {
    it(`6.${JSON.stringify(token)} invalid boolean → 422`, async () => {
      const r = await get(`/api/vendors?active_only=${encodeURIComponent(token)}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(422);
    });
  }

  it('7 q matches name (case-insensitive)', async () => {
    const r = await get('/api/vendors?q=alpha', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids).toEqual(['v-alpha']);
  });

  it('7b q matches name uppercase → case-insensitive', async () => {
    const r = await get('/api/vendors?q=ALPHA', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids).toEqual(['v-alpha']);
  });

  it('8 q matches mobile', async () => {
    const r = await get('/api/vendors?q=9222222222', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids).toEqual(['v-beta']);
  });

  it('9 q matches contact_person', async () => {
    const r = await get('/api/vendors?q=Charlie', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids).toEqual(['v-gamma']);
  });

  it('9b q partial substring matches across all three fields', async () => {
    // "3333" matches v-gamma (mobile). "Bo" matches v-beta (contact_person). "Delta" matches v-delta (name).
    const r1 = await get('/api/vendors?q=3333', { authorization: 'Bearer tok-owner' });
    expect((r1.json() as Record<string, unknown>[]).map((v) => v['id'])).toEqual(['v-gamma']);
    const r2 = await get('/api/vendors?q=Bo', { authorization: 'Bearer tok-owner' });
    expect((r2.json() as Record<string, unknown>[]).map((v) => v['id'])).toEqual(['v-beta']);
    const r3 = await get('/api/vendors?q=Delta', { authorization: 'Bearer tok-owner' });
    expect((r3.json() as Record<string, unknown>[]).map((v) => v['id'])).toEqual(['v-delta']);
  });

  it('10 q no match → empty array', async () => {
    const r = await get('/api/vendors?q=zzzznomatchzzzz', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('11 empty q → filter omitted (all vendors returned)', async () => {
    const r = await get('/api/vendors?q=', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('12 cross-user isolation — u2 rows never visible', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids).not.toContain('v-u2');
  });

  it('13 cross-company isolation — alt-company rows never visible under default scope', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids).not.toContain('v-alt');
  });

  it('14 owned X-Company-Id override → surfaces alt-company rows', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    const ids = (r.json() as Record<string, unknown>[]).map((v) => v['id']);
    expect(ids).toEqual(['v-alt']);
  });

  it('15 unowned X-Company-Id → falls back to default (co-a)', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('16 no X-Company-Id header → default company scope', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('17 projection strips _id and user_id', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('18 sort by name ASC', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    const names = (r.json() as Record<string, unknown>[]).map((v) => v['name'] as string);
    for (let i = 1; i < names.length; i++) {
      expect(names[i - 1]! <= names[i]!).toBe(true);
    }
    // Verify concrete order: Alpha, Beta, Delta, Gamma
    expect(names).toEqual(['Alpha Parts', 'Beta Tools', 'Delta Enterprise', 'Gamma Workshop']);
  });

  it('19 20000 cap smoke — small fixture fits comfortably', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBeLessThanOrEqual(20000);
  });

  it('20 extra stored fields preserved', async () => {
    const r = await get('/api/vendors?q=Beta', { authorization: 'Bearer tok-owner' });
    const row = (r.json() as Record<string, unknown>[])[0]!;
    expect(row['extra_field']).toBe('preserved');
    expect(row['name']).toBe('Beta Tools');
    expect(row['mobile']).toBe('9222222222');
  });

  it('21 list no auth → 401 Not authenticated', async () => {
    const r = await get('/api/vendors');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('21b list invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('21c list expired session → 401 Session expired', async () => {
    const r = await get('/api/vendors', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ─────────────────────────────── DETAIL ─────────────────────────────

  it('22 detail happy path', async () => {
    const r = await get('/api/vendors/v-alpha', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const row = r.json() as Record<string, unknown>;
    expect(row['id']).toBe('v-alpha');
    expect(row['name']).toBe('Alpha Parts');
    expect(row).not.toHaveProperty('_id');
    expect(row).not.toHaveProperty('user_id');
  });

  it('23 detail missing → 404 "Vendor not found"', async () => {
    const r = await get('/api/vendors/does-not-exist', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Vendor not found' });
  });

  it('24 detail cross-user → 404', async () => {
    const r = await get('/api/vendors/v-u2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Vendor not found' });
  });

  it('25 detail cross-company (correct user, wrong company) → 404', async () => {
    const r = await get('/api/vendors/v-alt', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Vendor not found' });
  });

  it('26 detail inactive vendor STILL RETURNED (no is_active filter)', async () => {
    const r = await get('/api/vendors/v-gamma', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const row = r.json() as Record<string, unknown>;
    expect(row['id']).toBe('v-gamma');
    expect(row['is_active']).toBe(false);
  });

  it('27 detail owned X-Company-Id override → alt-company row accessible', async () => {
    const r = await get('/api/vendors/v-alt', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(r.statusCode).toBe(200);
    const row = r.json() as Record<string, unknown>;
    expect(row['id']).toBe('v-alt');
  });

  it('27b detail extra fields preserved', async () => {
    const r = await get('/api/vendors/v-beta', { authorization: 'Bearer tok-owner' });
    const row = r.json() as Record<string, unknown>;
    expect(row['extra_field']).toBe('preserved');
  });

  it('28 detail no auth → 401 Not authenticated', async () => {
    const r = await get('/api/vendors/v-alpha');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('28b detail invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/vendors/v-alpha', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('28c detail expired session → 401 Session expired', async () => {
    const r = await get('/api/vendors/v-alpha', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ─────────────────────────────── AGGREGATE ───────────────────────────

  it('29 zero Node business writes across every branch', async () => {
    // List branches
    await get('/api/vendors', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?active_only=true', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?active_only=false', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?active_only=yes', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?active_only=maybe', { authorization: 'Bearer tok-owner' }); // 422
    await get('/api/vendors?q=alpha', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?q=9222222222', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?q=Charlie', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?q=zzznomatch', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors?q=', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/vendors', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/vendors');                                    // 401
    await get('/api/vendors', { authorization: 'Bearer nope' });  // 401
    await get('/api/vendors', { authorization: 'Bearer tok-expired' }); // 401
    // Detail branches
    await get('/api/vendors/v-alpha', { authorization: 'Bearer tok-owner' });
    await get('/api/vendors/v-gamma', { authorization: 'Bearer tok-owner' }); // inactive still visible
    await get('/api/vendors/does-not-exist', { authorization: 'Bearer tok-owner' }); // 404
    await get('/api/vendors/v-u2', { authorization: 'Bearer tok-owner' });    // 404
    await get('/api/vendors/v-alt', { authorization: 'Bearer tok-owner' });   // 404
    await get('/api/vendors/v-alt', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/vendors/v-alpha');                                        // 401
    expect(state.writes).toEqual([]);
  });
});
