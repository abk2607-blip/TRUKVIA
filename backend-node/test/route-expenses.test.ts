/**
 * TRUKVIA · Phase-3 · Gate-6i · Expense read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/expenses
 *   GET /api/expenses/{eid}
 *
 * Fake-DB write-forbid pattern reused from Gates 6c–6h.
 * Gate-6i-only fake-DB extension: `$ne`, `$in`, `$gte`/`$lte`
 * operators are added INLINE in this file. Shared / locked test
 * infrastructure is NOT touched.
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

// ── Gate-6i-only operator support (inline; no shared infra touched) ──
// Supported operators (subset sufficient for Gate-6i contract):
//   $ne  — literal-value inequality (used for boolean `true` exclusion)
//   $in  — membership
//   $gte / $lte — lexicographic comparison on ISO date strings
function matchOperator(dv: unknown, cond: Record<string, unknown>): boolean {
  for (const [op, val] of Object.entries(cond)) {
    if (op === '$ne') {
      if (dv === val) return false;
    } else if (op === '$in') {
      const arr = val as unknown[];
      if (!arr.some((x) => x === dv)) return false;
    } else if (op === '$gte') {
      if (dv === undefined || dv === null) return false;
      if ((dv as string) < (val as string)) return false;
    } else if (op === '$lte') {
      if (dv === undefined || dv === null) return false;
      if ((dv as string) > (val as string)) return false;
    } else {
      // Any unrecognised operator falls back to strict equality on the
      // entire condition object (defensive — Gate-6i uses only the four
      // operators above).
      return false;
    }
  }
  return true;
}

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x) && !(x instanceof Date);
}

function matches(d: Record<string, unknown>, f: Record<string, unknown>): boolean {
  for (const [k, v] of Object.entries(f)) {
    const dv = d[k];
    if (isPlainObject(v)) {
      const keys = Object.keys(v);
      const hasOps = keys.length > 0 && keys.every((kk) => kk.startsWith('$'));
      if (hasOps) {
        if (!matchOperator(dv, v)) return false;
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
    : name === 'expenses' ? state.expenses
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

// ── Fixture helpers ─────────────────────────────────────────────────
function exp(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'e-x', user_id: 'u1', company_id: 'co-a',
    date: '2026-01-15', amount: 100.0, category: 'Diesel',
    source_type: 'manual', party_type: 'vendor', party_id: 'v1',
    trip_id: '', vehicle_id: '', repair_event_id: '',
    vendor_bill_id: '', mechanic_work_order_id: '',
    is_deleted: false, is_reversed: false,
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
      { id: 'co-a', user_id: 'u1', is_default: true },
      { id: 'co-a-alt', user_id: 'u1', is_default: false },
      { id: 'co-b', user_id: 'u2', is_default: true },
    ],
    expenses: [
      // Default-visible rows (co-a, u1)
      exp({ id: 'e-1', date: '2026-01-10', category: 'Diesel', source_type: 'quick_op', trip_id: 't-1', vehicle_id: 'veh-1', party_type: 'vendor', party_id: 'v1' }),
      exp({ id: 'e-2', date: '2026-01-20', category: 'Toll', source_type: 'fastag_import', trip_id: 't-1', vehicle_id: 'veh-2', party_type: 'vendor', party_id: 'v2' }),
      exp({ id: 'e-3', date: '2026-01-05', category: 'Repair', source_type: 'manual', repair_event_id: 'rev-1', vendor_bill_id: 'vb-1', party_type: 'vendor', party_id: 'v3' }),
      exp({ id: 'e-4', date: '2026-01-25', category: 'Labour', source_type: 'manual', mechanic_work_order_id: 'wo-1', party_type: 'mechanic', party_id: 'm1', extra_field: 'preserved' }),
      exp({ id: 'e-5', date: '2026-01-15', category: 'Diesel', source_type: 'fleet_card_import', vehicle_id: 'veh-1' }),
      // Guarded rows — is_deleted variants (only literal true excluded by default)
      exp({ id: 'e-del-true',   date: '2026-01-11', is_deleted: true }),
      exp({ id: 'e-del-false',  date: '2026-01-12', is_deleted: false }),
      exp({ id: 'e-del-null',   date: '2026-01-13', is_deleted: null }),
      exp({ id: 'e-del-zero',   date: '2026-01-14', is_deleted: 0 }),
      exp({ id: 'e-del-str',    date: '2026-01-16', is_deleted: '' }),
      // Guarded rows — is_reversed variants
      exp({ id: 'e-rev-true',   date: '2026-01-17', is_reversed: true }),
      exp({ id: 'e-rev-false',  date: '2026-01-18', is_reversed: false }),
      exp({ id: 'e-rev-null',   date: '2026-01-19', is_reversed: null }),
      // Under alt company (same user) — must NOT appear under default scope
      exp({ id: 'e-alt', user_id: 'u1', company_id: 'co-a-alt', date: '2026-02-01', category: 'Diesel' }),
      // Cross-user isolation
      exp({ id: 'e-u2', user_id: 'u2', company_id: 'co-b', date: '2026-01-30', category: 'Diesel' }),
    ],
    writes: [],
  };
}

// e-del-true and e-rev-true are excluded by default. That leaves 11 default-visible rows under u1/co-a.
const DEFAULT_VISIBLE_UNDER_CO_A = 11;

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-6i · Expenses read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;

  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => { await app.close(); });

  const get = (url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });

  // ─────────────────────────────── LIST ──────────────────────────────

  it('1 happy path — returns visible rows under default company scope', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const rows = r.json() as Record<string, unknown>[];
    expect(rows.length).toBe(DEFAULT_VISIBLE_UNDER_CO_A);
  });

  it('2 default excludes is_deleted=true', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('e-del-true');
  });

  it('3 non-true is_deleted values remain visible', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    for (const id of ['e-del-false', 'e-del-null', 'e-del-zero', 'e-del-str']) {
      expect(ids).toContain(id);
    }
  });

  it('4 default excludes is_reversed=true', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('e-rev-true');
  });

  it('5 non-true is_reversed values remain visible', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    for (const id of ['e-rev-false', 'e-rev-null']) {
      expect(ids).toContain(id);
    }
  });

  it('6 include_cancelled=true surfaces deleted rows', async () => {
    const r = await get('/api/expenses?include_cancelled=true', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('e-del-true');
    expect(ids).not.toContain('e-rev-true');
  });

  it('7 include_reversed=true surfaces reversed rows', async () => {
    const r = await get('/api/expenses?include_reversed=true', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toContain('e-rev-true');
    expect(ids).not.toContain('e-del-true');
  });

  it('8 trip_id filter', async () => {
    const r = await get('/api/expenses?trip_id=t-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids.sort()).toEqual(['e-1', 'e-2'].sort());
  });

  it('9 vehicle_id filter', async () => {
    const r = await get('/api/expenses?vehicle_id=veh-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids.sort()).toEqual(['e-1', 'e-5'].sort());
  });

  it('10 repair_event_id filter', async () => {
    const r = await get('/api/expenses?repair_event_id=rev-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-3']);
  });

  it('11 vendor_bill_id filter', async () => {
    const r = await get('/api/expenses?vendor_bill_id=vb-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-3']);
  });

  it('12 mechanic_work_order_id filter', async () => {
    const r = await get('/api/expenses?mechanic_work_order_id=wo-1', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-4']);
  });

  it('13 party_type filter', async () => {
    const r = await get('/api/expenses?party_type=mechanic', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-4']);
  });

  it('14 party_id filter', async () => {
    const r = await get('/api/expenses?party_id=v2', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-2']);
  });

  it('15 category filter', async () => {
    // `category=Diesel` matches e-1, e-5 AND every guarded-variant row
    // (base fixture defaults category to 'Diesel'). Default guards still
    // exclude e-del-true and e-rev-true.
    const r = await get('/api/expenses?category=Diesel', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids.sort()).toEqual([
      'e-1', 'e-5',
      'e-del-false', 'e-del-null', 'e-del-str', 'e-del-zero',
      'e-rev-false', 'e-rev-null',
    ].sort());
  });

  it('15b category filter with distinct value (Toll) — only e-2', async () => {
    const r = await get('/api/expenses?category=Toll', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-2']);
  });

  it('16 source_type single equality', async () => {
    const r = await get('/api/expenses?source_type=quick_op', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-1']);
  });

  it('17 source_type multi CSV → $in', async () => {
    const r = await get('/api/expenses?source_type=quick_op,fastag_import', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids.sort()).toEqual(['e-1', 'e-2'].sort());
  });

  it('18 source_type empty/whitespace-only → filter omitted', async () => {
    const r1 = await get('/api/expenses?source_type=', { authorization: 'Bearer tok-owner' });
    expect((r1.json() as unknown[]).length).toBe(DEFAULT_VISIBLE_UNDER_CO_A);
    const r2 = await get('/api/expenses?source_type=%20%2C%20%2C%20', { authorization: 'Bearer tok-owner' });
    expect((r2.json() as unknown[]).length).toBe(DEFAULT_VISIBLE_UNDER_CO_A);
  });

  it('18b source_type CSV with padding + empty parts trimmed', async () => {
    const r = await get('/api/expenses?source_type=%20quick_op%20%2C%20%2C%20fastag_import%20', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids.sort()).toEqual(['e-1', 'e-2'].sort());
  });

  it('19 date_from lower bound', async () => {
    const r = await get('/api/expenses?date_from=2026-01-20', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    // Rows with date >= 2026-01-20: e-2 (01-20), e-4 (01-25). e-del-true and e-rev-true excluded.
    expect(ids.sort()).toEqual(['e-2', 'e-4'].sort());
  });

  it('20 date_to upper bound', async () => {
    const r = await get('/api/expenses?date_to=2026-01-10', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    // Rows with date <= 2026-01-10: e-1 (01-10), e-3 (01-05). Guarded rows excluded.
    expect(ids.sort()).toEqual(['e-1', 'e-3'].sort());
  });

  it('21 both date bounds inclusive', async () => {
    const r = await get('/api/expenses?date_from=2026-01-12&date_to=2026-01-18', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    // Dates in [2026-01-12, 2026-01-18] under default guards:
    //   e-del-false (12), e-del-null (13), e-del-zero (14), e-5 (15),
    //   e-del-str (16), e-rev-false (18). e-rev-null (19) is OUT of range.
    expect(ids.sort()).toEqual([
      'e-5', 'e-del-false', 'e-del-null', 'e-del-str', 'e-del-zero', 'e-rev-false',
    ].sort());
  });

  it('22 date DESC ordering', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const dates = (r.json() as Record<string, unknown>[]).map((x) => x['date'] as string);
    for (let i = 1; i < dates.length; i++) {
      expect(dates[i - 1]! >= dates[i]!).toBe(true);
    }
  });

  it('23 default guard combination — deleted AND reversed both excluded', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('e-del-true');
    expect(ids).not.toContain('e-rev-true');
  });

  it('24 cap behaviour — .limit(20000) does not error on small fixtures', async () => {
    // Practical smoke check: rows fit well under the 20k cap and are returned intact.
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBeLessThanOrEqual(20000);
  });

  it('25 user isolation — u2 rows never visible to u1', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('e-u2');
  });

  it('26 company isolation — alt-company rows never visible under default scope', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).not.toContain('e-alt');
  });

  // Boolean TRUE tokens (case-insensitive) — include_reversed
  for (const token of ['true', 'True', 'TRUE', 'yes', 'YES', '1', 'on', 'ON', 't', 'T']) {
    it(`27.${token} include_reversed=${token} → surfaces reversed row`, async () => {
      const r = await get(`/api/expenses?include_reversed=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
      expect(ids).toContain('e-rev-true');
    });
  }

  // Boolean FALSE tokens (case-insensitive) — include_reversed
  for (const token of ['false', 'False', 'FALSE', 'no', 'NO', '0', 'off', 'OFF', 'f', 'F', 'n', 'N']) {
    it(`28.${token} include_reversed=${token} → reversed row excluded`, async () => {
      const r = await get(`/api/expenses?include_reversed=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
      expect(ids).not.toContain('e-rev-true');
    });
  }

  // Boolean TRUE tokens — include_cancelled
  for (const token of ['true', 'yes', '1', 'on', 't']) {
    it(`29.${token} include_cancelled=${token} → surfaces deleted row`, async () => {
      const r = await get(`/api/expenses?include_cancelled=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
      expect(ids).toContain('e-del-true');
    });
  }

  // Boolean FALSE tokens — include_cancelled
  for (const token of ['false', 'no', '0', 'off', 'f']) {
    it(`30.${token} include_cancelled=${token} → deleted row excluded`, async () => {
      const r = await get(`/api/expenses?include_cancelled=${token}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(200);
      const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
      expect(ids).not.toContain('e-del-true');
    });
  }

  // Invalid boolean → 422
  for (const token of ['maybe', '2', '1.0', 'yesplease', 'sure', '']) {
    it(`31.${JSON.stringify(token)} invalid include_reversed → 422`, async () => {
      const r = await get(`/api/expenses?include_reversed=${encodeURIComponent(token)}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(422);
    });
    it(`31b.${JSON.stringify(token)} invalid include_cancelled → 422`, async () => {
      const r = await get(`/api/expenses?include_cancelled=${encodeURIComponent(token)}`, { authorization: 'Bearer tok-owner' });
      expect(r.statusCode).toBe(422);
    });
  }

  it('32 no auth → 401 Not authenticated', async () => {
    const r = await get('/api/expenses');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('32b invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('32c expired session → 401 Session expired', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  it('33 owned X-Company-Id override → surfaces alt-company rows', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    const ids = (r.json() as Record<string, unknown>[]).map((x) => x['id']);
    expect(ids).toEqual(['e-alt']);
  });

  it('34 unowned X-Company-Id → falls back to default (co-a)', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    expect((r.json() as unknown[]).length).toBe(DEFAULT_VISIBLE_UNDER_CO_A);
  });

  it('35 no X-Company-Id header → default company scope', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    expect((r.json() as unknown[]).length).toBe(DEFAULT_VISIBLE_UNDER_CO_A);
  });

  it('36 projection strips _id and user_id', async () => {
    const r = await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    for (const row of r.json() as Record<string, unknown>[]) {
      expect(row).not.toHaveProperty('_id');
      expect(row).not.toHaveProperty('user_id');
    }
  });

  it('37 extra stored fields preserved (e-4 has extra_field)', async () => {
    const r = await get('/api/expenses?mechanic_work_order_id=wo-1', { authorization: 'Bearer tok-owner' });
    const row = (r.json() as Record<string, unknown>[])[0]!;
    expect(row['extra_field']).toBe('preserved');
    // Also confirm business fields pass through unmodified.
    expect(row['category']).toBe('Labour');
    expect(row['party_type']).toBe('mechanic');
  });

  // ─────────────────────────────── DETAIL ─────────────────────────────

  it('39 detail happy path', async () => {
    const r = await get('/api/expenses/e-1', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    const row = r.json() as Record<string, unknown>;
    expect(row['id']).toBe('e-1');
    expect(row['category']).toBe('Diesel');
    expect(row).not.toHaveProperty('_id');
    expect(row).not.toHaveProperty('user_id');
  });

  it('40 detail missing → 404 "Expense not found"', async () => {
    const r = await get('/api/expenses/does-not-exist', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Expense not found' });
  });

  it('41 detail is_deleted=true → 404', async () => {
    const r = await get('/api/expenses/e-del-true', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Expense not found' });
  });

  it('42 detail is_deleted=false → visible', async () => {
    const r = await get('/api/expenses/e-del-false', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>)['id']).toBe('e-del-false');
  });

  it('42b detail is_deleted=null → visible ($ne:true excludes only literal true)', async () => {
    const r = await get('/api/expenses/e-del-null', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>)['id']).toBe('e-del-null');
  });

  it('43 detail cross-user → 404', async () => {
    const r = await get('/api/expenses/e-u2', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Expense not found' });
  });

  it('44 detail cross-company (correct user, wrong company) → 404', async () => {
    // e-alt is under co-a-alt; without X-Company-Id override we're on co-a.
    const r = await get('/api/expenses/e-alt', { authorization: 'Bearer tok-owner' });
    expect(r.statusCode).toBe(404);
    expect(r.json()).toEqual({ detail: 'Expense not found' });
  });

  it('44b detail with owned X-Company-Id override → alt row accessible', async () => {
    const r = await get('/api/expenses/e-alt', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    expect(r.statusCode).toBe(200);
    expect((r.json() as Record<string, unknown>)['id']).toBe('e-alt');
  });

  it('45 detail extra stored fields preserved', async () => {
    const r = await get('/api/expenses/e-4', { authorization: 'Bearer tok-owner' });
    const row = r.json() as Record<string, unknown>;
    expect(row['extra_field']).toBe('preserved');
  });

  it('46 detail no auth → 401 Not authenticated', async () => {
    const r = await get('/api/expenses/e-1');
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('46b detail invalid bearer → 401 Invalid session', async () => {
    const r = await get('/api/expenses/e-1', { authorization: 'Bearer nope' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Invalid session' });
  });

  it('46c detail expired session → 401 Session expired', async () => {
    const r = await get('/api/expenses/e-1', { authorization: 'Bearer tok-expired' });
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'Session expired' });
  });

  // ─────────────────────────────── AGGREGATE ───────────────────────────

  it('38+47 zero Node business writes across every branch', async () => {
    // List branches
    await get('/api/expenses', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?include_cancelled=true', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?include_reversed=true', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?trip_id=t-1', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?vehicle_id=veh-1', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?category=Diesel', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?source_type=quick_op,fastag_import', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?date_from=2026-01-10&date_to=2026-01-20', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses?include_reversed=maybe', { authorization: 'Bearer tok-owner' });   // 422
    await get('/api/expenses');                                                                  // 401
    await get('/api/expenses', { authorization: 'Bearer nope' });                                // 401
    await get('/api/expenses', { authorization: 'Bearer tok-expired' });                         // 401
    await get('/api/expenses', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-a-alt' });
    await get('/api/expenses', { authorization: 'Bearer tok-owner', 'x-company-id': 'co-b' });
    // Detail branches
    await get('/api/expenses/e-1', { authorization: 'Bearer tok-owner' });
    await get('/api/expenses/e-del-true', { authorization: 'Bearer tok-owner' });    // 404
    await get('/api/expenses/does-not-exist', { authorization: 'Bearer tok-owner' }); // 404
    await get('/api/expenses/e-u2', { authorization: 'Bearer tok-owner' });          // 404
    await get('/api/expenses/e-alt', { authorization: 'Bearer tok-owner' });         // 404
    await get('/api/expenses/e-1');                                                   // 401
    expect(state.writes).toEqual([]);
  });
});
