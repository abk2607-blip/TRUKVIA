/**
 * TRUKVIA · EmailPort — transactional email.
 * Providers: Resend (via Emergent proxy today), SES, Postmark.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export interface EmailSendRequest {
  readonly to: string | readonly string[];
  readonly cc?: readonly string[];
  readonly bcc?: readonly string[];
  readonly subject: string;
  readonly template_id: string;
  readonly template_vars: Readonly<Record<string, string | number | boolean>>;
  readonly reply_to?: string;
  readonly attachments?: readonly {
    readonly filename: string;
    readonly content_base64: string;
    readonly content_type: string;
  }[];
}

export interface EmailSendResult {
  readonly external_ref: ExternalRef;
  readonly accepted_at: string;
}

export type EmailWebhookEventKind =
  | "delivered"
  | "bounced"
  | "complained"
  | "opened"
  | "clicked";

export interface EmailWebhookEvent {
  readonly external_ref: ExternalRef;
  readonly kind: EmailWebhookEventKind;
  readonly at: string;
}

export interface EmailPort {
  send(req: EmailSendRequest, ctx: IntegrationContext): Promise<Result<EmailSendResult>>;
  verifyWebhook(
    raw_body: string,
    signature: string,
    ctx: IntegrationContext,
  ): Promise<Result<EmailWebhookEvent>>;
}
