/**
 * TRUKVIA · Phase-4 · Gate-9f · Node readiness for the routing layer — Vitest.
 *
 * `/health/ready` is 200 only when Mongo answers a ping AND every frozen
 * `.migration-allowlist` route is registered as a GET route. It performs no
 * business read or write (only `ping`), and it fails closed otherwise.
 */
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import type { Db } from 'mongodb';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const cfg: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1', mongoUrl: 'mongodb://localhost:27017',
  dbName: 'trukvia_node_test', corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};
const ALLOW = readFileSync(new URL('../.migration-allowlist', import.meta.url), 'utf8')
  .split('\n').map((l) => l.trim()).filter((l) => l !== '' && !l.startsWith('#'));

function mongo(ping: boolean): { conn: MongoConn; collection: ReturnType<typeof vi.fn> } {
  const collection = vi.fn(() => ({ createIndex: vi.fn(async () => 'ok') }));
  const db = { collection } as unknown as Db;
  return { conn: { client: {} as MongoConn['client'], db, ping: async () => ping, close: async () => undefined }, collection };
}
const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });

describe('Gate-9f · /health/ready', () => {
  it('ready: mongo ok + every frozen-allowlist route registered; ping only (no collection access)', async () => {
    const m = mongo(true);
    const app = await buildApp({ config: cfg, logger, mongo: m.conn });
    m.collection.mockClear();
    const r = await app.inject({ method: 'GET', url: '/health/ready' });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toEqual({
      status: 'ok', service: 'trukvia-backend-node',
      checks: { mongo: 'ok', routes: 'ok', allowlisted_routes: ALLOW.length, registered_routes: ALLOW.length },
    });
    expect(ALLOW.length).toBe(66);
    expect(m.collection).not.toHaveBeenCalled();
    await app.close();
  });

  it('not ready (503) when the Mongo ping fails, even with all routes registered', async () => {
    const app = await buildApp({ config: cfg, logger, mongo: mongo(false).conn });
    const r = await app.inject({ method: 'GET', url: '/health/ready' });
    expect(r.statusCode).toBe(503);
    expect(r.json()).toMatchObject({ status: 'degraded', checks: { mongo: 'unavailable', routes: 'ok' } });
    await app.close();
  });

  it('not ready (503) when the /api surface is not mounted', async () => {
    const app = await buildApp({ config: cfg, logger, mongo: null });
    const r = await app.inject({ method: 'GET', url: '/health/ready' });
    expect(r.statusCode).toBe(503);
    expect(r.json()).toMatchObject({ status: 'degraded', checks: { mongo: 'not_configured', routes: 'not_mounted' } });
    await app.close();
  });

  it('liveness stays process-only and both health paths bypass the Python router', async () => {
    const app = await buildApp({ config: cfg, logger, mongo: mongo(true).conn });
    expect((await app.inject({ method: 'GET', url: '/health/live' })).statusCode).toBe(200);
    expect((await app.inject({ method: 'GET', url: '/health/ready?x=1' })).statusCode).toBe(200);
    await app.close();
  });
});
