import type { FastifyInstance } from 'fastify';
import type { Db } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-6c · Invoice read-only shadow.
 *
 * Implements three READ-ONLY surfaces:
 *   GET /api/invoices/{iid}
 *   GET /api/invoices/{iid}/notes
 *   GET /api/invoices/next-preview
 *
 * Faithful shadows of:
 *   backend/routers/invoices.py::get_invoice
 *   backend/routers/notes.py::list_notes_for_invoice
 *   backend/routers/invoices.py::next_invoice_number_preview
 *
 * STRICTLY READ-ONLY. Node performs ZERO writes on ANY business collection.
 *
 * Gate-6c Class-B observation — Python-only on-read invoice
 * `_recompute_invoice` auto-heal is intentionally not ported to Node;
 * Node remains a strict zero-write shadow and serves invoice data as
 * stored. Parity fixtures MUST satisfy invariants I1–I11 so that Python's
 * `db.invoices.update_one` `$set` writes back identical values and
 * response parity holds byte-for-byte.
 */

// ── Numeric parity helper ─────────────────────────────────────────────
// Mirrors Python `round(x, 2)` for the value ranges produced by our
// aggregation (sums of pre-round-2 note totals). We add Number.EPSILON to
// coerce IEEE-754 residues (e.g. 0.1+0.2) into the same 2dp value Python
// obtains via banker's rounding on the same magnitudes.
const round2 = (x: number): number =>
  Math.round((x + Number.EPSILON) * 100) / 100;

// ── FY helpers (services._fy_from_iso + services._compose_invoice_number) ─
const FY_IN_PREFIX = /\d{2}-\d{2}/;

function fyFromIso(iso: string): string {
  // iso is validated `YYYY-MM-DD` before this call.
  const y = Number(iso.slice(0, 4));
  const m = Number(iso.slice(5, 7));
  const yr = y % 100;
  const yrNext = (y + 1) % 100;
  const pad = (n: number): string => n.toString().padStart(2, '0');
  return m >= 4 ? `${pad(yr)}-${pad(yrNext)}` : `${pad(yr - 1)}-${pad(yr)}`;
}

function composeInvoiceNumber(prefix: string, fy: string, seq: number): string {
  const p = (prefix || 'INV').replace(/\/+$/, '');
  const seqStr = seq.toString().padStart(4, '0');
  if (FY_IN_PREFIX.test(p)) return `${p}/${seqStr}`;
  return `${p}/${fy}/${seqStr}`;
}

function isValidIsoDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const y = Number(s.slice(0, 4));
  const m = Number(s.slice(5, 7));
  const d = Number(s.slice(8, 10));
  if (m < 1 || m > 12) return false;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === m - 1 &&
    dt.getUTCDate() === d
  );
}

