import { describe, it, expect, vi } from 'vitest';
import { buildApp } from '../src/app.js';
import { buildLogger } from '../src/logger.js';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const baseConfig: AppConfig = {
  nodeEnv: 'test',
  logLevel: 'silent',
  port: 0,
  host: '127.0.0.1',
  mongoUrl: 'mongodb://localhost:27017',
  dbName: 'trukvia_node_dev',
  corsOrigins: [],
  requestIdHeader: 'x-request-id',
  trustIncomingRequestId: false,
};

function fakeMongo(ping: () => Promise<boolean>): MongoConn {
  return {
    client: {} as MongoConn['client'],
    db: {} as MongoConn['db'],
    ping: vi.fn(ping),
    close: vi.fn(async () => undefined),
  };
}

describe('buildApp / health endpoints', () => {
  it('boots without dependencies', async () => {
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const app = await buildApp({ config: baseConfig, logger, mongo: null });
    // Ensure the app object is a Fastify instance with expected methods.
    expect(typeof app.inject).toBe('function');
    await app.close();
  });

  it('GET /health/live returns 200 with expected payload', async () => {
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const app = await buildApp({ config: baseConfig, logger, mongo: null });

    const res = await app.inject({ method: 'GET', url: '/health/live' });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { status: string; service: string; uptime_s: number };
    expect(body.status).toBe('ok');
    expect(body.service).toBe('trukvia-backend-node');
    expect(typeof body.uptime_s).toBe('number');
    await app.close();
  });

  it('GET /health/ready returns 200 when mongo ping ok', async () => {
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const mongo = fakeMongo(async () => true);
    const app = await buildApp({ config: baseConfig, logger, mongo });

    const res = await app.inject({ method: 'GET', url: '/health/ready' });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { status: string; checks: { mongo: string } };
    expect(body.status).toBe('ok');
    expect(body.checks.mongo).toBe('ok');
    await app.close();
  });

  it('GET /health/ready returns 503 when mongo ping fails', async () => {
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const mongo = fakeMongo(async () => false);
    const app = await buildApp({ config: baseConfig, logger, mongo });

    const res = await app.inject({ method: 'GET', url: '/health/ready' });
    expect(res.statusCode).toBe(503);
    const body = res.json() as { status: string; checks: { mongo: string } };
    expect(body.status).toBe('degraded');
    expect(body.checks.mongo).toBe('unavailable');
    await app.close();
  });

  it('GET /health/ready reports not_configured when mongo is null', async () => {
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const app = await buildApp({ config: baseConfig, logger, mongo: null });

    const res = await app.inject({ method: 'GET', url: '/health/ready' });
    expect(res.statusCode).toBe(503);
    const body = res.json() as { status: string; checks: { mongo: string } };
    expect(body.status).toBe('degraded');
    expect(body.checks.mongo).toBe('not_configured');
    await app.close();
  });

  it('echoes x-request-id header on health/live', async () => {
    const logger = buildLogger({ logLevel: 'silent', nodeEnv: 'test' });
    const app = await buildApp({ config: baseConfig, logger, mongo: null });

    const res = await app.inject({ method: 'GET', url: '/health/live' });
    expect(res.headers['x-request-id']).toMatch(/^[0-9a-f-]{36}$/);
    await app.close();
  });
});
