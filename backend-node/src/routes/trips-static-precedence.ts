import type { FastifyInstance } from 'fastify';

/**
 * TRUKVIA · Phase-3 · Gate-7t · /api/trips static-route precedence guards.
 *
 * NOT a migration. Python declares these static GET routes before
 * `/trips/{tid}` (backend/routers/trips.py L321, L1839 vs L1929), so it
 * serves them with their own handlers:
 *   GET /api/trips/export                 → trips.py::export_trips
 *   GET /api/trips/recurring-suggestions  → trips.py::recurring_suggestions
 *
 * Without these registrations the Gate-6a parametric `/api/trips/:tid`
 * captured both paths (tid = "export" / "recurring-suggestions") and
 * answered 404 "Trip not found" after an auth + DB lookup. Fastify always
 * prefers a static segment over a parametric one, so registering the two
 * static paths here removes the capture without touching the locked 6a file.
 *
 * The handlers do nothing but hand the request to Fastify's not-found
 * handler — exactly how Node answers any path it does not own. No auth,
 * no DB access, no response of their own. Both paths are listed in
 * `.migration-deferred` (never cutover-eligible); Python stays authoritative.
 */
export async function registerTripsStaticPrecedenceGuards(app: FastifyInstance): Promise<void> {
  // migration-deferred: phase-3-gate-7t (precedence guard, not a migration)
  app.get('/api/trips/export', async (_req, reply) => reply.callNotFound());
  // migration-deferred: phase-3-gate-7t (precedence guard, not a migration)
  app.get('/api/trips/recurring-suggestions', async (_req, reply) => reply.callNotFound());
}