function todayIsoUtc(): string {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = (d.getUTCMonth() + 1).toString().padStart(2, '0');
  const day = d.getUTCDate().toString().padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// ── CN/DN aggregator (services._apply_effective_balance) ──────────────
// Mirrors Python filter:
//   {"user_id": uid, "invoice_id": {"$in": [iid]}, "status": "issued"}
// plus optional {"company_id": <invoice.company_id>} when non-empty.
// On any error the try/except in Python OMITS the additive keys — Node
// mirrors that OMIT-vs-null behaviour.
async function applyEffectiveBalance(
  db: Db,
  invoice: Record<string, unknown>,
  userId: string,
): Promise<void> {
  const iid = invoice['id'] as string | undefined;
  if (!iid) return;
  const filter: Record<string, unknown> = {
    user_id: userId,
    invoice_id: { $in: [iid] },
    status: 'issued',
  };
  const cid = invoice['company_id'];
  if (typeof cid === 'string' && cid.length > 0) filter['company_id'] = cid;
  try {
    const notes = await db
      .collection('credit_debit_notes')
      .find(filter, {
        projection: { _id: 0, invoice_id: 1, kind: 1, total_amount: 1 },
      })
      .limit(5000)
      .toArray();
    let credits = 0;
    let debits = 0;
    for (const n of notes) {
      const amt = Number((n as Record<string, unknown>)['total_amount'] ?? 0) || 0;
      const kind = (n as Record<string, unknown>)['kind'];
      if (kind === 'credit') credits += amt;
      else if (kind === 'debit') debits += amt;
    }
    const rawTotal = Number(invoice['total_amount'] ?? 0) || 0;
    const amountPaid = Number(invoice['amount_paid'] ?? 0) || 0;
    const effectiveTotal = round2(rawTotal - credits + debits);
    const effectiveBalance = round2(effectiveTotal - amountPaid);
    invoice['effective_total_amount'] = effectiveTotal;
    invoice['effective_balance_due'] = effectiveBalance;
    invoice['credits_total'] = round2(credits);
    invoice['debits_total'] = round2(debits);
  } catch {
    // Mirror Python's `try/except: pass` — additive keys are OMITTED
    // (not nulled) so downstream consumers see the doc as-stored.
  }
}

// ── Query schemas ─────────────────────────────────────────────────────
// invoice_date is required — missing yields 422 to mirror FastAPI query
// validation, which fires before the auth dependency resolves.
// ── Gate 9e · next-preview query (route-local) ─────────────────────────
// FastAPI `invoice_date: str`: the only possible validation error is Pydantic
// v2 `missing` (any string is valid). Value = Starlette QueryParams.get →
// LAST occurrence, CPython 3.11 parse_qsl / unquote_plus (Gate-7v copy).
const PREVIEW_MISSING_422 = {
  detail: [
    {
      type: 'missing',
      loc: ['query', 'invoice_date'],
      msg: 'Field required',
      input: null,
      url: 'https://errors.pydantic.dev/2.13/v/missing',
    },
  ],
};

const QS_HEX = /^[0-9A-Fa-f]{2}$/;
const UTF8_REPLACE = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true });

// urllib.parse.unquote_to_bytes(<ASCII run>).decode('utf-8', 'replace')
function unquoteAsciiRun(run: string): string {
  const bits = run.split('%');
  if (bits.length === 1) return run;
  const bytes: number[] = [];
  const pushAscii = (t: string): void => {
    for (let i = 0; i < t.length; i++) bytes.push(t.charCodeAt(i));
  };
  pushAscii(bits[0] as string);
  for (let i = 1; i < bits.length; i++) {
    const item = bits[i] as string;
    const h = item.slice(0, 2);
    if (QS_HEX.test(h)) {
      bytes.push(parseInt(h, 16));
      pushAscii(item.slice(2));
    } else {
      bytes.push(0x25);
      pushAscii(item);
    }
  }
  return UTF8_REPLACE.decode(Uint8Array.from(bytes));
}

// urllib.parse.unquote_plus(s) on a latin-1-decoded str
function pyUnquotePlus(input: string): string {
  const s = input.replace(/\+/g, ' ');
  if (!s.includes('%')) return s;
  return s.replace(/[\x00-\x7f]+/g, (run) => unquoteAsciiRun(run));
}

// Last occurrence of `key` (ImmutableMultiDict.get), undefined when absent.
function pyQueryLast(rawUrl: string, key: string): string | undefined {
  const qi = rawUrl.indexOf('?');
  if (qi < 0) return undefined;
  let found: string | undefined;
  for (const field of rawUrl.slice(qi + 1).split('&')) {
    if (!field) continue;
    const eq = field.indexOf('=');
    const name = eq < 0 ? field : field.slice(0, eq);
    const value = eq < 0 ? '' : field.slice(eq + 1);
    if (pyUnquotePlus(name) === key) found = pyUnquotePlus(value);
  }
  return found;
}

