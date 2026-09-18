import type { FastifyInstance } from 'fastify';

/**
 * TRUKVIA · Phase-3 · Gate-7u · API root ping read-only shadow.
 *
 *   GET /api/
 *
 * Faithful shadow of:
 *   backend/server.py::root (L92-94)
 *
 *   @app.get("/api/")
 *   async def root():
 *       return {"message": "Bitumen Transport Accounting API"}
 *
 * No authentication dependency, no parameters, no DB access, no service
 * call. The response is FastAPI's JSONResponse rendering of a constant dict:
 * status 200, body bytes below, `content-type: application/json` (no
 * charset) — sent as a Buffer so Fastify does not append one.
 *
 * HEAD: FastAPI's APIRoute registers ONLY the declared method, so Python
 * answers `HEAD /api/` with 405 `{"detail":"Method Not Allowed"}` and
 * `allow: GET` (verified live). Fastify would auto-register a 200 HEAD for
 * every GET, so the auto route is disabled here and Python's 405 is
 * reproduced explicitly (body withheld on HEAD, content-length kept).
 *
 * The path is registered WITH its trailing slash, exactly as Python declares
 * it. `GET /api` (no slash) is a different path: Starlette answers it with a
 * 307 redirect (redirect_slashes) — a framework-gate item, not handled here.
 */
const BODY = Buffer.from('{"message":"Bitumen Transport Accounting API"}', 'utf8');
const METHOD_NOT_ALLOWED = Buffer.from('{"detail":"Method Not Allowed"}', 'utf8');

export async function registerApiRootRoute(app: FastifyInstance): Promise<void> {
  // migration-allowlisted: phase-3-gate-7u (read-only)
  app.get('/api/', { exposeHeadRoute: false }, async (_req, reply) =>
    reply.code(200).header('content-type', 'application/json').send(BODY));

  // Python parity: HEAD on a FastAPI GET route → 405 with `allow: GET`.
  app.head('/api/', async (_req, reply) =>
    reply.code(405).header('allow', 'GET').header('content-type', 'application/json').send(METHOD_NOT_ALLOWED));
}
