/**
 * TRUKVIA · Phase-3 · Gate-7e · Supplier vehicles list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/suppliers/{sid}/vehicles
 *
 * Fake-DB inline-duplicated from the Gate-6k pattern
 * (test/route-suppliers-list.test.ts). Shared / locked test infrastructure
 * is NOT touched — every helper below is local to this file.
 *
 * Supported operators (inline):
 *   * plain equality
 *   * $or  (top-level, branches recurse via matches())
 *   * $regex + $options (case-insensitive when 'i')
 *   * findOne / find(...).sort([[k,1]]).limit(n).toArray()
 *   * projection with include-list ({_id:0, name:1}) and exclude-list
 *     ({_id:0, user_id:0})
 *   * forbid() write-violation matcher on every mutation method
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
  suppliers: Record<string, unknown>[];
  vehicles: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

// ── Gate-7e-only operator support (inline; no shared infra touched) ──
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
    : name === 'suppliers' ? state.suppliers
    : name === 'vehicles' ? state.vehicles
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
function veh(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user_id: 'u1', company_id: 'co-a', vehicle_type: 'supplier',
    supplier_id: '', supplier_name: '',
    ...overrides,
  };
}

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-owner',   user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST()   },
      { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
    ],
    users: [
      { user_id: 'u1', email: 'u1@x' },
      { user_id: 'u2', email: 'u2@x' },
    ],
    companies: [
      { id: 'co-a',     user_id: 'u1', is_default: true,  name: 'Acme Co' },
      { id: 'co-a-alt', user_id: 'u1', is_default: false, name: 'Acme Alt' },
      { id: 'co-b',     user_id: 'u2', is_default: true,  name: 'Beta Co' },
    ],
    suppliers: [
      // u1 / co-a
      { id: 'sup-1', user_id: 'u1', company_id: 'co-a', name: 'Acme Transport', is_active: true },
      { id: 'sup-2', user_id: 'u1', company_id: 'co-a', name: 'Beta Freight',   is_active: true },
      // inactive supplier with regex-metacharacter name (bracket char class)
      { id: 'sup-3', user_id: 'u1', company_id: 'co-a', name: 'Gamma [X]',       is_active: false },
      // u1 / co-a-alt
      { id: 'sup-alt', user_id: 'u1', company_id: 'co-a-alt', name: 'Alt Supplier', is_active: true },
      // u2 / co-b — SAME NAME as sup-1 to exercise cross-user isolation
      { id: 'sup-cross', user_id: 'u2', company_id: 'co-b', name: 'Acme Transport', is_active: true },
    ],
    vehicles: [
      // u1 / co-a — sup-1 matches
      veh({ id: 'v1', vehicle_number: 'KA01AA0001', supplier_id: 'sup-1', supplier_name: 'Different Name' }),
      veh({ id: 'v2', vehicle_number: 'KA01AA0002', supplier_id: '',      supplier_name: 'Acme Transport' }),
      veh({ id: 'v3', vehicle_number: 'KA01AA0003', supplier_id: '',      supplier_name: 'acme transport' }),
      veh({ id: 'v4', vehicle_number: 'KA01AA0004', supplier_id: '',      supplier_name: 'ACME TRANSPORT' }),
      // No match for sup-1
      veh({ id: 'v5', vehicle_number: 'KA01AA0005', supplier_id: '',      supplier_name: 'Not Acme'       }),
      // Wrong vehicle_type — excluded despite supplier_id=sup-1
      veh({ id: 'v6', vehicle_number: 'KA01AA0006', supplier_id: 'sup-1', supplier_name: '',              vehicle_type: 'own' }),
      // sup-3 (inactive) matches — id branch + regex-metachar branch
      veh({ id: 'v-i1', vehicle_number: 'KA01AA0100', supplier_id: 'sup-3', supplier_name: 'irrelevant' }),
      veh({ id: 'v-i2', vehicle_number: 'KA01AA0101', supplier_id: '',      supplier_name: 'Gamma X'    }),
      // u1 / co-a-alt (company isolation)
      veh({ id: 'v-alt-1', company_id: 'co-a-alt', vehicle_number: 'KA01AA0201', supplier_id: 'sup-alt', supplier_name: 'Alt Supplier' }),
      veh({ id: 'v-alt-2', company_id: 'co-a-alt', vehicle_number: 'KA01AA0202', supplier_id: '',       supplier_name: 'alt supplier' }),
      // u2 / co-b — cross-user isolation
      veh({ id: 'v-cross', user_id: 'u2', company_id: 'co-b', vehicle_number: 'KA01AA0007', supplier_id: 'sup-cross', supplier_name: 'must not leak' }),
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

const idsOf = (rows: Record<string, unknown>[]): unknown[] => rows.map((r) => r['id']);

describe('Gate-7e · Supplier vehicles list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── Auth 401 literals ──────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('4 auth precedence — no bearer + missing sid → 401 (not 404)', async () => {
    const r = await get('/api/suppliers/does-not-exist/vehicles');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  // ── Supplier precheck / 404 ────────────────────────────────────────
  it('5 missing supplier → 404 Supplier not found', async () => {
    const r = await get('/api/suppliers/does-not-exist/vehicles', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Supplier not found' });
  });

  it('6 wrong-user supplier (u1 accesses u2\'s sup-cross) → 404', async () => {
    const r = await get('/api/suppliers/sup-cross/vehicles', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
  });

  it('7 wrong-company (owned X-Company-Id co-a-alt, sup-1 belongs to co-a) → 404', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(r.statusCode).toBe(404);
  });

  it('8 inactive supplier still succeeds — no is_active predicate', async () => {
    const r = await get('/api/suppliers/sup-3/vehicles', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    // sup-3 name = "Gamma [X]" → regex ^Gamma [X]$/i matches vehicle "Gamma X"
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['v-i1', 'v-i2']);
  });

  it('9 URL-encoded whitespace sid mismatch → 404', async () => {
    const r = await get('/api/suppliers/%20sup-1%20/vehicles', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
  });

  // ── Vehicle matching — $or branches ────────────────────────────────
  it('10 happy path — sup-1 → v1(id) + v2/v3/v4(name-regex) ASC', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['v1', 'v2', 'v3', 'v4']);
  });

  it('11 supplier_id branch wins even with mismatching supplier_name (v1)', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    const rows = r.json() as Record<string, unknown>[];
    const v1 = rows.find((v) => v['id'] === 'v1')!;
    expect(v1['supplier_id']).toBe('sup-1');
    expect(v1['supplier_name']).toBe('Different Name');
  });

  it('12 supplier_name exact-case match (v2)', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.find((v) => v['id'] === 'v2')).toBeDefined();
  });

  it('13 supplier_name case-insensitive match — lower + upper (v3, v4)', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).toContain('v3');
    expect(ids).toContain('v4');
  });

  it('14 wrong vehicle_type ("own") excluded even with supplier_id=sup-1 (v6)', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).not.toContain('v6');
  });

  it('15 non-matching supplier_name excluded (v5)', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).not.toContain('v5');
  });

  it('16 valid supplier with no matches → 200 []', async () => {
    const r = await get('/api/suppliers/sup-2/vehicles', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  // ── Regex — unescaped, anchored, case-insensitive ──────────────────
  it('17 regex metacharacters in supplier.name — unescaped char class `[X]` matches "Gamma X"', async () => {
    // sup-3 name = "Gamma [X]" ⇒ pattern ^Gamma [X]$ with /i.
    // In PCRE and JS RegExp, `[X]` is a char class of {X}, so pattern
    // matches exactly "Gamma X" (7 chars). Verifies NO route-side escape.
    const r = await get('/api/suppliers/sup-3/vehicles', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const rows = r.json() as Record<string, unknown>[];
    const vi2 = rows.find((v) => v['id'] === 'v-i2')!;
    expect(vi2).toBeDefined();
    expect(vi2['supplier_name']).toBe('Gamma X');
  });

  it('18 anchored regex — supplier_name "Not Acme" does not partially match "Acme Transport"', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).not.toContain('v5');
  });

  // ── Isolation ──────────────────────────────────────────────────────
  it('19 cross-company vehicle (v-alt-*) not surfaced under default co-a', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).not.toContain('v-alt-1');
    expect(ids).not.toContain('v-alt-2');
  });

  it('20 owned X-Company-Id co-a-alt + sup-alt → returns v-alt-1, v-alt-2', async () => {
    const r = await get('/api/suppliers/sup-alt/vehicles', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['v-alt-1', 'v-alt-2']);
  });

  it('21 unowned X-Company-Id co-b → fallback to co-a → sup-1 rows', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['v1', 'v2', 'v3', 'v4']);
  });

  it('22 no X-Company-Id header → default co-a scope', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['v1', 'v2', 'v3', 'v4']);
  });

  it('23 cross-user u2 → sup-cross → returns v-cross only (same name does not leak)', async () => {
    const r = await get('/api/suppliers/sup-cross/vehicles', { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['v-cross']);
  });

  it('24 u2 → sup-1 (belongs to u1) → 404', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(404);
  });

  // ── Response contract ──────────────────────────────────────────────
  it('25 response shape — bare array', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    expect(Array.isArray(r.json())).toBe(true);
  });

  it('26 projection strips _id and user_id, preserves other fields', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
      expect(row).toHaveProperty('id');
      expect(row).toHaveProperty('vehicle_number');
      expect(row).toHaveProperty('vehicle_type');
      expect(row).toHaveProperty('company_id');
    }
  });

  it('27 sort by vehicle_number ASC verified', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    const nums = (r.json() as Record<string, unknown>[]).map((v) => v['vehicle_number'] as string);
    const sorted = nums.slice().sort();
    expect(nums).toEqual(sorted);
  });

  it('28 500-row cap smoke — small fixture fits', async () => {
    const r = await get('/api/suppliers/sup-1/vehicles', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBeLessThanOrEqual(500);
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('29 zero Node business writes across every branch', async () => {
    await get('/api/suppliers/sup-1/vehicles',            { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-2/vehicles',            { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-3/vehicles',            { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-alt/vehicles',          { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/suppliers/does-not-exist/vehicles',   { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-cross/vehicles',        { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-1/vehicles',            { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/suppliers/sup-1/vehicles',            { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/suppliers/sup-cross/vehicles',        { authorization: 'Bearer tok-u2' });
    await get('/api/suppliers/sup-1/vehicles',            { authorization: 'Bearer tok-u2' });
    await get('/api/suppliers/%20sup-1%20/vehicles',      { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-1/vehicles');
    await get('/api/suppliers/sup-1/vehicles',            { authorization: 'Bearer nope' });
    await get('/api/suppliers/sup-1/vehicles',            { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
