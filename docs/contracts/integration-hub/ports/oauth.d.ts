/**
 * TRUKVIA · OAuthPort — social login / third-party OAuth handshake.
 * Providers: Emergent-managed Google (default), direct Google Cloud,
 * Microsoft.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result } from "./common";

export interface OAuthStartRequest {
  readonly redirect_uri: string;
  readonly state?: string;
  readonly scopes?: readonly string[];
}
export interface OAuthStartResult {
  readonly authorize_url: string;
  readonly state: string;
}

export interface OAuthExchangeRequest {
  readonly code: string;
  readonly redirect_uri: string;
}
export interface OAuthProfile {
  readonly provider_user_id: string;
  readonly email: string;
  readonly email_verified: boolean;
  readonly name?: string;
  readonly picture?: string;
}
export interface OAuthTokens {
  readonly access_token: string;
  readonly refresh_token?: string;
  readonly expires_at: string;
}
export interface OAuthExchangeResult {
  readonly profile: OAuthProfile;
  readonly tokens: OAuthTokens;
}

export interface OAuthPort {
  startAuth(req: OAuthStartRequest, ctx: IntegrationContext): Promise<Result<OAuthStartResult>>;
  exchangeCode(req: OAuthExchangeRequest, ctx: IntegrationContext): Promise<Result<OAuthExchangeResult>>;
  refresh(refresh_token: string, ctx: IntegrationContext): Promise<Result<OAuthTokens>>;
}
