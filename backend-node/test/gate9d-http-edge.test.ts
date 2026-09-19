/**
 * TRUKVIA · Phase-4 · Gate-9d · HTTP-edge parity (framework only) — Vitest.
 *
 * Expected values are the pinned Python stack's live-verified behaviour
 * (uvicorn 0.25 / h11 0.16 / Starlette 0.37.2, backend/server.py):
 *   * six security headers (setdefault) on every app response except the
 *     unhandled 500 (ServerErrorMiddleware is outermost) and h11's parser 400;
 *   * CORSMiddleware (allow_credentials False, methods/headers "*", expose
 *     Content-Disposition, max_age 600; origins from CORS_ORIGINS or "*");
 *   * Starlette Router: 405 + allow for the first PARTIAL match, HEAD 405 on GET
 *     routes, 307 slash redirects, {"detail":"Not Found"} 404s, decoded-path
 *     routing (%2F, %FF, %0A, ;);
 *   * JSON is exactly `application/json`; unhandled errors are text/plain 500.
 * Parser-level cases use real sockets (inject cannot send malformed HTTP).
 */
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import net from 'node:net';
import type { AddressInfo } from 'node:net';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

type Row = Record<string, unknown>;
interface State { data: Record<string, Row[]>; writes: string[]; reads: number }

const matches = (r: Row, f: Row): boolean => Object.entries(f).every(([k, v]) =>
  v !== null && typeof v === 'object' && '$ne' in (v as Row) ? r[k] !== (v as Row)['$ne'] : r[k] === v);
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
        state.reads++;
        const h = rows.find((r) => matches(r, f));
        return h ? project(h, o?.projection) : null;
      }),
      find: vi.fn((f: Row, o?: { projection?: Row }) => {
        state.reads++;
        let hits = rows.filter((r) => matches(r, f)).map((r) => project(r, o?.projection));
        const cur = { sort: () => cur, limit: (n: number) => { hits = hits.slice(0, n); return cur; }, toArray: async () => hits,
          // Gate 9e: Motor-style reads (async iteration, no server-side limit).
          [Symbol.asyncIterator]: async function* () { yield* await Promise.resolve(hits); },
          hasNext: (): Promise<boolean> => Promise.resolve(hits.length > 0),
          close: (): Promise<void> => Promise.resolve() };
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
const sess = (tok: string, uid: string): Row =>
  ({ user_id: uid, session_token: tok, expires_at: FUT(), created_at: new Date(), last_refreshed_at: new Date() });
function seed(): Record<string, Row[]> {
  return {
    user_sessions: [sess('tok-owner', 'u1'), sess('tok-acc', 's-acc'), sess('tok-view', 's-view'), sess('tok-500', 'u-noemail')],
    users: [{ user_id: 'u1', email: 'owner@x' }, { user_id: 's-acc', email: 'acc@x' }, { user_id: 's-view', email: 'view@x' },
      { user_id: 'u-noemail' }],
    team_members: [{ owner_user_id: 'u1', email: 'acc@x', role: 'accountant', active: true },
      { owner_user_id: 'u1', email: 'view@x', role: 'viewer', active: true }],
    companies: [{ id: 'co-a', user_id: 'u1', is_default: true }, { id: 'co-b', user_id: 'u1', is_default: false }],
    vendors: [{ id: 'v-a', user_id: 'u1', company_id: 'co-a', name: 'A' }, { id: 'v-b', user_id: 'u1', company_id: 'co-b', name: 'B' },
      { id: 'a?b', user_id: 'u1', company_id: 'co-a', name: 'Q' }, { id: '�', user_id: 'u1', company_id: 'co-a', name: 'R' }],
    company_bank_accounts: [{ id: 'cba', user_id: 'u1', company_id: 'co-a', account_number: '123456789012', masked_display: 'XXXX9012', created_at: 't' }],
  };
}

const cfg = (corsOrigins: string[]): AppConfig => ({
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1', mongoUrl: 'mongodb://localhost:27017',
  dbName: 'trukvia_node_test', corsOrigins, requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
});
async function makeApp(state: State, corsOrigins: string[]): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db: fakeDb(state), ping: async () => true, close: async () => undefined };
  return await buildApp({ config: cfg(corsOrigins), logger, mongo });
}

