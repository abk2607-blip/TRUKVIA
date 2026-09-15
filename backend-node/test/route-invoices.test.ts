/**
 * TRUKVIA · Phase-3 · Gate-6c · Invoice read-only shadow — Vitest matrix.
 *
 * Covers all three read-only surfaces:
 *   GET /api/invoices/{iid}
 *   GET /api/invoices/{iid}/notes
 *   GET /api/invoices/next-preview
 *
 * The fake DB tracks EVERY mutating collection method — a single call
 * raises + records the offending "collection.op" into `state.writes`.
 * All 34 cases assert `state.writes.length === 0` at teardown by way of
 * a dedicated final case, mirroring the write-forbidden discipline used
 * by Gates 6a / 6b.
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

const todayIsoUtc = (): string => {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = (d.getUTCMonth() + 1).toString().padStart(2, '0');
  const day = d.getUTCDate().toString().padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const tomorrowIsoUtc = (): string => {
  const d = new Date(Date.now() + 24 * 3600_000);
  const y = d.getUTCFullYear();
  const m = (d.getUTCMonth() + 1).toString().padStart(2, '0');
  const day = d.getUTCDate().toString().padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const fyFromIso = (iso: string): string => {
  const y = Number(iso.slice(0, 4));
  const m = Number(iso.slice(5, 7));
  const yr = y % 100;
  const yrNext = (y + 1) % 100;
  const pad = (n: number): string => n.toString().padStart(2, '0');
  return m >= 4 ? `${pad(yr)}-${pad(yrNext)}` : `${pad(yr - 1)}-${pad(yr)}`;
};

interface State {
  sessions: Record<string, unknown>[];
  users: Record<string, unknown>[];
  companies: Record<string, unknown>[];
  invoices: Record<string, unknown>[];
  credit_debit_notes: Record<string, unknown>[];
  writes: string[];
  // Test-time controls
  cdnFindThrows: boolean;
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
    : name === 'users' ? state.users
    : [];

  const collection = (name: string) => {
    const rows = rowsOf(name);

    function makeCursor(f: Record<string, unknown>, opts?: { projection?: Record<string, 0 | 1> }): {
      sort: (s: [string, 1 | -1][]) => ReturnType<typeof makeCursor>;
      skip: (n: number) => ReturnType<typeof makeCursor>;
      limit: (n: number) => ReturnType<typeof makeCursor>;
      toArray: () => Promise<Record<string, unknown>[]>;
    } {
      // Simulated read-time error path for the effective-balance omit case.
      if (name === 'credit_debit_notes' && state.cdnFindThrows) {
        const t = {
          sort: () => t,
          skip: () => t,
          limit: () => t,
          async toArray(): Promise<Record<string, unknown>[]> {
            throw new Error('injected credit_debit_notes read failure');
          },
        };
        return t;
      }
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

/** A stored invoice that ALREADY reflects `_recompute_invoice` totals.
 *  rcm=true → gross_total = subtotal; final_amount = subtotal (integer);
 *  total_tax = 5% of subtotal for cgst_sgst. */
