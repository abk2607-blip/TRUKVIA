/**
 * TRUKVIA · Phase-4 · Gate-9c · duplicate X-Company-Id tenant parity — Vitest.
 *
 * Python `request.headers.get("x-company-id")` (Starlette over h11) returns
 * the FIRST raw occurrence; names match case-insensitively; the parser strips
 * only SP/HTAB. Node's `req.headers` joins duplicates as "a, b", so
 * `activeCompanyId` must read `rawHeaders`. A SINGLE header containing a comma
 * stays one literal value. Ownership / default / first-company fallback runs
 * after selection, unchanged.
 *
 * `inject` cannot send real duplicate headers (it joins arrays), so these
 * tests listen on an ephemeral port and write raw HTTP bytes.
 */
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import net from 'node:net';
import type { AddressInfo } from 'node:net';
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
          // Gate 9e: routes read Motor-style (async iteration, no server-side limit).
          [Symbol.asyncIterator]: async function* () { yield* await cur.toArray(); },
          hasNext: (): Promise<boolean> => cur.toArray().then((a) => a.length > 0),
          close: (): Promise<void> => Promise.resolve(),
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
// Exactly the shape routers/auth_router.py writes at login (no role).
const sess = (tok: string, uid: string): Row =>
  ({ user_id: uid, session_token: tok, expires_at: FUT(), created_at: new Date(), last_refreshed_at: new Date() });

function seed(): Record<string, Row[]> {
  return {
    user_sessions: [sess('tok-owner', 'u1'), sess('tok-acc', 's-acc'), sess('tok-view', 's-view'),
      sess('tok-u2', 'u2'), sess('tok-nodef', 'u-nodef')],
    users: [{ user_id: 'u1', email: 'owner@x' }, { user_id: 's-acc', email: 'acc@x' }, { user_id: 's-view', email: 'view@x' },
      { user_id: 'u2', email: 'u2@x' }, { user_id: 'u-nodef', email: 'nodef@x' }],
    team_members: [{ owner_user_id: 'u1', email: 'acc@x', role: 'accountant', active: true },
      { owner_user_id: 'u1', email: 'view@x', role: 'viewer', active: true }],
    companies: [
      { id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false },
      { id: 'co-z', user_id: 'u2', is_default: true },
      { id: 'co-n1', user_id: 'u-nodef' }, { id: 'co-n2', user_id: 'u-nodef' },
    ],
    vendors: [
      { id: 'v-a', user_id: 'u1', company_id: 'co-a', name: 'A' }, { id: 'v-b', user_id: 'u1', company_id: 'co-b', name: 'B' },
      { id: 'v-z', user_id: 'u2', company_id: 'co-z', name: 'Z' },
      { id: 'v-n1', user_id: 'u-nodef', company_id: 'co-n1', name: 'N1' }, { id: 'v-n2', user_id: 'u-nodef', company_id: 'co-n2', name: 'N2' },
    ],
    files: [{ id: 'f1', user_id: 'u1', company_id: 'co-a', filename: 'a.pdf', is_deleted: false, created_at: 't1' }],
  };
}

interface Res { status: number; body: string }
function rawGet(port: number, path: string, lines: Buffer[]): Promise<Res> {
  return new Promise((resolve, reject) => {
    const s = net.connect(port, '127.0.0.1');
    const chunks: Buffer[] = [];
    s.on('data', (c: Buffer) => chunks.push(c));
    s.on('error', reject);
    s.on('end', () => {
      const text = Buffer.concat(chunks).toString('latin1');
      const [head = '', ...rest] = text.split('\r\n\r\n');
      resolve({ status: Number(head.slice(9, 12)), body: Buffer.from(rest.join('\r\n\r\n'), 'latin1').toString('utf8') });
    });
    s.write(Buffer.concat([
      Buffer.from(`GET ${path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n`, 'latin1'),
      ...lines.map((l) => Buffer.concat([l, Buffer.from('\r\n')])),
      Buffer.from('\r\n'),
    ]));
  });
}

