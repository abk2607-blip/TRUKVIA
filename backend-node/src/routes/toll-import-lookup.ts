import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7k · Toll-import lookup read-only shadow.
 *
 *   GET /api/toll-import/lookup
 *
 * Faithful shadow of:
 *   backend/routers/toll_import.py::toll_import_lookup (L59-85)
 *
 * Python (verbatim):
 * ```
 * @router.get("/toll-import/lookup")
 * async def toll_import_lookup(request, txn_ref: str = "", vendor: str = "",
 *                              user=Depends(get_current_user)):
 *     uid = user["user_id"]
 *     cid = await _active_company_id(request, user)
 *     if not txn_ref:
 *         raise HTTPException(status_code=400, detail="txn_ref query param is required")
 *     q = {"user_id": uid, "company_id": cid,
 *          "source_type": "fastag_import", "source_txn_ref": txn_ref}
 *     if vendor:
 *         q["source"] = vendor.lower()
 *     doc = await db.expenses.find_one(q, {"_id": 0, "user_id": 0})
 *     if not doc:
 *         doc = await db.expenses.find_one(
 *             {"user_id": uid, "company_id": cid, "source_key": txn_ref},
 *             {"_id": 0, "user_id": 0},
 *         )
 *     if not doc:
 *         raise HTTPException(status_code=404,
 *             detail=f"No canonical Expense with source_txn_ref={txn_ref!r}. "
 *                    f"The row was never committed — check the source file and re-import.")
 *     return doc
 * ```
 *
 * Semantics preserved verbatim:
 *   * `txn_ref: str = ""` and `vendor: str = ""` — plain `str`, NO 422 surface.
 *   * Auth precedes all handler logic. 400 "txn_ref query param is required"
 *     fires only after auth + activeCompanyId succeed and txn_ref is falsy.
 *   * Primary filter includes vendor.lower() as `source` when vendor truthy.
 *   * Fallback filter drops `source_type`/`source` and uses `source_key`.
 *   * 404 detail uses Python `repr()` (`{txn_ref!r}`) — single-quoted string
 *     with `\\` / `\'` / `\n` / `\r` / `\t` / `\xNN` escapes for control chars,
 *     switches to double-quote wrap when the string contains a `'` and no `"`.
 *   * Projection strips `_id` AND `user_id`.
 *   * Response: single expense document (not array).
 *
 * Toll-import writers (preview / commit / reconcile) remain
 * Python-authoritative and OUT OF SCOPE.
 */

interface ExpenseDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  source_type?: string;
  source?: string;
  source_txn_ref?: string;
  source_key?: string;
  [k: string]: unknown;
}

// ── Python `repr()` mimic for str values ──────────────────────────────
function pyRepr(s: string): string {
  const hasSingle = s.includes("'");
  const hasDouble = s.includes('"');
  const quote = hasSingle && !hasDouble ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const code = ch.codePointAt(0)!;
    if (ch === '\\') out += '\\\\';
    else if (ch === quote) out += '\\' + quote;
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (code < 0x20 || code === 0x7f) {
      out += '\\x' + code.toString(16).padStart(2, '0');
    } else {
      out += ch;
    }
  }
  out += quote;
  return out;
}

export async function registerTollImportLookupRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7k (read-only)
  app.get('/api/toll-import/lookup', async (req: FastifyRequest, reply: FastifyReply) => {
    // 1. Auth (401 short-circuit).
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

    // 2. Tenant (locked helper).
    const cid = await activeCompanyId(req, userId, db);

    // 3. Read raw query — plain strings, no coercion, no 422 branch.
    const q = (req.query ?? {}) as Record<string, unknown>;
    const txnRef =
      typeof q['txn_ref'] === 'undefined' ? '' : String(q['txn_ref']);
    const vendor =
      typeof q['vendor'] === 'undefined' ? '' : String(q['vendor']);

    // 4. 400 when txn_ref is falsy — verbatim message.
    if (!txnRef) {
      reply.code(400);
      return { detail: 'txn_ref query param is required' };
    }

    // 5. Primary find_one on expenses.
    const primaryFilter: Record<string, unknown> = {
      user_id: userId,
      company_id: cid,
      source_type: 'fastag_import',
      source_txn_ref: txnRef,
    };
    if (vendor) {
      primaryFilter['source'] = vendor.toLowerCase();
    }

    let doc = await db
      .collection<ExpenseDoc>('expenses')
      .findOne(primaryFilter as Filter<ExpenseDoc>, {
        projection: { _id: 0, user_id: 0 },
      });

    // 6. Fallback find_one on expenses by source_key (no source_type, no source).
    if (!doc) {
      doc = await db
        .collection<ExpenseDoc>('expenses')
        .findOne(
          { user_id: userId, company_id: cid, source_key: txnRef } as Filter<ExpenseDoc>,
          { projection: { _id: 0, user_id: 0 } },
        );
    }

    // 7. Not found — verbatim Python repr()-formatted 404 detail.
    if (!doc) {
      reply.code(404);
      return {
        detail:
          `No canonical Expense with source_txn_ref=${pyRepr(txnRef)}. ` +
          'The row was never committed — check the source file and re-import.',
      };
    }

    // 8. Single-document response.
    return doc;
  });
}
