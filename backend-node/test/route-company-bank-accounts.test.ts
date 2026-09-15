/**
 * TRUKVIA · Phase-3 · Gate-6m · Company bank account read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/company-bank-accounts
 *
 * Fake-DB write-forbid pattern reused from Gates 6c–6l. Gate-6m-only
 * fixture surface adds a `company_bank_accounts` rowset and exercises
 * the inline role-based masking predicate + `strip_full_number` clone.
 * Shared / locked test infrastructure is NOT touched.
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
  company_bank_accounts: Record<string, unknown>[];
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
      if (hasOps) continue; // Gate-6m route uses no operator filters.
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
    : name === 'company_bank_accounts' ? state.company_bank_accounts
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
              if (av === undefined) return 1 * d;
              if (bv === undefined) return -1 * d;
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

// Ordered created_at values so DESC sort deterministically yields A > B > C > D.
const T_A = '2026-02-01T04:00:00Z';
const T_B = '2026-02-01T03:00:00Z';
const T_C = '2026-02-01T02:00:00Z';
const T_D = '2026-02-01T01:00:00Z';

// Reference rows (u-owner + co-a scope unless overridden).
const CBA_A = {
  id: 'cba-A', user_id: 'u-owner', company_id: 'co-a',
  bank_name: 'Bank A', ifsc: 'IFSC0001',
  account_number: '1234567890', masked_display: 'XXXXXX7890',
  created_at: T_A,
} as const;
const CBA_B = {
  id: 'cba-B', user_id: 'u-owner', company_id: 'co-a',
  bank_name: 'Bank B', ifsc: 'IFSC0002',
  account_number: '9876', masked_display: '', // empty masked_display → computed
  created_at: T_B,
} as const;
const CBA_C = {
  id: 'cba-C', user_id: 'u-owner', company_id: 'co-a',
  bank_name: 'Bank C', ifsc: 'IFSC0003',
  account_number: '', masked_display: '',
  created_at: T_C,
} as const;
// cba-D: masked_display key MISSING; account_number > 4 chars; extra_field preserved.
const CBA_D = {
  id: 'cba-D', user_id: 'u-owner', company_id: 'co-a',
  bank_name: 'Bank D', ifsc: 'IFSC0004',
  account_number: '1111222233334444',
  extra_field: 'preserved',
  created_at: T_D,
} as const;
const CBA_ALT = {
  id: 'cba-alt', user_id: 'u-owner', company_id: 'co-a-alt',
  bank_name: 'Bank Alt', ifsc: 'IFSC-ALT',
  account_number: 'ALTACC',   masked_display: 'XXALTC',
  created_at: T_A,
} as const;
const CBA_U2 = {
  id: 'cba-u2', user_id: 'u2', company_id: 'co-b',
  bank_name: 'Bank U2', ifsc: 'IFSC-U2',
  account_number: 'U2SECRET', masked_display: 'XXU2ET',
  created_at: T_A,
} as const;

function makeState(): State {
  return {
    sessions: [
      { session_token: 'tok-owner',      user_id: 'u-owner',   effective_role: 'owner',      expires_at: IN_FUTURE() },
      { session_token: 'tok-accountant', user_id: 'u-owner',   effective_role: 'accountant', expires_at: IN_FUTURE() },
      { session_token: 'tok-admin',      user_id: 'u-owner',   effective_role: 'admin',      expires_at: IN_FUTURE() },
      { session_token: 'tok-admin-mix',  user_id: 'u-owner',   effective_role: 'Admin',      expires_at: IN_FUTURE() },
      { session_token: 'tok-viewer',     user_id: 'u-owner',   effective_role: 'viewer',     expires_at: IN_FUTURE() },
      { session_token: 'tok-manager',    user_id: 'u-owner',   effective_role: 'manager',    expires_at: IN_FUTURE() },
      { session_token: 'tok-norole',     user_id: 'u-owner',                                  expires_at: IN_FUTURE() },
      { session_token: 'tok-role-only',  user_id: 'u-owner',   role: 'admin',                expires_at: IN_FUTURE() },
      { session_token: 'tok-effpriority',user_id: 'u-owner',   effective_role: 'admin', role: 'viewer', expires_at: IN_FUTURE() },
      { session_token: 'tok-expired',    user_id: 'u-owner',   effective_role: 'owner',      expires_at: IN_PAST() },
      { session_token: 'tok-u2',         user_id: 'u2',        effective_role: 'owner',      expires_at: IN_FUTURE() },
    ],
    users: [
      { user_id: 'u-owner', email: 'owner@x' },
      { user_id: 'u2',      email: 'u2@x' },
    ],
    companies: [
      { id: 'co-a',     user_id: 'u-owner', is_default: true },
      { id: 'co-a-alt', user_id: 'u-owner', is_default: false },
      { id: 'co-b',     user_id: 'u2',      is_default: true },
    ],
    company_bank_accounts: [
      { ...CBA_A }, { ...CBA_B }, { ...CBA_C }, { ...CBA_D },
      { ...CBA_ALT }, { ...CBA_U2 },
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

// Expected unmasked co-a rows in DESC order.
const OWNER_IDS = ['cba-A', 'cba-B', 'cba-C', 'cba-D'];

describe('Gate-6m · Company bank account read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── ROLE MASKING (privileged view — full account_number) ────────────
  it('1 owner → full account_number', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const rows = r.json() as Record<string, unknown>[];
    const map = Object.fromEntries(rows.map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('1234567890');
    expect(map['cba-B']!['account_number']).toBe('9876');
    expect(map['cba-C']!['account_number']).toBe('');
    expect(map['cba-D']!['account_number']).toBe('1111222233334444');
  });

  it('2 accountant → full account_number', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-accountant' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('1234567890');
    expect(map['cba-D']!['account_number']).toBe('1111222233334444');
  });

  it('3 admin → full account_number', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-admin' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('1234567890');
    expect(map['cba-D']!['account_number']).toBe('1111222233334444');
  });

  it('4 viewer → masked account_number', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    // cba-A: masked_display truthy → used verbatim
    expect(map['cba-A']!['account_number']).toBe('XXXXXX7890');
    // cba-B: masked_display '' → computed mask of '9876' (len==4 → 'XXXX')
    expect(map['cba-B']!['account_number']).toBe('XXXX');
    // cba-C: '' account_number → ''
    expect(map['cba-C']!['account_number']).toBe('');
    // cba-D: masked_display MISSING → computed 'XXXXXXXXXXXX4444'
    expect(map['cba-D']!['account_number']).toBe('XXXXXXXXXXXX4444');
  });

  it('5 manager (unknown) → masked account_number', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-manager' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('XXXXXX7890');
    expect(map['cba-D']!['account_number']).toBe('XXXXXXXXXXXX4444');
  });

  it('6 missing role → masked (falsy → empty string → not privileged)', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-norole' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('XXXXXX7890');
  });

  it('7 effective_role missing, role="admin" → coalesced to admin → FULL', async () => {
    // AuthUser.effective_role is coalesced from session.effective_role || session.role.
    // With effective_role undefined and role='admin', AuthUser.effective_role='admin'.
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-role-only' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('1234567890');
  });

  it('8 effective_role="admin" takes priority over role="viewer" → FULL', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-effpriority' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('1234567890');
  });

  it('9 case-insensitive role ("Admin") → FULL', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-admin-mix' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['account_number']).toBe('1234567890');
  });

  // ── MASKING FIELD SEMANTICS ─────────────────────────────────────────
  it('10 masked_display preserved unchanged in privileged view', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['masked_display']).toBe('XXXXXX7890');
  });

  it('11 masked_display preserved unchanged in masked view', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-A']!['masked_display']).toBe('XXXXXX7890');
    // cba-B kept empty masked_display verbatim.
    expect(map['cba-B']!['masked_display']).toBe('');
  });

  it('12 masked_display truthy is used verbatim (no re-mask)', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    // Even though '1234567890' would compute 'XXXXXX7890', we use the stored masked_display AS-IS.
    expect(map['cba-A']!['account_number']).toBe('XXXXXX7890');
  });

  it('13 masked_display absent → computed mask fallback (len > 4)', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-D']!['account_number']).toBe('XXXXXXXXXXXX4444');
  });

  it('14 account_number length <= 4 → all X (computed mask fallback)', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-B']!['account_number']).toBe('XXXX');
  });

  it('15 empty account_number → empty string mask', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-C']!['account_number']).toBe('');
  });

  it('16 original state rows NOT mutated by response mapping', async () => {
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    // State row cba-A must still hold its full account_number.
    const stored = state.company_bank_accounts.find((r) => r['id'] === 'cba-A')!;
    expect(stored['account_number']).toBe('1234567890');
    expect(stored['masked_display']).toBe('XXXXXX7890');
  });

  it('17 extra fields preserved in privileged view', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-D']!['extra_field']).toBe('preserved');
  });

  it('18 extra fields preserved in masked view', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['cba-D']!['extra_field']).toBe('preserved');
  });

  // ── LIST BEHAVIOR ───────────────────────────────────────────────────
  it('19 cross-user isolation (u2 rows never visible to u-owner)', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('cba-u2');
  });

  it('20 cross-company isolation (co-a-alt hidden under default co-a)', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('cba-alt');
    expect(ids).toEqual(OWNER_IDS);
  });

  it('21 owned X-Company-Id override returns alt-company rows', async () => {
    const r = await get('/api/company-bank-accounts', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.map((x) => x['id'])).toEqual(['cba-alt']);
  });

  it('22 unowned X-Company-Id → default fallback (co-a)', async () => {
    const r = await get('/api/company-bank-accounts', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(OWNER_IDS);
  });

  it('23 no X-Company-Id header → default company scope', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(OWNER_IDS);
  });

  it('24 sort by created_at DESC', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    const rows = r.json() as Record<string, unknown>[];
    const timestamps = rows.map((x) => x['created_at'] as string);
    // Strictly non-increasing.
    for (let i = 1; i < timestamps.length; i++) {
      expect(timestamps[i - 1]! >= timestamps[i]!).toBe(true);
    }
    expect(rows.map((x) => x['id'])).toEqual(OWNER_IDS);
  });

  it('25 projection strips _id and user_id', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('26 cap 500 smoke', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBeLessThanOrEqual(500);
  });

  // ── AUTH FAILURES (exact 401 literals) ──────────────────────────────
  it('27 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/company-bank-accounts');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('28 invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('29 expired session → 401 Session expired', async () => {
    const r = await get('/api/company-bank-accounts', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── ZERO-WRITE AGGREGATE ────────────────────────────────────────────
  it('30 zero Node business writes across every branch', async () => {
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-owner' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-accountant' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-admin' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-admin-mix' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-viewer' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-manager' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-norole' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-role-only' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-effpriority' });
    await get('/api/company-bank-accounts', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    await get('/api/company-bank-accounts', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-u2' });
    await get('/api/company-bank-accounts');
    await get('/api/company-bank-accounts', { authorization: 'Bearer nope' });
    await get('/api/company-bank-accounts', { authorization: 'Bearer tok-expired' });
    expect(state.writes).toEqual([]);
  });
});
