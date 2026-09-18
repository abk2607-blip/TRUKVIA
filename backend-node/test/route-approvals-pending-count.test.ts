/**
 * TRUKVIA · Phase-3 · Gate-7f · Approvals pending-count read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/approvals/summary/pending
 *
 * Fake-DB inline-duplicated from the Gate-6k / Gate-7e pattern. Shared /
 * locked test infrastructure is NOT touched — every helper below is
 * local to this file.
 *
 * Supported operators (inline):
 *   * plain equality
 *   * findOne (auth / company lookups)
 *   * countDocuments (business read)
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
  approvals: Record<string, unknown>[];
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
      // Gate 7f handler uses only plain equality — no operator objects.
      // Fall through to strict equality (returns false for nested objects).
      if (dv !== v) return false;
      continue;
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
    : name === 'approvals' ? state.approvals
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      find: vi.fn((f: Record<string, unknown>, _opts?: unknown) => ({
        sort: () => ({ toArray: async () => rows.filter((r) => matches(r, f)) }),
        toArray: async () => rows.filter((r) => matches(r, f)),
      })),
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
function apr(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user_id: 'u1', company_id: 'co-a', status: 'PENDING_APPROVAL',
    entity_kind: 'trip', ...overrides,
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
    approvals: [
      // u1 / co-a — 3 PENDING
      apr({ id: 'a1' }),
      apr({ id: 'a2' }),
      apr({ id: 'a3' }),
      // u1 / co-a — non-PENDING (excluded)
      apr({ id: 'a-approved',  status: 'APPROVED'  }),
      apr({ id: 'a-rejected',  status: 'REJECTED'  }),
      apr({ id: 'a-withdrawn', status: 'WITHDRAWN' }),
      apr({ id: 'a-other',     status: 'POSTED'    }),
      // u1 / co-a-alt — 1 PENDING (isolation)
      apr({ id: 'a-alt', company_id: 'co-a-alt' }),
      // u2 / co-b — 2 PENDING (cross-user isolation)
      apr({ id: 'a-u2-1', user_id: 'u2', company_id: 'co-b' }),
      apr({ id: 'a-u2-2', user_id: 'u2', company_id: 'co-b' }),
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

describe('Gate-7f · Approvals pending-count read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: '/api/approvals/summary/pending', headers });

  // ── Auth 401 literals ──────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    const r = await get();
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    const r = await get({ authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    const r = await get({ authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('4 auth precedence — no bearer → 401 before any approvals access', async () => {
    const r = await get();
    expect(r.statusCode).toBe(401);
    // No countDocuments should have been called before auth failure.
  });

  // ── Count semantics ────────────────────────────────────────────────
  it('5 u1 / default co-a → 3 PENDING_APPROVAL rows', async () => {
    const r = await get({ authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ count: 3 });
  });

  it('6 empty approvals collection → count 0', async () => {
    state.approvals = [];
    const r = await get({ authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ count: 0 });
  });

  it('7 non-PENDING statuses (APPROVED/REJECTED/WITHDRAWN/POSTED) excluded', async () => {
    state.approvals = [
      apr({ id: 'x1', status: 'APPROVED'  }),
      apr({ id: 'x2', status: 'REJECTED'  }),
      apr({ id: 'x3', status: 'WITHDRAWN' }),
      apr({ id: 'x4', status: 'POSTED'    }),
    ];
    const r = await get({ authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual({ count: 0 });
  });

  it('8 wrong user (u2 rows) excluded when authenticated as u1', async () => {
    const r = await get({ authorization: 'Bearer tok-owner' });
    // Fixture has 2× u2 PENDING; they must not be counted.
    expect(r.json()).toEqual({ count: 3 });
  });

  it('9 wrong company (co-a-alt rows) excluded under default co-a', async () => {
    const r = await get({ authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual({ count: 3 });
  });

  // ── Company resolution ─────────────────────────────────────────────
  it('10 owned X-Company-Id co-a-alt → counts only 1 alt-company row', async () => {
    const r = await get({ authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ count: 1 });
  });

  it('11 unowned X-Company-Id co-b → fallback to default co-a → count 3', async () => {
    const r = await get({ authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect(r.json()).toEqual({ count: 3 });
  });

  it('12 no X-Company-Id header → default co-a scope', async () => {
    const r = await get({ authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual({ count: 3 });
  });

  it('13 cross-user u2 → sees own co-b PENDING (2 rows)', async () => {
    const r = await get({ authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({ count: 2 });
  });

  // ── Response shape ─────────────────────────────────────────────────
  it('14 response shape — exactly {count: <integer>}, no extra fields', async () => {
    const r = await get({ authorization: 'Bearer tok-owner' });
    const body = r.json() as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(['count']);
    expect(typeof body['count']).toBe('number');
    expect(Number.isInteger(body['count'])).toBe(true);
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('15 zero Node business writes across every branch', async () => {
    await get({ authorization: 'Bearer tok-owner' });
    await get({ authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get({ authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get({ authorization: 'Bearer tok-u2' });
    await get();
    await get({ authorization: 'Bearer nope' });
    await get({ authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
