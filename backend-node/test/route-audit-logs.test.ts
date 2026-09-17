/**
 * TRUKVIA · Phase-3 · Gate-6s · Audit-log read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/audit-logs?module=&action=&entity_id=&start=&end=&limit=
 *
 * Fake-DB write-forbid pattern reused inline. Gate-6s-only fixture
 * surface exercises the audit-log projection matrix without touching
 * any locked infrastructure. The tenant helper (`activeCompanyId`)
 * MUST NOT be invoked on this route.
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
  audit_logs: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x) && !(x instanceof Date);
}

// Fake-DB filter matcher — supports `$gte` and `$lte` on strings for
// the timestamp range binding.
function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isPlainObject(v)) {
      const keys = Object.keys(v);
      const rangeOnly = keys.length > 0 && keys.every((kk) => kk === '$gte' || kk === '$lte' || kk === '$ne');
      if (rangeOnly) {
        for (const [op, opv] of Object.entries(v)) {
          if (op === '$gte' && !(typeof dv === 'string' && typeof opv === 'string' && dv >= opv)) return false;
          if (op === '$lte' && !(typeof dv === 'string' && typeof opv === 'string' && dv <= opv)) return false;
          if (op === '$ne' && dv === opv) return false;
        }
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
    : name === 'audit_logs' ? state.audit_logs
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
              return ((av as string | number) < (bv as string | number) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
        skip(n: number) { hits = hits.slice(n); return cursor; },
        limit(n: number) { hits = hits.slice(0, Math.max(0, n)); return cursor; },
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

// Pre-built ordered timestamps — DESC sort MUST yield 07 > 06 > … > 01.
const TS = (n: number): string => `2026-01-${String(n).padStart(2, '0')}T10:00:00`;

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-u1',      user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
    ],
    users: [
      { user_id: 'u1', email: 'u1@x' },
      { user_id: 'u2', email: 'u2@x' },
    ],
    audit_logs: [
      { id: 'a1', user_id: 'u1', module: 'invoice',    action: 'create', entity_id: 'inv-1', timestamp: TS(1) },
      { id: 'a2', user_id: 'u1', module: 'invoice',    action: 'update', entity_id: 'inv-1', timestamp: TS(2) },
      { id: 'a3', user_id: 'u1', module: 'invoice',    action: 'delete', entity_id: 'inv-1', timestamp: TS(3) },
      { id: 'a4', user_id: 'u1', module: 'trip',       action: 'create', entity_id: 'trp-1', timestamp: TS(4) },
      { id: 'a5', user_id: 'u1', module: 'expense',    action: 'create', entity_id: 'exp-1', timestamp: TS(5) },
      { id: 'a6', user_id: 'u1', module: 'expense',    action: 'create', entity_id: 'exp-2', timestamp: TS(6) },
      { id: 'a7', user_id: 'u1', module: 'supplier',   action: 'create', entity_id: 'sup-1', timestamp: TS(7) },
      // Cross-user row — must never appear for u1.
      { id: 'x1', user_id: 'u2', module: 'invoice',    action: 'create', entity_id: 'inv-9', timestamp: TS(7) },
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

describe('Gate-6s · Audit-log read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 happy list · u1 sees 7 rows in timestamp DESC', async () => {
    const r = await get('/api/audit-logs', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a7', 'a6', 'a5', 'a4', 'a3', 'a2', 'a1']);
  });

  it('2 empty list · u with no audit rows → 200 []', async () => {
    state.sessions.push({ session_token: 'tok-u3', user_id: 'u3', effective_role: 'owner', expires_at: IN_FUTURE() });
    state.users.push({ user_id: 'u3', email: 'u3@x' });
    const r = await get('/api/audit-logs', { authorization: 'Bearer tok-u3' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('3 cross-user isolation · u2 never sees u1 rows and vice versa', async () => {
    const r = await get('/api/audit-logs', { authorization: 'Bearer tok-u2' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['x1']);
  });

  it('4 module filter · invoice only', async () => {
    const r = await get('/api/audit-logs?module=invoice', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a3', 'a2', 'a1']);
  });

  it('5 action filter · create only', async () => {
    const r = await get('/api/audit-logs?action=create', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a7', 'a6', 'a5', 'a4', 'a1']);
  });

  it('6 entity_id filter · inv-1 only', async () => {
    const r = await get('/api/audit-logs?entity_id=inv-1', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a3', 'a2', 'a1']);
  });

  it('7 combined module + action + entity_id', async () => {
    const r = await get('/api/audit-logs?module=invoice&action=update&entity_id=inv-1', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a2']);
  });

  it('8 start only · $gte 2026-01-05', async () => {
    const r = await get('/api/audit-logs?start=2026-01-05', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a7', 'a6', 'a5']);
  });

  it('9 end only · $lte end+"T23:59:59" (verified via boundary rows)', async () => {
    // end=2026-01-03 → $lte "2026-01-03T23:59:59". a3 has ts=2026-01-03T10:00:00 (included).
    const r = await get('/api/audit-logs?end=2026-01-03', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a3', 'a2', 'a1']);
  });

  it('10 start + end combined range', async () => {
    const r = await get('/api/audit-logs?start=2026-01-03&end=2026-01-05', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['a5', 'a4', 'a3']);
  });

  it('11 empty-string module MUST be omitted from filter (truthy gating)', async () => {
    // If `?module=` were incorrectly applied as {module: ""}, no rows would match.
    // Python treats "" as falsy → not added → all 7 rows return.
    const r = await get('/api/audit-logs?module=', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids.length).toBe(7);
  });

  it('12 default limit=200 · all 7 rows visible (no truncation below cap)', async () => {
    const r = await get('/api/audit-logs', { authorization: 'Bearer tok-u1' });
    expect((r.json() as unknown[]).length).toBe(7);
  });

  it('13 explicit limit=50 · same 7 rows (below cap)', async () => {
    const r = await get('/api/audit-logs?limit=50', { authorization: 'Bearer tok-u1' });
    expect((r.json() as unknown[]).length).toBe(7);
  });

  it('14 explicit limit=600 → capped to 500', async () => {
    state.audit_logs.length = 0;
    for (let i = 0; i < 501; i++) {
      state.audit_logs.push({
        id: 'z' + String(i).padStart(4, '0'),
        user_id: 'u1', module: 'x', action: 'x', entity_id: 'x',
        timestamp: `2026-06-${String((i % 28) + 1).padStart(2, '0')}T10:00:00`,
      });
    }
    const r = await get('/api/audit-logs?limit=600', { authorization: 'Bearer tok-u1' });
    expect((r.json() as unknown[]).length).toBe(500);
  });

  it('15 limit=1 → single row (newest by timestamp)', async () => {
    const r = await get('/api/audit-logs?limit=1', { authorization: 'Bearer tok-u1' });
    const arr = r.json() as Record<string, unknown>[];
    expect(arr).toHaveLength(1);
    expect(arr[0]!['id']).toBe('a7');
  });

  it('16 invalid limit=abc → 422 Pydantic-v2 int_parsing body', async () => {
    const r = await get('/api/audit-logs?limit=abc', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(422);
    const body = r.json() as { detail: Record<string, unknown>[] };
    expect(Array.isArray(body.detail)).toBe(true);
    expect(body.detail).toHaveLength(1);
    expect(body.detail[0]!['type']).toBe('int_parsing');
    expect(body.detail[0]!['loc']).toEqual(['query', 'limit']);
    expect(body.detail[0]!['input']).toBe('abc');
  });

  it('17 projection strips _id and user_id', async () => {
    const r = await get('/api/audit-logs', { authorization: 'Bearer tok-u1' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('18 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/audit-logs');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('19 invalid bearer → 401 Invalid session (BEFORE 422 for bad limit)', async () => {
    const r = await get('/api/audit-logs?limit=abc', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('20 expired session → 401 Session expired', async () => {
    const r = await get('/api/audit-logs', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('21 zero Node writes across every exercised branch', async () => {
    await get('/api/audit-logs');                                                      // 401
    await get('/api/audit-logs?limit=abc', { authorization: 'Bearer nope' });          // 401 pre-422
    await get('/api/audit-logs?limit=abc', { authorization: 'Bearer tok-u1' });        // 422
    await get('/api/audit-logs', { authorization: 'Bearer tok-u1' });                  // happy
    await get('/api/audit-logs?module=invoice', { authorization: 'Bearer tok-u1' });   // module
    await get('/api/audit-logs?action=create', { authorization: 'Bearer tok-u1' });    // action
    await get('/api/audit-logs?entity_id=inv-1', { authorization: 'Bearer tok-u1' });  // entity_id
    await get('/api/audit-logs?start=2026-01-03&end=2026-01-05', { authorization: 'Bearer tok-u1' }); // range
    await get('/api/audit-logs?limit=600', { authorization: 'Bearer tok-u1' });        // cap
    await get('/api/audit-logs?limit=1', { authorization: 'Bearer tok-u1' });          // limit=1
    await get('/api/audit-logs', { authorization: 'Bearer tok-u2' });                  // cross-user
    await get('/api/audit-logs', { authorization: 'Bearer tok-expired' });             // expired
    expect(state.writes).toEqual([]);
  });
});