const H = (s: string): Buffer => Buffer.from(s, 'latin1');
const auth = (tok: string): Buffer => H(`Authorization: Bearer ${tok}`);

describe('Gate-9c · duplicate X-Company-Id tenant parity (raw sockets)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let port: number;
  beforeAll(async () => {
    state = { data: seed(), ops: [], writes: [] };
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const mongo: MongoConn = { client: {} as MongoConn['client'], db: fakeDb(state), ping: async () => true, close: async () => undefined };
    app = await buildApp({ config: baseConfig, logger, mongo });
    await app.listen({ port: 0, host: '127.0.0.1' });
    port = (app.server.address() as AddressInfo).port;
  });
  afterAll(async () => {
    expect(state.writes).toEqual([]);
    await app.close();
  });

  const vendorIds = async (tok: string, cid: Buffer[]): Promise<string[]> => {
    const r = await rawGet(port, '/api/vendors', [auth(tok), ...cid]);
    expect(r.status).toBe(200);
    return (JSON.parse(r.body) as Row[]).map((v) => v['id'] as string);
  };
  const companyLookups = (): Row[] => state.ops.filter((o) => o.coll === 'companies').map((o) => o.filter);

  // [description, token, header lines, expected vendor ids]
  const CASES: Array<[string, string, string[], string[]]> = [
    ['A no header → default', 'tok-owner', [], ['v-a']],
    ['B single owned', 'tok-owner', ['X-Company-Id: co-b'], ['v-b']],
    ['C single unowned → default', 'tok-owner', ['X-Company-Id: co-z'], ['v-a']],
    ['D single unknown → default', 'tok-owner', ['X-Company-Id: co-nope'], ['v-a']],
    ['E single empty → default', 'tok-owner', ['X-Company-Id:'], ['v-a']],
    ['F SP/HTAB around value stripped by parser', 'tok-owner', ['X-Company-Id: \t co-b \t'], ['v-b']],
    ['F inner space kept → unknown', 'tok-owner', ['X-Company-Id: co -b'], ['v-a']],
    ['G name lower-case', 'tok-owner', ['x-company-id: co-b'], ['v-b']],
    ['G name upper-case', 'tok-owner', ['X-COMPANY-ID: co-b'], ['v-b']],
    ['H id casing is exact (CO-B unknown)', 'tok-owner', ['X-Company-Id: CO-B'], ['v-a']],
    ['I dup co-b, co-a → co-b', 'tok-owner', ['X-Company-Id: co-b', 'X-Company-Id: co-a'], ['v-b']],
    ['J dup co-a, co-b → co-a', 'tok-owner', ['X-Company-Id: co-a', 'X-Company-Id: co-b'], ['v-a']],
    ['K dup identical co-b', 'tok-owner', ['X-Company-Id: co-b', 'X-Company-Id: co-b'], ['v-b']],
    ['L dup mixed name casing', 'tok-owner', ['x-company-id: co-b', 'X-COMPANY-ID: co-a'], ['v-b']],
    ['L dup with other header between', 'tok-owner', ['X-Company-Id: co-b', 'X-Other: 1', 'X-Company-Id: co-a'], ['v-b']],
    ['M single literal "co-b, co-a" → unknown → default', 'tok-owner', ['X-Company-Id: co-b, co-a'], ['v-a']],
    ['M single literal "co-b,co-a" → default', 'tok-owner', ['X-Company-Id: co-b,co-a'], ['v-a']],
    ['N dup empty first → default (not second)', 'tok-owner', ['X-Company-Id:', 'X-Company-Id: co-b'], ['v-a']],
    ['N dup whitespace-only first → default', 'tok-owner', ['X-Company-Id:    ', 'X-Company-Id: co-b'], ['v-a']],
    ['dup unknown first → default', 'tok-owner', ['X-Company-Id: co-nope', 'X-Company-Id: co-b'], ['v-a']],
    ['dup unowned first → default', 'tok-owner', ['X-Company-Id: co-z', 'X-Company-Id: co-b'], ['v-a']],
    ['dup owned first, unowned second', 'tok-owner', ['X-Company-Id: co-b', 'X-Company-Id: co-z'], ['v-b']],
    ['NBSP kept (Python does not trim it) → default', 'tok-owner', ['X-Company-Id: co-b '], ['v-a']],
    ['O no-default user, no header → first company', 'tok-nodef', [], ['v-n1']],
    ['O no-default user, dup co-n2, co-n1', 'tok-nodef', ['X-Company-Id: co-n2', 'X-Company-Id: co-n1'], ['v-n2']],
    ['P other user: dup co-a (not theirs), co-z', 'tok-u2', ['X-Company-Id: co-a', 'X-Company-Id: co-z'], ['v-z']],
    ['P other user: dup co-z, co-a', 'tok-u2', ['X-Company-Id: co-z', 'X-Company-Id: co-a'], ['v-z']],
    ['staff accountant: dup co-b, co-a (owner scope)', 'tok-acc', ['X-Company-Id: co-b', 'X-Company-Id: co-a'], ['v-b']],
    ['staff viewer: dup co-a, co-b (owner scope)', 'tok-view', ['X-Company-Id: co-a', 'X-Company-Id: co-b'], ['v-a']],
    ['staff viewer: single literal comma', 'tok-view', ['X-Company-Id: co-b, co-a'], ['v-a']],
  ];

  for (const [desc, tok, lines, want] of CASES) {
    it(desc, async () => {
      expect(await vendorIds(tok, lines.map(H))).toEqual(want);
    });
  }

  it('exact ownership lookup uses the FIRST raw value; comma header looked up literally', async () => {
    state.ops = [];
    await vendorIds('tok-owner', [H('X-Company-Id: co-b'), H('X-Company-Id: co-a')]);
    expect(companyLookups()).toEqual([{ id: 'co-b', user_id: 'u1' }]);
    state.ops = [];
    await vendorIds('tok-owner', [H('X-Company-Id: co-b, co-a')]);
    expect(companyLookups()).toEqual([
      { id: 'co-b, co-a', user_id: 'u1' }, { user_id: 'u1', is_default: true },
    ]);
    state.ops = [];
    await vendorIds('tok-owner', [H('X-Company-Id:'), H('X-Company-Id: co-b')]);
    expect(companyLookups()).toEqual([{ user_id: 'u1', is_default: true }]); // "" → no override lookup
    state.ops = [];
    await vendorIds('tok-acc', [H('X-Company-Id: co-b'), H('X-Company-Id: co-a')]);
    expect(companyLookups()).toEqual([{ id: 'co-b', user_id: 'u1' }]); // staff → owner uid
  });

  it('header set A (two headers) and B (one comma header) are NOT equivalent', async () => {
    const a = await vendorIds('tok-owner', [H('X-Company-Id: co-b'), H('X-Company-Id: co-a')]);
    const b = await vendorIds('tok-owner', [H('X-Company-Id: co-b, co-a')]);
    expect(a).toEqual(['v-b']);
    expect(b).toEqual(['v-a']);
  });

  it('user-only control: /api/files ignores the header and never reads companies', async () => {
    state.ops = [];
    const r = await rawGet(port, '/api/files', [auth('tok-owner'), H('X-Company-Id: co-b'), H('X-Company-Id: co-a')]);
    expect(r.status).toBe(200);
    expect((JSON.parse(r.body) as Row[]).map((f) => f['id'])).toEqual(['f1']);
    expect(companyLookups()).toEqual([]);
  });

  it('auth precedes tenant: invalid session with duplicate headers → 401, no company read', async () => {
    state.ops = [];
    const r = await rawGet(port, '/api/vendors', [auth('nope'), H('X-Company-Id: co-b'), H('X-Company-Id: co-a')]);
    expect(r.status).toBe(401);
    expect(r.body).toBe('{"detail":"Invalid session"}');
    expect(companyLookups()).toEqual([]);
  });
});
