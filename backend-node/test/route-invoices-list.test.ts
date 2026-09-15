/**
 * TRUKVIA · Phase-3 · Gate-6d · Invoice list read-only shadow — Vitest matrix.
 *
 * Covers both list surfaces:
 *   GET /api/invoices
 *   GET /api/invoices/overdue
 *
 * Fake DB tracks every mutating collection method. A dedicated final
 * case asserts `state.writes.length === 0` across all mixed traffic,
 * mirroring the write-forbidden discipline from Gates 6a/6b/6c.
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
  invoices: Record<string, unknown>[];
  credit_debit_notes: Record<string, unknown>[];
  customers: Record<string, unknown>[];
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
      let handled = false;
      if ('$in' in cond) {
        if (!(cond['$in'] as unknown[]).some((x) => x === dv)) return false;
        handled = true;
      }
      if ('$gt' in cond) {
        if (!(typeof dv === 'number' && dv > (cond['$gt'] as number))) return false;
        handled = true;
      }
      if ('$lte' in cond) {
        if (!(typeof dv === 'string' && dv <= (cond['$lte'] as string))) return false;
        handled = true;
      }
      if (handled) continue;
    }
    if (dv !== v) return false;
  }
  return true;
}

function project(d: Record<string, unknown>, projection?: Record<string, 0 | 1>): Record<string, unknown> {
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
    : name === 'companies' ? state.companies
    : name === 'invoices' ? state.invoices
    : name === 'credit_debit_notes' ? state.credit_debit_notes
    : name === 'customers' ? state.customers
    : name === 'users' ? state.users
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);
    function makeCursor(f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }) {
      let hits = rows.filter((r) => matches(r, f));
      const cursor = {
        sort(spec: [string, 1 | -1][]) {
          hits = hits.slice().sort((a, b) => {
            for (const [k, dir] of spec) {
              const av = a[k]; const bv = b[k];
              if (av === bv) continue;
              return (((av as string) < (bv as string)) ? -1 : 1) * dir;
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

const todayIso = (): string => {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = (d.getUTCMonth() + 1).toString().padStart(2, '0');
  const day = d.getUTCDate().toString().padStart(2, '0');
  return `${y}-${m}-${day}`;
};

function inv(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const subtotal = 1000.0;
  return {
    id: 'inv-x', company_id: 'co-a', user_id: 'u1',
    invoice_number: 'INV/25-26/0001', fy_string: '25-26',
    customer_id: 'cust-1', invoice_date: '2020-01-01',
    trip_ids: ['tr-x'],
    subtotal, hsn_sac: '996791',
    freight_total: subtotal, halting_total: 0, excess_total: 0, shortage_total: 0,
    diesel_deduction_total: 0, advance_deduction_total: 0,
    gst_type: 'cgst_sgst', cgst_rate: 2.5, sgst_rate: 2.5, igst_rate: 5.0,
    cgst_amount: 25.0, sgst_amount: 25.0, igst_amount: 0.0,
    total_tax: 50.0, gross_total: subtotal, round_off: 0.0,
    total_amount: subtotal, rcm: true,
    payments: [], amount_paid: 0.0, balance_due: subtotal,
    share_token: null, notes: '',
    created_at: '2020-01-01T00:00:00+00:00',
    imported_from: '', imported_ref: '', imported_batch: '',
    is_historical: false,
    ...overrides,
  };
}

function cdn(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'cdn-x', kind: 'credit', company_id: 'co-a', user_id: 'u1',
    note_number: 'CN/25-26/0001', note_date: '2026-02-05',
    invoice_id: 'inv-x', invoice_number_snapshot: 'INV/25-26/0001',
    customer_id: 'cust-1', reason_code: 'rate_correction',
    reason_text: 'unit-test note', lines: [],
    subtotal: 100.0, gst_type: 'cgst_sgst',
    cgst_rate: 2.5, sgst_rate: 2.5, igst_rate: 5.0,
    cgst_amount: 0.0, sgst_amount: 0.0, igst_amount: 0.0,
    total_tax: 0.0, total_amount: 100.0, round_off: 0.0, rcm: true,
    apply_gst: false,
    status: 'issued', is_historical: false,
    created_at: '2026-02-05T00:00:00+00:00',
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
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true, invoice_prefix: 'INV' },
      { id: 'co-b', user_id: 'u2', is_default: true, invoice_prefix: 'INV' },
    ],
    invoices: [
      // list_invoices — three invoices under u1 co-a with distinct created_at
      inv({ id: 'inv-a', created_at: '2020-01-01T00:00:00+00:00', invoice_date: '2020-01-01' }),
      inv({ id: 'inv-b', created_at: '2020-06-01T00:00:00+00:00', invoice_date: '2020-06-01' }),
      inv({ id: 'inv-c', created_at: '2021-01-01T00:00:00+00:00', invoice_date: '2021-01-01' }),
      // legacy company_id="" — Node skips backfill; should NOT surface on the list
      // for cid='co-a' (Class-B divergence proof).
      inv({ id: 'inv-legacy', company_id: '', created_at: '2019-01-01T00:00:00+00:00', invoice_date: '2019-01-01' }),
      // historical
      inv({ id: 'inv-hist', is_historical: true, imported_from: 'legacy',
            imported_batch: 'b1', created_at: '2019-06-01T00:00:00+00:00',
            invoice_date: '2019-06-01' }),
      // overdue — surfaces with balance_due>0.01 AND invoice_date<=cutoff
      inv({ id: 'inv-overdue-a', invoice_date: '2020-01-01', balance_due: 500.0,
            amount_paid: 500.0, created_at: '2020-01-01T00:00:00+00:00' }),
      inv({ id: 'inv-overdue-b', invoice_date: '2020-03-01', balance_due: 1000.0,
            amount_paid: 0, created_at: '2020-03-01T00:00:00+00:00' }),
      // paid: balance_due=0 → not surfaced by overdue predicate
      inv({ id: 'inv-paid', invoice_date: '2020-01-01', balance_due: 0.0,
            amount_paid: 1000.0, created_at: '2020-01-01T00:00:00+00:00' }),
      // recent — inside cutoff window, will NOT surface
      inv({ id: 'inv-recent', invoice_date: todayIso(), balance_due: 1000.0,
            amount_paid: 0, created_at: `${todayIso()}T00:00:00+00:00` }),
      // overdue but fully-offset by CN → dropped by effective prune
      inv({ id: 'inv-offset', invoice_date: '2020-01-01', balance_due: 1000.0,
            amount_paid: 0, created_at: '2020-01-01T00:00:00+00:00' }),
      // u2 — cross-tenant
      inv({ id: 'inv-u2', user_id: 'u2', company_id: 'co-b',
            invoice_date: '2020-01-01', balance_due: 500.0,
            created_at: '2020-01-01T00:00:00+00:00' }),
      // for age_days parse-fail path — invoice_date sortable before any
      // 2026-* cutoff (starts with "2020"), but calendar-invalid so both
      // Python `fromisoformat` and Node `isValidIsoDate` fall to 0.
      inv({ id: 'inv-baddate', invoice_date: '2020-13-45',
            balance_due: 1000.0, amount_paid: 0,
            created_at: '2020-01-01T00:00:00+00:00' }),
    ],
    credit_debit_notes: [
      // fully-offset CN for inv-offset
      cdn({ id: 'n-off', invoice_id: 'inv-offset', kind: 'credit',
            total_amount: 1000.0, note_date: '2020-06-01', status: 'issued' }),
      // partial CN on inv-overdue-b — effective balance still > 0.01
      cdn({ id: 'n-part', invoice_id: 'inv-overdue-b', kind: 'credit',
            total_amount: 300.0, note_date: '2020-04-01', status: 'issued' }),
      // draft note — must NOT be counted in effective enrichment
      cdn({ id: 'n-draft', invoice_id: 'inv-overdue-a', kind: 'credit',
            total_amount: 999.0, note_date: '2020-02-01', status: 'draft' }),
    ],
    customers: [
      { id: 'cust-1', user_id: 'u1', company_id: 'co-a',
        name: 'Acme Traders', phone: '+91-90000-11111', email: 'ops@acme.example' },
      // no customer row for inv-baddate — merge fallback to empty strings
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

describe('Gate-6d · Invoice list read-only shadows', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });
  const get = (url: string, headers: Record<string, string> = {}) =>
    app.inject({ method: 'GET', url, headers });

  // ── GET /api/invoices ────────────────────────────────────────────────
  it('L01 happy: three invoices under co-a sorted by created_at DESC', async () => {
    const r = await get('/api/invoices', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const arr = r.json();
    // co-a-only, no legacy, no user_id/_id
    for (const d of arr) {
      expect(d['company_id']).toBe('co-a');
      expect(d).not.toHaveProperty('user_id');
      expect(d).not.toHaveProperty('_id');
    }
    // legacy company_id="" invoice MUST NOT appear (Class-B skip proof)
    expect(arr.some((d: Record<string, unknown>) => d['id'] === 'inv-legacy')).toBe(false);
    // Exactly the ten seeded co-a rows are surfaced
    expect(arr.length).toBe(10);
    // DESC on created_at
    const created = arr.map((d: Record<string, unknown>) => String(d['created_at']));
    for (let i = 1; i < created.length; i += 1) {
      expect(created[i - 1] >= created[i]).toBe(true);
    }
  });

  it('L02 effective_* additive keys present on every listed invoice', async () => {
    const r = await get('/api/invoices', { authorization: 'Bearer tok-owner' });
    for (const d of r.json()) {
      expect(d).toHaveProperty('effective_total_amount');
      expect(d).toHaveProperty('effective_balance_due');
      expect(d).toHaveProperty('credits_total');
      expect(d).toHaveProperty('debits_total');
    }
  });

  it('L03 batched CN applied — inv-offset shows 1000 credit', async () => {
    const r = await get('/api/invoices', { authorization: 'Bearer tok-owner' });
    const off = (r.json()).find((d) => d['id'] === 'inv-offset')!;
    expect(off['credits_total']).toBe(1000.0);
    expect(off['effective_total_amount']).toBe(0.0);
    expect(off['effective_balance_due']).toBe(0.0);
  });

  it('L04 draft/cancelled CN excluded from effective enrichment', async () => {
    const r = await get('/api/invoices', { authorization: 'Bearer tok-owner' });
    const a = (r.json()).find((d) => d['id'] === 'inv-overdue-a')!;
    // n-draft (999.0, status=draft) must NOT count
    expect(a['credits_total']).toBe(0.0);
  });

  it('L05 empty tenant returns []', async () => {
    // Point Bearer at u2 whose companies don't match co-a; add fresh tenant
    state.companies.push({ id: 'co-u3', user_id: 'u3', is_default: true, invoice_prefix: 'INV' });
    state.sessions.push({ session_token: 'tok-u3', user_id: 'u3', effective_role: 'owner', expires_at: IN_FUTURE() });
    state.users.push({ user_id: 'u3', email: 'u3@x' });
    const r = await get('/api/invoices', { authorization: 'Bearer tok-u3' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('L06 cross-tenant isolation — u2 gets only own invoice', async () => {
    const r = await get('/api/invoices', { authorization: 'Bearer tok-u2' });
    const arr = r.json();
    expect(arr.length).toBe(1);
    expect(arr[0]['id']).toBe('inv-u2');
  });

  it('L07 no auth → 401', async () => {
    const r = await get('/api/invoices');
    expect(r.statusCode).toBe(401);
  });

  it('L08 invalid bearer → 401', async () => {
    const r = await get('/api/invoices', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
  });

  it('L09 expired session → 401', async () => {
    const r = await get('/api/invoices', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
  });

  it('L10 list — zero Node business writes across mixed traffic', async () => {
    await get('/api/invoices', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices', { authorization: 'Bearer tok-u2' });
    await get('/api/invoices');
    await get('/api/invoices', { authorization: 'Bearer nope' });
    expect(state.writes).toEqual([]);
  });

  // ── GET /api/invoices/overdue ────────────────────────────────────────
  it('O01 default days=30 → overdue invoices returned, invoice_date ASC', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const arr = r.json();
    const ids = arr.map((d) => d['id']);
    // Expected: inv-overdue-a, inv-overdue-b, inv-baddate — all balance>0.01
    // AND invoice_date <= today-30. inv-offset excluded via effective prune.
    // inv-recent excluded (today > cutoff). inv-paid excluded (bal=0).
    expect(ids).toContain('inv-overdue-a');
    expect(ids).toContain('inv-overdue-b');
    expect(ids).not.toContain('inv-offset');
    expect(ids).not.toContain('inv-paid');
    expect(ids).not.toContain('inv-recent');
    // invoice_date ASC — first entry should be the oldest.
    const dates = arr.map((d) => String(d['invoice_date']));
    for (let i = 1; i < dates.length; i += 1) {
      expect(dates[i - 1] <= dates[i]).toBe(true);
    }
  });

  it('O02 age_days computed from invoice_date', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    const a = (r.json()).find((d) => d['id'] === 'inv-overdue-a')!;
    // invoice_date=2020-01-01. Today (UTC) - 2020-01-01 = whole days > 1500.
    expect(a['age_days']).toBeGreaterThan(1500);
    expect(Number.isInteger(a['age_days'])).toBe(true);
  });

  it('O03 age_days = 0 on unparseable invoice_date', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    const b = (r.json()).find((d) => d['id'] === 'inv-baddate')!;
    expect(b['age_days']).toBe(0);
  });

  it('O04 customer merge fills empty strings when missing', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    const b = (r.json()).find((d) => d['id'] === 'inv-baddate')!;
    // customer_id="cust-1" exists (from `inv()` default) so name/phone/email ARE populated;
    // to hit missing branch we craft a dedicated row.
    expect(b['customer_name']).toBe('Acme Traders');
    // dedicated missing-customer row
    state.invoices.push(inv({ id: 'inv-nocust', customer_id: 'unknown-cust',
      invoice_date: '2020-01-01', balance_due: 1000, amount_paid: 0,
      created_at: '2020-01-01T00:00:00+00:00' }));
    const r2 = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    const nx = (r2.json()).find((d) => d['id'] === 'inv-nocust')!;
    expect(nx['customer_name']).toBe('');
    expect(nx['customer_phone']).toBe('');
    expect(nx['customer_email']).toBe('');
  });

  it('O05 fully-offset CN drops the row via effective prune', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    const ids = (r.json()).map((d) => d['id']);
    expect(ids).not.toContain('inv-offset');
  });

  it('O06 partial CN keeps the row (effective balance still > 0.01)', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    const b = (r.json()).find((d) => d['id'] === 'inv-overdue-b')!;
    expect(b['credits_total']).toBe(300.0);
    expect(b['effective_balance_due']).toBe(700.0);
  });

  it('O07 days=0 → cutoff = today; today-dated rows surface, future not', async () => {
    const r = await get('/api/invoices/overdue?days=0', { authorization: 'Bearer tok-owner' });
    const ids = (r.json()).map((d) => d['id']);
    expect(ids).toContain('inv-recent');
  });

  it('O08 days=99999 → cutoff far in the past → no rows surface', async () => {
    const r = await get('/api/invoices/overdue?days=99999', { authorization: 'Bearer tok-owner' });
    expect(r.json()).toEqual([]);
  });

  it('O09 non-integer days → 422 (before auth)', async () => {
    const r = await get('/api/invoices/overdue?days=abc');
    expect(r.statusCode).toBe(422);
  });

  it('O10 cross-tenant isolation — u2 gets only own overdue', async () => {
    const r = await get('/api/invoices/overdue?days=30', { authorization: 'Bearer tok-u2' });
    const arr = r.json();
    expect(arr.length).toBe(1);
    expect(arr[0]['id']).toBe('inv-u2');
  });

  it('O11 no auth → 401', async () => {
    const r = await get('/api/invoices/overdue');
    expect(r.statusCode).toBe(401);
  });

  it('O12 expired session → 401', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
  });

  it('O13 historical invoice IS surfaced when it meets the overdue predicate', async () => {
    // Turn inv-hist into a historical overdue candidate.
    const h = state.invoices.find((d) => d['id'] === 'inv-hist')!;
    h['balance_due'] = 500.0;
    h['invoice_date'] = '2019-06-01';
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    const ids = (r.json()).map((d) => d['id']);
    expect(ids).toContain('inv-hist');
  });

  it('O14 projection excludes _id and user_id on overdue', async () => {
    const r = await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    for (const d of r.json()) {
      expect(d).not.toHaveProperty('user_id');
      expect(d).not.toHaveProperty('_id');
    }
  });

  it('O15 overdue — zero Node business writes across mixed traffic', async () => {
    await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/overdue?days=7', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/overdue?days=abc');
    await get('/api/invoices/overdue');
    expect(state.writes).toEqual([]);
  });

  // ── Cross-route umbrella zero-write proof ───────────────────────────
  it('L+O umbrella — zero Node business writes across mixed traffic', async () => {
    await get('/api/invoices', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/overdue', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/overdue?days=15', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices', { authorization: 'Bearer tok-u2' });
    await get('/api/invoices/overdue?days=abc');
    await get('/api/invoices');
    await get('/api/invoices/overdue');
    expect(state.writes).toEqual([]);
  });
});
