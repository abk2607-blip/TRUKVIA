/**
 * TRUKVIA · Phase-4 · Gate-9g · readiness failure modes (rehearsal support) — Vitest.
 *
 * The live rehearsal covers healthy start and database loss. The two cases that
 * would require editing the FROZEN allowlist on disk are simulated here by
 * mocking only `readFileSync` for `.migration-allowlist`:
 *   * allowlist unreadable        → 503, routes "unknown"  (fail closed)
 *   * allowlisted route missing   → 503, routes "missing"
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Db } from 'mongodb';
import type { AppConfig } from '../src/config.js';
import type { MongoConn } from '../src/db.js';

const state: { mode: 'real' | 'throw' | 'extra' } = { mode: 'real' };

vi.mock('node:fs', async (importOriginal) => {
  const real = await importOriginal<typeof import('node:fs')>();
  const readFileSync = ((path: unknown, ...rest: unknown[]) => {
    const isAllowlist = String(path instanceof URL ? path.pathname : path).endsWith('.migration-allowlist');
    if (isAllowlist && state.mode === 'throw') throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' });
    const out = (real.readFileSync as (...a: unknown[]) => unknown)(path, ...rest);
    if (isAllowlist && state.mode === 'extra') return `${String(out)}\n/api/not-registered-anywhere\n`;
    return out;
  }) as typeof real.readFileSync;
  return { ...real, default: { ...real, readFileSync }, readFileSync };
});

const cfg: AppConfig = {
  nodeEnv: 'test', logLevel: 'silent', port: 0, host: '127.0.0.1', mongoUrl: 'mongodb://localhost:27017',
  dbName: 'trukvia_node_test', corsOrigins: [], requestIdHeader: 'x-request-id', trustIncomingRequestId: false,
};
const mongo = (): MongoConn => ({
  client: {} as MongoConn['client'],
  db: { collection: vi.fn(() => ({ createIndex: vi.fn(async () => 'ok') })) } as unknown as Db,
  ping: async () => true, close: async () => undefined,
});

async function ready(): Promise<{ status: number; body: Record<string, unknown> }> {
  const { buildApp } = await import('../src/app.js');
  const { buildLogger } = await import('../src/logger.js');
  const app = await buildApp({ config: cfg, logger: buildLogger({ logLevel: 'silent', nodeEnv: 'test' }), mongo: mongo() });
  const r = await app.inject({ method: 'GET', url: '/health/ready' });
  await app.close();
  return { status: r.statusCode, body: r.json() };
}

describe('Gate-9g · /health/ready failure modes', () => {
  beforeEach(() => { state.mode = 'real'; });

  it('healthy baseline (real frozen allowlist) → 200', async () => {
    const r = await ready();
    expect(r.status).toBe(200);
    expect(r.body['checks']).toMatchObject({ routes: 'ok', allowlisted_routes: 66, registered_routes: 66 });
  });

  it('allowlist unreadable → 503, routes "unknown" (fail closed)', async () => {
    state.mode = 'throw';
    const r = await ready();
    expect(r.status).toBe(503);
    expect(r.body).toMatchObject({ status: 'degraded', checks: { mongo: 'ok', routes: 'unknown' } });
  });

  it('an allowlisted route not registered → 503, routes "missing"', async () => {
    state.mode = 'extra';
    const r = await ready();
    expect(r.status).toBe(503);
    expect(r.body).toMatchObject({ status: 'degraded', checks: { routes: 'missing', allowlisted_routes: 67, registered_routes: 66 } });
  });
});
