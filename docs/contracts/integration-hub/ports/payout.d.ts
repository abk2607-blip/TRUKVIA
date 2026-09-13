/**
 * TRUKVIA · PayoutPort — outward money movement.
 * Providers: Cashfree, Razorpay/RazorpayX, direct bank NEFT/RTGS APIs.
 *
 * DOCUMENTATION ARTEFACT ONLY. Runtime code MUST NOT live here.
 */
import type {
  IntegrationContext,
  Result,
  ExternalRef,
  IsoDateTime,
  RetryPolicy,
} from "./common";

/** Non-terminal + terminal payout states. Provider-agnostic. */
export type PayoutStatus =
  | "INITIATED"
  | "QUEUED"
  | "PROCESSING"
  | "PAID"
  | "FAILED"
  | "REFUNDED"
  | "REVERSED";

export type PayoutMode = "NEFT" | "IMPS" | "RTGS" | "UPI" | "CARD" | "WALLET";

/**
 * References into TRUKVIA's own party_bank_accounts / company_bank_accounts.
 * Adapters resolve to full account details via internal repo — the
 * caller never handles the account number.
 */
export interface PayoutRequest {
  readonly amount_paisa: number;              // integer paisa, never float rupees
  readonly source_bank_account_id: string;    // company_bank_accounts.id
  readonly destination_bank_account_id: string; // party_bank_accounts.id
  readonly mode: PayoutMode;
  readonly purpose_code: string;              // e.g. "supplier_payment", "driver_payment"
  readonly narration?: string;                // ≤ 20 chars for NEFT/RTGS
}

export interface PayoutInitiated {
  readonly external_ref: ExternalRef;
  readonly status: PayoutStatus;
  readonly initiated_at: IsoDateTime;
  readonly estimated_settlement?: IsoDateTime;
}

export interface PayoutStatusSnapshot {
  readonly external_ref: ExternalRef;
  readonly status: PayoutStatus;
  readonly terminal: boolean;
  readonly settled_at?: IsoDateTime;
  readonly failure_reason?: string;
}

export interface PayoutRefundRequest {
  readonly external_ref: ExternalRef;
  readonly reason: string;
}

/**
 * Webhook envelope — adapter parses provider payload and normalises here.
 * Signature verification is the adapter's responsibility BEFORE this
 * shape is returned.
 */
export interface PayoutWebhookEvent {
  readonly external_ref: ExternalRef;
  readonly status: PayoutStatus;
  readonly received_at: IsoDateTime;
  readonly signature_valid: boolean;
}

export interface PayoutPort {
  /** Idempotent when idempotency_key is preserved across retries. */
  initiate(
    req: PayoutRequest,
    ctx: IntegrationContext,
  ): Promise<Result<PayoutInitiated>>;

  /** Read-only. Safe to poll. */
  status(
    external_ref: ExternalRef,
    ctx: IntegrationContext,
  ): Promise<Result<PayoutStatusSnapshot>>;

  /** Best-effort — some providers may not support post-settlement refund. */
  refund(
    req: PayoutRefundRequest,
    ctx: IntegrationContext,
  ): Promise<Result<PayoutStatusSnapshot>>;

  /**
   * Provider-initiated webhook, normalised. Adapter MUST verify signature
   * before returning; on invalid signature, return { ok:false, ... } with
   * outcome="authorization_failed".
   */
  verifyWebhook(
    raw_body: string,
    signature: string,
    ctx: IntegrationContext,
  ): Promise<Result<PayoutWebhookEvent>>;
}

export const payoutRetryPolicy: RetryPolicy = {
  max_attempts: 3,
  base_delay_ms: 1000,
  max_delay_ms: 15000,
  retryable_outcomes: ["provider_timeout", "provider_down"],
};

/** Payout is Class-A: any accidental duplicate initiation is a critical failure. */
