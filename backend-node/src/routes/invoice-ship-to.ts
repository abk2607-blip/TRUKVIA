import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { authenticate } from '../auth.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6e · Invoice Ship-To read-only shadow.
 *
 *   GET /api/invoices/{iid}/ship-to
 *
 * Faithful shadow of:
 *   backend/routers/invoices.py::get_invoice_ship_to
 * with an inline TypeScript port of ONLY the `resolve_invoice_ship_to`
 * call path from `backend/ship_to_resolver.py`.
 *
 * STRICTLY READ-ONLY. Node performs ZERO writes on ANY business
 * collection. The Python handler is itself pure-read (no
 * `_recompute_invoice`, no `_backfill_to_default`, no
 * `_apply_effective_balance`), so there is NO Class-B write to shadow.
 *
 * Important discovery finding — mirrored EXACTLY:
 *   The Python route does NOT parse or consult `X-Company-Id`.
 *   The Node shadow MUST NOT invent company filtering either. Invoice /
 *   customer / trip lookups are scoped by `user_id` only.
 *
 * Resolver port scope — ONLY the helpers reached by
 *   `resolve_invoice_ship_to(customer, ordered_trips)`
 * are ported. The unused state-derivation helpers (
 *   `derive_state_from_gstin`, `apply_gstin_state_derivation`,
 *   `_gstin_state_code`
 * ) are intentionally OMITTED — they are not on the read call path and
 * would introduce a spurious `services` module dependency.
 */

// ── Regex parity ──────────────────────────────────────────────────────
// Mirrors Python module constants verbatim.
const TOKEN_MIN = 4;
const PIN_RE = /\b(\d{6})\b/;
const TOKEN_SPLIT_RE = /[^0-9a-z\u0900-\u097f]+/;
const GSTIN_PREFIX_RE = /^\s*(?:gstin|gstn|gst)\b[\s:.-]*/i;

// ── Pure resolver helpers (ported from ship_to_resolver.py) ───────────

/**
 * Return a cleaned GSTIN string. Blank input → empty string.
 * Mirrors Python `normalize_gstin`.
 */
function normalizeGstin(value: unknown): string {
  if (!value) return '';
  let s = String(value)
    .replace(/\t/g, ' ')
    .replace(/\r/g, ' ')
    .replace(/\n/g, ' ');
  s = s.trim();
  if (!s) return '';
  s = s.replace(GSTIN_PREFIX_RE, '');
  s = s.replace(/\s+/g, '').trim();
  return s.toUpperCase();
}

/**
 * Lower-cased, whitespace-collapsed, tab/newline-safe.
 * Mirrors Python `_norm` — `str(s).strip().casefold()` then `\s+` → ' '.
 * NOTE: JS `.toLowerCase()` deviates from Python `.casefold()` for a
 * handful of non-ASCII characters (e.g. German ß). Not relevant for
 * TRUKVIA fixtures (ASCII + Devanagari).
 */
function norm(s: unknown): string {
  if (s === null || s === undefined || s === '') return '';
  return String(s).trim().toLowerCase().replace(/\s+/g, ' ');
}

function extractPin(s: unknown): string | null {
  if (s === null || s === undefined) return null;
  const m = PIN_RE.exec(String(s));
  return m && m[1] !== undefined ? m[1] : null;
}

function siteMatchesTrip(
  site: Record<string, unknown>,
  trip: Record<string, unknown>,
): boolean {
  const toRaw = (trip['to_location'] as string | undefined) ?? '';
  const toN = norm(toRaw);
  if (!toN) return false;

  // R1 · normalized name equality.
  const rawName =
    (site['site_name'] as string | undefined) ??
    (site['name'] as string | undefined) ??
    '';
  const nameN = norm(rawName);
  if (nameN && nameN === toN) return true;

  // R2 · pincode match (dedicated field or embedded in address).
  const tripPin = extractPin(toRaw);
  if (tripPin) {
    const sitePin = norm((site['pincode'] as string | undefined) ?? '');
    const addrPin = extractPin((site['address'] as string | undefined) ?? '');
    if ((sitePin && sitePin === tripPin) || (addrPin && addrPin === tripPin)) {
      return true;
    }
  }

  // R3 · to_location appears as a whole token inside the site address.
  const addrN = norm((site['address'] as string | undefined) ?? '');
  if (addrN && toN.length >= TOKEN_MIN) {
    const tokens = addrN.split(TOKEN_SPLIT_RE).filter((t) => t.length > 0);
    if (tokens.includes(toN)) return true;
  }
  return false;
}

