/**
 * TRUKVIA · Phase-3 · Gate-7u · GET /api/ (API root ping) — Vitest.
 *
 * Expected bytes / status / content-type are the live Python server's
 * (`server.py::root`): 200, `{"message":"Bitumen Transport Accounting API"}`,
 * `application/json`. No auth, no DB.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const BODY = '{"message":"Bitumen Transport Accounting API"}';

const baseConfig: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017', dbName: 'trukvia_node_test',
  corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};

interface State { collections: string[] }

function fakeDb(state: State): Db {
  const collection = (name: string) => {
    state.collections.push(name);
    return {
      findOne: vi.fn(async () => null),
      find: vi.fn(() => ({ sort: () => ({ skip: () => ({ limit: () => ({ toArray: async () => [] }) }), limit: () => ({ toArray: async () => [] }), toArray: async () => [] }), toArray: async () => [] })),
      countDocuments: vi.fn(async () => 0),
      insertOne: vi.fn(() => { throw new Error(`WRITE ${name}`); }),
      updateOne: vi.fn(() => { throw new Error(`WRITE ${name}`); }),
      createIndex: vi.fn(async () => 'ok'),
    };
  };
  return { collection: vi.fn(collection) } as unknown as Db;
}

async function makeApp(state: State): Promise<Awaited<ReturnType<typeof buildApp>>> {
  const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
  const mongo: MongoConn = { client: {} as MongoConn['client'], db: fakeDb(state), ping: async () => true, close: async () => undefined };
  return await buildApp({ config: baseConfig, logger, mongo });
}

describe('Gate-7u · GET /api/', () => {
  let state: State;
  let app: Awaited<ReturnType<typeof makeApp>>;
  beforeEach(async () => {
    state = { collections: [] };
    app = await makeApp(state);
    state.collections = []; // drop the app-startup idempotency index touch
  });
  afterEach(async () => { await app.close(); });

  const expectRoot = (r: Awaited<ReturnType<typeof app.inject>>): void => {
    expect(r.statusCode).toBe(200);
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.body).toBe(BODY);
    expect(r.headers['content-length']).toBe(String(Buffer.byteLength(BODY)));
  };

  it('1 normal request → exact status, bytes, content-type (no charset)', async () => {
    expectRoot(await app.inject({ method: 'GET', url: '/api/' }));
  });

  it.each([
    ['valid-looking bearer', { authorization: 'Bearer tok-u1' }],
    ['garbage bearer', { authorization: 'Bearer nope' }],
    ['cookie session', { cookie: 'session_token=abc' }],
  ])('2 auth header ignored (%s) → same response, no auth lookup', async (_n, headers) => {
    expectRoot(await app.inject({ method: 'GET', url: '/api/', headers }));
    expect(state.collections).toEqual([]);
  });

  it.each(['/api/?x=1', '/api/?x=1&x=2', '/api/?limit=abc', '/api/?'])('3 query string %s ignored', async (url) => {
    expectRoot(await app.inject({ method: 'GET', url }));
  });

  it('4 irrelevant headers ignored', async () => {
    expectRoot(await app.inject({ method: 'GET', url: '/api/', headers: {
      'x-company-id': 'co-zzz', accept: 'text/html', 'idempotency-key': 'k-12345678', 'x-request-id': 'rid-1' } }));
  });

  it('5 repeated requests are identical', async () => {
    const bodies = new Set<string>();
    for (let i = 0; i < 5; i += 1) {
      const r = await app.inject({ method: 'GET', url: '/api/' });
      expectRoot(r);
      bodies.add(r.body);
    }
    expect(bodies.size).toBe(1);
  });

  it('6 zero database activity across all request forms', async () => {
    for (const url of ['/api/', '/api/?x=1']) {
      await app.inject({ method: 'GET', url, headers: { authorization: 'Bearer tok-u1' } });
    }
    expect(state.collections).toEqual([]);
  });

  it('7 precedence: /api/ does not capture nearby static/dynamic routes', async () => {
    // Static sibling still owned by its own handler (401 from auth, not the root body).
    const trips = await app.inject({ method: 'GET', url: '/api/trips' });
    expect(trips.statusCode).toBe(401);
    expect(trips.body).not.toBe(BODY);
    // Dynamic sibling still owned by its handler.
    const tid = await app.inject({ method: 'GET', url: '/api/trips/t1' });
    expect(tid.statusCode).toBe(401);
    // Unknown paths are not answered by the root.
    for (const url of ['/api/unknown', '/api/x/y']) {
      const r = await app.inject({ method: 'GET', url });
      expect(r.statusCode).toBe(404);
      expect(r.body).not.toBe(BODY);
    }
  });

  it('8 trailing-slash-less /api → Starlette 307 to /api/ (Gate 9d, verified live); not the root body', async () => {
    const r = await app.inject({ method: 'GET', url: '/api' });
    expect(r.statusCode).toBe(307);
    expect(r.headers['location']).toBe('http://localhost:80/api/');
    expect(r.body).not.toBe(BODY);
  });

  it('9 route registration: GET plus the explicit Python-parity HEAD; no writer methods', () => {
    expect(app.hasRoute({ method: 'GET', url: '/api/' })).toBe(true);
    expect(app.hasRoute({ method: 'HEAD', url: '/api/' })).toBe(true);
    for (const m of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) {
      expect(app.hasRoute({ method: m, url: '/api/' })).toBe(false);
    }
  });

  it('10 HEAD /api/ → 405 like FastAPI (allow: GET, JSON content-type, length 31), no DB', async () => {
    const r = await app.inject({ method: 'HEAD', url: '/api/' });
    expect(r.statusCode).toBe(405);
    expect(r.headers['allow']).toBe('GET');
    expect(r.headers['content-type']).toBe('application/json');
    expect(r.headers['content-length']).toBe('31');
    // light-my-request returns the payload even for HEAD; on a real socket
    // Node's HTTP layer withholds it (verified byte-for-byte by the live
    // gate7u harness: both servers send an empty body).
    expect(r.body).toBe('{"detail":"Method Not Allowed"}');
    expect(state.collections).toEqual([]);
  });
});
