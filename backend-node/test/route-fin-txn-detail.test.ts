/**
 * TRUKVIA · Phase-3 · Gate-7q · FinTxn detail read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/fin/fin-txn/:txid
 *
 * Fake-DB write-forbid pattern inlined (mirrors Gate 7p). Exercises the 404
 * literal, all 12 coll_map source types, the intentional `driver_payment`
 * gap, and every best-effort `source: {}` fallback (unknown / non-string
 * source_type, missing source doc, cross-company source, lookup error).
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

type Row = Record<string, unknown>;
interface State {
  colls: Record<string, Row[]>;
  failing: Set<string>;
  writes: string[];
  lookups: { coll: string; filter: Row; projection?: Record<string, 0 | 1> }[];
}

const MAP: [string, string][] = [
  ['invoice', 'invoices'], ['credit_debit_note', 'credit_debit_notes'],
  ['supplier_payment', 'supplier_payments'], ['vendor_payment', 'vendor_payments'],
  ['mechanic_payment', 'mechanic_payments'], ['expense', 'expenses'],
  ['vendor_bill', 'vendor_bills'], ['mechanic_work_order', 'mechanic_work_orders'],
  ['trip_customer_receipt', 'trips'], ['wallet_recharge', 'wallet_recharges'],
  ['wallet_transfer', 'wallet_transfers'], ['wallet_adjustment', 'wallet_adjustments'],
];

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

const matches = (d: Row, f: Row): boolean => Object.entries(f).every(([k, v]) => d[k] === v);

function project(d: Row, projection?: Record<string, 0 | 1>): Row {
  const o: Row = { ...d };
  if (!projection) return o;
  for (const [k, v] of Object.entries(projection)) if (v === 0) delete o[k];
  return o;
}

function fakeDb(state: State): Db {
  const collection = (name: string) => {
    const rows = state.colls[name] ?? [];
    return {
      find: vi.fn(() => { throw new Error(`unexpected find on ${name}`); }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Record<string, 0 | 1> }) => {
        if (!['user_sessions', 'users', 'companies'].includes(name)) {
          state.lookups.push({ coll: name, filter: f, projection: opts?.projection });
        }
        if (state.failing.has(name)) throw new Error(`boom on ${name}`);
        const hit = rows.find((r) => matches(r, f));
        return hit ? project(hit, opts?.projection) : null;
      }),
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

function tx(id: string, source_type: unknown, source_id: unknown, o: Row = {}): Row {
  const t: Row = { id, user_id: 'u1', company_id: 'co-a', txn_date: '2026-05-01', status: 'active',
    account_code: 'AR', direction: 'in', amount: 100.0, ...o };
  if (source_type !== undefined) t['source_type'] = source_type;
  if (source_id !== undefined) t['source_id'] = source_id;
  return t;
}

function makeState(): State {
  const colls: Record<string, Row[]> = {
    user_sessions: [
      { session_token: 'tok-u1',      user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2',      user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
    ],
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a',     user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b',     user_id: 'u2', is_default: true },
    ],
    fin_txn: [
      ...MAP.map(([st]) => tx(`tx-${st}`, st, `src-${st}`)),
      tx('tx-driver', 'driver_payment', 'src-driver'),
      tx('tx-unknown', 'mystery', 'src-x'),
      tx('tx-nosrc', 'invoice', 'src-missing'),
      tx('tx-xco-src', 'invoice', 'src-xco'),
      tx('tx-list', ['invoice'], 'src-invoice'),
      tx('tx-none', undefined, undefined),
      tx('tx-emptyid', 'expense', ''),
      tx('tx-alt', 'invoice', 'src-invoice', { company_id: 'co-a-alt' }),
      tx('tx-u2', 'invoice', 'src-invoice', { user_id: 'u2', company_id: 'co-b' }),
    ],
    driver_payments: [{ id: 'src-driver', user_id: 'u1', company_id: 'co-a' }],
  };
  for (const [st, coll] of MAP) {
    colls[coll] = [{ id: `src-${st}`, user_id: 'u1', company_id: 'co-a', label: st }];
  }
  (colls['invoices'] as Row[]).push({ id: 'src-xco', user_id: 'u1', company_id: 'co-a-alt' });
  (colls['expenses'] as Row[]).push({ id: '', user_id: 'u1', company_id: 'co-a', label: 'empty-id expense' });
  return { colls, failing: new Set(), writes: [], lookups: [] };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const U1 = { authorization: 'Bearer tok-u1' };
const url = (txid: string): string => `/api/fin/fin-txn/${txid}`;

describe('Gate-7q · FinTxn detail read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });

  it.each([
    [{}, 'Not authenticated'],
    [{ authorization: 'Bearer nope' }, 'Invalid session'],
    [{ authorization: 'Bearer tok-expired' }, 'Session expired'],
  ])('1 auth failure %j → 401 %s', async (h, detail) => {
    const r = await get(url('tx-invoice'), h as Record<string, string>);
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail });
    expect(state.lookups).toEqual([]);
  });

  it.each(MAP)('2 source_type %s → {collection: %s, doc}', async (st, coll) => {
    const r = await get(url(`tx-${st}`), U1);
    expect(r.statusCode).toBe(200);
    const body = r.json<{ txn: Row; source: Row }>();
    expect(Object.keys(body)).toEqual(['txn', 'source']);
    expect(body.txn['id']).toBe(`tx-${st}`);
    expect(body.txn).not.toHaveProperty('user_id');
    expect(body.source).toEqual({ collection: coll, doc: { id: `src-${st}`, company_id: 'co-a', label: st } });
  });

  it('3 exact reads · txn then mapped source', async () => {
    await get(url('tx-invoice'), U1);
    expect(state.lookups).toEqual([
      { coll: 'fin_txn', filter: { id: 'tx-invoice', user_id: 'u1', company_id: 'co-a' }, projection: { _id: 0, user_id: 0 } },
      { coll: 'invoices', filter: { user_id: 'u1', company_id: 'co-a', id: 'src-invoice' }, projection: { _id: 0, user_id: 0 } },
    ]);
  });

  it.each([
    ['driver_payment (intentional coll_map gap)', 'tx-driver', ['fin_txn']],
    ['unknown source_type', 'tx-unknown', ['fin_txn']],
    ['non-string source_type (list)', 'tx-list', ['fin_txn']],
    ['missing source_type / source_id', 'tx-none', ['fin_txn']],
    ['source doc missing', 'tx-nosrc', ['fin_txn', 'invoices']],
    ['source doc in other company', 'tx-xco-src', ['fin_txn', 'invoices']],
  ])('4 %s → source {}', async (_n, txid, colls) => {
    const r = await get(url(txid), U1);
    expect(r.statusCode).toBe(200);
    expect(r.json<Row>()['source']).toEqual({});
    expect(state.lookups.map((l) => l.coll)).toEqual(colls);
  });

  it('5 falsy source_id → lookup with "" (Python `or ""`)', async () => {
    const r = await get(url('tx-emptyid'), U1);
    expect(r.json<{ source: Row }>().source).toEqual({ collection: 'expenses', doc: { id: '', company_id: 'co-a', label: 'empty-id expense' } });
    expect(state.lookups[1]?.filter).toEqual({ user_id: 'u1', company_id: 'co-a', id: '' });
  });

  it('6 source lookup error swallowed → source {}', async () => {
    state.failing.add('invoices');
    const r = await get(url('tx-invoice'), U1);
    expect(r.statusCode).toBe(200);
    expect(r.json<Row>()['source']).toEqual({});
  });

  it.each([
    ['unknown txid', 'tx-gone', U1],
    ['cross-user txid', 'tx-u2', U1],
    ['other-company txid under default', 'tx-alt', U1],
  ])('7 %s → 404 FinTxn not found', async (_n, txid, h) => {
    const r = await get(url(txid), h);
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'FinTxn not found' });
    expect(state.lookups.map((l) => l.coll)).toEqual(['fin_txn']);
  });

  it('8 owned X-Company-Id co-a-alt → alt txn; source lookup scoped to alt', async () => {
    const r = await get(url('tx-alt'), { ...U1, 'x-company-id': 'co-a-alt' });
    expect(r.json<{ txn: Row; source: Row }>().txn['id']).toBe('tx-alt');
    expect(r.json<Row>()['source']).toEqual({});
    expect(state.lookups[1]?.filter).toEqual({ user_id: 'u1', company_id: 'co-a-alt', id: 'src-invoice' });
  });

  it('9 unowned X-Company-Id co-b → fallback co-a', async () => {
    const r = await get(url('tx-invoice'), { ...U1, 'x-company-id': 'co-b' });
    expect(r.statusCode).toBe(200);
  });

  it('10 cross-user u2 own txn', async () => {
    const r = await get(url('tx-u2'), { authorization: 'Bearer tok-u2' });
    expect(r.json<{ txn: Row }>().txn['id']).toBe('tx-u2');
  });

  it.each([
    ['/api/fin/fin-txn/a%2Fb', U1], ['/api/fin/fin-txn/a%2Fb', {}],
  ])('11 encoded slash %s → 404 Not Found before auth (%j)', async (path, h) => {
    const r = await get(path, h);
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Not Found' });
    expect(state.lookups).toEqual([]);
  });
});
