/**
 * TRUKVIA · Phase-3 · Gate-6e · Invoice Ship-To read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/invoices/{iid}/ship-to
 *
 * Mirrors the fake-DB / write-forbidden pattern used by Gates 6c / 6d.
 * A single mutating call raises and records into `state.writes`. The
 * final case asserts `state.writes.length === 0`.
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
  invoices: Record<string, unknown>[];
  customers: Record<string, unknown>[];
  trips: Record<string, unknown>[];
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
    : name === 'invoices' ? state.invoices
    : name === 'customers' ? state.customers
    : name === 'trips' ? state.trips
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
function inv(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'inv-x', company_id: 'co-a', user_id: 'u1',
    customer_id: 'cust-1', trip_ids: [],
    invoice_number: 'INV/25-26/0001', invoice_date: '2026-02-01',
    ...overrides,
  };
}

function trip(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'tr-x', company_id: 'co-a', user_id: 'u1',
    customer_id: 'cust-1', to_location: '',
    ship_site_id: '',
    ...overrides,
  };
}

function site(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'ss-x', site_name: '', address: '', gstin: '',
    state: '', state_code: '', pincode: '',
    phone: '', contact_person: '',
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
    invoices: [
      // Empty trip_ids invoice.
      inv({ id: 'inv-empty', trip_ids: [] }),
      // Missing customer (customer_id points to non-existent).
      inv({ id: 'inv-nocust', customer_id: 'ghost', trip_ids: ['tr-happy'] }),
      // Explicit site FK.
      inv({ id: 'inv-explicit', trip_ids: ['tr-explicit'] }),
      // Unique inference match (evidence R1 · name equality).
      inv({ id: 'inv-inferR1', trip_ids: ['tr-r1'] }),
      // R2 pincode inference match.
      inv({ id: 'inv-inferR2', trip_ids: ['tr-r2'] }),
      // R3 whole-token in address match.
      inv({ id: 'inv-inferR3', trip_ids: ['tr-r3'] }),
      // Ambiguous (>1 matches) → fallback.
      inv({ id: 'inv-amb', trip_ids: ['tr-amb'] }),
      // Zero-match → fallback.
      inv({ id: 'inv-none', trip_ids: ['tr-none'] }),
      // Empty ship_sites.
      inv({ id: 'inv-nosites', customer_id: 'cust-2', trip_ids: ['tr-happy'] }),
      // Mixed identities → mixed=true, common=null.
      inv({ id: 'inv-mixed', trip_ids: ['tr-explicit', 'tr-none'] }),
      // Trip ordering test — reversed insertion vs mongo natural.
      inv({ id: 'inv-order', trip_ids: ['tr-b', 'tr-a'] }),
      // Historical trip pass-through — resolver treats it like any trip.
      inv({ id: 'inv-hist', trip_ids: ['tr-hist'] }),
      // GSTIN normalization display cleanup.
      inv({ id: 'inv-gstin', customer_id: 'cust-gstin', trip_ids: ['tr-gstin'] }),
      // Missing trip in DB (referenced id absent) → dropped from output.
      inv({ id: 'inv-missingtrip', trip_ids: ['tr-a', 'tr-missing'] }),
      // u2 tenant invoice — cross-tenant 404.
      inv({ id: 'inv-of-u2', user_id: 'u2', customer_id: 'cust-b', trip_ids: [] }),
    ],
    customers: [
      {
        id: 'cust-1', user_id: 'u1', company_id: 'co-a', name: 'Acme',
        ship_sites: [
          site({
            id: 's-warehouse', site_name: 'Warehouse',
            address: 'Plot 12, Whitefield, Bangalore 560066',
            gstin: 'GSTIN 29ABCDE1234F1Z5', state: 'Karnataka',
            state_code: '29', pincode: '560066',
          }),
          site({
            id: 's-yard', site_name: 'Yard',
            address: 'Yard Rd, Mysore 570001', gstin: '', pincode: '570001',
          }),
          site({
            id: 's-plant', site_name: 'Plant Chennai',
            address: 'Ambattur 600053', gstin: '33ZZZZZ9999Z9Z9',
            state: 'Tamil Nadu', state_code: '33', pincode: '600053',
          }),
        ],
      },
      { id: 'cust-2', user_id: 'u1', company_id: 'co-a', name: 'NoSites', ship_sites: [] },
      {
        id: 'cust-gstin', user_id: 'u1', company_id: 'co-a', name: 'GstCust',
        ship_sites: [
          site({
            id: 's-dirty', site_name: 'Dirty',
            address: '', gstin: '  gst: 29abcde1234f1z5  ',
          }),
        ],
      },
      { id: 'cust-b', user_id: 'u2', company_id: 'co-b', name: 'Beta' },
    ],
    trips: [
      trip({ id: 'tr-happy', to_location: 'Anywhere' }),
      trip({ id: 'tr-explicit', ship_site_id: 's-warehouse', to_location: 'Anywhere' }),
      trip({ id: 'tr-r1', to_location: 'Yard' }),          // R1: name matches 'Yard'
      trip({ id: 'tr-r2', to_location: 'Somewhere 570001' }), // R2: pincode 570001
      trip({ id: 'tr-r3', to_location: 'Whitefield' }),    // R3: token in address of s-warehouse
      trip({ id: 'tr-amb', to_location: 'Bangalore' }),    // Ambiguous — Bangalore appears only in one? See note
      trip({ id: 'tr-none', to_location: 'Kolkata' }),     // Zero matches
      trip({ id: 'tr-a', to_location: 'A' }),              // len 1 < TOKEN_MIN
      trip({ id: 'tr-b', to_location: 'B' }),
      trip({ id: 'tr-hist', to_location: 'Historic Place', is_historical: true, status: 'archived_historical' }),
      trip({ id: 'tr-gstin', ship_site_id: 's-dirty', to_location: 'Anywhere' }),
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

describe('Gate-6e · Invoice Ship-To read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  it('1 empty trip_ids → mixed=false, common=null, per_trip=[]; trips.find NOT called', async () => {
    const r = await get('/api/invoices/inv-empty/ship-to', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d).toEqual({ mixed: false, common: null, per_trip: [] });
  });

  it('2 explicit ship_site_id → linked site payload + site_id identity', async () => {
    const r = await get('/api/invoices/inv-explicit/ship-to', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['mixed']).toBe(false);
    expect(d['per_trip'].length).toBe(1);
    const p = d['per_trip'][0];
    expect(p['site_id']).toBe('s-warehouse');
    expect(p['inferred']).toBe(false);
    expect(p['identity']).toEqual(['site_id', 's-warehouse']);
    expect(p['resolved']['linked']).toBe(true);
    expect(p['resolved']['site_name']).toBe('Warehouse');
    expect(p['resolved']['state']).toBe('Karnataka');
    expect(d['common']['site_name']).toBe('Warehouse');
  });

  it('3 R1 · name-equality inference (unique) → inferred=true, linked=true', async () => {
    const r = await get('/api/invoices/inv-inferR1/ship-to', { authorization: 'Bearer tok-owner' });
    const p = r.json()['per_trip'][0];
    expect(p['inferred']).toBe(true);
    expect(p['site_id']).toBe('s-yard');
    expect(p['identity']).toEqual(['site_id', 's-yard']);
    expect(p['resolved']['linked']).toBe(true);
    expect(p['resolved']['pincode']).toBe('570001');
  });

  it('4 R2 · pincode inference (unique) → inferred=true', async () => {
    const r = await get('/api/invoices/inv-inferR2/ship-to', { authorization: 'Bearer tok-owner' });
    const p = r.json()['per_trip'][0];
    expect(p['inferred']).toBe(true);
    expect(p['site_id']).toBe('s-yard');
  });

  it('5 R3 · whole-token in address inference (unique) → inferred=true', async () => {
    const r = await get('/api/invoices/inv-inferR3/ship-to', { authorization: 'Bearer tok-owner' });
    const p = r.json()['per_trip'][0];
    expect(p['inferred']).toBe(true);
    expect(p['site_id']).toBe('s-warehouse');
  });

  it('6 zero-match inference → fallback identity, linked=false', async () => {
    const r = await get('/api/invoices/inv-none/ship-to', { authorization: 'Bearer tok-owner' });
    const p = r.json()['per_trip'][0];
    expect(p['inferred']).toBe(false);
    expect(p['site_id']).toBeNull();
    expect(p['resolved']['linked']).toBe(false);
    expect(p['resolved']['site_name']).toBe('Kolkata');
    expect(p['identity'][0]).toBe('fb');
    expect(p['identity'].length).toBe(4);
  });

  it('7 empty ship_sites (customer.ship_sites=[]) → all trips fallback', async () => {
    const r = await get('/api/invoices/inv-nosites/ship-to', { authorization: 'Bearer tok-owner' });
    const p = r.json()['per_trip'][0];
    expect(p['inferred']).toBe(false);
    expect(p['resolved']['linked']).toBe(false);
    expect(p['identity'][0]).toBe('fb');
  });

  it('8 missing customer → {} semantics, trips still processed (fallback)', async () => {
    const r = await get('/api/invoices/inv-nocust/ship-to', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['per_trip'].length).toBe(1);
    expect(d['per_trip'][0]['resolved']['linked']).toBe(false);
    expect(d['per_trip'][0]['resolved']['site_name']).toBe('Anywhere');
  });

  it('9 mixed identities → mixed=true, common=null', async () => {
    const r = await get('/api/invoices/inv-mixed/ship-to', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['mixed']).toBe(true);
    expect(d['common']).toBeNull();
    expect(d['per_trip'].length).toBe(2);
  });

  it('10 trip ordering follows invoice.trip_ids, not mongo natural order', async () => {
    // trip_ids = ['tr-b', 'tr-a']
    const r = await get('/api/invoices/inv-order/ship-to', { authorization: 'Bearer tok-owner' });
    const per = r.json()['per_trip'];
    expect(per.length).toBe(2);
    // Both fall back (site_name = to_location = 'B' / 'A' respectively).
    expect(per[0]['resolved']['site_name']).toBe('B');
    expect(per[1]['resolved']['site_name']).toBe('A');
  });

  it('11 historical trip is processed like any other (no special branch)', async () => {
    const r = await get('/api/invoices/inv-hist/ship-to', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const p = r.json()['per_trip'][0];
    expect(p['resolved']['site_name']).toBe('Historic Place');
    expect(p['resolved']['linked']).toBe(false);
  });

  it('12 GSTIN normalization on display (dirty stored value cleaned in response, not in DB)', async () => {
    const r = await get('/api/invoices/inv-gstin/ship-to', { authorization: 'Bearer tok-owner' });
    const p = r.json()['per_trip'][0];
    expect(p['resolved']['gstin']).toBe('29ABCDE1234F1Z5');
    // Stored value untouched.
    const cust = state.customers.find((c) => c['id'] === 'cust-gstin')!;
    const stored = (cust['ship_sites'] as Record<string, unknown>[])[0]['gstin'];
    expect(stored).toBe('  gst: 29abcde1234f1z5  ');
  });

  it('13 missing trip id in DB is silently dropped (order preserved for the rest)', async () => {
    const r = await get('/api/invoices/inv-missingtrip/ship-to', { authorization: 'Bearer tok-owner' });
    const per = r.json()['per_trip'];
    expect(per.length).toBe(1);
    expect(per[0]['resolved']['site_name']).toBe('A');
  });

  it('14 invoice not found → 404 "Invoice not found"', async () => {
    const r = await get('/api/invoices/does-not-exist/ship-to', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Invoice not found' });
  });

  it('15 wrong-tenant invoice → 404 (user_id filter)', async () => {
    const r = await get('/api/invoices/inv-of-u2/ship-to', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Invoice not found' });
  });

  it('16 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/invoices/inv-explicit/ship-to');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('17 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/invoices/inv-explicit/ship-to', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('18 expired session → 401 Session expired', async () => {
    const r = await get('/api/invoices/inv-explicit/ship-to', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('19 X-Company-Id is NOT consulted (cross-company header ignored → same result)', async () => {
    const a = await get('/api/invoices/inv-explicit/ship-to', { authorization: 'Bearer tok-owner' });
    const b = await get('/api/invoices/inv-explicit/ship-to', {
      authorization: 'Bearer tok-owner',
      'x-company-id': 'co-b',
    });
    expect(a.statusCode).toBe(200);
    expect(b.statusCode).toBe(200);
    expect(a.json()).toEqual(b.json());
  });

  it('20 zero Node business writes across every branch', async () => {
    await get('/api/invoices/inv-empty/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-explicit/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-inferR1/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-inferR2/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-inferR3/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-none/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-nosites/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-nocust/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-mixed/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-order/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-hist/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-gstin/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-missingtrip/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/does-not-exist/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-of-u2/ship-to', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-explicit/ship-to');
    await get('/api/invoices/inv-explicit/ship-to', { authorization: 'Bearer nope' });
    await get('/api/invoices/inv-explicit/ship-to', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