function inv(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const subtotal = 1000.0;
  return {
    id: 'inv-x', company_id: 'co-a', user_id: 'u1',
    invoice_number: 'INV/25-26/0001', fy_string: '25-26',
    customer_id: 'cust-1', invoice_date: '2026-02-01',
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
    created_at: '2026-02-01T00:00:00+00:00',
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
      { id: 'co-a', user_id: 'u1', is_default: true, invoice_prefix: 'INV',
        next_invoice_number: 1, next_invoice_number_by_fy: { '25-26': 42 } },
      { id: 'co-a-legacy', user_id: 'u1', is_default: false, invoice_prefix: 'INV',
        next_invoice_number: 15 },
      { id: 'co-a-fyprefix', user_id: 'u1', is_default: false, invoice_prefix: 'VBK/25-26',
        next_invoice_number: 1 },
      { id: 'co-a-fresh', user_id: 'u1', is_default: false, invoice_prefix: 'INV',
        next_invoice_number: 1 },
      { id: 'co-b', user_id: 'u2', is_default: true, invoice_prefix: 'INV',
        next_invoice_number: 1 },
    ],
    invoices: [
      inv({ id: 'inv-happy' }),
      inv({ id: 'inv-cn' }),
      inv({ id: 'inv-dn' }),
      inv({ id: 'inv-mixed' }),
      inv({ id: 'inv-cnx' }),
      inv({ id: 'inv-legacy', company_id: '' }),
      inv({ id: 'inv-hist', is_historical: true, imported_from: 'legacy',
            imported_ref: 'batch-1', imported_batch: 'b1' }),
      inv({ id: 'inv-of-u2', user_id: 'u2', company_id: 'co-b',
            customer_id: 'cust-b' }),
      inv({ id: 'inv-omit' }),
    ],
    credit_debit_notes: [
      // inv-cn : 1 issued CN
      cdn({ id: 'n1', invoice_id: 'inv-cn', kind: 'credit', total_amount: 200.0, note_date: '2026-02-10', status: 'issued' }),
      // inv-dn : 1 issued DN
      cdn({ id: 'n2', invoice_id: 'inv-dn', kind: 'debit', total_amount: 150.0, note_date: '2026-02-12', status: 'issued' }),
      // inv-mixed : issued CN + DN
      cdn({ id: 'n3', invoice_id: 'inv-mixed', kind: 'credit', total_amount: 300.0, note_date: '2026-02-06', status: 'issued' }),
      cdn({ id: 'n4', invoice_id: 'inv-mixed', kind: 'debit', total_amount: 200.0, note_date: '2026-02-07', status: 'issued' }),
      // inv-cnx : cancelled + draft (both excluded from effective totals)
      cdn({ id: 'n5', invoice_id: 'inv-cnx', kind: 'credit', total_amount: 500.0, note_date: '2026-02-03', status: 'cancelled' }),
      cdn({ id: 'n6', invoice_id: 'inv-cnx', kind: 'debit', total_amount: 250.0, note_date: '2026-02-08', status: 'draft' }),
    ],
    writes: [],
    cdnFindThrows: false,
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6c · Invoice read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── GET /api/invoices/{iid} ─────────────────────────────────────────
  it('1 happy: matching invoice returns as-stored + effective_* additive keys', async () => {
    const r = await get('/api/invoices/inv-happy', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['id']).toBe('inv-happy');
    expect(d).not.toHaveProperty('_id');
    expect(d).not.toHaveProperty('user_id');
    expect(d['effective_total_amount']).toBe(1000.0);
    expect(d['effective_balance_due']).toBe(1000.0);
    expect(d['credits_total']).toBe(0.0);
    expect(d['debits_total']).toBe(0.0);
  });

  it('2 invoice with issued credit note → effective_total reduced', async () => {
    const r = await get('/api/invoices/inv-cn', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['effective_total_amount']).toBe(800.0);
    expect(d['credits_total']).toBe(200.0);
    expect(d['debits_total']).toBe(0.0);
    expect(d['effective_balance_due']).toBe(800.0);
  });

  it('3 invoice with issued debit note → effective_total increased', async () => {
    const r = await get('/api/invoices/inv-dn', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['effective_total_amount']).toBe(1150.0);
    expect(d['debits_total']).toBe(150.0);
    expect(d['credits_total']).toBe(0.0);
    expect(d['effective_balance_due']).toBe(1150.0);
  });

  it('4 invoice with mixed CN/DN → net delta applied', async () => {
    const r = await get('/api/invoices/inv-mixed', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['credits_total']).toBe(300.0);
    expect(d['debits_total']).toBe(200.0);
    expect(d['effective_total_amount']).toBe(900.0);
    expect(d['effective_balance_due']).toBe(900.0);
  });

  it('5 cancelled + draft notes are excluded from effective totals', async () => {
    const r = await get('/api/invoices/inv-cnx', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['credits_total']).toBe(0.0);
    expect(d['debits_total']).toBe(0.0);
    expect(d['effective_total_amount']).toBe(1000.0);
    expect(d['effective_balance_due']).toBe(1000.0);
  });

  it('6 legacy company_id="" invoice still returns effective_* (company_id filter dropped)', async () => {
    const r = await get('/api/invoices/inv-legacy', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['company_id']).toBe('');
    expect(d['effective_total_amount']).toBe(1000.0);
  });

  it('7 historical invoice passes through imported_* and is_historical=true', async () => {
    const r = await get('/api/invoices/inv-hist', { authorization: 'Bearer tok-owner' });
    const d = r.json();
    expect(d['is_historical']).toBe(true);
    expect(d['imported_from']).toBe('legacy');
    expect(d['imported_batch']).toBe('b1');
    expect(d['effective_total_amount']).toBe(1000.0);
  });

  it('8 invoice not found → 404 "Invoice not found"', async () => {
    const r = await get('/api/invoices/does-not-exist', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Invoice not found' });
  });

  it('9 wrong-tenant invoice → 404 (isolation via user_id filter)', async () => {
    const r = await get('/api/invoices/inv-of-u2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Invoice not found' });
  });

  it('10 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/invoices/inv-happy');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('11 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/invoices/inv-happy', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('12 expired session → 401 Session expired', async () => {
    const r = await get('/api/invoices/inv-happy', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('13 effective_* helper error → keys OMITTED (not null)', async () => {
    state.cdnFindThrows = true;
    const r = await get('/api/invoices/inv-omit', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d).not.toHaveProperty('effective_total_amount');
    expect(d).not.toHaveProperty('effective_balance_due');
    expect(d).not.toHaveProperty('credits_total');
    expect(d).not.toHaveProperty('debits_total');
    // core stored fields still present
    expect(d['total_amount']).toBe(1000.0);
  });

  it('14 invoice detail — zero Node business writes on every branch', async () => {
    await get('/api/invoices/inv-happy', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-cn', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-mixed', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/does-not-exist', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-of-u2', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-happy');
    await get('/api/invoices/inv-happy', { authorization: 'Bearer nope' });
    await get('/api/invoices/inv-happy', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });

  // ── GET /api/invoices/{iid}/notes ───────────────────────────────────
  it('15 no notes → []', async () => {
    const r = await get('/api/invoices/inv-happy/notes', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('16 issued credit note surfaces', async () => {
    const r = await get('/api/invoices/inv-cn/notes', { authorization: 'Bearer tok-owner' });
    const arr = r.json();
    expect(arr.length).toBe(1);
    expect(arr[0]['id']).toBe('n1');
    expect(arr[0]['status']).toBe('issued');
    expect(arr[0]).not.toHaveProperty('user_id');
  });

  it('17 cancelled note IS returned (no server-side status filter)', async () => {
    const r = await get('/api/invoices/inv-cnx/notes', { authorization: 'Bearer tok-owner' });
    const arr = r.json();
    const statuses = arr.map((n: Record<string, unknown>) => n['status']).sort();
    expect(statuses).toEqual(['cancelled', 'draft']);
  });

  it('18 mixed statuses on a single invoice — all returned', async () => {
    // seed extra draft on inv-mixed
    state.credit_debit_notes.push(cdn({ id: 'n3d', invoice_id: 'inv-mixed', kind: 'credit', total_amount: 10.0, note_date: '2026-02-04', status: 'draft' }));
    const r = await get('/api/invoices/inv-mixed/notes', { authorization: 'Bearer tok-owner' });
    const statuses = r.json().map((n: Record<string, unknown>) => n['status']).sort();
    expect(statuses).toEqual(['draft', 'issued', 'issued']);
  });

  it('19 unowned invoice_id → [] (no invoice-existence probe)', async () => {
    const r = await get('/api/invoices/inv-of-u2/notes', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  it('20 no auth → 401', async () => {
    const r = await get('/api/invoices/inv-cn/notes');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('21 note_date ASC ordering', async () => {
    // seed two more notes on inv-cn with earlier and later dates
    state.credit_debit_notes.push(cdn({ id: 'n1a', invoice_id: 'inv-cn', kind: 'credit', total_amount: 50.0, note_date: '2026-01-15', status: 'issued' }));
    state.credit_debit_notes.push(cdn({ id: 'n1c', invoice_id: 'inv-cn', kind: 'debit', total_amount: 20.0, note_date: '2026-03-01', status: 'issued' }));
    const r = await get('/api/invoices/inv-cn/notes', { authorization: 'Bearer tok-owner' });
    const dates = r.json().map((n: Record<string, unknown>) => n['note_date']);
    expect(dates).toEqual(['2026-01-15', '2026-02-10', '2026-03-01']);
  });

  // ── GET /api/invoices/next-preview ──────────────────────────────────
  it('22 existing FY bucket → uses stored seq', async () => {
    const r = await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    // default company co-a has fy_map['25-26']=42, prefix INV
    expect(r.json()).toEqual({ suggested_number: 'INV/25-26/0042', fy: '25-26', editable: false });
  });

  it('23 legacy scalar fallback when FY bucket absent and fy==server_fy', async () => {
    // Use co-a-legacy: no fy bucket, next_invoice_number=15.
    // Use today's date so fy_str == server_fy (always true).
    const t = todayIsoUtc();
    const r = await get(`/api/invoices/next-preview?invoice_date=${t}`,
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-legacy' });
    expect(r.statusCode).toBe(200);
    const j = r.json();
    expect(j['fy']).toBe(fyFromIso(t));
    expect(j['suggested_number']).toBe(`INV/${fyFromIso(t)}/0015`);
    expect(j['editable']).toBe(false);
  });

  it('24 FY boundary — Mar 31 vs Apr 1', async () => {
    // Both dates in the past (2025-*), both no FY bucket on co-a-legacy;
    // legacy scalar seed applies only when fy_str == server_fy — for a
    // past-FY invoice_date the seed does NOT apply → seq=1.
    const r1 = await get('/api/invoices/next-preview?invoice_date=2025-03-31',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-legacy' });
    const r2 = await get('/api/invoices/next-preview?invoice_date=2025-04-01',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-legacy' });
    expect(r1.json()['fy']).toBe('24-25');
    expect(r2.json()['fy']).toBe('25-26');
    expect(r1.json()['suggested_number']).toBe('INV/24-25/0001');
    // For fy=25-26 with today's server_fy=25-26 the legacy seed DOES apply.
    // We assert both possible outcomes by branch:
    const sfy = fyFromIso(todayIsoUtc());
    const expected25_26 = sfy === '25-26' ? 'INV/25-26/0015' : 'INV/25-26/0001';
    expect(r2.json()['suggested_number']).toBe(expected25_26);
  });

  it('25 future invoice_date → 400', async () => {
    const r = await get(`/api/invoices/next-preview?invoice_date=${tomorrowIsoUtc()}`,
      { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'invoice_date cannot be in the future' });
  });

  it('26 invalid ISO → 400', async () => {
    const r = await get('/api/invoices/next-preview?invoice_date=2026-02-31',
      { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({ detail: 'invoice_date must be ISO YYYY-MM-DD' });
  });

  it('27 missing invoice_date → 422 (before auth)', async () => {
    // No Authorization header — but 422 still fires first.
    const r = await get('/api/invoices/next-preview');
    expect(r.statusCode).toBe(422);
  });

  it('28 owned X-Company-Id override honoured', async () => {
    const r = await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-fyprefix' });
    expect(r.statusCode).toBe(200);
    // FY-in-prefix path: `VBK/25-26` + / + seq (no fy insertion). Fresh
    // company → seq=1.
    expect(r.json()['suggested_number']).toBe('VBK/25-26/0001');
  });

  it('29 unowned X-Company-Id → default fallback (co-a)', async () => {
    const r = await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect(r.statusCode).toBe(200);
    expect(r.json()['suggested_number']).toBe('INV/25-26/0042');
  });

  it('30 no auth → 401', async () => {
    const r = await get('/api/invoices/next-preview?invoice_date=2026-02-15');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('31 FY-in-prefix self-heals (no double FY insertion)', async () => {
    // Same as case 28 — deliberate; extra assertion on FY absence in composed number.
    const r = await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-fyprefix' });
    const s = r.json()['suggested_number'] as string;
    // The FY '25-26' must appear ONCE, not '25-26/25-26'.
    expect((s.match(/25-26/g) ?? []).length).toBe(1);
  });

  it('32 fresh company (no fy_map, no legacy>1) → seq=1', async () => {
    // Past FY on co-a-legacy → legacy seed does NOT apply → seq=1.
    const r = await get('/api/invoices/next-preview?invoice_date=2024-01-01',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-legacy' });
    expect(r.statusCode).toBe(200);
    expect(r.json()['suggested_number']).toBe('INV/23-24/0001');
  });

  it('33 company counters unchanged — no writes on preview path', async () => {
    await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-legacy' });
    await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-fyprefix' });
    expect(state.writes).toEqual([]);
    // sanity — the stored bucket / scalars were not mutated
    const coa = state.companies.find((c) => c['id'] === 'co-a')!;
    expect(coa['next_invoice_number_by_fy']).toEqual({ '25-26': 42 });
    const legacy = state.companies.find((c) => c['id'] === 'co-a-legacy')!;
    expect(legacy['next_invoice_number']).toBe(15);
  });

  // ── Cross-route write-observation umbrella ─────────────────────────
  it('34 Node write observation — 0 writes across mixed traffic', async () => {
    await get('/api/invoices/inv-happy', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-cn/notes', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/next-preview?invoice_date=2026-02-15',
      { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/does-not-exist', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/inv-of-u2/notes', { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/next-preview?invoice_date=2026-02-31',
      { authorization: 'Bearer tok-owner' });
    await get('/api/invoices/next-preview');
    expect(state.writes).toEqual([]);
  });
});
