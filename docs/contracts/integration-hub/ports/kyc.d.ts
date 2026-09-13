/**
 * TRUKVIA · KycPort — PAN / DL / GSTIN identity verification.
 * Providers: Signzy, IDfy, Surepass, DigiLocker (per verb availability).
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export interface PanVerifyRequest {
  readonly pan: string;                // full PAN — never logged
  readonly name?: string;
}
export interface PanVerifyResult {
  readonly verified: boolean;
  readonly canonical_name?: string;
  readonly external_ref: ExternalRef;
}

export interface DlVerifyRequest {
  readonly dl_number: string;          // never logged
  readonly dob: string;                // YYYY-MM-DD
}
export interface DlVerifyResult {
  readonly verified: boolean;
  readonly holder_name?: string;
  readonly valid_till?: string;        // YYYY-MM-DD
  readonly vehicle_classes?: readonly string[];
  readonly external_ref: ExternalRef;
}

export interface GstinVerifyRequest {
  readonly gstin: string;
}
export interface GstinVerifyResult {
  readonly verified: boolean;
  readonly legal_name?: string;
  readonly trade_name?: string;
  readonly registration_status?: "Active" | "Cancelled" | "Suspended";
  readonly external_ref: ExternalRef;
}

export interface KycPort {
  verifyPan(req: PanVerifyRequest, ctx: IntegrationContext): Promise<Result<PanVerifyResult>>;
  verifyDL(req: DlVerifyRequest, ctx: IntegrationContext): Promise<Result<DlVerifyResult>>;
  verifyGSTIN(req: GstinVerifyRequest, ctx: IntegrationContext): Promise<Result<GstinVerifyResult>>;
}

/** All KYC results are cached for 30 days keyed by verified value. */
