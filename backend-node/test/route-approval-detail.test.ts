/**
 * TRUKVIA · Phase-3 · Gate-7l · Approval detail read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/approvals/:aid
 *
 * Fake-DB inline-duplicated. Shared / locked infra NOT touched.
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
  approvals: Record<string, unknown>[];
  approval_revisions: Record<string, unknown>[];
  approval_audits: Record<string, unknown>[];
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
    : name === 'approvals' ? state.approvals
    : name === 'approval_revisions' ? state.approval_revisions
    : name === 'approval_audits' ? state.approval_audits
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
              return ((av as number) < (bv as number) ? -1 : 1) * d;
            }
            return 0;
          });
          return cursor;
        },
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
    approvals: [
      { id: 'apr-1', user_id: 'u1', company_id: 'co-a', status: 'PENDING_APPROVAL',
        entity_kind: 'invoice', entity_id: 'inv-1', created_at: '2026-01-01T10:00:00Z' },
      { id: 'apr-2', user_id: 'u1', company_id: 'co-a', status: 'APPROVED',
        entity_kind: 'trip', entity_id: 'trip-1', created_at: '2026-01-02T10:00:00Z' },
      { id: 'apr-alt', user_id: 'u1', company_id: 'co-a-alt', status: 'PENDING_APPROVAL',
        entity_kind: 'invoice', entity_id: 'inv-alt', created_at: '2026-01-03T10:00:00Z' },
      { id: 'apr-u2', user_id: 'u2', company_id: 'co-b', status: 'PENDING_APPROVAL',
        entity_kind: 'invoice', entity_id: 'inv-U2', created_at: '2026-01-04T10:00:00Z' },
    ],
    approval_revisions: [
      { approval_id: 'apr-1', user_id: 'u1', company_id: 'co-a', revision_index: 2, payload: { note: 'v2' } },
      { approval_id: 'apr-1', user_id: 'u1', company_id: 'co-a', revision_index: 1, payload: { note: 'v1' } },
      { approval_id: 'apr-1', user_id: 'u1', company_id: 'co-a', revision_index: 3, payload: { note: 'v3' } },
      { approval_id: 'apr-2', user_id: 'u1', company_id: 'co-a', revision_index: 1, payload: { note: 't1' } },
      // Wrong-user revision that must NOT leak
      { approval_id: 'apr-1', user_id: 'u2', company_id: 'co-b', revision_index: 99, payload: { note: 'leak' } },
    ],
    approval_audits: [
      { approval_id: 'apr-1', user_id: 'u1', company_id: 'co-a', at: '2026-01-01T11:00:00Z', action: 'created' },
      { approval_id: 'apr-1', user_id: 'u1', company_id: 'co-a', at: '2026-01-01T10:30:00Z', action: 'submitted' },
      { approval_id: 'apr-1', user_id: 'u1', company_id: 'co-a', at: '2026-01-01T12:00:00Z', action: 'notified' },
      // Wrong-user audit that must NOT leak
      { approval_id: 'apr-1', user_id: 'u2', company_id: 'co-b', at: '2026-01-01T09:00:00Z', action: 'leak' },
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

describe('Gate-7l · Approval detail read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── Auth 401 literals ──────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    const r = await get('/api/approvals/apr-1');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/approvals/apr-1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    const r = await get('/api/approvals/apr-1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── Primary hit ────────────────────────────────────────────────────
  it('4 authenticated hit returns wrapper {approval, revisions, audits}', async () => {
    const r = await get('/api/approvals/apr-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const body = r.json() as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(['approval', 'audits', 'revisions']);
    const approval = body.approval as Record<string, unknown>;
    expect(approval.id).toBe('apr-1');
    expect(approval).not.toHaveProperty('_id');
    // user_id PRESERVED (contrast Gate 7a–7f)
    expect(approval.user_id).toBe('u1');
  });

  it('5 revisions sorted revision_index ASC, cap 200', async () => {
    const r = await get('/api/approvals/apr-1', { authorization: 'Bearer tok-owner' });
    const revs = (r.json() as Record<string, unknown>).revisions as Record<string, unknown>[];
    expect(revs.map((v) => v.revision_index)).toEqual([1, 2, 3]);
    for (const v of revs) {
      expect(v).not.toHaveProperty('_id');
      expect(v.user_id).toBe('u1'); // user_id preserved
    }
  });

  it('6 audits sorted at ASC, cap 500', async () => {
    const r = await get('/api/approvals/apr-1', { authorization: 'Bearer tok-owner' });
    const audits = (r.json() as Record<string, unknown>).audits as Record<string, unknown>[];
    expect(audits.map((v) => v.at)).toEqual([
      '2026-01-01T10:30:00Z', '2026-01-01T11:00:00Z', '2026-01-01T12:00:00Z',
    ]);
    for (const a of audits) {
      expect(a).not.toHaveProperty('_id');
      expect(a.user_id).toBe('u1');
    }
  });

  // ── 404 exact ──────────────────────────────────────────────────────
  it('7 nonexistent aid → 404 Approval not found', async () => {
    const r = await get('/api/approvals/no-such-aid', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Approval not found' });
  });

  // ── Isolation ──────────────────────────────────────────────────────
  it('8 cross-user u2 requesting u1 apr-1 → 404', async () => {
    const r = await get('/api/approvals/apr-1', { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Approval not found' });
  });

  it('9 wrong company: u1 default co-a → apr-alt (co-a-alt) → 404', async () => {
    const r = await get('/api/approvals/apr-alt', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
  });

  it('10 owned X-Company-Id co-a-alt → apr-alt visible', async () => {
    const r = await get('/api/approvals/apr-alt', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, { id: string }>).approval.id).toBe('apr-alt');
  });

  it('11 unowned X-Company-Id co-b → fallback co-a → apr-1 visible', async () => {
    const r = await get('/api/approvals/apr-1', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, { id: string }>).approval.id).toBe('apr-1');
  });

  it('12 wrong-user revisions/audits do NOT leak into approval detail', async () => {
    const r = await get('/api/approvals/apr-1', { authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    const revs = body.revisions as Record<string, unknown>[];
    const audits = body.audits as Record<string, unknown>[];
    for (const v of revs) expect(v.user_id).toBe('u1');
    for (const a of audits) expect(a.user_id).toBe('u1');
    // Verify the leak-fixture revision_index 99 is NOT present
    expect(revs.find((v) => v.revision_index === 99)).toBeUndefined();
    // Verify the leak-fixture audit "leak" is NOT present
    expect(audits.find((a) => a.action === 'leak')).toBeUndefined();
  });

  // ── Empty revisions/audits ─────────────────────────────────────────
  it('13 approval with no revisions/audits → empty arrays', async () => {
    // apr-2 has one revision but zero audits; verify audits is []
    const r = await get('/api/approvals/apr-2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const body = r.json() as Record<string, unknown>;
    expect((body.revisions as unknown[]).length).toBe(1);
    expect(body.audits).toEqual([]);
  });

  // ── Static route precedence: 7f /summary/pending must NOT match here ─
  it('14 aid="summary" (edge) — Fastify routes to 7f static /summary/pending first', async () => {
    // Sanity: an aid literally equal to "summary" should still hit
    // /:aid handler because "summary" alone doesn't match the more
    // specific static route "/summary/pending".
    const r = await get('/api/approvals/summary', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Approval not found' });
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('15 zero Node business writes across every branch', async () => {
    await get('/api/approvals/apr-1', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals/apr-2', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals/apr-alt', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/approvals/nope', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals/apr-1', { authorization: 'Bearer tok-u2' });
    await get('/api/approvals/apr-1');
    await get('/api/approvals/apr-1', { authorization: 'Bearer nope' });
    await get('/api/approvals/apr-1', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
