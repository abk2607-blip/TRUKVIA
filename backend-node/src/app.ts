import Fastify, {
  type FastifyInstance,
  type FastifyHttpOptions,
  type FastifyBaseLogger,
} from 'fastify';
import type { Server } from 'node:http';
import type { Logger } from 'pino';
import type { AppConfig } from './config.js';
import type { MongoConn } from './db.js';
import { registerRequestId } from './request-id.js';
import { registerHealth } from './health.js';
import { registerApiRoutes } from './routes/index.js';
import { registerIdempotency, ensureIdempotencyIndex } from './idempotency.js';
import { createHttpEdge } from './http-edge.js';
import { readFileSync } from 'node:fs';
import type { RoutesCheck } from './health.js';

/**
 * Fastify skeleton for the TRUKVIA Node foundation + Phase-3 migration surface.
 *
 * Phase 2 (foundation) scope:
 *   - Health endpoints
 *   - Structured request logging with request_id
 *   - No writers
 *
 * Phase 3 (migration, gate-2 onwards) scope:
 *   - Read-only shadow routes under /api/* — mounted only when a real Mongo
 *     connection is provided (see `mongo` option). Each route MUST be on the
 *     `backend-node/.migration-allowlist` and MUST be a faithful shadow of an
 *     existing Python route. Python remains authoritative.
 */

export interface BuildAppOptions {
  config: AppConfig;
  logger: Logger;
  mongo: MongoConn | null;
}

export async function buildApp(opts: BuildAppOptions): Promise<FastifyInstance> {
  const { config, logger, mongo } = opts;
  // Gate 9d: Python (uvicorn/h11 + Starlette) HTTP-edge parity — see http-edge.ts.
  const edge = createHttpEdge({ corsOrigins: config.corsOrigins });

  // Fastify 4's FastifyBaseLogger declares `msgPrefix` as required. Pino's
  // Logger doesn't include that field at compile time (it's runtime-safe).
  // We narrow the type at the boundary here — no runtime effect.
  const fastifyOptions: FastifyHttpOptions<Server> = {
    logger: logger as unknown as FastifyBaseLogger,
    disableRequestLogging: false,
    bodyLimit: 1_048_576, // 1 MiB — foundation only
    trustProxy: false,
    // Gate 9d: FastAPI never adds HEAD; Starlette has no param-length cap; `;` is a
    // literal path character; routing decisions are taken by the Python-edge rewrite.
    exposeHeadRoutes: false,
    maxParamLength: 65_535,
    useSemicolonDelimiter: false,
    rewriteUrl: edge.rewriteUrl,
    clientErrorHandler: edge.clientErrorHandler,
    // h11 enforces the Host rules itself (http-edge.ts answers with its exact 400).
    http: { requireHostHeader: false },
    genReqId: () => {
      // Actual request_id is decided in the onRequest hook (request-id.ts).
      // Fastify still needs a genReqId to avoid its default incremental numbers.
      return '_pending_';
    },
  };
  const app: FastifyInstance = Fastify(fastifyOptions);

  await registerRequestId(app, config);
  edge.register(app);

  // Structured completion log with the required fields.
  app.addHook('onResponse', async (req, reply) => {
    const tenantHeader = req.headers['x-tenant-id'];
    const actorHeader = req.headers['x-actor-user-id'];
    const tenantId =
      typeof tenantHeader === 'string'
        ? tenantHeader
        : Array.isArray(tenantHeader)
        ? (tenantHeader[0] ?? null)
        : null;
    const actorUserId =
      typeof actorHeader === 'string'
        ? actorHeader
        : Array.isArray(actorHeader)
        ? (actorHeader[0] ?? null)
        : null;

    const fields = {
      request_id: req.requestId,
      tenant_id: tenantId,
      actor_user_id: actorUserId,
      route: req.routeOptions?.url ?? req.url,
      method: req.method,
      status: reply.statusCode,
      latency_ms: Math.round(reply.elapsedTime),
    };
    req.log.info(fields, 'request_completed');
  });

  // Gate 9f: readiness also proves every frozen-allowlist route is registered.
  let allowlist: string[] | null = null;
  const routesCheck = (): RoutesCheck => {
    try {
      allowlist ??= readFileSync(new URL('../.migration-allowlist', import.meta.url), 'utf8')
        .split('\n').map((l) => l.trim()).filter((l) => l !== '' && !l.startsWith('#'));
    } catch {
      return { status: 'unknown', allowlisted: 0, registered: 0 };
    }
    const registered = allowlist.filter((url) => app.hasRoute({ method: 'GET', url })).length;
    return { status: registered === allowlist.length && registered > 0 ? 'ok' : 'missing', allowlisted: allowlist.length, registered };
  };
  await registerHealth(app, mongo ? { mongo, routes: routesCheck } : { mongo });

  // Phase-3 read-only routes require a live Mongo connection. When `mongo`
  // is null (foundation smoke tests, /health-only harnesses) the /api surface
  // is intentionally not mounted — parity with the Phase-2 skeleton.
  if (mongo) {
    registerIdempotency(app, { db: mongo.db });
    await ensureIdempotencyIndex(mongo.db);
    await registerApiRoutes(app, { db: mongo.db });
  }

  return app;
}
