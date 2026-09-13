/**
 * TRUKVIA · VehicleVerificationPort — VAHAN / RC lookup.
 * Providers: VAHAN direct, Signzy VAHAN, Surepass.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export interface RcVerifyRequest {
  readonly rc_number: string;    // e.g. "AP01AB1234"
}

export interface RcVerifyResult {
  readonly rc_number: string;
  readonly owner_name?: string;
  readonly vehicle_class?: string;
  readonly fuel_type?: string;
  readonly manufactured_year?: number;
  readonly insurance_valid_till?: string;
  readonly pucc_valid_till?: string;
  readonly fitness_valid_till?: string;
  readonly tax_paid_till?: string;
  readonly permit_valid_till?: string;
  readonly cached_from_provider_at: string;
  readonly external_ref: ExternalRef;
}

export interface VehicleVerificationPort {
  verifyRC(req: RcVerifyRequest, ctx: IntegrationContext): Promise<Result<RcVerifyResult>>;
}

/** RC results cached for 30 days keyed by rc_number. */
