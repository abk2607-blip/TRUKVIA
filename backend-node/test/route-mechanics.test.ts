/**
 * TRUKVIA · Phase-3 · Gate-6l · Mechanic master read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/mechanics
 *   GET /api/mechanics/{mid}
 *
 * Fake-DB write-forbid pattern reused from Gates 6c–6k.
 * Gate-6l-only fake-DB extension: `$regex` + `$or` support added
 * INLINE (Mongo-style case-insensitive regex over `name`, `mobile`,
 * `skill`). Shared / locked test infrastructure is NOT touched.
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
  mechanics: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function matchOperator(dv: unknown, cond: Record<string, unknown>): boolean {
  if ('$regex' in cond) {
    if (typeof dv !== 'string') return false;
    const flags = typeof cond['$options'] === 'string' ? (cond['$options'] as string) : '';
    return new RegExp(cond['$regex'] as string, flags).test(dv);
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
    : name === 'mechanics' ? state.mechanics
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

function mech(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'm-x', user_id: 'u1', company_id: 'co-a',
    name: 'Mechanic X', mobile: '9999999999', skill: 'General',
    address: '', is_active: true,
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
    mechanics: [
      mech({ id: 'm-alpha', name: 'Alpha Motors',    mobile: '9111111111', skill: 'Engine',      is_active: true }),
      mech({ id: 'm-beta',  name: 'Beta Garage',     mobile: '9222222222', skill: 'Brakes',      is_active: true, extra_field: 'preserved' }),
      mech({ id: 'm-gamma', name: 'Gamma Workshop',  mobile: '9333333333', skill: 'Transmission', is_active: false }),
      mech({ id: 'm-delta', name: 'Delta Repair',    mobile: '9444444444', skill: 'Bodywork',    is_active: true }),
      mech({ id: 'm-alt', user_id: 'u1', company_id: 'co-a-alt', name: 'Alt Mechanic', mobile: '9555555555', skill: 'Electrical' }),
      mech({ id: 'm-u2', user_id: 'u2', company_id: 'co-b', name: 'U2 Mechanic', mobile: '9666666666', skill: 'General' }),
    ],
    writes: [],
  };
}

const VISIBLE = 4;
const ACTIVE = 3;

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6l · Mechanic master read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 happy path', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as unknown[]).length).toBe(VISIBLE);
  });

  it('2 active_only=true → filters inactive', async () => {
    const r = await get('/api/mechanics?active_only=true', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((m) => m['id']);
    expect(ids.length).toBe(ACTIVE);
    expect(ids).not.toContain('m-gamma');
  });

  it('3 active_only=false → all', async () => {
    const r = await get('/api/mechanics?active_only=false', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE);
  });

  it('3b active_only omitted → default false', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE);
  });

  for (const token of ['true', 'True', 'TRUE', 'yes', 'YES', '1', 'on', 'ON', 't', 'T']) {
    it(`4.${token} TRUE token`, async () => {
      const r = await get(`/api/mechanics?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect((r.json() as unknown[]).length).toBe(ACTIVE);
    });
  }
  for (const token of ['false', 'False', 'FALSE', 'no', 'NO', '0', 'off', 'OFF', 'f', 'F', 'n', 'N']) {
    it(`5.${token} FALSE token`, async () => {
      const r = await get(`/api/mechanics?active_only=${token}`, { authorization: 'Bearer tok-owner' });
      expect((r.json() as unknown[]).length).toBe(VISIBLE);
    });
  }
  for (const token of ['maybe', '2', '1.0', 'yesplease', '']) {
    it(`6.${JSON.stringify(token)} invalid → 422`, async () => {
      const r = await get(`/api/mechanics?active_only=${encodeURIComponent(token)}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(422);
    });
  }

  it('7 q matches name (case-insensitive lowercase)', async () => {
    const r = await get('/api/mechanics?q=alpha', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-alpha']);
  });
  it('7b q matches name UPPERCASE', async () => {
    const r = await get('/api/mechanics?q=ALPHA', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-alpha']);
  });
  it('8 q matches mobile', async () => {
    const r = await get('/api/mechanics?q=9222222222', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-beta']);
  });
  it('9 q matches SKILL (not contact_person)', async () => {
    const r = await get('/api/mechanics?q=Transmission', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-gamma']);
  });
  it('9b q matches skill lowercase', async () => {
    const r = await get('/api/mechanics?q=brakes', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-beta']);
  });
  it('9c q partial substring', async () => {
    const r1 = await get('/api/mechanics?q=3333', { authorization: 'Bearer tok-owner' });
    expect((r1.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-gamma']);
    const r2 = await get('/api/mechanics?q=Body', { authorization: 'Bearer tok-owner' });
    expect((r2.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-delta']);
  });
  it('10 q no match', async () => {
    const r = await get('/api/mechanics?q=zzznomatch', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
  });
  it('11 empty q ignored', async () => {
    const r = await get('/api/mechanics?q=', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE);
  });
  it('11b active_only + q combined (skill)', async () => {
    // "General" matches only m-x (default fixture id 'm-x') if seeded... instead use Brakes which matches m-beta (active)
    const r = await get('/api/mechanics?active_only=true&q=Brakes', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-beta']);
  });

  it('12 cross-user isolation', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((m) => m['id']);
    expect(ids).not.toContain('m-u2');
  });
  it('13 cross-company isolation', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((m) => m['id']);
    expect(ids).not.toContain('m-alt');
  });
  it('14 owned X-Company-Id override', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect((r.json() as Record<string, unknown>[]).map((m) => m['id'])).toEqual(['m-alt']);
  });
  it('15 unowned X-Company-Id → default fallback', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE);
  });
  it('16 no header → default scope', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(VISIBLE);
  });
  it('17 projection strips _id/user_id', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });
  it('18 sort by name ASC', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    const names = (r.json() as Record<string, unknown>[]).map((m) => m['name'] as string);
    expect(names).toEqual(['Alpha Motors', 'Beta Garage', 'Delta Repair', 'Gamma Workshop']);
  });
  it('19 20000 cap smoke', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBeLessThanOrEqual(20000);
  });
  it('20 extra fields preserved', async () => {
    const r = await get('/api/mechanics?q=Beta', { authorization: 'Bearer tok-owner' });
    const row = (r.json() as Record<string, unknown>[])[0]!;
    expect(row['extra_field']).toBe('preserved');
  });

  it('21 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/mechanics');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });
  it('21b invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });
  it('21c expired → 401 Session expired', async () => {
    const r = await get('/api/mechanics', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ─────── DETAIL ───────
  it('22 detail happy', async () => {
    const r = await get('/api/mechanics/m-alpha', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const row = r.json() as Record<string, unknown>;
    expect(row['id']).toBe('m-alpha');
    expect(row).not.toHaveProperty('_id');
    expect(row).not.toHaveProperty('user_id');
  });
  it('23 detail missing → 404 Mechanic not found', async () => {
    const r = await get('/api/mechanics/does-not-exist', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Mechanic not found' });
  });
  it('24 detail cross-user → 404', async () => {
    const r = await get('/api/mechanics/m-u2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Mechanic not found' });
  });
  it('25 detail cross-company → 404', async () => {
    const r = await get('/api/mechanics/m-alt', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Mechanic not found' });
  });
  it('26 detail INACTIVE mechanic STILL RETURNED (no is_active filter)', async () => {
    const r = await get('/api/mechanics/m-gamma', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const row = r.json() as Record<string, unknown>;
    expect(row['id']).toBe('m-gamma');
    expect(row['is_active']).toBe(false);
  });
  it('27 detail owned X-Company-Id override → alt row', async () => {
    const r = await get('/api/mechanics/m-alt', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>)['id']).toBe('m-alt');
  });
  it('27b detail extra fields preserved', async () => {
    const r = await get('/api/mechanics/m-beta', { authorization: 'Bearer tok-owner' });
    const row = r.json() as Record<string, unknown>;
    expect(row['extra_field']).toBe('preserved');
  });
  it('28 detail no auth → 401', async () => {
    const r = await get('/api/mechanics/m-alpha');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });
  it('28b detail invalid bearer → 401', async () => {
    const r = await get('/api/mechanics/m-alpha', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });
  it('28c detail expired → 401', async () => {
    const r = await get('/api/mechanics/m-alpha', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('29 zero Node business writes across every branch', async () => {
    await get('/api/mechanics', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?active_only=true', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?active_only=false', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?active_only=yes', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?active_only=maybe', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?q=alpha', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?q=Transmission', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?q=9222222222', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?q=zzznomatch', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?q=', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics?active_only=true&q=Brakes', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/mechanics', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/mechanics');
    await get('/api/mechanics', { authorization: 'Bearer nope' });
    await get('/api/mechanics', { authorization: 'Bearer tok-expired' });
    await get('/api/mechanics/m-alpha', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics/m-gamma', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics/does-not-exist', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics/m-u2', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics/m-alt', { authorization: 'Bearer tok-owner' });
    await get('/api/mechanics/m-alt', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/mechanics/m-alpha');
    expect(state.writes).toEqual([]);
  });
});
