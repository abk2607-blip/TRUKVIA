/**
 * TRUKVIA · GstPort — GSTR filing / status / 2A download.
 * Providers: ClearTax / IRIS / GSTN direct.
 * The current codebase ONLY produces GSTR JSON files (routers/gst.py);
 * no live filing exists. This port is the future contract.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export type GstrPeriod = string;   // "MMYYYY" e.g. "022026"

export interface GstrInvoiceRow {
  readonly gstin: string;
  readonly invoice_no: string;
  readonly invoice_date: string;
  readonly taxable_value_paisa: number;
  readonly cgst_paisa: number;
  readonly sgst_paisa: number;
  readonly igst_paisa: number;
  readonly cess_paisa: number;
  readonly place_of_supply: string;
  readonly reverse_charge: boolean;
  readonly invoice_type: "B2B" | "B2CL" | "B2CS" | "EXP" | "CDNR" | "CDNUR";
}

export interface FileGstr1Request {
  readonly period: GstrPeriod;
  readonly invoices: readonly GstrInvoiceRow[];
}
export interface FileGstr1Result {
  readonly external_ref: ExternalRef;
  readonly ack_id?: string;
  readonly filed_at: string;
}

export type GstrFilingStatus =
  | "NOT_FILED"
  | "SUBMITTED"
  | "FILED"
  | "ERROR"
  | "PROCESSING";

export interface Gstr2ARow {
  readonly counterparty_gstin: string;
  readonly invoice_no: string;
  readonly invoice_date: string;
  readonly taxable_value_paisa: number;
  readonly cgst_paisa: number;
  readonly sgst_paisa: number;
  readonly igst_paisa: number;
  readonly cess_paisa: number;
}

export interface GstPort {
  fileGSTR1(req: FileGstr1Request, ctx: IntegrationContext): Promise<Result<FileGstr1Result>>;
  fetchStatus(period: GstrPeriod, ctx: IntegrationContext): Promise<Result<{ status: GstrFilingStatus; last_updated: string }>>;
  download2A(period: GstrPeriod, ctx: IntegrationContext): Promise<Result<{ rows: readonly Gstr2ARow[] }>>;
}