/**
 * Return the single evidence-matched site, or `null` if 0 or >1 matches.
 * Mirrors Python `infer_site_for_trip`.
 */
function inferSiteForTrip(
  trip: Record<string, unknown>,
  sites: Record<string, unknown>[],
): Record<string, unknown> | null {
  const matches = (sites || []).filter((s) => siteMatchesTrip(s, trip));
  return matches.length === 1 && matches[0] !== undefined ? matches[0] : null;
}

function displayFromSite(site: Record<string, unknown>): Record<string, unknown> {
  const strp = (v: unknown): string =>
    typeof v === 'string' ? v.trim() : v ? String(v).trim() : '';
  return {
    site_name: strp(site['site_name'] ?? site['name'] ?? ''),
    address: strp(site['address']),
    // Render-time GSTIN cleanup — never mutates the stored DB value.
    gstin: normalizeGstin(site['gstin']),
    state: strp(site['state']),
    state_code: strp(site['state_code']),
    pincode: strp(site['pincode']),
    phone: strp(site['phone']),
    contact_person: strp(site['contact_person']),
    linked: true,
  };
}

function displayFallback(trip: Record<string, unknown>): Record<string, unknown> {
  const strp = (v: unknown): string =>
    typeof v === 'string' ? v.trim() : v ? String(v).trim() : '';
  return {
    site_name: strp(trip['to_location']),
    address: '',
    gstin: '',
    state: '',
    state_code: '',
    pincode: '',
    phone: '',
    contact_person: '',
    linked: false,
  };
}

/**
 * Identity tuple — trips with equal tuples share the same Ship-To.
 * Python emits a tuple; the HTTP route serializes it as a JSON array via
 * `list(...)`. This TS port returns the array directly.
 *
 * Shape:
 *   ['site_id', <sid>]                                   (linked to a site)
 *   ['fb', normName, normAddr, gstinUpper]               (unlinked fallback)
 */
function identity(
  trip: Record<string, unknown>,
  resolved: Record<string, unknown>,
  inferredSid: string | null,
): (string)[] {
  const rawSid = trip['ship_site_id'];
  const explicitSid = typeof rawSid === 'string' ? rawSid.trim() : '';
  const sid = explicitSid || inferredSid || '';
  if (sid) return ['site_id', sid];
  const gstin =
    typeof resolved['gstin'] === 'string' ? (resolved['gstin'] as string) : '';
  return [
    'fb',
    norm(resolved['site_name']),
    norm(resolved['address']),
    gstin.trim().toUpperCase(),
  ];
}

interface PerTripEntry {
  resolved: Record<string, unknown>;
  site_id: string | null;
  inferred: boolean;
  identity: string[];
}

interface ShipToResult {
  mixed: boolean;
  common: Record<string, unknown> | null;
  per_trip: PerTripEntry[];
}

/**
 * Resolve the Ship-To header for an invoice's trip list.
 * Faithful port of `resolve_invoice_ship_to` — same call graph, same
 * ordering guarantees, same 0/1/many inference semantics, same
 * mixed/common determination.
 */
