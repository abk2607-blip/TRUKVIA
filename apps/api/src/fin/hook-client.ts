/**
 * Client for the INTERNAL Python projection hook (backend/routers/internal_fin.py).
 *
 * Why this exists: the TypeScript port in ./projection.ts is a second
 * implementation of ledger maths, which can drift from Python's. When this
 * client is configured, the projection is delegated to Python instead, so one
 * implementation owns the ledger again. The port stays as the local-development
 * fallback and as the seed for the finance slice.
 *
 * Configuration (both required, else the port is used):
 *   TRUKVIA_FIN_HOOK_URL    e.g. http://127.0.0.1:8001/internal/fin/reproject
 *   TRUKVIA_INTERNAL_TOKEN  the shared secret, >= 32 chars
 *
 * The token is sent only in the X-Internal-Token header. It is never logged,
 * and the URL is only ever reported without credentials.
 *
 * Failure semantics match Python's hook: a projection failure NEVER fails the
 * caller's write. A transport failure is reported as ok=false so the caller can
 * fall back, exactly as a hook failure would be.
 */
export interface ProjectionResult {
  ok: boolean;
  deleted?: number;
  written?: number;
  error?: string;
}

export type HookSource = 'vendor_bill' | 'vendor_payment';

const TIMEOUT_MS = Number(process.env.TRUKVIA_FIN_HOOK_TIMEOUT_MS ?? 10_000);

export function hookConfigured(): boolean {
  const url = (process.env.TRUKVIA_FIN_HOOK_URL ?? '').trim();
  const token = (process.env.TRUKVIA_INTERNAL_TOKEN ?? '').trim();
  return url.length > 0 && token.length >= 32;
}

export async function callPythonHook(
  uid: string,
  cid: string,
  sourceType: HookSource,
  sourceId: string,
): Promise<ProjectionResult> {
  const url = (process.env.TRUKVIA_FIN_HOOK_URL ?? '').trim();
  const token = (process.env.TRUKVIA_INTERNAL_TOKEN ?? '').trim();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-internal-token': token,
      },
      body: JSON.stringify({
        user_id: uid,
        company_id: cid,
        source_type: sourceType,
        source_id: sourceId,
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      // Never include the response body verbatim: keep credentials and internal
      // detail out of anything a caller might log.
      return { ok: false, error: `internal hook returned ${res.status}` };
    }
    const body = (await res.json()) as ProjectionResult;
    return { ok: Boolean(body.ok), deleted: body.deleted, written: body.written, error: body.error };
  } catch (err) {
    const name = err instanceof Error ? err.name : 'Error';
    return { ok: false, error: `internal hook unreachable (${name})` };
  } finally {
    clearTimeout(timer);
  }
}
