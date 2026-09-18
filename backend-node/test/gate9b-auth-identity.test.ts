/**
 * TRUKVIA · Phase-4 · Gate-9b · Login identity + role parity — Vitest.
 *
 * `authenticate()` must build the SAME context as Python `get_current_user`
 * (backend/auth.py L115-188) for PRODUCTION-SHAPED sessions (login stores
 * {user_id, session_token, expires_at(Date), created_at, last_refreshed_at}
 * — no role): users lookup (401 "User not found"), team_members staff
 * remap to the owner's scope, effective_role / is_staff, the
 * `effective_role or users.role` masking chain — with ZERO writes.
 * Exercised through already-locked Class-C routes.
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

type Row = Record<string, unknown>;
interface Op { coll: string; method: string; filter: Row }
interface State { data: Record<string, Row[]>; ops: Op[]; writes: string[] }

const matches = (r: Row, f: Row): boolean => Object.entries(f).every(([k, v]) => r[k] === v);
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
        state.ops.push({ coll: name, method: 'findOne', filter: f });
        const h = rows.find((r) => matches(r, f));
        return h ? project(h, o?.projection) : null;
      }),
      find: vi.fn((f: Row, o?: { projection?: Row }) => {
        state.ops.push({ coll: name, method: 'find', filter: f });
        let hits = rows.filter((r) => matches(r, f)).map((r) => project(r, o?.projection));
        const cur = {
          sort: () => cur,
          limit: (n: number) => { hits = hits.slice(0, n); return cur; },
          toArray: async () => hits,
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
const PAST = (): Date => new Date(Date.now() - 60_000);
// Exactly the shape routers/auth_router.py writes at login.
const sess = (tok: string, uid: unknown, exp: unknown = FUT()): Row =>
  ({ user_id: uid, session_token: tok, expires_at: exp, created_at: new Date(), last_refreshed_at: new Date() });

function seed(): Record<string, Row[]> {
  return {
    user_sessions: [
      sess('tok-owner', 'u1'), sess('tok-acc', 's-acc'), sess('tok-view', 's-view'), sess('tok-inactive', 's-inactive'),
      sess('tok-norole', 's-norole'), sess('tok-multi', 's-multi'), sess('tok-self', 'u-self'), sess('tok-ghost', 'ghost'),
      sess('tok-empty-user', 'u-empty'), sess('tok-noemail', 'u-noemail'), sess('tok-expired', 'u1', PAST()),
      sess('tok-u2', 'u2'), sess('tok-nodefault', 'u-nodef'),
      sess('tok-str-naive', 'u1', '2999-01-01T00:00:00'), sess('tok-str-past', 'u1', '2001-01-01T00:00:00+05:30'),
      sess('tok-str-week', 'u1', '2999-W01-1'), sess('tok-str-bad', 'u1', 'not-a-date'),
      sess('tok-nullexp', 'u1', null), { user_id: 'u1', session_token: 'tok-noexp' }, sess('tok-numexp', 'u1', 12345),
      { session_token: 'tok-nouid', expires_at: FUT() },
      sess('tok space', 'u1'), sess(' tok-lead', 'u1'), sess('tok"q', 'u1'),
    ],
    users: [
      { user_id: 'u1', email: 'owner@x', name: 'Owner' },
      { user_id: 'u2', email: 'u2@x' },
      { user_id: 's-acc', email: 'acc@x' },
      { user_id: 's-view', email: 'view@x' },
      { user_id: 's-inactive', email: 'inactive@x' },
      { user_id: 's-norole', email: 'norole@x' },
      { user_id: 's-multi', email: 'multi@x' },
      { user_id: 'u-self', email: 'self@x' },
      { user_id: 'u-empty' },
      { user_id: 'u-noemail', name: 'No Email' },
      { user_id: 'u-nodef', email: 'nodef@x' },
    ].map((u) => (u.user_id === 'u-empty' ? { user_id: 'u-empty' } : u)),
    team_members: [
      { owner_user_id: 'u1', email: 'acc@x', role: 'accountant', active: true },
      { owner_user_id: 'u1', email: 'view@x', role: 'viewer', active: true },
      { owner_user_id: 'u1', email: 'inactive@x', role: 'accountant', active: false },
      { owner_user_id: 'u1', email: 'norole@x', active: true },                        // no role key → "accountant"
      { owner_user_id: 'u1', email: 'multi@x', role: 'viewer', active: true },         // first match wins
      { owner_user_id: 'u2', email: 'multi@x', role: 'accountant', active: true },
      { owner_user_id: 'u-self', email: 'self@x', role: 'viewer', active: true },       // owner_user_id == self → owner
    ],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false },
      { id: 'co-z', user_id: 'u2', is_default: true },
      { id: 'co-n1', user_id: 'u-nodef' }, { id: 'co-n2', user_id: 'u-nodef' },
    ],
    vendors: [
      { id: 'v1', user_id: 'u1', company_id: 'co-a', name: 'Acme' },
      { id: 'v2', user_id: 'u1', company_id: 'co-b', name: 'Beta' },
      { id: 'vz', user_id: 'u2', company_id: 'co-z', name: 'Zed' },
      { id: 'vn', user_id: 'u-nodef', company_id: 'co-n1', name: 'NoDef' },
      { id: 'vs', user_id: 's-acc', company_id: '', name: 'Staff own scope — must never show' },
    ],
    company_bank_accounts: [
      { id: 'cba1', user_id: 'u1', company_id: 'co-a', account_number: '123456789012', masked_display: 'XXXXXXXX9012', created_at: 't1' },
    ],
    party_bank_accounts: [
      { id: 'pba1', user_id: 'u1', party_type: 'vendor', party_id: 'v1', account_number: '998877665544',
        masked_display: 'XXXXXXXX5544', created_at: 't1' },
    ],
    files: [
      { id: 'f1', user_id: 'u1', company_id: 'co-a', filename: 'a.pdf', is_deleted: false, created_at: 't1' },
      { id: 'f2', user_id: 's-acc', filename: 'staff-own.pdf', is_deleted: false, created_at: 't2' },
    ],
    fin_txn: [{ id: 'tx1', user_id: 'u1', company_id: 'co-a', amount: 10, source_type: 'nope', source_id: 'x' }],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db: fakeDb(state), ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const B = (tok: string, extra: Record<string, string> = {}): Record<string, string> => ({ authorization: `Bearer ${tok}`, ...extra });

describe('Gate-9b · login identity + role parity (production-shaped sessions)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = { data: seed(), ops: [], writes: [] }; app = await makeApp(state); state.ops = []; });
  afterEach(async () => {
    expect(state.writes).toEqual([]); // 24 · no Node auth writes
    await app.close();
  });

  const get = (url: string, headers: Record<string, string>): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url, headers });
  const ids = async (url: string, headers: Record<string, string>): Promise<unknown[]> =>
    (JSON.parse((await get(url, headers)).payload) as Row[]).map((r) => r['id']);
  const acct = async (url: string, tok: string): Promise<unknown> =>
    (JSON.parse((await get(url, B(tok))).payload) as Row[])[0]?.['account_number'];

  it('1 owner: own scope, default company, full bank numbers', async () => {
    expect(await ids('/api/vendors', B('tok-owner'))).toEqual(['v1']);
    expect(await acct('/api/company-bank-accounts', 'tok-owner')).toBe('123456789012');
    expect(await acct('/api/party-bank-accounts?party_type=vendor&party_id=v1', 'tok-owner')).toBe('998877665544');
  });

  it('2/9/10/11 accountant staff: remapped to owner scope, privileged → full numbers', async () => {
    expect(await ids('/api/vendors', B('tok-acc'))).toEqual(['v1']);
    expect(await acct('/api/company-bank-accounts', 'tok-acc')).toBe('123456789012');
  });

  it('3 viewer staff: owner scope, NOT privileged → masked numbers', async () => {
    expect(await ids('/api/vendors', B('tok-view'))).toEqual(['v1']);
    expect(await acct('/api/company-bank-accounts', 'tok-view')).toBe('XXXXXXXX9012');
    expect(await acct('/api/party-bank-accounts?party_type=vendor&party_id=v1', 'tok-view')).toBe('XXXXXXXX5544');
  });

  it('4 inactive team membership → treated as an owner of its own (empty) scope', async () => {
    expect(await ids('/api/vendors', B('tok-inactive'))).toEqual([]);
    expect(await ids('/api/company-bank-accounts', B('tok-inactive'))).toEqual([]);
  });

  it('5/23 missing users doc → exact 401 "User not found"; users doc without email → Python KeyError 500', async () => {
    const r = await get('/api/vendors', B('tok-ghost'));
    expect(r.statusCode).toBe(401);
    expect(r.json()).toEqual({ detail: 'User not found' });
    expect((await get('/api/vendors', B('tok-empty-user'))).statusCode).toBe(500);
  });

  it('6/7/23 expired / invalid / missing token → exact 401 literals', async () => {
    const cases: [Record<string, string>, string][] = [
      [B('tok-expired'), 'Session expired'], [B('tok-str-past'), 'Session expired'],
      [B('nope'), 'Invalid session'], [{}, 'Not authenticated'], [{ authorization: 'Bearer ' }, 'Not authenticated'],
      [{ authorization: 'bearer tok-owner' }, 'Not authenticated'],
    ];
    for (const [h, detail] of cases) {
      const r = await get('/api/vendors', h);
      expect(r.statusCode, JSON.stringify(h)).toBe(401);
      expect(r.json()).toEqual({ detail });
    }
  });

  it('8 exact read sequence: user_sessions → users → team_members({email, active:true}) → companies → route', async () => {
    await get('/api/vendors', B('tok-acc'));
    expect(state.ops.slice(0, 3)).toEqual([
      { coll: 'user_sessions', method: 'findOne', filter: { session_token: 'tok-acc' } },
      { coll: 'users', method: 'findOne', filter: { user_id: 's-acc' } },
      { coll: 'team_members', method: 'findOne', filter: { email: 'acc@x', active: true } },
    ]);
    expect(state.ops.filter((o) => o.coll === 'vendors')[0]?.filter).toEqual({ user_id: 'u1', company_id: 'co-a' });
  });

  it('12 owner fallback: team row pointing at self → owner role (full numbers, own scope)', async () => {
    expect(await ids('/api/vendors', B('tok-self'))).toEqual([]);
    expect(state.ops.find((o) => o.coll === 'vendors')?.filter).toMatchObject({ user_id: 'u-self' });
  });

  it('13 multiple team rows → first match; missing role key → "accountant" (privileged)', async () => {
    expect(await ids('/api/vendors', B('tok-multi'))).toEqual(['v1']);
    expect(await acct('/api/company-bank-accounts', 'tok-multi')).toBe('XXXXXXXX9012'); // viewer row first
    expect(await acct('/api/company-bank-accounts', 'tok-norole')).toBe('123456789012');
  });

  it('14/15 no-default-company user → first company; multiple companies via owned header', async () => {
    expect(await ids('/api/vendors', B('tok-nodefault'))).toEqual(['vn']);
    expect(await ids('/api/vendors', B('tok-owner', { 'x-company-id': 'co-b' }))).toEqual(['v2']);
    expect(await ids('/api/vendors', B('tok-acc', { 'x-company-id': 'co-b' }))).toEqual(['v2']); // staff uses owner's companies
  });

  it('16 bank masking follows the Python role chain (owner/accountant full, viewer masked)', async () => {
    const byTok: Record<string, string> = { 'tok-owner': '123456789012', 'tok-acc': '123456789012', 'tok-view': 'XXXXXXXX9012' };
    for (const [tok, want] of Object.entries(byTok)) expect(await acct('/api/company-bank-accounts', tok), tok).toBe(want);
  });

  it('17/18/19 isolation: staff never see their own-id data; other users and companies stay isolated', async () => {
    expect(await ids('/api/vendors', B('tok-acc'))).not.toContain('vs');
    expect(await ids('/api/vendors', B('tok-u2'))).toEqual(['vz']);
    expect(await ids('/api/vendors', B('tok-u2', { 'x-company-id': 'co-a' }))).toEqual(['vz']);
    expect(await ids('/api/files', B('tok-acc'))).toEqual(['f1']); // user-only route → owner scope
    expect((await get('/api/vendors/v1', B('tok-acc'))).json()).toMatchObject({ id: 'v1' });
    expect((await get('/api/vendors/v1', B('tok-u2'))).statusCode).toBe(404);
  });

  it('20/21/22 single X-Company-Id: owned alt, none, unowned → default', async () => {
    expect(await ids('/api/vendors', B('tok-view', { 'x-company-id': 'co-b' }))).toEqual(['v2']);
    expect(await ids('/api/vendors', B('tok-view'))).toEqual(['v1']);
    expect(await ids('/api/vendors', B('tok-view', { 'x-company-id': 'co-z' }))).toEqual(['v1']);
  });

  it('finance route under staff identity (fin-txn detail, owner scope)', async () => {
    const r = await get('/api/fin/fin-txn/tx1', B('tok-acc'));
    expect(r.statusCode).toBe(200);
    expect(r.json().txn['id']).toBe('tx1');
  });

  it('expires_at string forms follow CPython fromisoformat (naive = UTC, week dates); invalid → 500', async () => {
    for (const tok of ['tok-str-naive', 'tok-str-week']) expect((await get('/api/vendors', B(tok))).statusCode, tok).toBe(200);
    for (const tok of ['tok-str-bad', 'tok-nullexp', 'tok-noexp', 'tok-numexp', 'tok-nouid', 'tok-noemail']) {
      expect((await get('/api/vendors', B(tok))).statusCode, tok).toBe(500);
    }
  });

  it('token extraction: Bearer remainder is NOT trimmed; cookie parsed Starlette-style (last wins, _unquote)', async () => {
    expect((await get('/api/vendors', { authorization: 'Bearer tok space' })).statusCode).toBe(200);
    expect((await get('/api/vendors', { authorization: 'Bearer  tok-lead' })).statusCode).toBe(200);
    expect((await get('/api/vendors', { cookie: 'a=1; session_token=nope; session_token=tok-owner' })).statusCode).toBe(200);
    expect((await get('/api/vendors', { cookie: 'session_token="tok\\"q"' })).statusCode).toBe(200);
    expect((await get('/api/vendors', { cookie: 'session_token=', authorization: 'Bearer tok-owner' })).statusCode).toBe(200);
  });
});
