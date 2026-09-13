import type { FastifyInstance } from 'fastify';
import type { MongoConn } from './db.js';

/**
 * Infrastructure-only health endpoints.
 *
 * These are NEW Node skeleton endpoints. They are NOT under /api/*
 * and MUST NOT be mapped into the existing ingress in this phase.
 *
 *   GET /health/live   — process is up (no dependency check)
 *   GET /health/ready  — dependencies (Mongo) are reachable
 */

export interface HealthDeps {
  mongo: Pick<MongoConn, 'ping'> | null;
}

export interface LiveResponse {
  status: 'ok';
  service: 'trukvia-backend-node';
  uptime_s: number;
}

export interface ReadyResponse {
  status: 'ok' | 'degraded';
  service: 'trukvia-backend-node';
  checks: {
    mongo: 'ok' | 'unavailable' | 'not_configured';
  };
}

export async function registerHealth(app: FastifyInstance, deps: HealthDeps): Promise<void> {
  app.get('/health/live', async (): Promise<LiveResponse> => {
    return {
      status: 'ok',
      service: 'trukvia-backend-node',
      uptime_s: Math.round(process.uptime()),
    };
  });

  app.get('/health/ready', async (_req, reply): Promise<ReadyResponse> => {
    let mongoStatus: ReadyResponse['checks']['mongo'];
    if (!deps.mongo) {
      mongoStatus = 'not_configured';
    } else {
      const ok = await deps.mongo.ping();
      mongoStatus = ok ? 'ok' : 'unavailable';
    }
    const overall: ReadyResponse['status'] = mongoStatus === 'ok' ? 'ok' : 'degraded';
    if (overall !== 'ok') {
      reply.code(503);
    }
    return {
      status: overall,
      service: 'trukvia-backend-node',
      checks: { mongo: mongoStatus },
    };
  });
}
