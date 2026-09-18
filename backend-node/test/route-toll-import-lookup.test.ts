/**
 * TRUKVIA · Phase-3 · Gate-7k · Toll-import lookup read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/toll-import/lookup
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
  expenses: Record<string, unknown>[];
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
    : name === 'expenses' ? state.expenses
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      find: vi.fn((f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        let hits = rows.filter((r) => matches(r, f));
        const cursor = {
          sort() { return cursor; },
          limit(n: number) { hits = hits.slice(0, n); return cursor; },
          async toArray(): Promise<Record<string, unknown>[]> {
            return hits.map((d) => project(d, opts?.projection));
          },
        };
        return cursor;
      }),
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
    expenses: [
      // Primary-lookup matches
      { id: 'e-idfc-1', user_id: 'u1', company_id: 'co-a',
        source_type: 'fastag_import', source: 'idfc',
        source_txn_ref: 'TXN-IDFC-100', source_key: 'idfc|co-a|TXN-IDFC-100',
        amount: 570, vehicle_number: 'AP16TA1234', category: 'toll' },
      { id: 'e-livq-1', user_id: 'u1', company_id: 'co-a',
        source_type: 'fastag_import', source: 'livq',
        source_txn_ref: 'TXN-LIVQ-200', source_key: 'livq|co-a|TXN-LIVQ-200',
        amount: 320, vehicle_number: 'AP16TA5678', category: 'toll' },
      // Alt-company row for u1 (owned X-Company-Id target)
      { id: 'e-alt', user_id: 'u1', company_id: 'co-a-alt',
        source_type: 'fastag_import', source: 'idfc',
        source_txn_ref: 'TXN-ALT-1', source_key: 'idfc|co-a-alt|TXN-ALT-1',
        amount: 100, vehicle_number: 'AP99XX0001' },
      // Fallback-only row (has source_key equal to lookup value, but no
      // source_type/source_txn_ref match)
      { id: 'e-fbk-1', user_id: 'u1', company_id: 'co-a',
        source_type: 'manual', source_key: 'FALLBACK-KEY-1',
        amount: 88 },
      // Cross-user u2
      { id: 'e-u2', user_id: 'u2', company_id: 'co-b',
        source_type: 'fastag_import', source: 'idfc',
        source_txn_ref: 'TXN-U2-1', source_key: 'idfc|co-b|TXN-U2-1',
        amount: 250 },
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

describe('Gate-7k · Toll-import lookup read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── Auth 401 literals ──────────────────────────────────────────────
  it('1 no bearer → 401 Not authenticated', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('2 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=X', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('3 expired bearer → 401 Session expired', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=X', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── Required-param 400 (after auth) ────────────────────────────────
  it('4 missing txn_ref → 400 "txn_ref query param is required"', async () => {
    const r = await get('/api/toll-import/lookup', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'txn_ref query param is required' });
  });

  it('5 blank txn_ref → 400 (auth precedes)', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'txn_ref query param is required' });
  });

  it('6 no bearer + missing txn_ref → 401 (auth wins over 400)', async () => {
    const r = await get('/api/toll-import/lookup');
    expect(r.statusCode).toBe(401);
  });

  // ── Primary hit ────────────────────────────────────────────────────
  it('7 primary hit by source_txn_ref (no vendor)', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const body = r.json() as Record<string, unknown>;
    expect(body.id).toBe('e-idfc-1');
    expect(body).not.toHaveProperty('_id');
    expect(body).not.toHaveProperty('user_id');
    expect(body.company_id).toBe('co-a');
  });

  it('8 primary hit with vendor=idfc → same row (source filter matches)', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100&vendor=idfc', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>).id).toBe('e-idfc-1');
  });

  it('9 vendor lowercased: vendor=IDFC still matches source=idfc', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100&vendor=IDFC', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>).id).toBe('e-idfc-1');
  });

  it('10 vendor=livq narrows primary (wrong vendor → no primary hit, fallback also miss)', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100&vendor=livq', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({
      detail: "No canonical Expense with source_txn_ref='TXN-IDFC-100'. The row was never committed — check the source file and re-import.",
    });
  });

  // ── Fallback ───────────────────────────────────────────────────────
  it('11 primary miss + fallback hit via source_key', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=FALLBACK-KEY-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>).id).toBe('e-fbk-1');
  });

  it('12 both miss → 404 with exact repr-formatted detail', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=NOPE', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({
      detail: "No canonical Expense with source_txn_ref='NOPE'. The row was never committed — check the source file and re-import.",
    });
  });

  // ── 404 repr-formatting parity ─────────────────────────────────────
  it('13 404 repr for txn_ref with single quote uses double-quote wrap', async () => {
    const r = await get(`/api/toll-import/lookup?txn_ref=${encodeURIComponent("it's")}`, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({
      detail: `No canonical Expense with source_txn_ref="it's". The row was never committed — check the source file and re-import.`,
    });
  });

  it('14 404 repr for txn_ref with double quote uses single-quote wrap', async () => {
    const r = await get(`/api/toll-import/lookup?txn_ref=${encodeURIComponent('a"b')}`, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({
      detail: `No canonical Expense with source_txn_ref='a"b'. The row was never committed — check the source file and re-import.`,
    });
  });

  it('15 404 repr for txn_ref with backslash', async () => {
    const r = await get(`/api/toll-import/lookup?txn_ref=${encodeURIComponent('a\\b')}`, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({
      detail: `No canonical Expense with source_txn_ref='a\\\\b'. The row was never committed — check the source file and re-import.`,
    });
  });

  it('16 404 repr for txn_ref with newline', async () => {
    const r = await get(`/api/toll-import/lookup?txn_ref=${encodeURIComponent('a\nb')}`, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({
      detail: `No canonical Expense with source_txn_ref='a\\nb'. The row was never committed — check the source file and re-import.`,
    });
  });

  it('17 404 repr for txn_ref with space (no escape needed)', async () => {
    const r = await get(`/api/toll-import/lookup?txn_ref=${encodeURIComponent('a b c')}`, { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({
      detail: `No canonical Expense with source_txn_ref='a b c'. The row was never committed — check the source file and re-import.`,
    });
  });

  // ── Isolation ──────────────────────────────────────────────────────
  it('18 wrong user cannot see u1 rows', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100', { authorization: 'Bearer tok-u2' });
    expect(r.statusCode).toBe(404);
  });

  it('19 wrong company: u1 default co-a → cannot see e-alt (co-a-alt)', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-ALT-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
  });

  it('20 owned X-Company-Id co-a-alt → e-alt visible', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-ALT-1', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>).id).toBe('e-alt');
  });

  it('21 unowned X-Company-Id co-b → fallback co-a → e-idfc-1 visible via primary', async () => {
    const r = await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>).id).toBe('e-idfc-1');
  });

  // ── Zero-write aggregate ───────────────────────────────────────────
  it('22 zero Node business writes across every branch', async () => {
    await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100', { authorization: 'Bearer tok-owner' });
    await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100&vendor=IDFC', { authorization: 'Bearer tok-owner' });
    await get('/api/toll-import/lookup?txn_ref=FALLBACK-KEY-1', { authorization: 'Bearer tok-owner' });
    await get('/api/toll-import/lookup?txn_ref=NOPE', { authorization: 'Bearer tok-owner' });
    await get('/api/toll-import/lookup', { authorization: 'Bearer tok-owner' });
    await get('/api/toll-import/lookup?txn_ref=', { authorization: 'Bearer tok-owner' });
    await get('/api/toll-import/lookup?txn_ref=TXN-ALT-1', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/toll-import/lookup?txn_ref=TXN-IDFC-100', { authorization: 'Bearer tok-u2' });
    await get('/api/toll-import/lookup?txn_ref=X');
    await get('/api/toll-import/lookup?txn_ref=X', { authorization: 'Bearer nope' });
    await get('/api/toll-import/lookup?txn_ref=X', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
