/**
 * TRUKVIA · Phase-3 · Gate-6h · Company / Supplier read-only shadow — Vitest.
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
  suppliers: Record<string, unknown>[];
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
    : name === 'companies' ? state.companies
    : name === 'suppliers' ? state.suppliers
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

// ── Canonical default (mirrors the source impl for assertion) ────────
const DEFAULT_CO_NON_ID: Record<string, unknown> = {
  name: '', address: '', phone: '', email: '', gstin: '', pan: '',
  state: '', pincode: '', bank_name: '', account_number: '', ifsc: '',
  branch: '', hsn_sac: '996791', invoice_prefix: 'INV',
  next_invoice_number: 1, next_invoice_number_by_fy: {}, lr_prefix: 'LR',
  next_lr_number: 1, logo: '', udyam_registration: '',
  signature_file_id: '', authorised_signatory_name: '',
  authorised_signatory_designation: '', signature_mode: 'none',
  jurisdiction: '', system_generated_note: '', is_default: false,
  credit_note_prefix: 'CN', next_credit_note_number: 1,
  debit_note_prefix: 'DN', next_debit_note_number: 1,
  require_cdn_approval: false, require_approval_trip: false,
  require_approval_invoice: false, require_approval_payment: false,
};
const ID_RE = /^co_[0-9a-f]{16}$/;

// ── Fixture state ────────────────────────────────────────────────────
function makeState(overrideCompanies?: Record<string, unknown>[]): State {
  return {
    sessions: [
      { session_token: 'tok-owner', user_id: 'u1', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired', user_id: 'u1', effective_role: 'owner', expires_at: IN_PAST() },
      { session_token: 'tok-nocompany', user_id: 'u-nocompany', effective_role: 'owner', expires_at: IN_FUTURE() },
      { session_token: 'tok-u2', user_id: 'u2', effective_role: 'owner', expires_at: IN_FUTURE() },
    ],
    users: [
      { user_id: 'u1', email: 'u1@x' },
      { user_id: 'u-nocompany', email: 'nc@x' },
      { user_id: 'u2', email: 'u2@x' },
    ],
    companies: overrideCompanies ?? [
      { id: 'co-a', user_id: 'u1', is_default: true, name: 'Acme Ltd', gstin: '29ABCDE1234F1Z5', hsn_sac: '996791', extra_field: 'kept' },
      { id: 'co-a-alt', user_id: 'u1', is_default: false, name: 'Acme Alt', hsn_sac: '996791' },
      { id: 'co-b', user_id: 'u2', is_default: true, name: 'Beta' },
    ],
    suppliers: [
      { id: 'sup-1', user_id: 'u1', company_id: 'co-a', name: 'Diesel Vendor',
        mobile: '9998887777', is_active: true, gstin: '29XXX', extra_field: 'kept' },
      { id: 'sup-2', user_id: 'u1', company_id: 'co-a-alt', name: 'Alt Vendor', is_active: true },
      { id: 'sup-b', user_id: 'u2', company_id: 'co-b', name: 'U2 Vendor', is_active: true },
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

describe('Gate-6h · Company / Supplier read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── /api/company ────────────────────────────────────────────────────
  it('1 existing default company returned as-stored', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['id']).toBe('co-a');
    expect(d['name']).toBe('Acme Ltd');
    expect(d['extra_field']).toBe('kept');
    expect(d).not.toHaveProperty('user_id');
  });

  it('2 owned X-Company-Id → alt company', async () => {
    const r = await get('/api/company', {
      authorization: 'Bearer tok-owner',
      'x-company-id': 'co-a-alt',
    });
    expect(r.statusCode).toBe(200);
    expect(r.json()['id']).toBe('co-a-alt');
    expect(r.json()['name']).toBe('Acme Alt');
  });

  it('3 unowned X-Company-Id → default fallback (co-a)', async () => {
    const r = await get('/api/company', {
      authorization: 'Bearer tok-owner',
      'x-company-id': 'co-b',
    });
    expect(r.statusCode).toBe(200);
    expect(r.json()['id']).toBe('co-a');
  });

  it('4 missing company → 200 with default Company object', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-nocompany' });
    expect(r.statusCode).toBe(200);
  });

  it('5 miss-path id starts with co_', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-nocompany' });
    expect((r.json()['id'] as string).startsWith('co_')).toBe(true);
  });

  it('6 miss-path id matches ^co_[0-9a-f]{16}$', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-nocompany' });
    expect(ID_RE.test(r.json()['id'] as string)).toBe(true);
  });

  it('7 miss-path 35 non-id defaults exact', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-nocompany' });
    const d = r.json();
    for (const [k, v] of Object.entries(DEFAULT_CO_NON_ID)) {
      expect(d[k]).toEqual(v);
    }
    expect(Object.keys(d).length).toBe(36);
  });

  it('8 miss-path next_invoice_number_by_fy is {} (empty object, not array/null)', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-nocompany' });
    const val = r.json()['next_invoice_number_by_fy'];
    expect(val).toEqual({});
    expect(Array.isArray(val)).toBe(false);
    expect(val).not.toBeNull();
  });

  it('9 miss-path Maker-Checker defaults all false', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-nocompany' });
    const d = r.json();
    expect(d['require_cdn_approval']).toBe(false);
    expect(d['require_approval_trip']).toBe(false);
    expect(d['require_approval_invoice']).toBe(false);
    expect(d['require_approval_payment']).toBe(false);
  });

  it('10 hit-path extra stored fields preserved', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-owner' });
    expect(r.json()['extra_field']).toBe('kept');
  });

  it('11 /api/company no auth → 401', async () => {
    const r = await get('/api/company');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('12 /api/company invalid bearer → 401', async () => {
    const r = await get('/api/company', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('13 /api/company expired session → 401', async () => {
    const r = await get('/api/company', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── /api/suppliers/{sid} ────────────────────────────────────────────
  it('14 existing supplier returned as-stored', async () => {
    const r = await get('/api/suppliers/sup-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const d = r.json();
    expect(d['id']).toBe('sup-1');
    expect(d['name']).toBe('Diesel Vendor');
    expect(d).not.toHaveProperty('user_id');
  });

  it('15 missing supplier → 404 "Supplier not found"', async () => {
    const r = await get('/api/suppliers/does-not-exist', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Supplier not found' });
  });

  it('16 cross-user supplier → 404', async () => {
    const r = await get('/api/suppliers/sup-b', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Supplier not found' });
  });

  it('17 cross-company supplier → 404 (sup-2 lives in co-a-alt, default is co-a)', async () => {
    const r = await get('/api/suppliers/sup-2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Supplier not found' });
  });

  it('18 no X-Company-Id header → default company scope', async () => {
    const r = await get('/api/suppliers/sup-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
  });

  it('19 owned X-Company-Id override → alt-company supplier accessible', async () => {
    const r = await get('/api/suppliers/sup-2', {
      authorization: 'Bearer tok-owner',
      'x-company-id': 'co-a-alt',
    });
    expect(r.statusCode).toBe(200);
    expect(r.json()['id']).toBe('sup-2');
  });

  it('20 unowned X-Company-Id → default fallback (sup-1 accessible under co-a)', async () => {
    const r = await get('/api/suppliers/sup-1', {
      authorization: 'Bearer tok-owner',
      'x-company-id': 'co-b',
    });
    expect(r.statusCode).toBe(200);
    expect(r.json()['id']).toBe('sup-1');
  });

  it('21 hit-path extra stored fields preserved', async () => {
    const r = await get('/api/suppliers/sup-1', { authorization: 'Bearer tok-owner' });
    expect(r.json()['extra_field']).toBe('kept');
  });

  it('22 /api/suppliers no auth → 401', async () => {
    const r = await get('/api/suppliers/sup-1');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('23 /api/suppliers invalid bearer → 401', async () => {
    const r = await get('/api/suppliers/sup-1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('24 /api/suppliers expired session → 401', async () => {
    const r = await get('/api/suppliers/sup-1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('25 zero Node business writes across every branch', async () => {
    // /api/company branches
    await get('/api/company', { authorization: 'Bearer tok-owner' });
    await get('/api/company', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/company', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/company', { authorization: 'Bearer tok-nocompany' });
    await get('/api/company');
    await get('/api/company', { authorization: 'Bearer nope' });
    await get('/api/company', { authorization: 'Bearer tok-expired' });
    // /api/suppliers/{sid} branches
    await get('/api/suppliers/sup-1', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/does-not-exist', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-b', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-2', { authorization: 'Bearer tok-owner' });
    await get('/api/suppliers/sup-2', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/suppliers/sup-1', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    await get('/api/suppliers/sup-1');
    await get('/api/suppliers/sup-1', { authorization: 'Bearer nope' });
    await get('/api/suppliers/sup-1', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
