/**
 * TRUKVIA Node · Phase-3 · shared HTTP error surface.
 *
 * These classes carry the exact `status` + `detail` string that the frontend
 * interceptor + toasts already string-match against — see
 * `docs/contracts/error-string-parity.md`. NEW error literals require a
 * Phase-3 gate; do NOT invent strings here.
 */

export class HttpError extends Error {
  public readonly status: number;
  public readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'HttpError';
    this.status = status;
    this.detail = detail;
  }
}
