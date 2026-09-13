/**
 * TRUKVIA · InsurancePort — motor insurance policy validity.
 * Providers: IIB (Insurance Information Bureau), individual insurer APIs.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export interface PolicyVerifyRequest {
  readonly policy_no: string;
  readonly rc_number?: string;
}

export interface PolicyVerifyResult {
  readonly valid: boolean;
  readonly insurer?: string;
  readonly policy_type?: "Comprehensive" | "TP" | "OD";
  readonly idv_paisa?: number;
  readonly expiry?: string;               // YYYY-MM-DD
  readonly external_ref: ExternalRef;
}

export interface InsurancePort {
  verifyPolicy(req: PolicyVerifyRequest, ctx: IntegrationContext): Promise<Result<PolicyVerifyResult>>;
}
