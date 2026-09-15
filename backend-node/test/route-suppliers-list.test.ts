/**
 * TRUKVIA · Phase-3 · Gate-6k · Supplier master list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/suppliers
 *
 * Fake-DB write-forbid pattern reused from Gates 6c–6j.
 * Gate-6k-only fake-DB extension: `$regex` + `$or` support added
 * INLINE in this file (Mongo-style case-insensitive regex). Shared /
 * locked test infrastructure is NOT touched.
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
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

// ── Gate-6k-only operator support (inline; no shared infra touched) ──
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
function sup(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 's-x', user_id: 'u1', company_id: 'co-a',
    name: 'Supplier X', mobile: '9999999999', contact_person: 'PersonX',
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
    suppliers: [
      sup({ id: 's-alpha', name: 'Alpha Freight',   mobile: '9111111111', contact_person: 'Alice',   is_active: true }),
      sup({ id: 's-beta',  name: 'Beta Logistics',  mobile: '9222222222', contact_person: 'Bob',     is_active: true, extra_field: 'preserved' }),
      sup({ id: 's-gamma', name: 'Gamma Transport', mobile: '9333333333', contact_person: 'Charlie', is_active: false }),
      sup({ id: 's-delta', name: 'Delta Carriers',  mobile: '9444444444', contact_person: 'Dave',    is_active: true }),
      // Same-user alt company
      sup({ id: 's-alt', user_id: 'u1', company_id: 'co-a-alt', name: 'Alt Supplier', mobile: '9555555555', contact_person: 'Eve' }),
      // Cross-user isolation
      sup({ id: 's-u2', user_id: 'u2', company_id: 'co-b', name: 'U2 Supplier', mobile: '9666666666', contact_person: 'Frank' }),
    ],
    writes: [],
  };
}

const VISIBLE_UNDER_CO_A = 4;
const ACTIVE_UNDER_CO_A = 3;

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6k · Supplier list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 happy path — returns all visible suppliers under default company', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('2 active_only=true → filters inactive', async () => {
    const r = await get('/api/suppliers?active_only=true', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((s) => s['id']);
    expect(ids.length).toBe(ACTIVE_UNDER_CO_A);
    expect(ids).not.toContain('s-gamma');
  });

  it('3 active_only=false → all suppliers', async () => {
    const r = await get('/api/suppliers?active_only=false', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('3b active_only omitted → default false', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  for (const token of ['true', 'True', 'TRUE', 'yes', 'YES', '1', 'on', 'ON', 't', 'T']) {
    it(`4.${token} active_only=${token} → filters inactive`, async () => {
      const r = await get(`/api/suppliers?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      expect((r.json() as unknown[]).length).toBe(ACTIVE_UNDER_CO_A);
    });
  }

  for (const token of ['false', 'False', 'FALSE', 'no', 'NO', '0', 'off', 'OFF', 'f', 'F', 'n', 'N']) {
    it(`5.${token} active_only=${token} → all suppliers`, async () => {
      const r = await get(`/api/suppliers?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
    });
  }

  for (const token of ['maybe', '2', '1.0', 'yesplease', '']) {
    it(`6.${JSON.stringify(token)} invalid boolean → 422`, async () => {
      const r = await get(`/api/suppliers?active_only=${encodeURIComponent(token)}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(422);
    });
  }

  it('7 q matches name (case-insensitive)', async () => {
    const r = await get('/api/suppliers?q=alpha', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((s) => s['id']);
    expect(ids).toEqual(['s-alpha']);
  });

  it('7b q matches name UPPERCASE', async () => {
    const r = await get('/api/suppliers?q=ALPHA', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((s) => s['id']);
    expect(ids).toEqual(['s-alpha']);
  });

  it('8 q matches mobile', async () => {
    const r = await get('/api/suppliers?q=9222222222', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((s) => s['id'])).toEqual(['s-beta']);
  });

  it('9 q matches contact_person', async () => {
    const r = await get('/api/suppliers?q=Charlie', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((s) => s['id'])).toEqual(['s-gamma']);
  });

  it('9b q partial substring matches across fields', async () => {
    const r1 = await get('/api/suppliers?q=3333', { authorization: 'Bearer tok-owner' });
    expect((r1.json() as Record<string, unknown>[]).map((s) => s['id'])).toEqual(['s-gamma']);
    const r2 = await get('/api/suppliers?q=Bo', { authorization: 'Bearer tok-owner' });
    expect((r2.json() as Record<string, unknown>[]).map((s) => s['id'])).toEqual(['s-beta']);
    const r3 = await get('/api/suppliers?q=Delta', { authorization: 'Bearer tok-owner' });
    expect((r3.json() as Record<string, unknown>[]).map((s) => s['id'])).toEqual(['s-delta']);
  });

  it('10 q no match → empty array', async () => {
    const r = await get('/api/suppliers?q=zzznomatchzzz', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('11 empty q → filter omitted', async () => {
    const r = await get('/api/suppliers?q=', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('11b active_only + q combined', async () => {
    const r = await get('/api/suppliers?active_only=true&q=Beta', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((s) => s['id'])).toEqual(['s-beta']);
  });

  it('12 cross-user isolation', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((s) => s['id']);
    expect(ids).not.toContain('s-u2');
  });

  it('13 cross-company isolation', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((s) => s['id']);
    expect(ids).not.toContain('s-alt');
  });

  it('14 owned X-Company-Id override → surfaces alt-company rows', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect((r.json() as Record<string, unknown>[]).map((s) => s['id'])).toEqual(['s-alt']);
  });

  it('15 unowned X-Company-Id → default fallback', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('16 no X-Company-Id header → default scope', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE_UNDER_CO_A);
  });

  it('17 projection strips _id/user_id', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('18 sort by name ASC', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    const names = (r.json() as Record<string, unknown>[]).map((s) => s['name'] as string);
    expect(names).toEqual(['Alpha Freight', 'Beta Logistics', 'Delta Carriers', 'Gamma Transport']);
  });

  it('19 20000 cap smoke — small fixture fits', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBeLessThanOrEqual(20000);
  });

  it('20 extra stored fields preserved', async () => {
    const r = await get('/api/suppliers?q=Beta', { authorization: 'Bearer tok-owner' });
    const row = (r.json() as Record<string, unknown>[])[0]!;
    expect(row['extra_field']).toBe('preserved');
    expect(row['name']).toBe('Beta Logistics');
  });

  it('21 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/suppliers');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('21b invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('21c expired → 401 Session expired', async () => {
    const r = await get('/api/suppliers', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('22 zero Node business writes across every branch', async () => {
    await get('/api/suppliers', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?active_only=true', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?active_only=false', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?active_only=yes', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?active_only=maybe', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?q=alpha', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?q=9222222222', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?q=Charlie', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?q=zzznomatch', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?q=', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers?active_only=true&q=Beta', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/suppliers', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/suppliers');
    await get('/api/suppliers', { authorization: 'Bearer nope' });
    await get('/api/suppliers', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
