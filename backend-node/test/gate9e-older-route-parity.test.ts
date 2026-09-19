/**
 * TRUKVIA · Phase-4 · Gate-9e · Older-route parity cleanup — Vitest.
 *
 * Expected values are the live-verified Python responses (pre-fix probe,
 * scratch/g9e/before.txt):
 *   A · GET /api/files/usage — exact Python JSON (pct int/float + repr +
 *       half-even round; `int(v or 0)` over BSON types; dict key semantics).
 *   B · GET /api/invoices/next-preview — auth before query validation;
 *       Pydantic v2 `missing` 422; Starlette last-value query lookup.
 *   C · limit parsing on /api/audit-logs, /api/policy-changes, /api/approvals —
 *       exact Pydantic 2.13.4 int (1.0, 1_000, -0.0 …), size error, last value,
 *       audit `to_list(0)` → [] and negative → 500.
 *   D · Motor `to_list(n)` routes read WITHOUT a server-side limit.
 */
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import type { Db } from 'mongodb';
import { Double, Int32, Long } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

type Row = Record<string, unknown>;
interface State { data: Record<string, Row[]>; writes: string[]; limits: Array<[string, number]> }

const baseConfig: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017', dbName: 'trukvia_node_test',
  corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};

const eq = (a: unknown, b: unknown): boolean =>
  b !== null && typeof b === 'object' && !Array.isArray(b)
    ? Object.entries(b as Row).every(([op, v]) =>
      op === '$ne' ? a !== v : op === '$in' ? (v as unknown[]).includes(a) : op === '$gte' ? String(a) >= String(v)
        : op === '$lte' ? String(a) <= String(v) : false)
    : a === b;
const matches = (r: Row, f: Row): boolean => Object.entries(f).every(([k, v]) => eq(r[k], v));
const project = (r: Row, p: Row = {}): Row => {
  const inc = Object.entries(p).filter(([, v]) => v === 1).map(([k]) => k);
  if (inc.length) return Object.fromEntries(inc.filter((k) => k in r).map((k) => [k, r[k]]));
  const o: Row = { ...r };
  for (const [k, v] of Object.entries(p)) if (v === 0) delete o[k];
  return o;
};

function fakeDb(state: State): Db {
  const collection = (name: string) => {
    const rows = (state.data[name] ??= []);
    const forbid = (m: string) => (): never => { state.writes.push(`${name}.${m}`); throw new Error(`WRITE ${name}.${m}`); };
    return {
      findOne: vi.fn(async (f: Row, o?: { projection?: Row }) => {
        const h = rows.find((r) => matches(r, f));
        return h ? project(h, o?.projection) : null;
      }),
      countDocuments: vi.fn(async (f: Row) => rows.filter((r) => matches(r, f)).length),
      find: vi.fn((f: Row, o?: { projection?: Row }) => {
        let hits = rows.filter((r) => matches(r, f)).map((r) => project(r, o?.projection));
        const cur = {
          sort: (spec: Array<[string, 1 | -1]> | Row) => {
            const s = Array.isArray(spec) ? spec : (Object.entries(spec) as Array<[string, 1 | -1]>);
            hits = hits.slice().sort((a, b) => {
              for (const [k, d] of s) if (a[k] !== b[k]) return (String(a[k]) < String(b[k]) ? -1 : 1) * d;
              return 0;
            });
            return cur;
          },
          limit: (n: number) => { state.limits.push([name, n]); hits = hits.slice(0, n); return cur; },
          toArray: async () => hits,
          [Symbol.asyncIterator]: async function* () { yield* await Promise.resolve(hits); },
          hasNext: (): Promise<boolean> => Promise.resolve(hits.length > 0),
          close: (): Promise<void> => Promise.resolve(),
        };
        return cur;
      }),
      insertOne: vi.fn(forbid('insertOne')), insertMany: vi.fn(forbid('insertMany')),
      updateOne: vi.fn(forbid('updateOne')), updateMany: vi.fn(forbid('updateMany')),
      replaceOne: vi.fn(forbid('replaceOne')), deleteOne: vi.fn(forbid('deleteOne')),
      deleteMany: vi.fn(forbid('deleteMany')), findOneAndUpdate: vi.fn(forbid('findOneAndUpdate')),
      bulkWrite: vi.fn(forbid('bulkWrite')), createIndex: vi.fn(async () => 'ok'),
    };
  };
  return { collection: vi.fn(collection) } as unknown as Db;
}

