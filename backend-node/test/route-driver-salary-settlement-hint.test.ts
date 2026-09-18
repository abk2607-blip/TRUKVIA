/**
 * TRUKVIA · Phase-3 · Gate-7z · Driver salary-settlement hint read-only shadow — Vitest.
 *
 * Covers:
 *   GET /api/drivers/{did}/salary-settlement-hint?month=...
 *
 * Fake-DB write-forbid pattern inlined. Verifies the COPIED Python
 * behaviour: the filter uses top-level `month` + `kind:"settlement"`, which
 * the real settlement writer never stores → realistic data always yields
 * {"possible_duplicate":false,"existing_settlement":null}; no driver
 * existence check (the `drivers` collection is never read).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Double, Int32, Long, ObjectId, type Db } from 'mongodb';
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
const FALSE = '{"possible_duplicate":false,"existing_settlement":null}';
const MISSING =
  '{"detail":[{"type":"missing","loc":["query","month"],"msg":"Field required","input":null,'
  + '"url":"https://errors.pydantic.dev/2.13/v/missing"}]}';

type Row = Record<string, unknown>;
interface FindOneCall { filter: Row; projection?: Row; sort?: Row; promoteValues?: boolean }
interface State {
  sessions: Row[]; users: Row[]; companies: Row[]; entries: Row[];
  writes: string[]; driverReads: number; lookups: FindOneCall[];
}

const forbid = (state: State, name: string) => (): never => {
  state.writes.push(name);
  throw new Error(`READ-ONLY VIOLATION: ${name}`);
};

const matches = (r: Row, f: Row): boolean => Object.entries(f).every(([k, v]) => r[k] === v);

function fakeDb(state: State): Db {
  const rowsOf = (name: string): Row[] =>
    name === 'user_sessions' ? state.sessions
    : name === 'users' ? state.users
    : name === 'companies' ? state.companies
    : name === 'driver_ledger_entries' ? state.entries
    : [];
  const collection = (name: string) => {
    const rows = rowsOf(name);
    return {
      find: vi.fn(() => { throw new Error(`unexpected find on ${name}`); }),
      findOne: vi.fn(async (f: Row, opts?: { projection?: Row; sort?: Row; promoteValues?: boolean }) => {
        if (name === 'drivers') state.driverReads++;
        if (name === 'driver_ledger_entries') {
          state.lookups.push({ filter: f, projection: opts?.projection, sort: opts?.sort, promoteValues: opts?.promoteValues });
        }
        const h = rows.find((r) => matches(r, f));
        if (!h) return null;
        const o: Row = { ...h };
        for (const [k, v] of Object.entries(opts?.projection ?? {})) if (v === 0) delete o[k];
        return o;
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

// Exactly what driver_ledger.py::settle stores — no top-level month / kind.
const realSettlement = (uid: string, cid: string, did: string, month: string): Row => ({
  _id: `oid-real-${did}-${month}`, user_id: uid, company_id: cid, driver_id: did, entry_date: `${month}-30`,
  month_key: month, entry_type: 'settlement', direction: 'debit', amount: new Double(18000), source: 'system',
  reference: { kind: 'settlement', month }, id: `dle-real-${did}-${month}`,
});

const hinted = (uid: string, cid: string, did: string, month: string, marker: string, extra: Row = {}): Row => ({
  _id: `oid-${marker}`, id: `dle-${marker}`, user_id: uid, company_id: cid, driver_id: did, month,
  kind: 'settlement', marker, ...extra,
});

function makeState(): State {
  return {
    sessions: ['u1', 'u2'].map((u) => ({ session_token: `tok-${u}`, user_id: u, effective_role: 'owner', expires_at: IN_FUTURE() })),
    users: [{ user_id: 'u1', email: 'u1@x' }, { user_id: 'u2', email: 'u2@x' }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false },
      { id: 'co-z', user_id: 'u2', is_default: true },
    ],
    entries: [
      realSettlement('u1', 'co-a', 'd1', '2026-05'),
      hinted('u1', 'co-a', 'd1', '2026-04', 'u1-a', {
        amount: new Double(18000), days: new Int32(30), big: Long.fromString('9007199254740993'), z: new Double(-0), note: null,
      }),
      hinted('u1', 'co-b', 'd1', '2026-04', 'u1-b'),
      hinted('u2', 'co-a', 'd1', '2026-04', 'u2-in-co-a'),
      hinted('u1', 'co-a', 'd1', '', 'empty-month'),
      hinted('u1', 'co-a', 'd1', '1.0', 'month-1.0'),
      hinted('u1', 'co-a', 'd1', '�', 'replacement'),
      hinted('u1', 'co-a', 'drv-é', '2026-04', 'did-unicode'),
      hinted('u1', 'co-a', 'd-nan', '2026-04', 'nan', { amount: new Double(NaN) }),
      hinted('u1', 'co-a', 'd-oid', '2026-04', 'oid', { ref: new ObjectId('65a000000000000000000001') }),
      { _id: 'oid-kind', user_id: 'u1', company_id: 'co-a', driver_id: 'd-kind', month: '2026-04', kind: 'advance' },
    ],
    writes: [], driverReads: 0, lookups: [],
  };
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const db = fakeDb(state);
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db, ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

const url = (did: string, qs: string | null = 'month=2026-04'): string =>
  `/api/drivers/${did}/salary-settlement-hint${qs === null ? '' : `?${qs}`}`;
const as = (u: string, cid?: string): Record<string, string> =>
  cid === undefined ? { authorization: `Bearer tok-${u}` } : { authorization: `Bearer tok-${u}`, 'x-company-id': cid };

describe('Gate-7z · Driver salary-settlement hint read-only shadow', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => { state = makeState(); app = await makeApp(state); });
  afterEach(async () => {
    expect(state.writes).toEqual([]);
    expect(state.driverReads).toBe(0);
    await app.close();
  });

  const get = (u: string, headers: Record<string, string> = as('u1')): ReturnType<typeof app.inject> =>
    app.inject({ method: 'GET', url: u, headers });
  const marker = async (u: string, headers?: Record<string, string>): Promise<unknown> =>
    (JSON.parse((await get(u, headers)).payload) as { existing_settlement: Row | null }).existing_settlement?.['marker'] ?? null;

  it('PYTHON BUG COPIED: a real settlement (entry_type/month_key/reference) is never matched → false', async () => {
    const r = await get(url('d1', 'month=2026-05'));
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.payload).toBe(FALSE);
    expect(r.headers['content-length']).toBe(String(FALSE.length));
  });

  it('exact find_one: {user_id, company_id, driver_id, month, kind:"settlement"}, projection {_id:0}, no sort', async () => {
    await get(url('d1'));
    expect(state.lookups).toEqual([{
      filter: { user_id: 'u1', company_id: 'co-a', driver_id: 'd1', month: '2026-04', kind: 'settlement' },
      projection: { _id: 0 }, sort: undefined, promoteValues: false,
    }]);
  });

  it('true branch: top-level match returned verbatim (user_id kept), Python number formatting', async () => {
    const r = await get(url('d1'));
    expect(r.payload).toBe(
      '{"possible_duplicate":true,"existing_settlement":{"id":"dle-u1-a","user_id":"u1","company_id":"co-a",'
      + '"driver_id":"d1","month":"2026-04","kind":"settlement","marker":"u1-a","amount":18000.0,"days":30,'
      + '"big":9007199254740993,"z":-0.0,"note":null}}',
    );
  });

  it('no driver existence check: nonexistent / other-kind drivers → false (never 404)', async () => {
    for (const did of ['nope', 'd-kind', 'd2']) expect((await get(url(did))).payload, did).toBe(FALSE);
  });

  it('company isolation: owned alt / unowned / unknown / empty header; other user', async () => {
    expect(await marker(url('d1'), as('u1', 'co-b'))).toBe('u1-b');
    for (const cid of ['co-a', 'co-z', 'co-nope', '']) expect(await marker(url('d1'), as('u1', cid)), cid).toBe('u1-a');
    expect((await get(url('d1'), as('u2'))).payload).toBe(FALSE);
    expect((await get(url('d1'), as('u2', 'co-a'))).payload).toBe(FALSE);
  });

  it('month is a plain str: "", bare key, 1.0, U+FFFD match verbatim; 1 / 01 / 1_0 / junk do not', async () => {
    expect(await marker(url('d1', 'month='))).toBe('empty-month');
    expect(await marker(url('d1', 'month'))).toBe('empty-month');
    expect(await marker(url('d1', 'month=1.0'))).toBe('month-1.0');
    expect(await marker(url('d1', 'month=%C3'))).toBe('replacement');
    for (const qs of ['month=1', 'month=01', 'month=1_0', 'month=%zz', 'month=%202026-04%20']) {
      expect((await get(url('d1', qs))).payload, qs).toBe(FALSE);
    }
  });

  it('missing month → 422 (incl. month[] / Month / empty query); repeated → last', async () => {
    for (const qs of [null, '', 'month%5B%5D=2026-04', 'Month=2026-04', 'other=1']) {
      const r = await get(url('d1', qs));
      expect(r.statusCode, String(qs)).toBe(422);
      expect(r.payload).toBe(MISSING);
    }
    expect(await marker(url('d1', 'month=x&month=2026-04'))).toBe('u1-a');
    expect((await get(url('d1', 'month=2026-04&month=x'))).payload).toBe(FALSE);
    expect(await marker(url('d1', 'mon%74h=2026-04'))).toBe('u1-a');
  });

  it('401 precedes 422 and the read', async () => {
    for (const qs of [null, 'month=2026-04']) {
      const r = await get(url('d1', qs), {});
      expect(r.statusCode).toBe(401);
      expect(r.headers['content-type']).toBe('application/json');
    }
    expect(state.lookups).toEqual([]);
  });

  it('path: Unicode did decoded; empty segment / encoded slash → 404 Not Found before auth', async () => {
    expect(await marker(url('drv-%C3%A9'))).toBe('did-unicode');
    for (const did of ['', 'a%2Fb']) {
      const r = await get(url(did), {});
      expect(r.statusCode, did).toBe(404);
      expect(r.payload).toBe('{"detail":"Not Found"}');
    }
  });

  it('NaN / ObjectId in the matched document → 500 text/plain', async () => {
    for (const did of ['d-nan', 'd-oid']) {
      const r = await get(url(did));
      expect(r.statusCode, did).toBe(500);
      expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
      expect(r.payload).toBe('Internal Server Error');
    }
  });

  it('HEAD → 405 allow: GET before auth / validation', async () => {
    for (const [u, headers] of [[url('d1'), as('u1')], [url('d1', null), {}]] as const) {
      const r = await app.inject({ method: 'HEAD', url: u, headers });
      expect(r.statusCode).toBe(405);
      expect(r.headers['allow']).toBe('GET');
      expect(r.headers['content-length']).toBe('31');
    }
    expect(state.lookups).toEqual([]);
  });

  it('only GET (+ explicit HEAD) registered on the path — no writer', () => {
    const p = '/api/drivers/:did/salary-settlement-hint';
    expect(app.hasRoute({ method: 'GET', url: p })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) expect(app.hasRoute({ method: m, url: p })).toBe(false);
  });
});