// ── Handlers registrar ────────────────────────────────────────────────
export async function registerInvoicesRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // ── GET /api/invoices/next-preview  (static path — Fastify's find-my-way
  //    always prefers the static match over the `:iid` param, but we also
  //    register it first for clarity.) ───────────────────────────────────
  //
  // migration-allowlisted: phase-3-gate-6c (read-only)
  app.get('/api/invoices/next-preview', async (req, reply) => {
    // 1. Auth (401) FIRST — FastAPI solves `Depends(get_current_user)` before
    //    validating query params (Gate 9e, verified live).
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

    // 2. Missing `invoice_date` → Pydantic v2 `missing` 422 (exact body).
    const invoiceDate = pyQueryLast(req.raw.url ?? '', 'invoice_date');
    if (invoiceDate === undefined) {
      reply.code(422);
      return PREVIEW_MISSING_422;
    }

    // 3. Invalid ISO date → 400.
    if (!isValidIsoDate(invoiceDate)) {
      reply.code(400);
      return { detail: 'invoice_date must be ISO YYYY-MM-DD' };
    }

    // 4. Future date (server UTC clock) → 400.
    if (invoiceDate > todayIsoUtc()) {
      reply.code(400);
      return { detail: 'invoice_date cannot be in the future' };
    }

    // 5. Resolve active company (X-Company-Id override + default fallback).
    const cid = await activeCompanyId(req, userId, db);

    // 6. Pure-read preview — NO $inc, NO update_one, NO findOneAndUpdate.
    //    Mirrors services._preview_next_invoice_number verbatim.
    const fyStr = fyFromIso(invoiceDate);
    const company = (await db.collection('companies').findOne(
      { id: cid, user_id: userId },
      {
        projection: {
          _id: 0,
          invoice_prefix: 1,
          next_invoice_number: 1,
          next_invoice_number_by_fy: 1,
        },
      },
    )) as Record<string, unknown> | null;
    const co = company ?? {};

    const prefix = (co['invoice_prefix'] as string | undefined) ?? 'INV';
    const fyMap = (co['next_invoice_number_by_fy'] as Record<string, number> | undefined) ?? {};
    let seq: number;
    if (Object.prototype.hasOwnProperty.call(fyMap, fyStr)) {
      seq = Number(fyMap[fyStr] ?? 1) || 1;
    } else {
      const serverFy = fyFromIso(todayIsoUtc());
      const legacy = Number(co['next_invoice_number'] ?? 1) || 1;
      if (fyStr === serverFy && legacy > 1) seq = legacy;
      else seq = 1;
    }

    return {
      suggested_number: composeInvoiceNumber(prefix, fyStr, seq),
      fy: fyStr,
      editable: false,
    };
  });

  // ── GET /api/invoices/{iid}  ─────────────────────────────────────────
  //
  // migration-allowlisted: phase-3-gate-6c (read-only)
  //
  // NOTE (Class-B): Python's `_recompute_invoice` performs an on-read
  // `db.invoices.update_one` $set on totals/tax/balance fields when the
  // linked trips have drifted. Node intentionally SKIPS this write. For
  // fixtures satisfying invariants I1–I11 the write is a no-op and
  // responses are byte-identical.
  app.get<{ Params: { iid: string } }>(
    '/api/invoices/:iid',
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

      // NOTE (Class-B): Python calls `_recompute_invoice(iid, user)` here.
      // Node intentionally does NOT. Zero writes on this route.

      const doc = await db.collection('invoices').findOne(
        { id: iid, user_id: userId },
        { projection: { _id: 0, user_id: 0 } },
      );

      if (!doc) {
        reply.code(404);
        return { detail: 'Invoice not found' };
      }

      // Additive keys (best-effort; OMIT on error per Python parity).
      await applyEffectiveBalance(db, doc, userId);

      return doc;
    },
  );

  // ── GET /api/invoices/{iid}/notes  ───────────────────────────────────
  //
  // migration-allowlisted: phase-3-gate-6c (read-only)
  //
  // Semantics reproduced verbatim from routers/notes.py::list_notes_for_invoice:
  //   * NO feature-flag gate (`_require_flag()` is intentionally NOT called
  //     — the route is always 200 for authenticated callers so the UI's
  //     "Related Notes" panel renders as empty when the flag is off).
  //   * NO invoice-existence probe; unowned invoice_id returns [].
  //   * NO server-side status filter (draft / issued / cancelled all
  //     returned; callers filter downstream).
  //   * Sort: note_date ASC; hard cap 500.
  app.get<{ Params: { iid: string } }>(
    '/api/invoices/:iid/notes',
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
      const docs = await db
        .collection('credit_debit_notes')
        .find(
          { user_id: userId, invoice_id: iid },
          { projection: { _id: 0, user_id: 0 } },
        )
        .sort([['note_date', 1]])
        .limit(500)
        .toArray();

      return docs;
    },
  );
}