function resolveInvoiceShipTo(
  customer: Record<string, unknown>,
  trips: Record<string, unknown>[],
): ShipToResult {
  const rawSites = customer ? (customer['ship_sites'] as unknown) : null;
  const sites: Record<string, unknown>[] = Array.isArray(rawSites)
    ? (rawSites as Record<string, unknown>[])
    : [];
  const sitesById = new Map<string, Record<string, unknown>>();
  for (const s of sites) {
    const id = s['id'];
    if (typeof id === 'string' && id.length > 0) sitesById.set(id, s);
  }
  const perTrip: PerTripEntry[] = [];
  for (const t of trips || []) {
    const rawSid = t['ship_site_id'];
    const explicitSid = typeof rawSid === 'string' ? rawSid.trim() : '';
    let site: Record<string, unknown> | null = explicitSid
      ? sitesById.get(explicitSid) ?? null
      : null;
    let inferredSid: string | null = null;
    if (!site && !explicitSid) {
      const candidate = inferSiteForTrip(t, sites);
      if (candidate) {
        site = candidate;
        const cid = candidate['id'];
        inferredSid = typeof cid === 'string' && cid.length > 0 ? cid : null;
      }
    }
    const resolved = site ? displayFromSite(site) : displayFallback(t);
    perTrip.push({
      resolved,
      site_id: explicitSid || inferredSid || null,
      inferred: Boolean(inferredSid && !explicitSid),
      identity: identity(t, resolved, inferredSid),
    });
  }
  // Python: `identities = {p["identity"] for p in per_trip}` — a set of
  // tuples. In JS we compare via JSON serialization of the array form.
  const identitySet = new Set<string>();
  for (const p of perTrip) identitySet.add(JSON.stringify(p.identity));
  const mixed = identitySet.size > 1;
  const first = perTrip[0];
  const common = perTrip.length > 0 && !mixed && first ? first.resolved : null;
  return { mixed, common, per_trip: perTrip };
}

// ── Handler registrar ─────────────────────────────────────────────────
export async function registerInvoiceShipToRoute(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/invoices/{iid}/ship-to ─────────────────────────────────
  //
  // migration-allowlisted: phase-3-gate-6e (read-only)
  //
  // Faithful shadow of `get_invoice_ship_to`:
  //   * user_id-scoped invoice/customer/trip lookups.
  //   * X-Company-Id NOT consulted (mirrors Python).
  //   * `invoice.trip_ids` insertion order preserved via id-keyed lookup.
  //   * Missing customer becomes `{}` (empty-object semantics), not null.
  //   * Empty/absent trip_ids → skip the trips query entirely.
  //   * Identity tuple → JSON array (matches Python `list(tuple)`).
  app.get<{ Params: { iid: string } }>(
    '/api/invoices/:iid/ship-to',
    async (req, reply) => {
      let userId: string;
      try {
        userId = (await authenticate(req, db)).user_id;
      } catch (err) {
        if (err instanceof HttpError) {
          reply.code(err.status);
          return { detail: err.detail };
        }
        throw err;
      }

      const iid = req.params.iid;

      const inv = (await db.collection('invoices').findOne(
        { id: iid, user_id: userId },
        { projection: { _id: 0, user_id: 0 } },
      )) as Record<string, unknown> | null;

      if (!inv) {
        reply.code(404);
        return { detail: 'Invoice not found' };
      }

      const customerId = inv['customer_id'];
      const customer =
        typeof customerId === 'string'
          ? ((await db.collection('customers').findOne(
              { id: customerId, user_id: userId },
              { projection: { _id: 0, user_id: 0 } },
            )) as Record<string, unknown> | null)
          : null;
      // Python: `... or {}` — empty-object fallback (NOT null/undefined).
      const customerDoc: Record<string, unknown> = customer ?? {};

      const rawTripIds = inv['trip_ids'];
      const tripIds: string[] = Array.isArray(rawTripIds)
        ? (rawTripIds as unknown[]).filter(
            (t): t is string => typeof t === 'string',
          )
        : [];

      // Python: `... if trip_ids else []` — skip the query entirely when empty.
      let trips: Record<string, unknown>[] = [];
      if (tripIds.length > 0) {
        trips = (await db
          .collection('trips')
          .find(
            { id: { $in: tripIds }, user_id: userId },
            { projection: { _id: 0, user_id: 0 } },
          )
          .limit(1000)
          .toArray()) as Record<string, unknown>[];
      }

      // Preserve `invoice.trip_ids` order (Python:
      // `ordered_trips = [trip_by_id[t] for t in trip_ids if t in trip_by_id]`).
      const tripById = new Map<string, Record<string, unknown>>();
      for (const t of trips) {
        const tid = t['id'];
        if (typeof tid === 'string') tripById.set(tid, t);
      }
      const orderedTrips: Record<string, unknown>[] = [];
      for (const t of tripIds) {
        const doc = tripById.get(t);
        if (doc) orderedTrips.push(doc);
      }

      const result = resolveInvoiceShipTo(customerDoc, orderedTrips);
      // Identity already an array (Python: `list(tuple)`).
      return result;
    },
  );
}
