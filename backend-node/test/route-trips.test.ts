/**
 * TRUKVIA · Phase-3 · Gate-6a · GET /api/trips/{tid} unit tests.
 * Read-only route — fake DB verifies zero writes on every path.
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

const IN_FUTURE = () => new Date(Date.now() + 3600_000).toISOString();
const IN_PAST = () => new Date(Date.now() - 60_000).toISOString();

interface Session { session_token: string; user_id: string; effective_role: string; expires_at: string }
interface Company { id: string; user_id: string; is_default?: boolean }

interface State {
  sessions: Session[]; companies: Company[]; trips: Record<string, unknown>[];
  users: { user_id: string; email: string }[];
  writes: string[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

function fakeDb(state: State): Db {
  const projFn = (d: Record<string, unknown>, projection?: Record<string, 0 | 1>): Record<string, unknown> => {
    if (!projection) return { ...d };
    const exc = Object.entries(projection).filter(([, v]) => v === 0).map(([k]) => k);
    const o: Record<string, unknown> = { ...d };
    for (const k of exc) delete o[k];
    return o;
  };
  const matches = (d: Record<string, unknown>, f: Record<string, unknown>): boolean => {
    for (const [k, v] of Object.entries(f)) { if (d[k] !== v) return false; } return true;
  };
  const collection = (name: string) => {
    const rows: Record<string, unknown>[] =
      name === 'user_sessions' ? state.sessions as unknown as Record<string, unknown>[]
      : name === 'companies' ? state.companies as unknown as Record<string, unknown>[]
      : name === 'trips' ? state.trips
      : name === 'users' ? state.users as unknown as Record<string, unknown>[]
      : [];
    return {
      findOne: vi.fn(async (f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) => {
        const hit = rows.find((r) => matches(r, f));
        return hit ? projFn(hit, opts?.projection) : null;
      }),
      // ZERO writes allowed on ANY collection under Slice-6a.
      insertOne: vi.fn(forbid(state, `${name}.insertOne`)),
      updateOne: vi.fn(forbid(state, `${name}.updateOne`)),
      deleteOne: vi.fn(forbid(state, `${name}.deleteOne`)),
      insertMany: vi.fn(forbid(state, `${name}.insertMany`)),
      updateMany: vi.fn(forbid(state, `${name}.updateMany`)),
      deleteMany: vi.fn(forbid(state, `${name}.deleteMany`)),
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

function trip(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'trip_default1', company_id: 'co-a', user_id: 'u1',
    customer_id: 'cust-1', date: '2026-02-01', vehicle_number: 'AB01CD1234',
    vehicle_id: 'v1', vehicle_type: 'own', tons: 30, freight_mode: 'per_ton',
    rate_per_ton: 1000, fixed_amount: 0, freight_amount: 30000,
    loaded_qty: 30, unloaded_qty: 30, excess_qty: 0, shortage_qty: 0,
    shortage_amount: 0, excess_amount: 0, halting_amount: 0,
    supplier_diesel_entries: [], supplier_advance_entries: [],
    expenses: {}, total_expense: 0, profit: 0, net_settlement: 0,
    status: 'posted', is_historical: false,
    created_at: '2026-02-01T00:00:00.000Z',
    applied_freight_method: 'per_ton_loading',
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
    users: [ { user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' } ],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b', user_id: 'u2', is_default: true },
    ],
    trips: [
      trip({ id: 'trip_a1', customer_id: 'cust-1', company_id: 'co-a', user_id: 'u1', vehicle_number: 'AB01AA0001' }),
      trip({ id: 'trip_a2', customer_id: 'cust-2', company_id: 'co-a-alt', user_id: 'u1', vehicle_number: 'AB01AA0002' }),
      trip({ id: 'trip_b1', customer_id: 'cust-3', company_id: 'co-b', user_id: 'u2', vehicle_number: 'AB01AA0003' }),
      trip({ id: 'trip_hist', customer_id: 'cust-1', company_id: 'co-a', user_id: 'u1', vehicle_number: 'AB01AA0004',
        is_historical: true, imported_from: 'legacy', imported_batch: 'batch-1',
        status: 'archived_historical' }),
      trip({ id: 'trip_supp', customer_id: 'cust-1', company_id: 'co-a', user_id: 'u1', vehicle_number: 'AB01AA0005',
        vehicle_type: 'supplier', supplier_id: 'sup-1', supplier_name: 'Acme Suppliers',
        supplier_freight: 25000, supplier_net_payable: 22000,
        supplier_diesel_entries: [{ id: 'sd1', amount: 2000, date: '2026-02-01', mode: 'Bank' }],
        supplier_advance_entries: [{ id: 'sa1', amount: 1000, date: '2026-02-01', mode: 'Cash' }],
        customer_receipts: [{ id: 'r1', type: 'advance', amount: 500, date: '2026-02-01', mode: 'Bank' }],
        driver_recovery: { policy_id: 'pol1', method: 'rate_per_kg', rate_per_kg: 12 },
        applied_customer_shortage_limit: 100, applied_customer_shortage_limit_type: 'kg',
        applied_customer_shortage_method: 'net_shortage', applied_product_shortage_pct: 0.5,
        applied_supplier_shortage_limit_kg: 200, policy_snapshot_at: '2026-02-01T00:00:00.000Z' }),
    ],
    writes: [],
  };
}

async function makeApp(state: State) {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('GET /api/trips/{tid} — Gate-6a shadow (read-only)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (tid: string, headers: Record<string, string> = {}) =>
    app.inject({ method: 'GET', url: `/api/trips/${tid}`, headers });

  it('1 valid existing trip → 200 doc without user_id', async () => {
    const r = await get('trip_a1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['id']).toBe('trip_a1');
    expect(d['company_id']).toBe('co-a');
    expect(d).not.toHaveProperty('user_id');
    expect(d).not.toHaveProperty('_id');
  });

  it('2 not-found trip → 404 "Trip not found"', async () => {
    const r = await get('trip_nope', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Trip not found' });
  });

  it('3 unauthenticated → 401 Not authenticated', async () => {
    const r = await get('trip_a1');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('4 invalid token → 401 Invalid session', async () => {
    const r = await get('trip_a1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('5 expired session → 401 Session expired', async () => {
    const r = await get('trip_a1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('6 wrong-tenant trip → 404 (Isolation via find_one filter)', async () => {
    // trip_b1 belongs to u2/co-b — u1 must never see it.
    const r = await get('trip_b1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Trip not found' });
  });

  it('7 owned X-Company-Id override → returns trip from that company', async () => {
    const r = await get('trip_a2', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(r.statusCode).toBe(200);
    expect((r.json())['company_id']).toBe('co-a-alt');
  });

  it('8 unowned X-Company-Id → fallback to default (trip in fallback co-a returned)', async () => {
    const r = await get('trip_a1', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect(r.statusCode).toBe(200);
    expect((r.json())['company_id']).toBe('co-a');
  });

  it('9 cookie auth', async () => {
    const r = await get('trip_a1', { cookie: 'session_token=tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json())['id']).toBe('trip_a1');
  });

  it('10 historical trip returns is_historical=true', async () => {
    const r = await get('trip_hist', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['is_historical']).toBe(true);
    expect(d['status']).toBe('archived_historical');
  });

  it('11 supplier trip carries nested arrays and driver_recovery', async () => {
    const r = await get('trip_supp', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['vehicle_type']).toBe('supplier');
    expect(d['supplier_id']).toBe('sup-1');
    expect((d['supplier_diesel_entries'] as unknown[]).length).toBe(1);
    expect((d['supplier_advance_entries'] as unknown[]).length).toBe(1);
    expect((d['customer_receipts'] as unknown[]).length).toBe(1);
    expect(d['driver_recovery']).toBeTruthy();
  });

  it('12 empty arrays remain empty (not null)', async () => {
    const r = await get('trip_a1', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['supplier_diesel_entries']).toEqual([]);
    expect(d['supplier_advance_entries']).toEqual([]);
  });

  it('13 deterministic serialization — repeated GETs return identical body', async () => {
    const a = await get('trip_a1', { authorization: 'Bearer tok-owner' });
    const b = await get('trip_a1', { authorization: 'Bearer tok-owner' });
    expect(a.payload).toBe(b.payload);
  });

  it('14 write-observation — no writes on any path', async () => {
    await get('trip_a1', { authorization: 'Bearer tok-owner' });         // 200
    await get('trip_nope', { authorization: 'Bearer tok-owner' });       // 404
    await get('trip_a1');                                                 // 401
    await get('trip_a1', { authorization: 'Bearer nope' });               // 401
    await get('trip_a1', { authorization: 'Bearer tok-expired' });        // 401
    await get('trip_b1', { authorization: 'Bearer tok-owner' });          // 404 (isolation)
    await get('trip_supp', { authorization: 'Bearer tok-owner' });        // 200
    expect(state.writes).toEqual([]);
  });

  it('15 nested expenses object is passed through unchanged', async () => {
    state.trips[0]!.expenses = { toll: 250, misc: 100, notes: 'sample' };
    const r = await get('trip_a1', { authorization: 'Bearer tok-owner' });
    expect((r.json())['expenses']).toEqual({ toll: 250, misc: 100, notes: 'sample' });
  });

  it('16 same-user cross-company scoping: unowned override → not found in fallback', async () => {
    // trip_a2 is in co-a-alt; if user u1 sends X-Company-Id: co-b (unowned),
    // fallback lands on co-a — trip_a2 is not in co-a → 404.
    const r = await get('trip_a2', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect(r.statusCode).toBe(404);
  });
});
