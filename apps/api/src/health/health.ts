/**
 * Infrastructure-only health checks for the Finance writer (`apps/api`).
 *
 * Ported semantics, not a new contract: this mirrors `backend-node/src/health.ts`
 *   GET /health/live   — process is up (no dependency check)
 *   GET /health/ready  — dependencies (Mongo) are reachable; 503 when they are not
 *
 * Two deliberate differences from backend-node, both because this is a
 * different application:
 *   * `service` names THIS application. Claiming to be `trukvia-backend-node`
 *     would make the two processes indistinguishable to whatever probes them.
 *   * There is no `routes` check. backend-node's readiness also requires every
 *     frozen-allowlist route to be registered; `apps/api` has no allowlist, and
 *     inventing one here would be a new contract rather than a port.
 *
 * Nothing here reads or writes business data: readiness is `{ ping: 1 }` on the
 * database the application already holds. The response carries no database
 * name, no connection string, no credential, no token and no error text — a
 * failed ping is reported as the word `unavailable` and nothing more, because a
 * health endpoint is the wrong place to learn what went wrong.
 */

export const SERVICE_NAME = 'trukvia-apps-api';

export interface LiveResponse {
  status: 'ok';
  service: typeof SERVICE_NAME;
  uptime_s: number;
}

export interface ReadyResponse {
  status: 'ok' | 'degraded';
  service: typeof SERVICE_NAME;
  checks: {
    mongo: 'ok' | 'unavailable' | 'not_configured';
  };
}

/** The one capability readiness needs, so a test does not need a real driver. */
export interface Pingable {
  command(command: Record<string, unknown>): Promise<unknown>;
}

export function liveReport(uptimeSeconds: number = process.uptime()): LiveResponse {
  return {
    status: 'ok',
    service: SERVICE_NAME,
    uptime_s: Math.round(uptimeSeconds),
  };
}

/**
 * Returns the HTTP status alongside the body: readiness is the one endpoint
 * whose status code carries information, and a caller that forgets to apply it
 * turns an outage into a silent 200.
 */
export async function readyReport(
  db: Pingable | null,
): Promise<{ status: number; body: ReadyResponse }> {
  let mongo: ReadyResponse['checks']['mongo'];
  if (!db) {
    mongo = 'not_configured';
  } else {
    try {
      const res = (await db.command({ ping: 1 })) as { ok?: unknown } | null;
      mongo = res?.ok === 1 ? 'ok' : 'unavailable';
    } catch {
      // Swallowed on purpose: the reason belongs in the process log, not in a
      // response body that anything on the loopback interface can read.
      mongo = 'unavailable';
    }
  }
  const status: ReadyResponse['status'] = mongo === 'ok' ? 'ok' : 'degraded';
  return {
    status: status === 'ok' ? 200 : 503,
    body: { status, service: SERVICE_NAME, checks: { mongo } },
  };
}
