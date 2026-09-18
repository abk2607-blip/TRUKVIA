/**
 * TRUKVIA · Phase-3 · Gate-6r · Party bank account read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/party-bank-accounts?party_type=&party_id=
 *
 * Fake-DB write-forbid pattern reused inline (no shared/locked test
 * infrastructure touched). Gate-6r-only fixture surface exercises:
 *   * Required-query 422 (Pydantic-v2 detail array).
 *   * Tuple-membership 400 with exact Python literal.
 *   * Auth-order short-circuit (401 before 422/400).
 *   * Gate-6m masking matrix reused verbatim.
 *   * All five PARTY_TYPES.
 *   * NO company_id filter (drivers with missing company_id still visible).
 *   * X-Company-Id header must NOT alter rowset (invocation-parity only).
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
  team_members: Record<string, unknown>[];
  companies: Record<string, unknown>[];
  party_bank_accounts: Record<string, unknown>[];
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
      if (hasOps) continue;
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
    : name === 'team_members' ? state.team_members
    : name === 'companies' ? state.companies
    : name === 'party_bank_accounts' ? state.party_bank_accounts
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
              return ((av as string | number) < (bv as string | number) ? -1 : 1) * d;
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
const T_A = '2026-03-01T04:00:00Z';
const T_B = '2026-03-01T03:00:00Z';
const T_C = '2026-03-01T02:00:00Z';
const T_D = '2026-03-01T01:00:00Z';

// Reference rows (u-owner + party supplier sup-1 unless overridden).
const PBA_SUP_A = {
  id: 'pba-A', user_id: 'u-owner', party_type: 'supplier', party_id: 'sup-1',
  bank_name: 'Bank A', ifsc: 'IFSC0001',
  account_number: '1234567890', masked_display: 'XXXXXX7890',
  created_at: T_A,
} as const;
const PBA_SUP_B = {
  id: 'pba-B', user_id: 'u-owner', party_type: 'supplier', party_id: 'sup-1',
  bank_name: 'Bank B', ifsc: 'IFSC0002',
  account_number: '9876', masked_display: '', // empty → computed
  created_at: T_B,
} as const;
const PBA_SUP_C = {
  id: 'pba-C', user_id: 'u-owner', party_type: 'supplier', party_id: 'sup-1',
  bank_name: 'Bank C', ifsc: 'IFSC0003',
  account_number: '', masked_display: '',
  created_at: T_C,
} as const;
// pba-D: masked_display MISSING; account_number > 4 chars; extra_field preserved.
const PBA_SUP_D = {
  id: 'pba-D', user_id: 'u-owner', party_type: 'supplier', party_id: 'sup-1',
  bank_name: 'Bank D', ifsc: 'IFSC0004',
  account_number: '1111222233334444',
  extra_field: 'preserved',
  created_at: T_D,
} as const;
// Party of type driver — driver party master may not have company_id;
// filter has no company_id, so this row must be visible for u-owner.
const PBA_DRV = {
  id: 'pba-drv', user_id: 'u-owner', party_type: 'driver', party_id: 'drv-1',
  bank_name: 'Bank DRV', ifsc: 'IFSC-DRV',
  account_number: 'DRV1234567', masked_display: 'XXXXXX4567',
  created_at: T_A,
} as const;
// Other party types — one row each for happy-list-per-type coverage.
const PBA_VND = {
  id: 'pba-vnd', user_id: 'u-owner', party_type: 'vendor', party_id: 'vnd-1',
  bank_name: 'Bank VND', ifsc: 'IFSC-VND',
  account_number: 'VND1234567', masked_display: 'XXXXXX4567',
  created_at: T_A,
} as const;
const PBA_MCH = {
  id: 'pba-mch', user_id: 'u-owner', party_type: 'mechanic', party_id: 'mch-1',
  bank_name: 'Bank MCH', ifsc: 'IFSC-MCH',
  account_number: 'MCH1234567', masked_display: 'XXXXXX4567',
  created_at: T_A,
} as const;
const PBA_CUS = {
  id: 'pba-cus', user_id: 'u-owner', party_type: 'customer', party_id: 'cus-1',
  bank_name: 'Bank CUS', ifsc: 'IFSC-CUS',
  account_number: 'CUS1234567', masked_display: 'XXXXXX4567',
  created_at: T_A,
} as const;
// Cross-user row — u2 owner; must never appear for u-owner.
const PBA_U2 = {
  id: 'pba-u2', user_id: 'u2', party_type: 'supplier', party_id: 'sup-1',
  bank_name: 'Bank U2', ifsc: 'IFSC-U2',
  account_number: 'U2SECRET', masked_display: 'XXU2ET',
  created_at: T_A,
} as const;

function makeState(): State {
  return {
    // Gate 9b: production-shaped sessions (login stores no role). Roles come from
    // Python get_current_user: owner → "owner"; staff → team_members.role under
    // the owner's scope; the masking chain is `effective_role or users.role`.
    sessions: [
      { session_token: 'tok-owner',       user_id: 'u-owner',    expires_at: IN_FUTURE() },
      { session_token: 'tok-accountant',  user_id: 's-acc',      expires_at: IN_FUTURE() },
      { session_token: 'tok-admin',       user_id: 's-admin',    expires_at: IN_FUTURE() },
      { session_token: 'tok-admin-mix',   user_id: 's-adminmix', expires_at: IN_FUTURE() },
      { session_token: 'tok-viewer',      user_id: 's-viewer',   expires_at: IN_FUTURE() },
      { session_token: 'tok-manager',     user_id: 's-manager',  expires_at: IN_FUTURE() },
      { session_token: 'tok-norole',      user_id: 's-norole',   expires_at: IN_FUTURE() },
      { session_token: 'tok-role-only',   user_id: 's-roleonly', expires_at: IN_FUTURE() },
      { session_token: 'tok-effpriority', user_id: 's-effprio',  expires_at: IN_FUTURE() },
      { session_token: 'tok-expired',     user_id: 'u-owner',    expires_at: IN_PAST() },
      { session_token: 'tok-u2',          user_id: 'u2',         expires_at: IN_FUTURE() },
    ],
    users: [
      { user_id: 'u-owner', email: 'owner@x' },
      { user_id: 'u2',      email: 'u2@x' },
      { user_id: 's-acc',      email: 'acc@x' },
      { user_id: 's-admin',    email: 'admin@x' },
      { user_id: 's-adminmix', email: 'adminmix@x' },
      { user_id: 's-viewer',   email: 'viewer@x' },
      { user_id: 's-manager',  email: 'manager@x' },
      { user_id: 's-norole',   email: 'norole@x' },
      { user_id: 's-roleonly', email: 'roleonly@x', role: 'admin' },
      { user_id: 's-effprio',  email: 'effprio@x', role: 'viewer' },
    ],
    team_members: [
      { owner_user_id: 'u-owner', email: 'acc@x',      role: 'accountant', active: true },
      { owner_user_id: 'u-owner', email: 'admin@x',    role: 'admin',      active: true },
      { owner_user_id: 'u-owner', email: 'adminmix@x', role: 'Admin',      active: true },
      { owner_user_id: 'u-owner', email: 'viewer@x',   role: 'viewer',     active: true },
      { owner_user_id: 'u-owner', email: 'manager@x',  role: 'manager',    active: true },
      { owner_user_id: 'u-owner', email: 'norole@x',   role: '',           active: true },
      { owner_user_id: 'u-owner', email: 'roleonly@x', role: '',           active: true },
      { owner_user_id: 'u-owner', email: 'effprio@x',  role: 'admin',      active: true },
    ],
    companies: [
      { id: 'co-a',     user_id: 'u-owner', is_default: true },
      { id: 'co-a-alt', user_id: 'u-owner', is_default: false },
      { id: 'co-b',     user_id: 'u2',      is_default: true },
    ],
    party_bank_accounts: [
      { ...PBA_SUP_A }, { ...PBA_SUP_B }, { ...PBA_SUP_C }, { ...PBA_SUP_D },
      { ...PBA_DRV }, { ...PBA_VND }, { ...PBA_MCH }, { ...PBA_CUS },
      { ...PBA_U2 },
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

// Sorted DESC by created_at: A > B > C > D.
const SUP1_IDS = ['pba-A', 'pba-B', 'pba-C', 'pba-D'];

describe('Gate-6r · Party bank account read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ── QUERY VALIDATION ────────────────────────────────────────────────
  it('1 valid auth + missing party_type → 422 Pydantic-v2 shape (party_type only)', async () => {
    const r = await get('/api/party-bank-accounts?party_id=sup-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    const body = r.json() as { detail: Record<string, unknown>[] };
    expect(Array.isArray(body.detail)).toBe(true);
    expect(body.detail).toHaveLength(1);
    expect(body.detail[0]!['type']).toBe('missing');
    expect(body.detail[0]!['loc']).toEqual(['query', 'party_type']);
    expect(body.detail[0]!['msg']).toBe('Field required');
  });

  it('2 valid auth + missing party_id → 422 Pydantic-v2 shape (party_id only)', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    const body = r.json() as { detail: Record<string, unknown>[] };
    expect(body.detail).toHaveLength(1);
    expect(body.detail[0]!['loc']).toEqual(['query', 'party_id']);
  });

  it('3 valid auth + missing both → 422 with both entries in declaration order', async () => {
    const r = await get('/api/party-bank-accounts', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(422);
    const body = r.json() as { detail: Record<string, unknown>[] };
    expect(body.detail).toHaveLength(2);
    expect(body.detail[0]!['loc']).toEqual(['query', 'party_type']);
    expect(body.detail[1]!['loc']).toEqual(['query', 'party_id']);
  });

  it('4 valid auth + invalid party_type → 400 EXACT Python literal', async () => {
    const r = await get('/api/party-bank-accounts?party_type=foo&party_id=x', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(400);
    expect(r.json()).toEqual({
      detail: "unsupported party_type. Allowed: ('supplier', 'vendor', 'mechanic', 'driver', 'customer')",
    });
  });

  it('5 valid auth + valid party_type + unknown party_id → 200 []', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=no-such', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual([]);
  });

  // ── PARTY TYPES (five happy lists) ──────────────────────────────────
  it('6 happy list · supplier · sup-1 · four rows DESC', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(SUP1_IDS);
  });
  it('7 happy list · vendor · vnd-1', async () => {
    const r = await get('/api/party-bank-accounts?party_type=vendor&party_id=vnd-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['pba-vnd']);
  });
  it('8 happy list · mechanic · mch-1', async () => {
    const r = await get('/api/party-bank-accounts?party_type=mechanic&party_id=mch-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['pba-mch']);
  });
  it('9 happy list · driver · drv-1 (party master may lack company_id — must still return)', async () => {
    const r = await get('/api/party-bank-accounts?party_type=driver&party_id=drv-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['pba-drv']);
  });
  it('10 happy list · customer · cus-1', async () => {
    const r = await get('/api/party-bank-accounts?party_type=customer&party_id=cus-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['pba-cus']);
  });

  // ── SCOPING ─────────────────────────────────────────────────────────
  it('11 cross-user isolation · u2 rows never visible to u-owner', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('pba-u2');
  });

  it('12 owned X-Company-Id override MUST NOT change rowset (invocation-parity only)', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(SUP1_IDS);
  });

  it('13 unowned X-Company-Id MUST NOT change rowset', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', {
      authorization: 'Bearer tok-owner', 'x-company-id': 'co-b',
    });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(SUP1_IDS);
  });

  it('14 no X-Company-Id header baseline · same rowset', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(SUP1_IDS);
  });

  // ── SORT / CAP / PROJECTION ─────────────────────────────────────────
  it('15 sort by created_at DESC', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner' });
    const timestamps = (r.json() as Record<string, unknown>[]).map((x) => x['created_at'] as string);
    for (let i = 1; i < timestamps.length; i++) {
      expect(timestamps[i - 1]! >= timestamps[i]!).toBe(true);
    }
  });

  it('16 500 cap · exactly 500 returned when >500 rows exist', async () => {
    state.party_bank_accounts.length = 0;
    for (let i = 0; i < 501; i++) {
      state.party_bank_accounts.push({
        id: 'p' + String(i).padStart(4, '0'),
        user_id: 'u-owner', party_type: 'supplier', party_id: 'sup-big',
        bank_name: 'BB', ifsc: 'IF', account_number: '999999' + i, masked_display: '',
        // Descending timestamps so first 500 (by DESC sort) are the newest.
        created_at: '2026-04-01T' + String(9 - Math.floor(i / 1000)).padStart(2, '0') + ':00:00.000Z',
      });
    }
    // Give the first row the most recent timestamp regardless of loop skew.
    (state.party_bank_accounts[0] as Record<string, unknown>)['created_at'] = '2027-01-01T00:00:00Z';
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-big', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(500);
  });

  it('17 projection strips _id and user_id', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  // ── ROLE MASKING (Gate-6m matrix reused verbatim) ───────────────────
  it('18 owner → full account_number', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('1234567890');
    expect(map['pba-B']!['account_number']).toBe('9876');
    expect(map['pba-C']!['account_number']).toBe('');
    expect(map['pba-D']!['account_number']).toBe('1111222233334444');
  });

  it('19 accountant → full', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-accountant' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('1234567890');
  });

  it('20 admin → full', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-admin' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-D']!['account_number']).toBe('1111222233334444');
  });

  it('21 "Admin" case-insensitive → full', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-admin-mix' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('1234567890');
  });

  it('22 viewer → masked (masked_display truthy verbatim; empty→computed; missing→computed; len<=4→XXXX; empty→"")', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-viewer' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('XXXXXX7890');    // truthy verbatim
    expect(map['pba-B']!['account_number']).toBe('XXXX');          // empty → computed (len==4)
    expect(map['pba-C']!['account_number']).toBe('');              // empty acc → ''
    expect(map['pba-D']!['account_number']).toBe('XXXXXXXXXXXX4444'); // missing → computed
  });

  it('23 manager (unknown role) → masked', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-manager' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('XXXXXX7890');
  });

  it('24 no-role → masked', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-norole' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('XXXXXX7890');
  });

  it('25 role fallback · effective_role absent, role="admin" → FULL', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-role-only' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('1234567890');
  });

  it('26 effective_role priority · effective_role="admin" > role="viewer" → FULL', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-effpriority' });
    const map = Object.fromEntries((r.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(map['pba-A']!['account_number']).toBe('1234567890');
  });

  it('27 extra fields preserved in privileged AND masked views', async () => {
    const rOwner = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner' });
    const rView = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-viewer' });
    const mo = Object.fromEntries((rOwner.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    const mv = Object.fromEntries((rView.json() as Record<string, unknown>[]).map((x) => [x['id'], x]));
    expect(mo['pba-D']!['extra_field']).toBe('preserved');
    expect(mv['pba-D']!['extra_field']).toBe('preserved');
  });

  it('28 original state rows NOT mutated by response mapping', async () => {
    await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-viewer' });
    const stored = state.party_bank_accounts.find((r) => r['id'] === 'pba-A')!;
    expect(stored['account_number']).toBe('1234567890');
    expect(stored['masked_display']).toBe('XXXXXX7890');
  });

  // ── AUTH-ORDER SHORT-CIRCUIT (locked 401 literals) ──────────────────
  it('29 no auth + missing params → 401 Not authenticated (401 BEFORE 422)', async () => {
    const r = await get('/api/party-bank-accounts');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('30 invalid bearer + invalid party_type → 401 Invalid session (401 BEFORE 400)', async () => {
    const r = await get('/api/party-bank-accounts?party_type=foo&party_id=x', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('31 expired session → 401 Session expired', async () => {
    const r = await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ── ZERO-WRITE AGGREGATE ────────────────────────────────────────────
  it('32 zero Node business writes across every exercised branch', async () => {
    // 401 branches
    await get('/api/party-bank-accounts');
    await get('/api/party-bank-accounts?party_type=foo&party_id=x', { authorization: 'Bearer nope' });
    await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-expired' });
    // 422 branches
    await get('/api/party-bank-accounts?party_id=x', { authorization: 'Bearer tok-owner' });
    await get('/api/party-bank-accounts?party_type=supplier', { authorization: 'Bearer tok-owner' });
    await get('/api/party-bank-accounts', { authorization: 'Bearer tok-owner' });
    // 400 branch
    await get('/api/party-bank-accounts?party_type=foo&party_id=x', { authorization: 'Bearer tok-owner' });
    // 200 branches for all five party types + unknown party_id + all masking roles
    for (const p of [
      '?party_type=supplier&party_id=sup-1', '?party_type=vendor&party_id=vnd-1',
      '?party_type=mechanic&party_id=mch-1', '?party_type=driver&party_id=drv-1',
      '?party_type=customer&party_id=cus-1', '?party_type=supplier&party_id=no-such',
    ]) {
      for (const t of [
        'tok-owner', 'tok-accountant', 'tok-admin', 'tok-admin-mix',
        'tok-viewer', 'tok-manager', 'tok-norole', 'tok-role-only', 'tok-effpriority',
      ]) {
        await get('/api/party-bank-accounts' + p, { authorization: 'Bearer ' + t });
      }
    }
    // X-Company-Id branches
    await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    // u2 view
    await get('/api/party-bank-accounts?party_type=supplier&party_id=sup-1', { authorization: 'Bearer tok-u2' });
    expect(state.writes).toEqual([]);
  });
});
