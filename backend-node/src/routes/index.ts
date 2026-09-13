import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { registerSupplierCorrectionsRoute } from './supplier-payments-corrections.js';

/**
 * TRUKVIA Node · Phase-3 API-route registrar.
 *
 * Every route mounted here MUST be:
 *   - read-only in this gate,
 *   - present in `backend-node/.migration-allowlist`,
 *   - a faithful shadow of an existing Python route (Python remains
 *     authoritative until the parity harness + traffic-split cutover).
 */

export interface ApiRouteDeps {
  db: Db;
}

export async function registerApiRoutes(
  app: FastifyInstance,
  deps: ApiRouteDeps,
): Promise<void> {
  await registerSupplierCorrectionsRoute(app, deps);
}
