/**
 * TRUKVIA · Phase-3 · Gate-7h · Fuel vehicle maps list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/fuel/vehicle-maps
 *
 * Fake-DB inline-duplicated from Gate-7e / Gate-7g pattern. Shared /
 * locked test infrastructure is NOT touched.
 *
 * Supported operators (inline):
 *   * plain equality
 *   * find(...).sort([['source_vehicle_ref', 1]]).limit(n).toArray()
 *   * projection strip-only ({_id: 0, user_id: 0})
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
  fuel_vehicle_maps: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    if (d[k] !== v) return false;
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
    : name === 'fuel_vehicle_maps' ? state.fuel_vehicle_maps
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    function makeCursor(
      f: Record<string, unknown>,
      opts?: { projection?: Record<string, 0 | 1> },
    ): {
      sort: (s: [string, 1 | -1][]) => ReturnType<typeof makeCursor>;
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
        // Gate 9e: routes read Motor-style (async iteration, no server-side limit).
        async *[Symbol.asyncIterator]() { yield* await cursor.toArray(); },
        hasNext: (): Promise<boolean> => cursor.toArray().then((a) => a.length > 0),
        close: (): Promise<void> => Promise.resolve(),
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
function fvm(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user_id: 'u1', company_id: 'co-a',
    source: 'iocl', source_vehicle_ref: 'REF-1',
    vehicle_id: 'v1', vehicle_number: 'AP16TA1234',
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
    fuel_vehicle_maps: [
      // co-a rows (u1) — sorted by source_vehicle_ref ASC across both sources:
      // "IOCL-A" < "IOCL-B" < "BPCL-Z"? actually ASCII: "B" < "I" so:
      //   "BPCL-Z" (0x42) < "IOCL-A" (0x49) < "IOCL-B" (0x49). But test uses full string compare.
      fvm({ id: 'm1', source: 'iocl', source_vehicle_ref: 'IOCL-A' }),
      fvm({ id: 'm2', source: 'iocl', source_vehicle_ref: 'IOCL-B' }),
      fvm({ id: 'm3', source: 'bpcl', source_vehicle_ref: 'BPCL-Z', vehicle_number: 'AP16TA9999' }),
      // Alt-company row for u1:
      fvm({ id: 'm-alt', company_id: 'co-a-alt', source: 'iocl', source_vehicle_ref: 'ALT-IOCL-1' }),
      // Cross-user rows (u2 / co-b):
      fvm({ id: 'm-u2-1', user_id: 'u2', company_id: 'co-b', source: 'iocl', source_vehicle_ref: 'U2-IOCL-1' }),
      fvm({ id: 'm-u2-2', user_id: 'u2', company_id: 'co-b', source: 'bpcl', source_vehicle_ref: 'U2-BPCL-1' }),
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

describe('Gate-7h · Fuel vehicle maps list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── Auth 401 literals ──────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    const r = await get('/api/fuel/vehicle-maps');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── Tenant scoping ─────────────────────────────────────────────────
  it('4 no-header default → co-a → m3 (BPCL-Z) · m1 (IOCL-A) · m2 (IOCL-B) ASC', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  it('5 owned X-Company-Id co-a-alt → only m-alt', async () => {
    const r = await get('/api/fuel/vehicle-maps', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m-alt']);
  });

  it('6 unowned X-Company-Id co-b → fallback co-a → default set', async () => {
    const r = await get('/api/fuel/vehicle-maps', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  it('7 cross-user u2 default → own co-b rows only, ASC', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-u2' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m-u2-2', 'm-u2-1']);
  });

  // ── Source filter — accepted values ────────────────────────────────
  it('8 source=iocl → only iocl rows (m1, m2 ASC)', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=iocl', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m1', 'm2']);
  });

  it('9 source=bpcl → only bpcl rows (m3)', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=bpcl', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3']);
  });

  // ── Source filter — silently ignored (case-sensitive) ──────────────
  it('10 source="" → predicate dropped → base set', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  it('11 source=other → predicate dropped → base set (NO 422)', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=other', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  it('12 source=IOCL (uppercase) → predicate dropped (case-sensitive)', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=IOCL', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  it('13 source=iOcl (mixed) → predicate dropped (case-sensitive)', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=iOcl', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  it('14 source=bp (prefix) → predicate dropped (exact-match only)', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=bp', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  it('15 source=zzz (arbitrary) → 200, base set (NO 422, NO 400)', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=zzz%20%21%40%23', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['m3', 'm1', 'm2']);
  });

  // ── Source filter — exclusion when active ──────────────────────────
  it('16 source=iocl excludes bpcl rows even when both exist', async () => {
    const r = await get('/api/fuel/vehicle-maps?source=iocl', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).not.toContain('m3');
    expect(ids).toEqual(['m1', 'm2']);
  });

  // ── Isolation ──────────────────────────────────────────────────────
  it('17 wrong-user rows excluded (m-u2-*)', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).not.toContain('m-u2-1');
    expect(ids).not.toContain('m-u2-2');
  });

  it('18 wrong-company rows excluded on default (m-alt)', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).not.toContain('m-alt');
  });

  // ── Response shape / projection ────────────────────────────────────
  it('19 projection strips _id AND user_id; all other fields preserved', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
      expect(row).toHaveProperty('id');
      expect(row).toHaveProperty('company_id');
      expect(row).toHaveProperty('source');
      expect(row).toHaveProperty('source_vehicle_ref');
      expect(row).toHaveProperty('vehicle_id');
      expect(row).toHaveProperty('vehicle_number');
    }
  });

  it('20 response is a bare JSON array', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    expect(Array.isArray(r.json())).toBe(true);
  });

  it('21 sort source_vehicle_ref ASC verified across both sources', async () => {
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    const refs = (r.json() as Record<string, unknown>[]).map((v) => v['source_vehicle_ref'] as string);
    const sorted = refs.slice().sort();
    expect(refs).toEqual(sorted);
  });

  it('22 empty tenant → 200 []', async () => {
    // u2 with owned-but-empty co-b-alt-like set: use owned override to a co with no fvm.
    state.companies.push({ id: 'co-a-empty', user_id: 'u1', is_default: false, name: 'Empty' });
    const r = await get('/api/fuel/vehicle-maps', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-empty',
    });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  // ── 5000 cap smoke ─────────────────────────────────────────────────
  it('23 5000 cap: at 5001 fixture rows, response length <= 5000', async () => {
    // Push additional 5000 co-a rows (already have m1-m3 = 3, so total 5003).
    for (let i = 0; i < 5000; i++) {
      state.fuel_vehicle_maps.push(fvm({
        id: `bulk-${i}`, source: 'iocl',
        source_vehicle_ref: `Z-BULK-${String(i).padStart(5, '0')}`,
      }));
    }
    const r = await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const len = (r.json() as unknown[]).length;
    expect(len).toBeLessThanOrEqual(5000);
    expect(len).toBe(5000);
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('24 zero Node business writes across every branch', async () => {
    await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner' });
    await get('/api/fuel/vehicle-maps?source=iocl', { authorization: 'Bearer tok-owner' });
    await get('/api/fuel/vehicle-maps?source=bpcl', { authorization: 'Bearer tok-owner' });
    await get('/api/fuel/vehicle-maps?source=', { authorization: 'Bearer tok-owner' });
    await get('/api/fuel/vehicle-maps?source=other', { authorization: 'Bearer tok-owner' });
    await get('/api/fuel/vehicle-maps?source=IOCL', { authorization: 'Bearer tok-owner' });
    await get('/api/fuel/vehicle-maps?source=iOcl', { authorization: 'Bearer tok-owner' });
    await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-u2' });
    await get('/api/fuel/vehicle-maps');
    await get('/api/fuel/vehicle-maps', { authorization: 'Bearer nope' });
    await get('/api/fuel/vehicle-maps', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
