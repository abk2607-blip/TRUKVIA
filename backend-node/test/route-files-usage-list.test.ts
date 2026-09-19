/**
 * TRUKVIA · Phase-3 · Gate-7j · Files-usage summary read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/files/usage
 *
 * Fake-DB inline-duplicated from Gate-7i pattern. Shared / locked test
 * infrastructure is NOT touched.
 *
 * NEW parity axis for Gate 7j:
 *   Application-side aggregation with 5 fixed response keys —
 *   total_bytes, limit_bytes, pct, file_count, by_category.
 *   Verbatim Python semantics:
 *     * `int(d.get("size", 0) or 0)` truncation
 *     * key-based `d.get("category", "general")` default (missing key
 *       only — null/empty key values are preserved literally)
 *     * `by_cat` insertion-order preserved
 *     * `pct = round(min(100, total/limit*100), 2)`
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
  files: Record<string, unknown>[];
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
    : name === 'files' ? state.files
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

// ── Fixture ─────────────────────────────────────────────────────────
function makeState(files: Record<string, unknown>[] = []): State {
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
      { id: 'co-a', user_id: 'u1', is_default: true, name: 'Acme Co' },
      { id: 'co-b', user_id: 'u2', is_default: true, name: 'Beta Co' },
    ],
    files,
    writes: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const LIMIT_BYTES = 500 * 1024 * 1024; // 524288000

describe('Gate-7j · Files usage summary read-only shadow (USER-SCOPED)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  const setup = async (files: Record<string, unknown>[]) => {
    state = makeState(files);
    app = await makeApp(state);
  };

  afterEach(async () => { if (app) await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── Auth 401 literals ──────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    await setup([]);
    const r = await get('/api/files/usage');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    await setup([]);
    const r = await get('/api/files/usage', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    await setup([]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── Empty aggregation ──────────────────────────────────────────────
  it('4 empty files → zero-usage response with fixed shape', async () => {
    await setup([]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({
      total_bytes: 0, limit_bytes: LIMIT_BYTES, pct: 0,
      file_count: 0, by_category: {},
    });
  });

  // ── Single file ────────────────────────────────────────────────────
  it('5 one file (general, 1000 bytes)', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const expectedPct = Math.round((1000 / LIMIT_BYTES) * 100 * 100) / 100;
    expect(r.json()).toEqual({
      total_bytes: 1000, limit_bytes: LIMIT_BYTES, pct: expectedPct,
      file_count: 1, by_category: { general: 1000 },
    });
  });

  // ── Multiple files same category ───────────────────────────────────
  it('6 multiple files same category accumulate', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general' },
      { user_id: 'u1', is_deleted: false, size: 2000, category: 'general' },
      { user_id: 'u1', is_deleted: false, size: 500,  category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(3500);
    expect(body.file_count).toBe(3);
    expect(body.by_category).toEqual({ general: 3500 });
  });

  // ── Multiple categories ────────────────────────────────────────────
  it('7 multiple categories tracked separately', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general' },
      { user_id: 'u1', is_deleted: false, size: 2500, category: 'invoice' },
      { user_id: 'u1', is_deleted: false, size: 800,  category: 'vehicle' },
      { user_id: 'u1', is_deleted: false, size: 200,  category: 'invoice' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(4500);
    expect(body.file_count).toBe(4);
    expect(body.by_category).toEqual({ general: 1000, invoice: 2700, vehicle: 800 });
  });

  // ── USER-ONLY scope ────────────────────────────────────────────────
  it('8 same user across different company_id values still counted', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general', company_id: 'co-a' },
      { user_id: 'u1', is_deleted: false, size: 2000, category: 'general', company_id: 'co-a-alt' },
      { user_id: 'u1', is_deleted: false, size: 3000, category: 'general' /* no company_id */ },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(6000);
    expect(body.file_count).toBe(3);
  });

  it('9 X-Company-Id header MUST NOT narrow the aggregate', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general', company_id: 'co-a' },
      { user_id: 'u1', is_deleted: false, size: 2000, category: 'general', company_id: 'co-a-alt' },
    ]);
    const rNoHdr = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const rHdr   = await get('/api/files/usage', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(rHdr.json()).toEqual(rNoHdr.json());
  });

  it('10 cross-user u2 excluded', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general' },
      { user_id: 'u2', is_deleted: false, size: 9999, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(1000);
    expect(body.file_count).toBe(1);
  });

  // ── Deleted semantics ──────────────────────────────────────────────
  it('11 is_deleted=true excluded from aggregate', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general' },
      { user_id: 'u1', is_deleted: true,  size: 9999, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(1000);
    expect(body.file_count).toBe(1);
  });

  it('12 missing is_deleted field excluded (exact-equality {is_deleted: false})', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 1000, category: 'general' },
      { user_id: 'u1',                    size: 9999, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(1000);
    expect(body.file_count).toBe(1);
  });

  // ── Category default (Python d.get("category", "general")) ─────────
  it('13 missing category key → default "general"', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 500 /* no category */ },
      { user_id: 'u1', is_deleted: false, size: 700 /* no category */ },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.by_category).toEqual({ general: 1200 });
    expect(body.total_bytes).toBe(1200);
  });

  it('14 empty-string category preserved as literal key ("" — Python key-based default only applies to missing)', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 400, category: '' },
      { user_id: 'u1', is_deleted: false, size: 600, category: 'invoice' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.by_category).toEqual({ '': 400, invoice: 600 });
  });

  // ── Size normalization (int(d.get("size", 0) or 0)) ────────────────
  it('15 missing size → 0', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, category: 'general' /* no size */ },
      { user_id: 'u1', is_deleted: false, size: 100, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(100);
    expect(body.file_count).toBe(2);
    expect(body.by_category).toEqual({ general: 100 });
  });

  it('16 size 0 → contributes 0 but still counted in file_count', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 0, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.total_bytes).toBe(0);
    expect(body.file_count).toBe(1);
    expect(body.by_category).toEqual({ general: 0 });
  });

  // ── Pct calc / cap ─────────────────────────────────────────────────
  it('17 total > limit → pct capped at 100', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: LIMIT_BYTES + 1_000_000, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.pct).toBe(100);
    expect(body.total_bytes).toBe(LIMIT_BYTES + 1_000_000);
  });

  it('18 exact 50% pct', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: LIMIT_BYTES / 2, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.pct).toBe(50);
  });

  // ── Response shape ─────────────────────────────────────────────────
  it('19 response has EXACTLY 5 top-level keys, no extras', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 100, category: 'general' },
    ]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const keys = Object.keys(r.json() as Record<string, unknown>).sort();
    expect(keys).toEqual(['by_category', 'file_count', 'limit_bytes', 'pct', 'total_bytes']);
  });

  it('20 limit_bytes always exactly 500 * 1024 * 1024', async () => {
    await setup([{ user_id: 'u1', is_deleted: false, size: 1, category: 'general' }]);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    expect((r.json() as Record<string, unknown>).limit_bytes).toBe(524288000);
  });

  // ── 5000 cap ───────────────────────────────────────────────────────
  it('21 5000 read cap: at 5001 files, file_count ≤ 5000', async () => {
    const files: Record<string, unknown>[] = [];
    for (let i = 0; i < 5001; i++) {
      files.push({ user_id: 'u1', is_deleted: false, size: 1, category: 'bulk' });
    }
    await setup(files);
    const r = await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(body.file_count).toBe(5000);
    expect(body.total_bytes).toBe(5000);
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('22 zero Node business writes across every branch', async () => {
    await setup([
      { user_id: 'u1', is_deleted: false, size: 100, category: 'general' },
      { user_id: 'u1', is_deleted: false, size: 200, category: 'invoice' },
      { user_id: 'u1', is_deleted: true,  size: 999, category: 'invoice' },
      { user_id: 'u2', is_deleted: false, size: 300, category: 'general' },
    ]);
    await get('/api/files/usage', { authorization: 'Bearer tok-owner' });
    await get('/api/files/usage', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/files/usage', { authorization: 'Bearer tok-u2' });
    await get('/api/files/usage');
    await get('/api/files/usage', { authorization: 'Bearer nope' });
    await get('/api/files/usage', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
