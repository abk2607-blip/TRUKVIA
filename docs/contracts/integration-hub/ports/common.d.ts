/**
 * TRUKVIA · Integration Hub — common port types
 * Contract tag: contract@v1.iter150j
 *
 * DOCUMENTATION ARTEFACT ONLY. This file is NOT imported at runtime by
 * any current TRUKVIA code. It exists to freeze the semantic contract
 * every provider adapter (Cashfree, Razorpay, Signzy, VAHAN, ...) must
 * eventually satisfy.
 *
 * RULES for future adapters:
 *   1. Adapters implement these Port interfaces. Nothing else in the
 *      TRUKVIA domain layer imports a provider SDK directly.
 *   2. Every port method receives a fresh IntegrationContext.
 *   3. Every port method returns a discriminated-union Result<T>.
 *   4. Every call is audited to `integration_events` (append-only).
 *   5. Sensitive fields (PAN, account_number, DL, PAN, secrets) never
 *      appear inside logged request/response snapshots.
 */

/** Opaque identifier — provider-side reference echoed back to us. */
export type ExternalRef = string;

/** ISO-8601 UTC timestamp string. */
export type IsoDateTime = string;

/**
 * Every port method receives this. Populated by the hub, never by the
 * caller domain module.
 */
export interface IntegrationContext {
  /** Tenant (company_id in the current data model). */
  readonly tenant_id: string;
  /** Actor's user_id — recorded in the integration audit trail. */
  readonly actor_user_id: string;
  /** Cross-service request/trace id. */
  readonly request_id: string;
  /**
   * Domain-minted idempotency key, forwarded to the provider verbatim
   * where the provider supports it. Required on all non-idempotent verbs.
   */
  readonly idempotency_key: string;
  /**
   * Free-form label describing the caller domain (e.g. "driver_payment
   * payout", "trip vehicle-verify"). Landed as-is in `integration_events`.
   */
  readonly audit_scope: string;
  /**
   * When true, adapter selects sandbox credentials + endpoints. Never
   * bleed into production data.
   */
  readonly sandbox: boolean;
}

/** Terminal outcome classification for a port call. */
export type Outcome =
  | "success"
  | "provider_rejected"
  | "provider_timeout"
  | "provider_down"
  | "invalid_input"
  | "authorization_failed"
  | "conflict"
  | "unknown";

/** Discriminated-union Result — every port method returns this. */
export type Result<T> =
  | { readonly ok: true; readonly data: T; readonly external_ref?: ExternalRef }
  | { readonly ok: false; readonly error: IntegrationError };

export interface IntegrationError {
  readonly outcome: Outcome;
  /** Stable, human-readable code (e.g. "PAYOUT_INSUFFICIENT_BALANCE"). */
  readonly code: string;
  /** Non-sensitive message; MUST NOT contain PAN / account numbers. */
  readonly message: string;
  /** Provider-side reference if available. */
  readonly external_ref?: ExternalRef;
  /** True when retry with the same idempotency key may succeed. */
  readonly retryable: boolean;
}

/** Retry policy declared by each port, honoured by the hub. */
export interface RetryPolicy {
  readonly max_attempts: number;
  readonly base_delay_ms: number;
  readonly max_delay_ms: number;
  readonly retryable_outcomes: readonly Outcome[];
}

/** Circuit-breaker configuration per (port, provider) binding. */
export interface CircuitConfig {
  readonly failure_threshold: number;
  readonly cooldown_ms: number;
  readonly half_open_probe_count: number;
}

/**
 * Audit record shape written to `integration_events`. Populated by the
 * hub, adapters cannot forge or omit fields.
 */
export interface IntegrationEvent {
  readonly id: string;
  readonly tenant_id: string;
  readonly provider: string;
  readonly port: string;
  readonly verb: string;
  readonly request_id: string;
  readonly idempotency_key: string;
  readonly started_at: IsoDateTime;
  readonly finished_at: IsoDateTime;
  readonly latency_ms: number;
  readonly outcome: Outcome;
  readonly external_ref?: ExternalRef;
  readonly redacted_request: Readonly<Record<string, unknown>>;
  readonly redacted_response: Readonly<Record<string, unknown>>;
}
