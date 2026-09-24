/**
 * Unit tests for the `apps/api` health surface.
 *
 * The negative readiness case is exercised here rather than against a running
 * process, because the only way to make a real Mongo unreachable is to stop the
 * local server, and that is shared state. A stub that fails the way the driver
 * fails proves the same branch without touching anything.
 */
import { describe, expect, it } from 'vitest';
import { liveReport, readyReport, SERVICE_NAME, type Pingable } from '../src/health/health';

const pinger = (impl: () => Promise<unknown>): Pingable => ({ command: impl });

describe('/health/live — liveness makes no dependency call', () => {
  it('reports ok for this service, with whole-second uptime', () => {
    expect(liveReport(12.7)).toEqual({ status: 'ok', service: SERVICE_NAME, uptime_s: 13 });
  });

  it('names THIS application, not backend-node', () => {
    expect(SERVICE_NAME).toBe('trukvia-apps-api');
    expect(liveReport(0).service).not.toBe('trukvia-backend-node');
  });
});

describe('/health/ready — 200 only when Mongo answers the ping', () => {
  it('is ok when the ping comes back ok:1', async () => {
    const r = await readyReport(pinger(async () => ({ ok: 1 })));
    expect(r).toEqual({
      status: 200,
      body: { status: 'ok', service: SERVICE_NAME, checks: { mongo: 'ok' } },
    });
  });

  it('is 503 degraded when the ping resolves without ok:1', async () => {
    const r = await readyReport(pinger(async () => ({ ok: 0 })));
    expect(r.status).toBe(503);
    expect(r.body).toEqual({
      status: 'degraded',
      service: SERVICE_NAME,
      checks: { mongo: 'unavailable' },
    });
  });

  it('is 503 degraded when the ping throws — the driver failure mode', async () => {
    const r = await readyReport(
      pinger(async () => {
        throw new Error('MongoServerSelectionError: connect ECONNREFUSED 127.0.0.1:27017');
      }),
    );
    expect(r.status).toBe(503);
    expect(r.body.checks.mongo).toBe('unavailable');
  });

  it('reports not_configured, and 503, when there is no database at all', async () => {
    const r = await readyReport(null);
    expect(r.status).toBe(503);
    expect(r.body.checks.mongo).toBe('not_configured');
  });

  it('pings only — it never reads or writes business data', async () => {
    const seen: Record<string, unknown>[] = [];
    await readyReport(
      pinger(async function (this: unknown) {
        return { ok: 1 };
      }) as Pingable & { command: (c: Record<string, unknown>) => Promise<unknown> },
    );
    const probe: Pingable = {
      command: async (c) => {
        seen.push(c);
        return { ok: 1 };
      },
    };
    await readyReport(probe);
    expect(seen).toEqual([{ ping: 1 }]);
  });
});

describe('the response body leaks nothing', () => {
  it('carries no database name, connection string, credential or error text', async () => {
    const leaky = 'MongoServerSelectionError: mongodb://user:pw@host/secret_db_name';
    const r = await readyReport(
      pinger(async () => {
        throw new Error(leaky);
      }),
    );
    const rendered = JSON.stringify(r.body) + JSON.stringify(liveReport(1));
    for (const secret of ['mongodb://', 'user:pw', 'secret_db_name', 'MongoServerSelectionError']) {
      expect(rendered).not.toContain(secret);
    }
    expect(Object.keys(r.body)).toEqual(['status', 'service', 'checks']);
    expect(Object.keys(r.body.checks)).toEqual(['mongo']);
  });
});
