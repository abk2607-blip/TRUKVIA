/**
 * TRUKVIA · BankStatementPort — pull normalised bank statement rows.
 * Providers: per-bank feed OR aggregator (Setu, Perfios, DigiTap).
 * Feeds into `services_reconciliation.py` equivalent on Node.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export type StatementRowDirection = "credit" | "debit";

export interface NormalisedStatementRow {
  readonly txn_id: string;                 // provider-side unique ref
  readonly txn_date: string;               // YYYY-MM-DD
  readonly value_date?: string;
  readonly description: string;
  readonly amount_paisa: number;
  readonly direction: StatementRowDirection;
  readonly balance_paisa?: number;
  readonly upi_ref?: string;
  readonly cheque_no?: string;
  readonly counterparty_hint?: string;
  readonly external_ref: ExternalRef;
}

export interface BankStatementPort {
  fetch(
    company_bank_account_id: string,
    from: string,
    to: string,
    ctx: IntegrationContext,
  ): Promise<Result<{ rows: readonly NormalisedStatementRow[] }>>;
}

/** Reconciliation guarantee: this port must NEVER back-write to source
 *  documents. Statement rows are stored in a fresh `bank_statement_rows`
 *  collection and matched by the reconciliation service alone. */
