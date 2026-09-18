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
import { registerRepairEventsReadRoutes } from './repair-events.js';
import { registerMechanicWorkOrdersReadRoutes } from './mechanic-work-orders.js';
import { registerVendorBillsReadRoutes } from './vendor-bills.js';
import { registerSupplierPaymentsListReadRoutes } from './supplier-payments-list.js';
import { registerMechanicPaymentsListReadRoutes } from './mechanic-payments-list.js';
import { registerDriverPaymentsListReadRoutes } from './driver-payments-list.js';
import { registerVendorPaymentsListReadRoutes } from './vendor-payments-list.js';
import { registerWalletAdjustmentsListReadRoutes } from './wallet-adjustments-list.js';
import { registerWalletTransfersListReadRoutes } from './wallet-transfers-list.js';
import { registerWalletRechargesListReadRoutes } from './wallet-recharges-list.js';
import { registerPolicyChangesListReadRoutes } from './policy-changes-list.js';
import { registerSupplierVehiclesListReadRoutes } from './supplier-vehicles-list.js';
import { registerApprovalsPendingCountRoutes } from './approvals-pending-count.js';
import { registerApprovalsListRoutes } from './approvals-list.js';
import { registerFuelVehicleMapsListRoutes } from './fuel-vehicle-maps-list.js';
import { registerFilesListRoutes } from './files-list.js';
import { registerFilesUsageListRoutes } from './files-usage-list.js';
import { registerTollImportLookupRoutes } from './toll-import-lookup.js';
import { registerApprovalDetailRoutes } from './approval-detail.js';
import { registerFinDayClosuresListRoutes } from './fin-day-closures-list.js';
import { registerFinDayClosureDetailRoutes } from './fin-day-closure-detail.js';
import { registerFinDayStatusRoutes } from './fin-day-status.js';
import { registerDriverSalaryMastersListRoutes } from './driver-salary-masters-list.js';
import { registerFinTxnDetailRoutes } from './fin-txn-detail.js';
import { registerFinDayClosureLateEntriesRoutes } from './fin-day-closure-late-entries.js';
import { registerFinDayBookRoutes } from './fin-day-book.js';
import { registerTripsStaticPrecedenceGuards } from './trips-static-precedence.js';
import { registerApiRootRoute } from './api-root.js';
import { registerGstinLookupRoutes } from './gstin-lookup.js';
import { registerSavedTripFiltersListRoute } from './saved-trip-filters-list.js';
import { registerAiSessionsListRoute } from './ai-sessions-list.js';
import { registerRemindersDigestRoute } from './reminders-digest.js';
import { registerDriverSalarySettlementHintRoute } from './driver-salary-settlement-hint.js';
import { registerAiSessionMessagesRoute } from './ai-session-messages.js';

/**
 * TRUKVIA Node · Phase-3 API-route registrar.
 *
 * Every route mounted here MUST be:
 *   - read-only in this gate,
 *   - present in `backend-node/.migration-allowlist` (Class-C cutover-
 *     eligible) or `backend-node/.migration-deferred` (registered but never
 *     cutover-eligible — Gate 7t),
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
  await registerRepairEventsReadRoutes(app, deps);
  await registerMechanicWorkOrdersReadRoutes(app, deps);
  await registerVendorBillsReadRoutes(app, deps);
  await registerSupplierPaymentsListReadRoutes(app, deps);
  await registerMechanicPaymentsListReadRoutes(app, deps);
  await registerDriverPaymentsListReadRoutes(app, deps);
  await registerVendorPaymentsListReadRoutes(app, deps);
  await registerWalletAdjustmentsListReadRoutes(app, deps);
  await registerWalletTransfersListReadRoutes(app, deps);
  await registerWalletRechargesListReadRoutes(app, deps);
  await registerPolicyChangesListReadRoutes(app, deps);
  await registerSupplierVehiclesListReadRoutes(app, deps);
  await registerApprovalsPendingCountRoutes(app, deps);
  await registerApprovalsListRoutes(app, deps);
  await registerFuelVehicleMapsListRoutes(app, deps);
  await registerFilesListRoutes(app, deps);
  await registerFilesUsageListRoutes(app, deps);
  await registerTollImportLookupRoutes(app, deps);
  await registerApprovalDetailRoutes(app, deps);
  await registerFinDayClosuresListRoutes(app, deps);
  await registerFinDayClosureDetailRoutes(app, deps);
  await registerFinDayStatusRoutes(app, deps);
  await registerDriverSalaryMastersListRoutes(app, deps);
  await registerFinTxnDetailRoutes(app, deps);
  await registerFinDayClosureLateEntriesRoutes(app, deps);
  await registerFinDayBookRoutes(app, deps);
  await registerTripsStaticPrecedenceGuards(app);
  await registerApiRootRoute(app);
  await registerGstinLookupRoutes(app, deps);
  await registerSavedTripFiltersListRoute(app, deps);
  await registerAiSessionsListRoute(app, deps);
  await registerRemindersDigestRoute(app, deps);
  await registerDriverSalarySettlementHintRoute(app, deps);
  await registerAiSessionMessagesRoute(app, deps);
}