const SEC: Record<string, string> = {
  'x-content-type-options': 'nosniff',
  'x-frame-options': 'DENY',
  'referrer-policy': 'strict-origin-when-cross-origin',
  'strict-transport-security': 'max-age=31536000; includeSubDomains',
  'permissions-policy': 'camera=(), microphone=(self), geolocation=()',
  'content-security-policy':
    "default-src 'self' https:; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https:; " +
    "script-src 'self' 'unsafe-inline' https:; connect-src 'self' https: wss:; font-src 'self' data: https:; " +
    "frame-ancestors 'none'",
};
const expectSec = (h: Record<string, unknown>, present: boolean): void => {
  for (const [k, v] of Object.entries(SEC)) expect(h[k], k).toBe(present ? v : undefined);
};
const A = { authorization: 'Bearer tok-owner' };
const H11_400 = 'HTTP/1.1 400 Bad Request\r\ncontent-type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n' +
  'Invalid HTTP request received.';
const ALLM = 'DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT';

function rawSend(port: number, data: string | Buffer): Promise<string> {
  return new Promise((resolve, reject) => {
    const s = net.connect(port, '127.0.0.1');
    const chunks: Buffer[] = [];
    s.on('data', (c: Buffer) => chunks.push(c));
    s.on('error', reject);
    s.on('close', () => resolve(Buffer.concat(chunks).toString('latin1')));
    s.write(data);
  });
}

