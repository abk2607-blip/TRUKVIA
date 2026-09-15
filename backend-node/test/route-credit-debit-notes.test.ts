/**
 * TRUKVIA · Phase-3 · Gate-6f · Credit / Debit Note read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/credit-notes
 *   GET /api/credit-notes/{nid}
 *   GET /api/debit-notes
 *   GET /api/debit-notes/{nid}
 *
 * Mirrors fake-DB / write-forbidden pattern from Gates 6c–6e.
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
  credit_debit_notes: Record<string, unknown>[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const cond = v as Record<string, unknown>;
      if ('$in' in cond) {
        if (!(cond['$in'] as unknown[]).some((x) => x === dv)) return false;
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
    : name === 'credit_debit_notes' ? state.credit_debit_notes
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

// ── Fixture helpers ─────────────────────────────────────────────────
function cn(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'cn-x', kind: 'credit', company_id: 'co-a', user_id: 'u1',
    note_number: 'CN/25-26/0001', note_date: '2026-02-05',
    invoice_id: 'inv-x', customer_id: 'cust-1',
    reason_code: 'rate_correction', reason_text: 'unit-test',
    lines: [], subtotal: 100, gst_type: 'cgst_sgst',
    cgst_rate: 2.5, sgst_rate: 2.5, igst_rate: 5,
    cgst_amount: 0, sgst_amount: 0, igst_amount: 0,
    total_tax: 0, total_amount: 100, round_off: 0, rcm: true,
    apply_gst: false, status: 'issued', is_historical: false,
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
    credit_debit_notes: [
      // credit notes for u1 (varied statuses / customers / invoices)
      cn({ id: 'c1', kind: 'credit', customer_id: 'cust-1', invoice_id: 'inv-a', status: 'issued', note_date: '2026-02-10' }),
      cn({ id: 'c2', kind: 'credit', customer_id: 'cust-1', invoice_id: 'inv-b', status: 'issued', note_date: '2026-02-08' }),
      cn({ id: 'c3', kind: 'credit', customer_id: 'cust-2', invoice_id: 'inv-c', status: 'draft',  note_date: '2026-02-12' }),
      cn({ id: 'c4', kind: 'credit', customer_id: 'cust-2', invoice_id: 'inv-a', status: 'cancelled', note_date: '2026-02-06' }),
      cn({ id: 'c5', kind: 'credit', customer_id: 'cust-3', invoice_id: 'inv-d', status: 'issued', note_date: '2026-02-15' }),
      // debit notes for u1
      cn({ id: 'd1', kind: 'debit',  customer_id: 'cust-1', invoice_id: 'inv-a', status: 'issued', note_date: '2026-02-11' }),
      cn({ id: 'd2', kind: 'debit',  customer_id: 'cust-2', invoice_id: 'inv-c', status: 'issued', note_date: '2026-02-09' }),
      cn({ id: 'd3', kind: 'debit',  customer_id: 'cust-2', invoice_id: 'inv-c', status: 'draft',  note_date: '2026-02-13' }),
      // u2 notes for isolation
      cn({ id: 'cU2', kind: 'credit', user_id: 'u2', customer_id: 'cust-b', invoice_id: 'inv-u2', status: 'issued' }),
      cn({ id: 'dU2', kind: 'debit',  user_id: 'u2', customer_id: 'cust-b', invoice_id: 'inv-u2', status: 'issued' }),
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

describe('Gate-6f · Credit/Debit-Note read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  const prevFlag = process.env['ENABLE_CDN'];

  beforeEach(async () => {
    process.env['ENABLE_CDN'] = '1';
    state = makeState();
    app = await makeApp(state);
  });
  afterEach(async () => {
    await app.close();
    if (prevFlag === undefined) delete process.env['ENABLE_CDN'];
    else process.env['ENABLE_CDN'] = prevFlag;
  });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── LIST · credit ──────────────────────────────────────────────────
  it('1 credit list happy path — kind=credit only, sorted note_date DESC', async () => {
    const r = await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const arr = r.json();
    expect(arr.length).toBe(5); // c1..c5, no debit or u2 rows
    expect(arr.every((x: Record<string, unknown>) => x['kind'] === 'credit')).toBe(true);
    const dates = arr.map((x: Record<string, unknown>) => x['note_date']);
    expect(dates).toEqual(['2026-02-15', '2026-02-12', '2026-02-10', '2026-02-08', '2026-02-06']);
    expect(arr[0]).not.toHaveProperty('user_id');
  });

  it('2 credit list — customer_id filter', async () => {
    const r = await get('/api/credit-notes?customer_id=cust-1', { authorization: 'Bearer tok-owner' });
    const ids = r.json().map((x: Record<string, unknown>) => x['id']).sort();
    expect(ids).toEqual(['c1', 'c2']);
  });

  it('3 credit list — invoice_id filter', async () => {
    const r = await get('/api/credit-notes?invoice_id=inv-a', { authorization: 'Bearer tok-owner' });
    const ids = r.json().map((x: Record<string, unknown>) => x['id']).sort();
    expect(ids).toEqual(['c1', 'c4']);
  });

  it('4 credit list — status filter', async () => {
    const r = await get('/api/credit-notes?status=draft', { authorization: 'Bearer tok-owner' });
    const ids = r.json().map((x: Record<string, unknown>) => x['id']);
    expect(ids).toEqual(['c3']);
  });

  it('5 credit list — empty string filters ignored (customer_id=)', async () => {
    const r = await get('/api/credit-notes?customer_id=&status=', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json().length).toBe(5);
  });

  it('6 credit list — custom limit=2 truncates to 2 most-recent', async () => {
    const r = await get('/api/credit-notes?limit=2', { authorization: 'Bearer tok-owner' });
    const arr = r.json();
    expect(arr.length).toBe(2);
    expect(arr[0]['id']).toBe('c5');
    expect(arr[1]['id']).toBe('c3');
  });

  it('7 credit list — limit > 500 → 422', async () => {
    const r = await get('/api/credit-notes?limit=1000', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
  });

  it('8 credit list — non-integer limit → 422', async () => {
    const r = await get('/api/credit-notes?limit=abc', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
  });

  it('9 credit list — u1 does not see u2 rows (user_id isolation)', async () => {
    const r = await get('/api/credit-notes', { authorization: 'Bearer tok-u2' });
    const ids = r.json().map((x: Record<string, unknown>) => x['id']);
    expect(ids).toEqual(['cU2']);
  });

  // ── LIST · debit ────────────────────────────────────────────────────
  it('10 debit list happy path — kind=debit only, sorted DESC', async () => {
    const r = await get('/api/debit-notes', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const arr = r.json();
    expect(arr.length).toBe(3);
    expect(arr.every((x: Record<string, unknown>) => x['kind'] === 'debit')).toBe(true);
    const dates = arr.map((x: Record<string, unknown>) => x['note_date']);
    expect(dates).toEqual(['2026-02-13', '2026-02-11', '2026-02-09']);
  });

  it('11 debit list — combined customer_id + status filter', async () => {
    const r = await get('/api/debit-notes?customer_id=cust-2&status=issued', { authorization: 'Bearer tok-owner' });
    const ids = r.json().map((x: Record<string, unknown>) => x['id']);
    expect(ids).toEqual(['d2']);
  });

  // ── DETAIL · credit ─────────────────────────────────────────────────
  it('12 credit detail happy path', async () => {
    const r = await get('/api/credit-notes/c1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['id']).toBe('c1');
    expect(d['kind']).toBe('credit');
    expect(d).not.toHaveProperty('user_id');
  });

  it('13 credit detail — DELIBERATE cross-kind quirk: returns debit-kind body', async () => {
    // GET /api/credit-notes/d1 fetches a debit-kind note — Python behaviour.
    const r = await get('/api/credit-notes/d1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['id']).toBe('d1');
    expect(d['kind']).toBe('debit'); // <— deliberate quirk preserved
  });

  it('14 credit detail — missing note → 404 "Not found" (lowercase f)', async () => {
    const r = await get('/api/credit-notes/does-not-exist', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Not found' });
  });

  it('15 credit detail — cross-tenant → 404 (user_id filter)', async () => {
    const r = await get('/api/credit-notes/cU2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Not found' });
  });

  // ── DETAIL · debit ──────────────────────────────────────────────────
  it('16 debit detail happy path', async () => {
    const r = await get('/api/debit-notes/d1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()['id']).toBe('d1');
    expect(r.json()['kind']).toBe('debit');
  });

  it('17 debit detail — credit-kind note REJECTED via kind:"debit" filter → 404', async () => {
    const r = await get('/api/debit-notes/c1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Not found' });
  });

  // ── Auth ────────────────────────────────────────────────────────────
  it('18 no auth → 401 Not authenticated (credit list)', async () => {
    const r = await get('/api/credit-notes');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('19 invalid bearer → 401 Invalid session (debit detail)', async () => {
    const r = await get('/api/debit-notes/d1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('20 expired session → 401 Session expired (credit detail)', async () => {
    const r = await get('/api/credit-notes/c1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── Feature flag ────────────────────────────────────────────────────
  it('21 flag OFF (unset) → all four routes return 404 "Not Found" (capital F)', async () => {
    delete process.env['ENABLE_CDN'];
    const r1 = await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    const r2 = await get('/api/credit-notes/c1', { authorization: 'Bearer tok-owner' });
    const r3 = await get('/api/debit-notes', { authorization: 'Bearer tok-owner' });
    const r4 = await get('/api/debit-notes/d1', { authorization: 'Bearer tok-owner' });
    for (const r of [r1, r2, r3, r4]) {
      expect(r.statusCode).toBe(404);
      expect(r.json()).toEqual({ detail: 'Not Found' });
    }
  });

  it('22 flag != "1" → 404 "Not Found" (ENABLE_CDN=0)', async () => {
    process.env['ENABLE_CDN'] = '0';
    const r = await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Not Found' });
  });

  it('23 flag read at request-time (flip on->off between requests)', async () => {
    process.env['ENABLE_CDN'] = '1';
    const r1 = await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    expect(r1.statusCode).toBe(200);
    process.env['ENABLE_CDN'] = '0';
    const r2 = await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    expect(r2.statusCode).toBe(404);
    expect(r2.json()).toEqual({ detail: 'Not Found' });
    process.env['ENABLE_CDN'] = '1';
    const r3 = await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    expect(r3.statusCode).toBe(200);
  });

  it('24 auth fires BEFORE flag (401 wins over 404 flag-off when no bearer)', async () => {
    // FastAPI parity: dependency (auth) resolves before body (_require_flag).
    delete process.env['ENABLE_CDN'];
    const r = await get('/api/credit-notes');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('25 query 422 fires BEFORE auth (limit=1000, no bearer → 422)', async () => {
    // FastAPI parity: query param validation fires ahead of dependency resolution.
    const r = await get('/api/credit-notes?limit=1000');
    expect(r.statusCode).toBe(422);
  });

  // ── Zero-write umbrella ─────────────────────────────────────────────
  it('26 zero Node business writes across every branch', async () => {
    // exercise both flag states and every response branch
    await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    await get('/api/credit-notes?customer_id=cust-1', { authorization: 'Bearer tok-owner' });
    await get('/api/credit-notes?limit=2', { authorization: 'Bearer tok-owner' });
    await get('/api/credit-notes?limit=1000', { authorization: 'Bearer tok-owner' });
    await get('/api/credit-notes/c1', { authorization: 'Bearer tok-owner' });
    await get('/api/credit-notes/d1', { authorization: 'Bearer tok-owner' });
    await get('/api/credit-notes/does-not-exist', { authorization: 'Bearer tok-owner' });
    await get('/api/debit-notes', { authorization: 'Bearer tok-owner' });
    await get('/api/debit-notes/d1', { authorization: 'Bearer tok-owner' });
    await get('/api/debit-notes/c1', { authorization: 'Bearer tok-owner' });
    await get('/api/credit-notes');
    await get('/api/credit-notes/c1', { authorization: 'Bearer nope' });
    await get('/api/credit-notes/c1', { authorization: 'Bearer tok-expired' });
    delete process.env['ENABLE_CDN'];
    await get('/api/credit-notes', { authorization: 'Bearer tok-owner' });
    await get('/api/debit-notes/d1', { authorization: 'Bearer tok-owner' });
    expect(state.writes).toEqual([]);
  });
});
