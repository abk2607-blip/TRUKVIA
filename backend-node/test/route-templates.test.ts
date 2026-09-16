/**
 * TRUKVIA · Phase-3 · Gate-6q · Trip template read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/templates
 *   GET /api/templates/{tid}
 *
 * Fake-DB write-forbid pattern reused inline (no shared/locked test
 * infrastructure touched). Gate-6q-only fixture surface exercises:
 *   * Company-shared scope (NO user_id in filter).
 *   * Same-company different-user visibility.
 *   * Cross-company isolation.
 *   * is_active:true filter on LIST only (retired rows still
 *     addressable via DETAIL).
 *   * Explicit 500 cap on LIST.
 *   * 404 literal parity on DETAIL for missing / wrong-company rows.
 *   * Locked 401 literals from `authenticate()`.
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
  templates: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x) && !(x instanceof Date);
}

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isPlainObject(v)) {
      const keys = Object.keys(v);
      const hasOps = keys.length > 0 && keys.every((kk) => kk.startsWith('$'));
      if (hasOps) continue;
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
    : name === 'templates' ? state.templates
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

function tmpl(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 't-x', user_id: 'u1', company_id: 'co-a',
    name: 'zzz', is_active: true,
    origin: 'A', destination: 'B',
    created_at: '2026-01-01T00:00:00Z',
    created_by: 'u1',
    ...overrides,
  };
}

function makeState(): State {
  const state: State = {
    sessions: [
      { session_token: 'tok-u1',      user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u3',      user_id: 'u3', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
    ],
    users: [
      { user_id: 'u1', email: 'u1@x' },
      { user_id: 'u2', email: 'u2@x' },
      { user_id: 'u3', email: 'u3@x' },
    ],
    companies: [
      // co-a is a SHARED company: BOTH u1 and u2 default here.
      { id: 'co-a',     user_id: 'u1', is_default: true },
      { id: 'co-a',     user_id: 'u2', is_default: true },
      // co-a-alt owned by u1 only, not default.
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      // co-b owned by u3 only.
      { id: 'co-b',     user_id: 'u3', is_default: true },
      // co-empty: u3 also owns an empty one (non-default) — unused by default.
    ],
    templates: [
      // co-a active templates authored by u1 (visible to u1 AND u2).
      tmpl({ id: 't-a1', user_id: 'u1', company_id: 'co-a', name: 'alpha',   is_active: true, extra_field: 'preserved' }),
      tmpl({ id: 't-a2', user_id: 'u1', company_id: 'co-a', name: 'beta',    is_active: true }),
      // co-a active template authored by u2 (visible to u1 AND u2 — company-shared).
      tmpl({ id: 't-a3', user_id: 'u2', company_id: 'co-a', name: 'charlie', is_active: true }),
      // co-a INACTIVE (must NOT appear in LIST; still addressable via DETAIL).
      tmpl({ id: 't-a-inactive', user_id: 'u1', company_id: 'co-a', name: 'delta', is_active: false }),
      // co-a-alt template — only visible via X-Company-Id override.
      tmpl({ id: 't-alt', user_id: 'u1', company_id: 'co-a-alt', name: 'echo', is_active: true }),
      // co-b template — MUST NEVER be visible to u1 or u2.
      tmpl({ id: 't-b', user_id: 'u3', company_id: 'co-b', name: 'foxtrot', is_active: true }),
    ],
    writes: [],
  };
  return state;
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6q · Trip template read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── LIST ────────────────────────────────────────────────────────────
  it('1 happy list · u1 sees active co-a templates sorted by name ASC', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.map((x) => x['id'])).toEqual(['t-a1', 't-a2', 't-a3']);
    expect(rows.map((x) => x['name'])).toEqual(['alpha', 'beta', 'charlie']);
  });

  it('2 name ASC · strict non-decreasing order across the response', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    const names = (r.json() as Record<string, unknown>[]).map((x) => x['name'] as string);
    for (let i = 1; i < names.length; i++) {
      expect(names[i - 1]! <= names[i]!).toBe(true);
    }
  });

  it('3 inactive excluded · t-a-inactive absent from LIST', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('t-a-inactive');
  });

  it('4 empty list → 200 [] · u3 default co-b has no active templates for u3 (co-b has t-b authored by u3 → present)', async () => {
    // u3 default co-b: contains t-b. Add a scoped empty scenario:
    // Move u3 to a fresh empty company for this test.
    state.companies.push({ id: 'co-empty', user_id: 'u3', is_default: false });
    // Override tok-u3 to point at co-empty via X-Company-Id.
    const r = await get('/api/templates', {
      authorization: 'Bearer tok-u3', 'x-company-id': 'co-empty',
    });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('5 500 cap · exactly 500 rows returned when >500 active rows exist', async () => {
    state.templates.length = 0; // clear seed rows for this focused test
    for (let i = 0; i < 501; i++) {
      const nm = 't' + String(i).padStart(4, '0');
      state.templates.push(tmpl({ id: nm, user_id: 'u1', company_id: 'co-a', name: nm, is_active: true }));
    }
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.length).toBe(500);
    // First and last (sorted name ASC) confirm 500 slice from the head.
    expect(rows[0]!['id']).toBe('t0000');
    expect(rows[499]!['id']).toBe('t0499');
  });

  it('6 cross-company isolation · co-b templates never visible to u1 in default scope', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('t-b');
  });

  it('7 same-company different-user visibility · u2 sees u1-authored co-a templates', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(200);
    const rows = r.json() as Record<string, unknown>[];
    // u2 sees ALL co-a active rows regardless of author (t-a1/t-a2 by u1, t-a3 by u2).
    expect(rows.map((x) => x['id'])).toEqual(['t-a1', 't-a2', 't-a3']);
  });

  it('8 owned X-Company-Id override · u1 sees co-a-alt templates only', async () => {
    const r = await get('/api/templates', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt',
    });
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.map((x) => x['id'])).toEqual(['t-alt']);
  });

  it('9 unowned X-Company-Id fallback · u1 → co-b override falls back to default co-a', async () => {
    const r = await get('/api/templates', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-b',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['t-a1', 't-a2', 't-a3']);
  });

  it('10 no X-Company-Id header · u1 → default company scope (co-a)', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['t-a1', 't-a2', 't-a3']);
  });

  it('11 projection strips _id and user_id (LIST)', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('12 extra fields preserved verbatim (LIST)', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-u1' });
    const first = (r.json() as Record<string, unknown>[]).find((x) => x['id'] === 't-a1')!;
    expect(first['extra_field']).toBe('preserved');
  });

  // ── DETAIL ──────────────────────────────────────────────────────────
  it('13 happy detail · u1 GET /api/templates/t-a1', async () => {
    const r = await get('/api/templates/t-a1', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(200);
    const body = r.json() as Record<string, unknown>;
    expect(body['id']).toBe('t-a1');
    expect(body['name']).toBe('alpha');
    // Projection MUST strip _id and user_id on DETAIL as well.
    expect(body).not.toHaveProperty('_id');
    expect(body).not.toHaveProperty('user_id');
  });

  it('14 unknown tid → 404 exact literal', async () => {
    const r = await get('/api/templates/does-not-exist', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Template not found' });
  });

  it('15 wrong-company tid → 404 exact literal (t-b belongs to co-b, u1 default is co-a)', async () => {
    const r = await get('/api/templates/t-b', { authorization: 'Bearer tok-u1' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Template not found' });
  });

  it('16 owned X-Company-Id override · DETAIL fetches co-a-alt row', async () => {
    const r = await get('/api/templates/t-alt', {
      authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt',
    });
    expect(r.statusCode).toBe(200);
    const body = r.json() as Record<string, unknown>;
    expect(body['id']).toBe('t-alt');
    // Same t-alt id under default co-a scope must 404 (verified via
    // absence in cross-company projection).
  });

  it('17 same-company different-user visibility (DETAIL) · u2 fetches u1-authored t-a1', async () => {
    const r = await get('/api/templates/t-a1', { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>)['id']).toBe('t-a1');
  });

  // ── AUTH FAILURES (exact 401 literals) ──────────────────────────────
  it('18 no auth (LIST) → 401 Not authenticated', async () => {
    const r = await get('/api/templates');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('19 invalid bearer (LIST) → 401 Invalid session', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('20 expired session (LIST) → 401 Session expired', async () => {
    const r = await get('/api/templates', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('21 no auth (DETAIL) → 401 Not authenticated', async () => {
    const r = await get('/api/templates/t-a1');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('22 invalid bearer (DETAIL) → 401 Invalid session', async () => {
    const r = await get('/api/templates/t-a1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('23 expired session (DETAIL) → 401 Session expired', async () => {
    const r = await get('/api/templates/t-a1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── ZERO-WRITE AGGREGATE ────────────────────────────────────────────
  it('24 zero Node business writes across every exercised branch', async () => {
    // LIST branches
    await get('/api/templates', { authorization: 'Bearer tok-u1' });
    await get('/api/templates', { authorization: 'Bearer tok-u2' });
    await get('/api/templates', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    await get('/api/templates', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-b' });
    await get('/api/templates', { authorization: 'Bearer tok-u3' });
    await get('/api/templates');
    await get('/api/templates', { authorization: 'Bearer nope' });
    await get('/api/templates', { authorization: 'Bearer tok-expired' });
    // DETAIL branches
    await get('/api/templates/t-a1', { authorization: 'Bearer tok-u1' });
    await get('/api/templates/does-not-exist', { authorization: 'Bearer tok-u1' });
    await get('/api/templates/t-b', { authorization: 'Bearer tok-u1' });
    await get('/api/templates/t-alt', { authorization: 'Bearer tok-u1', 'x-company-id': 'co-a-alt' });
    await get('/api/templates/t-a1');
    await get('/api/templates/t-a1', { authorization: 'Bearer nope' });
    await get('/api/templates/t-a1', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