const FUT = (): Date => new Date(Date.now() + 30 * 86_400_000);
const LIMIT = 524288000;
const FILE_USERS: Record<string, Row[]> = {
  zero: [{ size: new Int32(0), category: 'general' }],
  tie: [{ size: new Int32(655360), category: 'a' }], // 0.125 → half-even 0.12
  cap: [{ size: new Int32(LIMIT) }], // exactly 100.0 → min() keeps the INT 100
  near: [{ size: new Int32(LIMIT - 5000) }], // 99.999… → 100.0 (float)
  bool: [{ size: true, category: 'x' }],
  under: [{ size: '1_000', category: 's' }, { size: ' ٣ ', category: 's' }],
  badstr: [{ size: '1.5' }],
  nan: [{ size: new Double(NaN) }],
  neg: [{ size: new Int32(-5), category: 'n' }],
  long: [{ size: Long.fromString('9007199254740993'), category: 'L' }],
  floats: [{ size: new Double(12.9), category: 'f' }, { size: new Double(7), category: 'f' }],
  cats: [
    { size: new Int32(1), category: 'general' }, { size: new Int32(2), category: '2024' }, { size: new Int32(3), category: null },
    { size: new Int32(4) }, { size: new Int32(5), category: new Int32(1) }, { size: new Int32(6), category: '1' },
    { size: new Int32(7), category: true }, { size: new Int32(8), category: new Double(1) }, { size: new Int32(9), category: 'é' },
  ],
  empty: [],
};

function seed(): Record<string, Row[]> {
  const sess = (tok: string, uid: string): Row =>
    ({ user_id: uid, session_token: tok, expires_at: FUT(), created_at: new Date(), last_refreshed_at: new Date() });
  const users = ['u1', ...Object.keys(FILE_USERS)];
  const ties = (n: number, base: Row, pre: string): Row[] =>
    Array.from({ length: n }, (_, i) => ({ id: `${pre}-${String(i).padStart(3, '0')}`, user_id: 'u1', ...base }));
  return {
    user_sessions: users.map((u) => sess(`tok-${u}`, u)),
    users: users.map((u) => ({ user_id: u, email: `${u}@x` })),
    companies: [{ id: 'co-a', user_id: 'u1', is_default: true, invoice_prefix: 'A-' }],
    files: Object.entries(FILE_USERS).flatMap(([u, docs]) => docs.map((d, i) => ({ id: `${u}-${i}`, user_id: u, is_deleted: false, ...d }))),
    audit_logs: ties(12, { timestamp: '2026-05-01T00:00:00' }, 'al'),
    policy_change_events: ties(12, { company_id: 'co-a', created_at: 'T' }, 'pc'),
    approvals: ties(3, { company_id: 'co-a', created_at: 'T', status: 'PENDING_APPROVAL' }, 'ap'),
    wallet_transfers: ties(6, { company_id: 'co-a', date: '2026-05-01' }, 'wt'),
    company_bank_accounts: ties(4, { company_id: 'co-a', created_at: 'T', account_number: '1234567890' }, 'cb'),
    templates: ties(3, { company_id: 'co-a', is_active: true, name: 'T' }, 'tp'),
  };
}

const A = (u = 'u1'): Record<string, string> => ({ authorization: `Bearer tok-${u}` });
const INT_URL = 'https://errors.pydantic.dev/2.13/v/int_parsing';
const INT_MSG = 'Input should be a valid integer, unable to parse string as an integer';
const intErr = (input: string, type = 'int_parsing'): string => JSON.stringify({ detail: [{
  type, loc: ['query', 'limit'],
  msg: type === 'int_parsing' ? INT_MSG : 'Unable to parse input string as an integer, exceeded maximum size',
  input, url: type === 'int_parsing' ? INT_URL : 'https://errors.pydantic.dev/2.13/v/int_parsing_size',
}] });

