/**
 * TRUKVIA · Phase-3 · Gate-7i · Files list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/files
 *
 * Fake-DB inline-duplicated from Gate-7e / Gate-7g / Gate-7h pattern.
 * Shared / locked test infrastructure is NOT touched.
 *
 * Supported operators (inline):
 *   * plain equality (including `is_deleted: false` exact match)
 *   * find(...).sort([['created_at', -1]]).limit(n).toArray()
 *   * projection strip-only ({_id: 0, user_id: 0})
 *   * forbid() write-violation matcher on every mutation method
 *
 * NEW parity axis for Gate 7i:
 *   USER-ONLY scope — NO company_id predicate. Same user across multiple
 *   company_id values must remain visible.
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

// Plain-equality matcher — reproduces Python Mongo semantics:
//   `{"is_deleted": False}` matches ONLY docs where the field is
//   exactly false. Missing / null / true are all excluded.
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

// ── Fixture helpers ─────────────────────────────────────────────────
function fr(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user_id: 'u1', is_deleted: false,
    category: 'general', linked_type: '', linked_id: '',
    storage_path: 'bitumen-accounting/uploads/u1/aaa.jpg',
    original_filename: 'aaa.jpg', content_type: 'image/jpeg', size: 12345,
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
    files: [
      // u1 rows — MIXED company_id values MUST remain visible (user-only scope).
      fr({ id: 'f1', created_at: '2026-01-01T10:00:00Z', category: 'general' }),
      fr({ id: 'f2', created_at: '2026-01-02T10:00:00Z', category: 'invoice', linked_type: 'invoice', linked_id: 'inv-9' }),
      fr({ id: 'f3', created_at: '2026-01-03T10:00:00Z', category: 'vehicle', linked_type: 'vehicle', linked_id: 'v-7', company_id: 'co-a' }),
      fr({ id: 'f-alt', created_at: '2026-01-04T10:00:00Z', category: 'general', company_id: 'co-a-alt' }),
      fr({ id: 'f-nocid', created_at: '2026-01-05T10:00:00Z', category: 'general' }), // no company_id field
      // Deleted rows — MUST be excluded.
      fr({ id: 'f-del', created_at: '2026-01-06T10:00:00Z', is_deleted: true }),
      // Missing is_deleted field — Python's exact-equality {is_deleted: False} EXCLUDES.
      { user_id: 'u1', id: 'f-nodel', created_at: '2026-01-07T10:00:00Z', category: 'general', storage_path: 'x', original_filename: 'x', content_type: 'image/png', size: 1 },
      // Cross-user (u2) — MUST be excluded.
      fr({ id: 'f-u2-1', user_id: 'u2', company_id: 'co-b', created_at: '2026-01-08T10:00:00Z', category: 'general' }),
      fr({ id: 'f-u2-2', user_id: 'u2', company_id: 'co-b', created_at: '2026-01-09T10:00:00Z', category: 'invoice', linked_type: 'invoice', linked_id: 'inv-U2' }),
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

describe('Gate-7i · Files list read-only shadow (USER-SCOPED)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── Auth 401 literals ──────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    const r = await get('/api/files');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/files', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── USER-ONLY SCOPE (CRITICAL Gate 7i axis) ────────────────────────
  it('4 no query → all u1 non-deleted rows across ALL company_id values DESC', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    // f-nodel is excluded (missing is_deleted); f-del excluded (is_deleted:true).
    // f-alt (co-a-alt), f3 (co-a), f-nocid (no company_id) all remain visible.
    // created_at DESC: f-nocid(01-05) > f-alt(01-04) > f3(01-03) > f2(01-02) > f1(01-01).
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f-nocid', 'f-alt', 'f3', 'f2', 'f1']);
  });

  it('5 X-Company-Id header MUST NOT narrow — same u1 rows returned regardless', async () => {
    const rNoHdr = await get('/api/files', { authorization: 'Bearer tok-owner' });
    const rAlt   = await get('/api/files', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    const rB     = await get('/api/files', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect(idsOf(rAlt.json() as Record<string, unknown>[])).toEqual(idsOf(rNoHdr.json() as Record<string, unknown>[]));
    expect(idsOf(rB.json() as Record<string, unknown>[])).toEqual(idsOf(rNoHdr.json() as Record<string, unknown>[]));
  });

  it('6 cross-user u2 → only u2 rows (f-u2-2, f-u2-1 DESC)', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-u2' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f-u2-2', 'f-u2-1']);
  });

  it('7 wrong-user rows excluded from u1 result', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).not.toContain('f-u2-1');
    expect(ids).not.toContain('f-u2-2');
  });

  // ── Deleted semantics (exact Python {is_deleted: False}) ───────────
  it('8 is_deleted=true excluded (f-del)', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).not.toContain('f-del');
  });

  it('9 missing is_deleted field excluded (exact-equality semantics — no $ne guard)', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-owner' });
    const ids = idsOf(r.json() as Record<string, unknown>[]);
    expect(ids).not.toContain('f-nodel');
  });

  // ── category filter ────────────────────────────────────────────────
  it('10 category=general → f-nocid, f-alt, f1 DESC', async () => {
    const r = await get('/api/files?category=general', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f-nocid', 'f-alt', 'f1']);
  });

  it('11 category=invoice → only f2', async () => {
    const r = await get('/api/files?category=invoice', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f2']);
  });

  it('12 category=General (uppercase) → [] (case-sensitive)', async () => {
    const r = await get('/api/files?category=General', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
  });

  it('13 category=nonexistent → []', async () => {
    const r = await get('/api/files?category=nonexistent', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
  });

  it('14 blank category → predicate dropped → full default set', async () => {
    const r = await get('/api/files?category=', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f-nocid', 'f-alt', 'f3', 'f2', 'f1']);
  });

  // ── linked_type / linked_id filters ────────────────────────────────
  it('15 linked_type=invoice → only f2', async () => {
    const r = await get('/api/files?linked_type=invoice', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f2']);
  });

  it('16 linked_id=v-7 → only f3', async () => {
    const r = await get('/api/files?linked_id=v-7', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f3']);
  });

  it('17 blank linked_type → predicate dropped', async () => {
    const r = await get('/api/files?linked_type=', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f-nocid', 'f-alt', 'f3', 'f2', 'f1']);
  });

  it('18 blank linked_id → predicate dropped', async () => {
    const r = await get('/api/files?linked_id=', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f-nocid', 'f-alt', 'f3', 'f2', 'f1']);
  });

  // ── Combined filters ───────────────────────────────────────────────
  it('19 category=invoice + linked_type=invoice + linked_id=inv-9 → f2', async () => {
    const r = await get('/api/files?category=invoice&linked_type=invoice&linked_id=inv-9', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['f2']);
  });

  it('20 conflicting combo → []', async () => {
    const r = await get('/api/files?category=invoice&linked_id=nope', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
  });

  // ── Response shape / projection ────────────────────────────────────
  it('21 projection strips _id AND user_id; all other fields preserved', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
      expect(row).toHaveProperty('id');
      expect(row).toHaveProperty('is_deleted');
      expect(row).toHaveProperty('storage_path');
      expect(row).toHaveProperty('original_filename');
      expect(row).toHaveProperty('created_at');
    }
  });

  it('22 response is a bare JSON array', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-owner' });
    expect(Array.isArray(r.json())).toBe(true);
  });

  it('23 sort created_at DESC verified', async () => {
    const r = await get('/api/files', { authorization: 'Bearer tok-owner' });
    const ts = (r.json() as Record<string, unknown>[]).map((v) => v['created_at'] as string);
    const sorted = ts.slice().sort().reverse();
    expect(ts).toEqual(sorted);
  });

  it('24 empty user → 200 []', async () => {
    // Use a session whose user has no files
    state.sessions.push({ session_token: 'tok-u3', user_id: 'u3', effective_role: 'owner', expires_at: IN_FUTURE() });
    state.users.push({ user_id: 'u3', email: 'u3@x' });
    const r = await get('/api/files', { authorization: 'Bearer tok-u3' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  // ── 500 cap ────────────────────────────────────────────────────────
  it('25 500-row cap: at 501 fixture rows, response length ≤ 500', async () => {
    for (let i = 0; i < 500; i++) {
      state.files.push(fr({
        id: `bulk-${i}`, category: 'bulk',
        created_at: `2025-01-${String((i % 28) + 1).padStart(2, '0')}T00:00:00Z`,
      }));
    }
    const r = await get('/api/files?category=bulk', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const len = (r.json() as unknown[]).length;
    expect(len).toBeLessThanOrEqual(500);
    expect(len).toBe(500);
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('26 zero Node business writes across every branch', async () => {
    await get('/api/files', { authorization: 'Bearer tok-owner' });
    await get('/api/files?category=general', { authorization: 'Bearer tok-owner' });
    await get('/api/files?category=invoice', { authorization: 'Bearer tok-owner' });
    await get('/api/files?linked_type=invoice', { authorization: 'Bearer tok-owner' });
    await get('/api/files?linked_id=v-7', { authorization: 'Bearer tok-owner' });
    await get('/api/files?category=&linked_type=&linked_id=', { authorization: 'Bearer tok-owner' });
    await get('/api/files?category=nonexistent', { authorization: 'Bearer tok-owner' });
    await get('/api/files', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/files', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/files', { authorization: 'Bearer tok-u2' });
    await get('/api/files');
    await get('/api/files', { authorization: 'Bearer nope' });
    await get('/api/files', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
