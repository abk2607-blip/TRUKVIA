/**
 * TRUKVIA · Phase-3 · Gate-7g · Approvals list read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/approvals
 *
 * Fake-DB inline-duplicated from the Gate-6k / Gate-7e pattern. Shared /
 * locked test infrastructure is NOT touched.
 *
 * Supported operators (inline):
 *   * plain equality
 *   * $in (default status set)
 *   * find(...).sort([['created_at', -1]]).limit(n).toArray()
 *   * projection strip-only ({_id: 0}) — preserves user_id
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
      const keys = Object.keys(v);
      const hasOps = keys.length > 0 && keys.every((kk) => kk.startsWith('$'));
      if (hasOps) {
        if ('$in' in v) {
          const arr = v['$in'] as unknown[];
          if (!arr.some((x) => x === dv)) return false;
          continue;
        }
        return false;
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
    : name === 'approvals' ? state.approvals
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
      apr({ id: 'a1', created_at: '2026-01-01T10:00:00Z' }),
      apr({ id: 'a2', created_at: '2026-01-02T10:00:00Z', entity_kind: 'invoice' }),
      apr({ id: 'a3', created_at: '2026-01-03T10:00:00Z', status: 'REJECTED' }),
      apr({ id: 'a4', created_at: '2026-01-04T10:00:00Z', status: 'WITHDRAWN', entity_kind: 'supplier_payment' }),
      apr({ id: 'a5', created_at: '2026-01-05T10:00:00Z', status: 'APPROVED' }),
      apr({ id: 'a6', created_at: '2026-01-06T10:00:00Z', status: 'POSTED' }),
      apr({ id: 'a-alt', company_id: 'co-a-alt', created_at: '2026-01-07T10:00:00Z' }),
      apr({ id: 'a-u2-1', user_id: 'u2', company_id: 'co-b', created_at: '2026-01-08T10:00:00Z' }),
      apr({ id: 'a-u2-2', user_id: 'u2', company_id: 'co-b', status: 'APPROVED', created_at: '2026-01-09T10:00:00Z' }),
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

describe('Gate-7g · Approvals list read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── 422 envelopes (Pydantic v2.13.4 byte-verified) ─────────────────
  it('1 include_all=xyz → 422 bool_parsing envelope', async () => {
    const r = await get('/api/approvals?include_all=xyz', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({ detail: [{
      type: 'bool_parsing', loc: ['query', 'include_all'],
      msg: 'Input should be a valid boolean, unable to interpret input',
      input: 'xyz', url: 'https://errors.pydantic.dev/2.13/v/bool_parsing',
    }] });
  });

  it('2 limit=abc → 422 int_parsing envelope', async () => {
    const r = await get('/api/approvals?limit=abc', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({ detail: [{
      type: 'int_parsing', loc: ['query', 'limit'],
      msg: 'Input should be a valid integer, unable to parse string as an integer',
      input: 'abc', url: 'https://errors.pydantic.dev/2.13/v/int_parsing',
    }] });
  });

  it('3 limit=0 → 422 greater_than_equal envelope (ge=1)', async () => {
    const r = await get('/api/approvals?limit=0', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({ detail: [{
      type: 'greater_than_equal', loc: ['query', 'limit'],
      msg: 'Input should be greater than or equal to 1',
      input: '0', ctx: { ge: 1 },
      url: 'https://errors.pydantic.dev/2.13/v/greater_than_equal',
    }] });
  });

  it('4 limit=501 → 422 less_than_equal envelope (le=500)', async () => {
    const r = await get('/api/approvals?limit=501', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect(r.json()).toEqual({ detail: [{
      type: 'less_than_equal', loc: ['query', 'limit'],
      msg: 'Input should be less than or equal to 500',
      input: '501', ctx: { le: 500 },
      url: 'https://errors.pydantic.dev/2.13/v/less_than_equal',
    }] });
  });

  it('5 limit=1.5 → 422 int_parsing (no float coercion)', async () => {
    const r = await get('/api/approvals?limit=1.5', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect((r.json() as { detail: Array<{ type: string }> }).detail[0].type).toBe('int_parsing');
  });

  it('6 limit=-5 → 422 greater_than_equal', async () => {
    const r = await get('/api/approvals?limit=-5', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect((r.json() as { detail: Array<{ type: string }> }).detail[0].type).toBe('greater_than_equal');
  });

  it('7 limit blank → 422 int_parsing', async () => {
    const r = await get('/api/approvals?limit=', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    expect((r.json() as { detail: Array<{ input: string }> }).detail[0].input).toBe('');
  });

  // ── Validation precedence: 422 before 401 ──────────────────────────
  it('8 unauthenticated + invalid include_all → 422 (not 401)', async () => {
    const r = await get('/api/approvals?include_all=xyz');
    expect(r.statusCode).toBe(422);
  });

  it('9 unauthenticated + valid query → 401 Not authenticated', async () => {
    const r = await get('/api/approvals');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('10 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/approvals', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('11 expired bearer → 401 Session expired', async () => {
    const r = await get('/api/approvals', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── Bool spellings (Pydantic v2 accepted set) ──────────────────────
  for (const [v, expected] of [
    ['true', true], ['True', true], ['TRUE', true],
    ['false', false], ['False', false], ['FALSE', false],
    ['1', true], ['0', false],
    ['yes', true], ['no', false],
    ['on', true], ['off', false],
  ] as [string, boolean][]) {
    it(`12 include_all=${v} accepted (bool=${expected})`, async () => {
      const r = await get(`/api/approvals?include_all=${v}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
    });
  }

  // ── Default $in set ────────────────────────────────────────────────
  it('13 default (no params) → PENDING/REJECTED/WITHDRAWN sorted DESC', async () => {
    const r = await get('/api/approvals', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a4', 'a3', 'a2', 'a1']);
  });

  it('14 include_all=true → all statuses under scope, DESC', async () => {
    const r = await get('/api/approvals?include_all=true', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a6', 'a5', 'a4', 'a3', 'a2', 'a1']);
  });

  it('15 include_all=false (explicit) → same as default', async () => {
    const r = await get('/api/approvals?include_all=false', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a4', 'a3', 'a2', 'a1']);
  });

  // ── Status override ────────────────────────────────────────────────
  it('16 status=APPROVED → only a5 (bypasses default $in)', async () => {
    const r = await get('/api/approvals?status=APPROVED', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a5']);
  });

  it('17 status=APPROVED + include_all=true → status wins → only a5', async () => {
    const r = await get('/api/approvals?status=APPROVED&include_all=true', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a5']);
  });

  it('18 status=NONEXISTENT → []', async () => {
    const r = await get('/api/approvals?status=NONEXISTENT', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
  });

  it('19 blank status → treated as falsy (default $in)', async () => {
    const r = await get('/api/approvals?status=', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a4', 'a3', 'a2', 'a1']);
  });

  it('20 status is case-sensitive — lowercase does not match', async () => {
    const r = await get('/api/approvals?status=approved', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
  });

  // ── entity_kind filter ─────────────────────────────────────────────
  it('21 entity_kind=invoice → only a2', async () => {
    const r = await get('/api/approvals?entity_kind=invoice', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a2']);
  });

  it('22 entity_kind=trip + include_all=true → a1, a3, a5, a6 DESC', async () => {
    const r = await get('/api/approvals?entity_kind=trip&include_all=true', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a6', 'a5', 'a3', 'a1']);
  });

  it('23 blank entity_kind → treated as falsy (no filter)', async () => {
    const r = await get('/api/approvals?entity_kind=', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a4', 'a3', 'a2', 'a1']);
  });

  // ── Limit ──────────────────────────────────────────────────────────
  it('24 limit=2 → first 2 of default DESC', async () => {
    const r = await get('/api/approvals?limit=2', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a4', 'a3']);
  });

  it('25 limit=500 → all default rows (within cap)', async () => {
    const r = await get('/api/approvals?limit=500', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(4);
  });

  it('26 limit=1 accepted (ge=1 lower bound)', async () => {
    const r = await get('/api/approvals?limit=1', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(1);
  });

  it('27 limit=+1 accepted (Pydantic accepts leading +)', async () => {
    const r = await get('/api/approvals?limit=%2B1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as unknown[]).length).toBe(1);
  });

  // ── Isolation ──────────────────────────────────────────────────────
  it('28 owned X-Company-Id co-a-alt → a-alt only', async () => {
    const r = await get('/api/approvals', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a-alt']);
  });

  it('29 unowned X-Company-Id co-b → fallback co-a → default rows', async () => {
    const r = await get('/api/approvals', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a4', 'a3', 'a2', 'a1']);
  });

  it('30 no X-Company-Id header → default co-a scope', async () => {
    const r = await get('/api/approvals', { authorization: 'Bearer tok-owner' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a4', 'a3', 'a2', 'a1']);
  });

  it('31 cross-user u2 → own co-b scope, PENDING only (a-u2-1)', async () => {
    const r = await get('/api/approvals', { authorization: 'Bearer tok-u2' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a-u2-1']);
  });

  it('32 u2 + include_all=true → both a-u2-2 (APPROVED), a-u2-1 DESC', async () => {
    const r = await get('/api/approvals?include_all=true', { authorization: 'Bearer tok-u2' });
    expect(idsOf(r.json() as Record<string, unknown>[])).toEqual(['a-u2-2', 'a-u2-1']);
  });

  // ── Response shape / projection ────────────────────────────────────
  it('33 projection strips _id ONLY; user_id PRESERVED', async () => {
    const r = await get('/api/approvals', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).toHaveProperty('user_id');
      expect(row).toHaveProperty('id');
      expect(row).toHaveProperty('status');
      expect(row).toHaveProperty('created_at');
    }
  });

  it('34 response is a bare JSON array', async () => {
    const r = await get('/api/approvals', { authorization: 'Bearer tok-owner' });
    expect(Array.isArray(r.json())).toBe(true);
  });

  it('35 sort created_at DESC verified', async () => {
    const r = await get('/api/approvals?include_all=true', { authorization: 'Bearer tok-owner' });
    const ts = (r.json() as Record<string, unknown>[]).map((v) => v['created_at'] as string);
    const sorted = ts.slice().sort().reverse();
    expect(ts).toEqual(sorted);
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('36 zero Node business writes across every branch', async () => {
    await get('/api/approvals', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals?include_all=true', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals?status=APPROVED', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals?entity_kind=trip', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals?limit=2', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/approvals', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/approvals', { authorization: 'Bearer tok-u2' });
    await get('/api/approvals?include_all=xyz', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals?limit=0', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals?limit=501', { authorization: 'Bearer tok-owner' });
    await get('/api/approvals');
    await get('/api/approvals', { authorization: 'Bearer nope' });
    await get('/api/approvals', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
