import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { registerSupplierCorrectionsRoute } from './supplier-payments-corrections.js';
import { registerSavedTripFiltersRoute } from './saved-trip-filters.js';
import { registerExpenditureTypesRoute } from './expenditure-types.js';
import { registerTripsReadRoute } from './trips.js';
import { registerTripsListRoute } from './trips-list.js';
import { registerInvoicesRoutes } from './invoices.js';
import { registerInvoicesListRoutes } from './invoices-list.js';
import { registerInvoiceShipToRoute } from './invoice-ship-to.js';

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
  await registerSavedTripFiltersRoute(app, deps);
  await registerExpenditureTypesRoute(app, deps);
  await registerTripsReadRoute(app, deps);
  await registerTripsListRoute(app, deps);
  await registerInvoicesRoutes(app, deps);
  await registerInvoicesListRoutes(app, deps);
  await registerInvoiceShipToRoute(app, deps);
}
