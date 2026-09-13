import { randomUUID } from 'node:crypto';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { AppConfig } from './config.js';

/**
 * Request-ID infrastructure.
 *
 * - If `trustIncomingRequestId` is true and the incoming header matches
 *   a safe pattern, propagate it; otherwise generate a fresh UUIDv4.
 * - Always echo the (final) request-id back in the response header.
 * - Attach `request_id` to the per-request logger so downstream logs
 *   inherit it automatically.
 */

// UUIDs, ULID-ish or hex-ish IDs up to 128 chars. Anything else is rejected.
const SAFE_ID = /^[A-Za-z0-9_-]{8,128}$/;

declare module 'fastify' {
  interface FastifyRequest {
    requestId: string;
  }
}

export function isSafeRequestId(raw: unknown): raw is string {
  return typeof raw === 'string' && SAFE_ID.test(raw);
}

export function resolveRequestId(
  incoming: unknown,
  trustIncoming: boolean,
): { id: string; source: 'incoming' | 'generated' } {
  if (trustIncoming && isSafeRequestId(incoming)) {
    return { id: incoming, source: 'incoming' };
  }
  return { id: randomUUID(), source: 'generated' };
}

export async function registerRequestId(
  app: FastifyInstance,
  cfg: Pick<AppConfig, 'requestIdHeader' | 'trustIncomingRequestId'>,
): Promise<void> {
  const header = cfg.requestIdHeader.toLowerCase();

  app.addHook('onRequest', async (req: FastifyRequest, reply: FastifyReply) => {
    const incoming = req.headers[header];
    const first = Array.isArray(incoming) ? incoming[0] : incoming;
    const { id } = resolveRequestId(first, cfg.trustIncomingRequestId);
    req.requestId = id;
    reply.header(header, id);
    // Bind request_id onto Fastify's per-request logger.
    req.log = req.log.child({ request_id: id });
  });
}
