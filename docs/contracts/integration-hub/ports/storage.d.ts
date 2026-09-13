/**
 * TRUKVIA · StoragePort — S3-compatible object storage.
 * Providers: Emergent Object Storage (default today, via boto3),
 * AWS S3, Cloudflare R2, GCS in S3-compat mode.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result } from "./common";

export interface PutObjectRequest {
  readonly key: string;
  readonly body: Uint8Array | Buffer;
  readonly content_type: string;
  readonly metadata?: Readonly<Record<string, string>>;
}
export interface PutObjectResult {
  readonly key: string;
  readonly url: string;
  readonly etag: string;
}

export interface SignedUrlRequest {
  readonly key: string;
  readonly expires_seconds: number;
  readonly download_filename?: string;
}
export interface SignedUrlResult {
  readonly url: string;
  readonly expires_at: string;
}

export interface StoragePort {
  putObject(req: PutObjectRequest, ctx: IntegrationContext): Promise<Result<PutObjectResult>>;
  getSignedUrl(req: SignedUrlRequest, ctx: IntegrationContext): Promise<Result<SignedUrlResult>>;
  deleteObject(key: string, ctx: IntegrationContext): Promise<Result<{ deleted: true }>>;
}

/** Provider-specific URL patterns are hidden inside adapters. Domain
 *  code MUST NOT construct or parse S3 URLs directly. */