describe('Gate-9d · HTTP edge (CORS_ORIGINS unset → "*")', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  let port: number;
  beforeAll(async () => {
    state = { data: seed(), writes: [], reads: 0 };
    app = await makeApp(state, []);
    await app.listen({ port: 0, host: '127.0.0.1' });
    port = (app.server.address() as AddressInfo).port;
  });
  afterAll(async () => { expect(state.writes).toEqual([]); await app.close(); });
  const inj = (method: string, url: string, headers: Record<string, string> = {}): ReturnType<typeof app.inject> =>
    app.inject({ method: method as 'GET', url, headers });

  it('200 / 401 / 404 / 422 JSON: exact application/json + all six security headers, no CORS without Origin', async () => {
    for (const [url, h, status] of [['/api/vendors', A, 200], ['/api/vendors', {}, 401], ['/api/vendors/nope', A, 404],
      ['/api/fin/day-book?date_from=x', A, 422]] as const) {
      const r = await inj('GET', url, h);
      expect(r.statusCode, url).toBe(status);
      expect(r.headers['content-type'], url).toBe('application/json');
      expectSec(r.headers, true);
      expect(r.headers['access-control-allow-origin']).toBeUndefined();
    }
  });

  it('unhandled 500 → text/plain "Internal Server Error", no security / CORS headers (ServerErrorMiddleware)', async () => {
    const r = await inj('GET', '/api/vendors', { authorization: 'Bearer tok-500', origin: 'https://x.example' });
    expect(r.statusCode).toBe(500);
    expect(r.headers['content-type']).toBe('text/plain; charset=utf-8');
    expect(r.body).toBe('Internal Server Error');
    expectSec(r.headers, false);
    expect(r.headers['access-control-allow-origin']).toBeUndefined();
  });

  it('405: every non-GET method on a GET-only migrated path, before auth; body + allow + headers', async () => {
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'PROPFIND', 'HEAD']) {
      const r = await inj(m, '/api/fin/day-status');
      expect(r.statusCode, m).toBe(405);
      expect(r.headers['allow'], m).toBe('GET');
      expect(r.headers['content-type'], m).toBe('application/json');
      expect(r.headers['content-length'], m).toBe('31');
      if (m !== 'HEAD') expect(r.body, m).toBe('{"detail":"Method Not Allowed"}');
      expectSec(r.headers, true);
    }
  });

  it('405 allow = FIRST partial Python route (resolve → PUT /driver-shortage-policies/{pid})', async () => {
    const r = await inj('HEAD', '/api/driver-shortage-policies/resolve');
    expect(r.statusCode).toBe(405);
    expect(r.headers['allow']).toBe('PUT');
  });

  it('a method Python serves with a NON-migrated handler is not served by Node (404, never a write)', async () => {
    const r = await inj('POST', '/api/vendors', A);
    expect(r.statusCode).toBe(404);
    expect(r.body).toBe('{"detail":"Not Found"}');
  });

  it('307 slash redirect: query kept, all trailing slashes stripped, HEAD too, Host verbatim', async () => {
    let r = await inj('GET', '/api/vendors/?a=1&b=%20', { ...A, host: 'probe.local:8080' });
    expect(r.statusCode).toBe(307);
    expect(r.headers['location']).toBe('http://probe.local:8080/api/vendors?a=1&b=%20');
    expect(r.headers['content-length']).toBe('0');
    expect(r.headers['content-type']).toBeUndefined();
    expectSec(r.headers, true);
    r = await inj('GET', '/api/fin/day-status///?date=x', { host: 'h' });
    expect(r.headers['location']).toBe('http://h/api/fin/day-status?date=x');
    r = await inj('HEAD', '/api/vendors/', { host: 'h' });
    expect([r.statusCode, r.headers['location'], r.headers['content-length']]).toEqual([307, 'http://h/api/vendors', '0']);
    r = await inj('GET', '/api', { host: 'h' });
    expect(r.headers['location']).toBe('http://h/api/');
  });

  it('307 scheme honours X-Forwarded-Proto (last value, stripped) only from 127.0.0.1', async () => {
    let r = await app.inject({ method: 'GET', url: '/api/vendors/', headers: { host: 'h', 'x-forwarded-proto': ' https ' } });
    expect(r.headers['location']).toBe('https://h/api/vendors');
    r = await app.inject({ method: 'GET', url: '/api/vendors/', remoteAddress: '10.0.0.9', headers: { host: 'h', 'x-forwarded-proto': 'https' } });
    expect(r.headers['location']).toBe('http://h/api/vendors');
  });

  it('decoded-path routing like uvicorn/Starlette: %2F, %FF, %0A, %3F, ;, //, long params', async () => {
    expect((await inj('GET', '/api/vendors/a%2Fb', A)).body).toBe('{"detail":"Not Found"}');
    expect((await inj('GET', '/api/vendors/%FF', A)).json()).toEqual({ id: '�', company_id: 'co-a', name: 'R' });
    expect((await inj('GET', '/api/vendors%0A', A)).statusCode).toBe(200); // Python `$` matches before a final \n
    expect((await inj('GET', '/api/vendors/a%3Fb', A)).json()).toEqual({ id: 'a?b', company_id: 'co-a', name: 'Q' });
    expect((await inj('GET', '/api/vendors;x', A)).body).toBe('{"detail":"Not Found"}');
    expect((await inj('GET', '/api//vendors', A)).body).toBe('{"detail":"Not Found"}');
    const long = await inj('GET', `/api/vendors/${'x'.repeat(150)}`, A);
    expect([long.statusCode, long.body]).toEqual([404, '{"detail":"Vendor not found"}']);
  });

  it('CORS simple response ("*"): ACAO *, expose Content-Disposition; Cookie → echoed origin + Vary', async () => {
    let r = await inj('GET', '/api/vendors', { ...A, origin: 'https://any.example' });
    expect(r.headers['access-control-allow-origin']).toBe('*');
    expect(r.headers['access-control-expose-headers']).toBe('Content-Disposition');
    expect(r.headers['vary']).toBeUndefined();
    r = await inj('GET', '/api/vendors', { ...A, origin: 'https://any.example', cookie: 'x=1' });
    expect(r.headers['access-control-allow-origin']).toBe('https://any.example');
    expect(r.headers['vary']).toBe('Origin');
    r = await inj('GET', '/api/nowhere', { origin: 'https://any.example' }); // 404 also carries CORS
    expect([r.statusCode, r.headers['access-control-allow-origin']]).toEqual([404, '*']);
  });

  it('preflight ("*"): answered before routing, echoes requested headers, 400 on bad method', async () => {
    let r = await inj('OPTIONS', '/nowhere', { origin: 'https://a', 'access-control-request-method': 'PUT',
      'access-control-request-headers': 'authorization, x-company-id' });
    expect([r.statusCode, r.body, r.headers['content-type']]).toEqual([200, 'OK', 'text/plain; charset=utf-8']);
    expect(r.headers['access-control-allow-origin']).toBe('*');
    expect(r.headers['access-control-allow-methods']).toBe(ALLM);
    expect(r.headers['access-control-max-age']).toBe('600');
    expect(r.headers['access-control-allow-headers']).toBe('authorization, x-company-id');
    expect(r.headers['access-control-expose-headers']).toBeUndefined();
    expectSec(r.headers, true);
    r = await inj('OPTIONS', '/api/vendors', { origin: 'https://a', 'access-control-request-method': 'get' });
    expect([r.statusCode, r.body]).toEqual([400, 'Disallowed CORS method']);
    r = await inj('OPTIONS', '/api/vendors', { origin: 'https://a' }); // no ACRM → routing → 405 + simple CORS
    expect([r.statusCode, r.headers['allow'], r.headers['access-control-allow-origin']]).toEqual([405, 'GET', '*']);
  });

  it('Node-only /health/* bypasses the Python router', async () => {
    expect((await inj('GET', '/health/live')).statusCode).toBe(200);
  });

  it('parser level (raw sockets): non-vchar target and llhttp errors → h11 400 bytes exactly', async () => {
    const nonAscii = Buffer.concat([Buffer.from('GET /api/vendors/'), Buffer.from([0xc3, 0xa9]),
      Buffer.from(' HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n')]);
    expect(await rawSend(port, nonAscii)).toBe(H11_400);
    expect(await rawSend(port, 'GARBAGE\r\n\r\n')).toBe(H11_400);
    // h11 Request(): HTTP/1.1 without Host, or more than one Host (any version).
    expect(await rawSend(port, 'GET /api/vendors HTTP/1.1\r\nConnection: close\r\n\r\n')).toBe(H11_400);
    expect(await rawSend(port, 'GET /api/vendors HTTP/1.1\r\nHost: a\r\nHost: b\r\nConnection: close\r\n\r\n')).toBe(H11_400);
    expect(await rawSend(port, 'GET /api/vendors HTTP/1.0\r\nHost: a\r\nhost: a\r\n\r\n')).toBe(H11_400);
    // Documented, NOT at parity: Python h11 accepts obs-fold (200) and unknown token methods (405);
    // Node's llhttp rejects both at the parser — answered with the same h11-style 400 bytes.
    expect(await rawSend(port, 'GET /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\nX-A: 1\r\n  2\r\n\r\n')).toBe(H11_400);
    expect(await rawSend(port, 'FOO /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n')).toBe(H11_400);
  });

  it('Gate 9c preserved: duplicate X-Company-Id → first raw value; staff owner scope (raw socket)', async () => {
    const get = async (tok: string, cids: string[]): Promise<string> => {
      const res = await rawSend(port, `GET /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\nAuthorization: Bearer ${tok}\r\n` +
        cids.map((c) => `X-Company-Id: ${c}\r\n`).join('') + '\r\n');
      return res.split('\r\n\r\n')[1] ?? '';
    };
    expect(await get('tok-owner', ['co-b', 'co-a'])).toContain('"id":"v-b"');
    expect(await get('tok-acc', ['co-b', 'co-a'])).toContain('"id":"v-b"');
    expect(await get('tok-view', ['co-b, co-a'])).toContain('"id":"v-a"');
  });

  it('Gate 9b preserved: viewer masked, owner/accountant full bank numbers', async () => {
    const num = async (tok: string): Promise<unknown> =>
      ((await inj('GET', '/api/company-bank-accounts', { authorization: `Bearer ${tok}` })).json())[0]?.['account_number'];
    expect(await num('tok-owner')).toBe('123456789012');
    expect(await num('tok-acc')).toBe('123456789012');
    expect(await num('tok-view')).toBe('XXXX9012');
  });
});

