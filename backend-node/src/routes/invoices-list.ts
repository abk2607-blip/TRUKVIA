import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { z } from 'zod';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6d · Invoice list read-only shadows.
 *
 *   GET /api/invoices
 *   GET /api/invoices/overdue
 *
 * Faithful shadows of:
 *   backend/routers/invoices.py::list_invoices          (137–149)
 *   backend/routers/invoices.py::list_overdue_invoices  (151–187)
 *
 * STRICTLY READ-ONLY. Node performs ZERO writes on ANY business
 * collection.
 *
 * Gate-6d Class-B observation — Python `list_invoices` invokes
 * `company._backfill_to_default(user_id)` on read, which fan-outs
 * `update_many` across ten collections (trips, invoices, files,
 * audit_logs, fuel, customers, vehicles, drivers, products, parties)
 * to assign a default company_id to any legacy doc missing one. This
 * is a bounded non-financial legacy-migration write. Node
 * INTENTIONALLY DOES NOT PORT this write. Parity fixtures pre-assign
 * `company_id` on every seeded row so Python's backfill matches zero
 * documents and the observation becomes a no-op. Identical protocol
 * to Gate-6b list_trips.
 *
 * Gate-6d Class-C observation — `list_overdue_invoices` performs zero
 * writes on any collection. Its call chain (`_active_company_id`,
 * `_apply_effective_balance`, customers.find + in-memory merge, and
 * `age_days` arithmetic) is a pure read.
 */

// ── Numeric parity helper ─────────────────────────────────────────────
const round2 = (x: number): number =>
  Math.round((x + Number.EPSILON) * 100) / 100;

// ── UTC date helpers (mirror `now_utc().date()` — server-clock date) ──
function todayUtcMs(): number {
  const d = new Date();
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}
function isoFromUtcMs(ms: number): string {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = (d.getUTCMonth() + 1).toString().padStart(2, '0');
  const day = d.getUTCDate().toString().padStart(2, '0');
  return `${y}-${m}-${day}`;
}
function cutoffIsoFromDays(days: number): string {
  return isoFromUtcMs(todayUtcMs() - days * 86_400_000);
}

// Strict ISO YYYY-MM-DD validator — mirrors Python's `datetime.fromisoformat`
// on date-only inputs (rejects out-of-range month / day / non-existent
// dates such as "2020-13-45" or "2020-02-31").
function isValidIsoDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const y = Number(s.slice(0, 4));
  const m = Number(s.slice(5, 7));
  const d = Number(s.slice(8, 10));
  if (m < 1 || m > 12 || d < 1 || d > 31) return false;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === m - 1 &&
    dt.getUTCDate() === d
  );
}

// ── Overdue query schema (Python: `days: int = 30`) ───────────────────
// Missing → 30. Non-int → 422 (FastAPI parity — 422 fires before auth).
const OverdueQuerySchema = z.object({
  days: z.coerce.number().int().default(30),
});

// ── Batched effective_* enrichment (services._apply_effective_balance)
// Mirrors Python filter:
//   {"user_id": uid, "invoice_id": {"$in": <ids>}, "status": "issued"}
// plus optional {"company_id": <active_cid>} when non-empty.
// On any error the try/except in Python OMITS the additive keys — Node
// mirrors OMIT-vs-null semantics.
async function batchedEffective(
  db: Db,
  invoices: Record<string, unknown>[],
  userId: string,
  activeCid: string,
): Promise<void> {
  if (!invoices.length) return;
  const invIds: string[] = [];
  for (const inv of invoices) {
    const id = inv['id'];
    if (typeof id === 'string') invIds.push(id);
  }
  if (!invIds.length) return;

  const filter: Record<string, unknown> = {
    user_id: userId,
    invoice_id: { $in: invIds },
    status: 'issued',
  };
  if (activeCid) filter['company_id'] = activeCid;

  try {
    const notes = await db
      .collection('credit_debit_notes')
      .find(filter, {
        projection: { _id: 0, invoice_id: 1, kind: 1, total_amount: 1 },
      })
      .limit(5000)
      .toArray();
    const byInv = new Map<string, { c: number; d: number }>();
    for (const n of notes) {
      const iid = (n as Record<string, unknown>)['invoice_id'];
      if (typeof iid !== 'string') continue;
      if (!byInv.has(iid)) byInv.set(iid, { c: 0, d: 0 });
      const b = byInv.get(iid)!;
      const amt = Number((n as Record<string, unknown>)['total_amount'] ?? 0) || 0;
      const kind = (n as Record<string, unknown>)['kind'];
      if (kind === 'credit') b.c += amt;
      else if (kind === 'debit') b.d += amt;
    }
    for (const inv of invoices) {
      const id = inv['id'] as string | undefined;
      const b = (id && byInv.get(id)) || { c: 0, d: 0 };
      const rawTotal = Number(inv['total_amount'] ?? 0) || 0;
      const amountPaid = Number(inv['amount_paid'] ?? 0) || 0;
      const effT = round2(rawTotal - b.c + b.d);
      const effB = round2(effT - amountPaid);
      inv['effective_total_amount'] = effT;
      inv['effective_balance_due'] = effB;
      inv['credits_total'] = round2(b.c);
      inv['debits_total'] = round2(b.d);
    }
  } catch {
    // Mirror Python's `try/except: pass` — OMIT additive keys.
  }
}