describe('Gate-9e · older-route parity', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof buildApp>>;
  beforeAll(async () => {
    state = { data: seed(), writes: [], limits: [] };
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const mongo: MongoConn = { client: {} as MongoConn['client'], db: fakeDb(state), ping: async () => true, close: async () => undefined };
    app = await buildApp({ config: baseConfig, logger, mongo });
  });
  afterAll(async () => { expect(state.writes).toEqual([]); await app.close(); });
  const get = (url: string, headers: Record<string, string> = A()): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });
  const usage = async (u: string): Promise<{ status: number; body: string }> => {
    const r = await get('/api/files/usage', A(u));
    return { status: r.statusCode, body: r.body };
  };
  const U = (total: string, pct: string, count: number, cats: string): string =>
    `{"total_bytes":${total},"limit_bytes":524288000,"pct":${pct},"file_count":${count},"by_category":{${cats}}}`;

  // ── A · files/usage (Python bodies captured live) ──────────────────
  it('A1 pct zero / tie / cap / near-cap / negative render exactly like Python', async () => {
    expect((await usage('zero')).body).toBe(U('0', '0.0', 1, '"general":0'));
    expect((await usage('tie')).body).toBe(U('655360', '0.12', 1, '"a":655360'));
    expect((await usage('cap')).body).toBe(U('524288000', '100', 1, '"general":524288000'));
    expect((await usage('near')).body).toBe(U('524283000', '100.0', 1, '"general":524283000'));
    expect((await usage('neg')).body).toBe(U('-5', '-0.0', 1, '"n":-5'));
    expect((await usage('empty')).body).toBe(U('0', '0.0', 0, ''));
  });

  it('A2 int(v or 0): True → 1, "1_000", Unicode digit, float trunc, exact int64', async () => {
    expect((await usage('bool')).body).toBe(U('1', '0.0', 1, '"x":1'));
    expect((await usage('under')).body).toBe(U('1003', '0.0', 2, '"s":1003'));
    expect((await usage('floats')).body).toBe(U('19', '0.0', 2, '"f":19'));
    expect((await usage('long')).body).toBe(U('9007199254740993', '100', 1, '"L":9007199254740993'));
  });

  it('A3 Python ValueError branches → text/plain 500', async () => {
    for (const u of ['badstr', 'nan']) {
      const r = await get('/api/files/usage', A(u));
      expect([r.statusCode, r.headers['content-type'], r.body], u).toEqual([500, 'text/plain; charset=utf-8', 'Internal Server Error']);
    }
  });

  it('A4 by_category is a Python dict: insertion order, 1 == True == 1.0, "1" distinct, None → "null"', async () => {
    expect((await usage('cats')).body).toBe(U('45', '0.0', 9, '"general":5,"2024":2,"null":3,"1":20,"1":6,"é":9'));
  });

  it('A5 exact content-type; no server-side limit on the files read', async () => {
    const r = await get('/api/files/usage', A('zero'));
    expect(r.headers['content-type']).toBe('application/json');
    expect(state.limits.filter(([c]) => c === 'files')).toEqual([]);
  });

  // ── B · invoices/next-preview ──────────────────────────────────────
  const MISSING = '{"detail":[{"type":"missing","loc":["query","invoice_date"],"msg":"Field required","input":null,' +
    '"url":"https://errors.pydantic.dev/2.13/v/missing"}]}';
  it('B1 unauthenticated + missing → 401 (auth first); authenticated + missing → exact Pydantic 422', async () => {
    const anon = await get('/api/invoices/next-preview', {});
    expect([anon.statusCode, anon.body]).toEqual([401, '{"detail":"Not authenticated"}']);
    for (const q of ['', '?x=1', '?invoice%5Fdat=1']) {
      const r = await get(`/api/invoices/next-preview${q}`);
      expect([r.statusCode, r.headers['content-type'], r.body], q).toEqual([422, 'application/json', MISSING]);
    }
  });

  it('B2 repeated invoice_date → LAST value wins (Starlette); valid date unchanged', async () => {
    const ok = '{"suggested_number":"A-/26-27/0001","fy":"26-27","editable":false}';
    expect((await get('/api/invoices/next-preview?invoice_date=x&invoice_date=2026-05-01')).body).toBe(ok);
    expect((await get('/api/invoices/next-preview?invoice_date=2026-05-01')).body).toBe(ok);
    const bad = await get('/api/invoices/next-preview?invoice_date=2026-05-01&invoice_date=x');
    expect([bad.statusCode, bad.body]).toEqual([400, '{"detail":"invoice_date must be ISO YYYY-MM-DD"}']);
  });

  // ── C · limit parsing (exact Pydantic 2.13.4) ──────────────────────
  it.each([
    ['1.0', 1], ['1.00', 1], ['-0.0', 0], ['1_000', 12], ['0_0', 0], ['00012', 12], ['+5', 5], ['%207%20', 7],
    ['%C2%A05', 5], ['abc&limit=2', 2],
  ])('C1 audit-logs limit=%s → accepted like Pydantic (%i rows)', async (v, n) => {
    const r = await get(`/api/audit-logs?limit=${v}`);
    expect(r.statusCode, v).toBe(200);
    expect((r.json()).length, v).toBe(n);
  });

  it.each([['1.5'], ['1.'], ['1e3'], ['1__0'], ['_1'], ['abc'], [''], ['0x10'], ['1+']])(
    'C2 limit=%s → int_parsing 422 with the raw input (all three routes)', async (v) => {
      for (const route of ['/api/audit-logs', '/api/policy-changes', '/api/approvals']) {
        const r = await get(`${route}?limit=${encodeURIComponent(v)}`);
        expect([r.statusCode, r.body], `${route} ${v}`).toEqual([422, intErr(v)]);
      }
    });

  it('C3 %FF → U+FFFD input; 4301 digits → int_parsing_size', async () => {
    expect((await get('/api/policy-changes?limit=%FF')).body).toBe(intErr('�'));
    const big = '1'.repeat(4301);
    expect((await get(`/api/approvals?limit=${big}`)).body).toBe(intErr(big, 'int_parsing_size'));
  });

  it('C4 audit-logs: limit=0 → [] (to_list(0)); negative → Motor ValueError → text/plain 500', async () => {
    expect((await get('/api/audit-logs?limit=0')).body).toBe('[]');
    const neg = await get('/api/audit-logs?limit=-1');
    expect([neg.statusCode, neg.body]).toEqual([500, 'Internal Server Error']);
    expect((await get(`/api/audit-logs?limit=-${'9'.repeat(25)}`)).statusCode).toBe(500);
  });

  it('C5 policy-changes clamp max(1, min(200, int)) after exact parsing; approvals ge/le keep raw input', async () => {
    expect(((await get('/api/policy-changes?limit=-0.0')).json()).total).toBe(1);
    expect(((await get('/api/policy-changes?limit=1_000')).json()).total).toBe(12);
    const ge = await get('/api/approvals?limit=0.0');
    expect(ge.statusCode).toBe(422);
    expect((ge.json()).detail[0]).toMatchObject({ type: 'greater_than_equal', input: '0.0' });
    expect(((await get('/api/approvals?limit=2.0')).json()).length).toBe(2);
  });

  // ── D · Motor to_list(n): no server-side limit, stop after n ────────
  it('D1 capped routes read without .limit(); results still capped at n', async () => {
    state.limits = [];
    expect(((await get('/api/policy-changes?limit=3')).json()).total).toBe(3);
    expect(((await get('/api/audit-logs?limit=5')).json()).length).toBe(5);
    await get('/api/wallet-transfers');
    await get('/api/company-bank-accounts');
    await get('/api/templates');
    expect(state.limits).toEqual([]);
  });
});
