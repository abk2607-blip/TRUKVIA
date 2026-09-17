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
import { registerCreditDebitNoteRoutes } from './credit-debit-notes.js';
import { registerCustomerShipSitesRoute } from './customer-ship-sites.js';
import { registerCompanySupplierReadRoutes } from './company-supplier-reads.js';
import { registerExpensesReadRoutes } from './expenses.js';
import { registerVendorsReadRoutes } from './vendors.js';
import { registerSuppliersListReadRoutes } from './suppliers-list.js';
import { registerMechanicsReadRoutes } from './mechanics.js';
import { registerCompanyBankAccountsReadRoutes } from './company-bank-accounts.js';
import { registerMechanicPaymentsCorrectionsReadRoutes } from './mechanic-payments-corrections.js';
import { registerVendorPaymentsCorrectionsReadRoutes } from './vendor-payments-corrections.js';
import { registerDriverPaymentsCorrectionsReadRoutes } from './driver-payments-corrections.js';
import { registerTemplatesReadRoutes } from './templates.js';
import { registerPartyBankAccountsReadRoutes } from './party-bank-accounts.js';
import { registerAuditLogsReadRoutes } from './audit-logs.js';

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
  await registerCreditDebitNoteRoutes(app, deps);
  await registerCustomerShipSitesRoute(app, deps);
  await registerCompanySupplierReadRoutes(app, deps);
  await registerExpensesReadRoutes(app, deps);
  await registerVendorsReadRoutes(app, deps);
  await registerSuppliersListReadRoutes(app, deps);
  await registerMechanicsReadRoutes(app, deps);
  await registerCompanyBankAccountsReadRoutes(app, deps);
  await registerMechanicPaymentsCorrectionsReadRoutes(app, deps);
  await registerVendorPaymentsCorrectionsReadRoutes(app, deps);
  await registerDriverPaymentsCorrectionsReadRoutes(app, deps);
  await registerTemplatesReadRoutes(app, deps);
  await registerPartyBankAccountsReadRoutes(app, deps);
  await registerAuditLogsReadRoutes(app, deps);
}