// ── Handlers registrar ────────────────────────────────────────────────
export async function registerInvoicesListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/invoices/overdue (static — register before ambiguous
  //    params for defensive routing ordering; Fastify's find-my-way
  //    already prefers static routes but explicit ordering aids
  //    readability). ────────────────────────────────────────────────
  //
  // migration-allowlisted: phase-3-gate-6d (read-only)
  app.get('/api/invoices/overdue', async (req, reply) => {
    // 1. `days` validation — 422 BEFORE auth (FastAPI parity).
    const parsed = OverdueQuerySchema.safeParse(req.query);
    if (!parsed.success) {
      reply.code(422);
      return {
        detail: parsed.error.issues.map((i) => ({
          loc: ['query', ...i.path.map(String)],
          msg: i.message,
          type: i.code,
        })),
      };
    }

    // 2. Auth (401).
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

    const days = parsed.data.days;
    const cid = await activeCompanyId(req, userId, db);
    const cutoff = cutoffIsoFromDays(days);

    let docs = (await db
      .collection('invoices')
      .find(
        {
          user_id: userId,
          company_id: cid,
          balance_due: { $gt: 0.01 },
          invoice_date: { $lte: cutoff },
        },
        { projection: { _id: 0, user_id: 0 } },
      )
      .sort([['invoice_date', 1]])
      .limit(500)
      .toArray()) as Record<string, unknown>[];

    // 3. Batched effective_* enrichment.
    await batchedEffective(db, docs, userId, cid);

    // 4. Post-enrich prune: drop rows whose CN has fully offset balance.
    //    Python uses `float(d.get("effective_balance_due",
    //    d.get("balance_due", 0))) > 0.01`.
    docs = docs.filter((d) => {
      const eb =
        d['effective_balance_due'] !== undefined
          ? d['effective_balance_due']
          : d['balance_due'] ?? 0;
      return Number(eb) > 0.01;
    });

    // 5. Customer merge — batch load, in-memory join.
    const customers = (await db
      .collection('customers')
      .find({ user_id: userId, company_id: cid }, { projection: { _id: 0 } })
      .limit(2000)
      .toArray()) as Record<string, unknown>[];
    const cmap = new Map<string, Record<string, unknown>>();
    for (const c of customers) {
      const id = c['id'];
      if (typeof id === 'string') cmap.set(id, c);
    }

    const todayMs = todayUtcMs();
    for (const d of docs) {
      const cid2 = d['customer_id'];
      const c =
        (typeof cid2 === 'string' && cmap.get(cid2)) || ({} as Record<string, unknown>);
      let ageDays = 0;
      const invd = d['invoice_date'];
      if (typeof invd === 'string' && isValidIsoDate(invd)) {
        const y = Number(invd.slice(0, 4));
        const mo = Number(invd.slice(5, 7));
        const day = Number(invd.slice(8, 10));
        const invMs = Date.UTC(y, mo - 1, day);
        ageDays = Math.floor((todayMs - invMs) / 86_400_000);
      }
      d['customer_name'] = (c['name'] as string | undefined) ?? '';
      d['customer_phone'] = (c['phone'] as string | undefined) ?? '';
      d['customer_email'] = (c['email'] as string | undefined) ?? '';
      d['age_days'] = ageDays;
    }
    return docs;
  });

  // ── GET /api/invoices  ───────────────────────────────────────────────
  //
  // migration-allowlisted: phase-3-gate-6d (read-only)
  //
  // NOTE (Class-B): Python calls `_backfill_to_default(user_id)` first,
  // fan-outing `update_many` over trips/invoices/files/audit_logs/fuel/
  // customers/vehicles/drivers/products/parties for rows missing
  // `company_id`. Node intentionally SKIPS this write. Fixtures with
  // pre-assigned `company_id` on every row make Python's write a no-op.
  app.get('/api/invoices', async (req, reply) => {
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

    // NOTE (Class-B): Python calls `_backfill_to_default(user_id)` here.
    // Node intentionally does NOT.

    const cid = await activeCompanyId(req, userId, db);

    const docs = await db
      .collection('invoices')
      .find(
        { user_id: userId, company_id: cid },
        { projection: { _id: 0, user_id: 0 } },
      )
      .sort([['created_at', -1]])
      .limit(1000)
      .toArray();

    await batchedEffective(db, docs, userId, cid);
    return docs;
  });
}