describe('Gate-9d · HTTP edge (explicit CORS_ORIGINS list)', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeAll(async () => { state = { data: seed(), writes: [], reads: 0 }; app = await makeApp(state, ['https://app.example']); });
  afterAll(async () => { expect(state.writes).toEqual([]); await app.close(); });

  it('allowed origin: echoed + Vary: Origin; disallowed: only expose-headers', async () => {
    let r = await app.inject({ method: 'GET', url: '/api/vendors', headers: { ...A, origin: 'https://app.example' } });
    expect([r.headers['access-control-allow-origin'], r.headers['vary']]).toEqual(['https://app.example', 'Origin']);
    expect(r.headers['access-control-expose-headers']).toBe('Content-Disposition');
    r = await app.inject({ method: 'GET', url: '/api/vendors', headers: { ...A, origin: 'https://evil.example' } });
    expect([r.headers['access-control-allow-origin'], r.headers['vary']]).toEqual([undefined, undefined]);
    expect(r.headers['access-control-expose-headers']).toBe('Content-Disposition');
  });

  it('preflight: Vary: Origin always; disallowed origin → 400 "Disallowed CORS origin"', async () => {
    let r = await app.inject({ method: 'OPTIONS', url: '/api/vendors', headers: { origin: 'https://app.example', 'access-control-request-method': 'GET' } });
    expect([r.statusCode, r.headers['access-control-allow-origin'], r.headers['vary']]).toEqual([200, 'https://app.example', 'Origin']);
    r = await app.inject({ method: 'OPTIONS', url: '/api/vendors', headers: { origin: 'https://evil.example', 'access-control-request-method': 'DELETE' } });
    expect([r.statusCode, r.body, r.headers['access-control-allow-origin'], r.headers['vary']])
      .toEqual([400, 'Disallowed CORS origin', undefined, 'Origin']);
  });
});
