/**
 * TRUKVIA · FastagPort — live FASTag balance / statement / blacklist.
 * Providers: HDFC / ICICI / SBI / Paytm / IHMCL (per-issuer).
 * The current codebase supports CSV import only (routers/toll_import.py);
 * live queries are the future contract.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export interface FastagBalanceResult {
  readonly tag_id: string;
  readonly balance_paisa: number;
  readonly last_recharge_at?: string;
  readonly external_ref: ExternalRef;
}

export interface FastagStatementRow {
  readonly txn_id: string;
  readonly plaza_code: string;
  readonly plaza_name?: string;
  readonly amount_paisa: number;
  readonly txn_time: string;                // ISO-8601
  readonly vehicle_class?: string;
  readonly lane_number?: string;
}

export interface FastagBlacklistResult {
  readonly tag_id: string;
  readonly blacklisted: boolean;
  readonly reason?: string;
  readonly since?: string;
  readonly external_ref: ExternalRef;
}

export interface FastagPort {
  balance(tag_id: string, ctx: IntegrationContext): Promise<Result<FastagBalanceResult>>;
  statement(tag_id: string, from: string, to: string, ctx: IntegrationContext): Promise<Result<{ rows: readonly FastagStatementRow[] }>>;
  blacklist(tag_id: string, ctx: IntegrationContext): Promise<Result<FastagBlacklistResult>>;
}
