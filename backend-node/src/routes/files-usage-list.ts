import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter } from 'mongodb';
import { authenticate } from '../auth.js';
import { HttpError } from '../errors.js';

/**
 * TRUKVIA · Phase-3 · Gate-7j · Files-usage summary read-only shadow.
 *
 *   GET /api/files/usage
 *
 * Faithful shadow of:
 *   backend/routers/files.py::file_usage (L94-109)
 *
 * Python (verbatim):
 * ```
 * @router.get("/files/usage")
 * async def file_usage(user=Depends(get_current_user)):
 *     docs = await db.files.find(
 *         {"user_id": user["user_id"], "is_deleted": False},
 *         {"_id": 0, "size": 1, "category": 1}
 *     ).to_list(5000)
 *     total = sum(int(d.get("size", 0) or 0) for d in docs)
 *     by_cat = {}
 *     for d in docs:
 *         c = d.get("category", "general")
 *         by_cat[c] = by_cat.get(c, 0) + int(d.get("size", 0) or 0)
 *     limit = 500 * 1024 * 1024  # 500MB soft cap
 *     return {
 *         "total_bytes": total,
 *         "limit_bytes": limit,
 *         "pct": round(min(100, total / limit * 100), 2) if limit else 0,
 *         "file_count": len(docs),
 *         "by_category": by_cat,
 *     }
 * ```
 *
 * ── SEMANTICS PRESERVED VERBATIM ────────────────────────────────────
 *   * `int(d.get("size", 0) or 0)` — missing/None/0/False/"" → 0; numbers
 *     truncate toward zero (matches Python `int(float)`). Fixtures use
 *     non-negative int sizes; symbolic behavior mirrored for parity.
 *   * `d.get("category", "general")` — KEY-BASED default. Missing key →
 *     "general". Key PRESENT with value `null` / `""` / other string →
 *     that literal value is used as the by_cat key. NOT `d.get(k) or default`.
 *   * `by_cat` insertion-order preserved (dict since Py 3.7; V8 objects
 *     preserve string-key insertion order). No sort applied.
 *   * `limit_bytes` = `500 * 1024 * 1024` = 524288000 (constant int).
 *   * `pct` = round(min(100, total/limit*100), 2) — limit is always
 *     truthy so the `else 0` branch never executes. Python 3 division
 *     `/` is float; `min(100, float)` returns 100 (int) when capped or
 *     the float otherwise; `round(int, 2)` returns int, `round(float, 2)`
 *     returns float. JSON int/float comparison at parity level uses
 *     numeric equality — `50.0 == 50` matches.
 *
 * ── USER-ONLY SCOPE (Gate 7i axis carried forward) ──────────────────
 *   NO `activeCompanyId`. Base filter is `{user_id, is_deleted: false}`.
 *   Same-user rows across arbitrary `company_id` values remain visible;
 *   cross-user rows excluded.
 *
 * Zero writer hook / audit / backfill / recompute / FinTxn / counters /
 * idempotency / cross-collection reads on the GET path. No object-store
 * call. Files writers + object-store egress remain Python-authoritative.
 */

interface FileUsageDoc {
  size?: number | null | string | undefined;
  category?: string | null | undefined;
  [k: string]: unknown;
}

function toIntOrZero(v: unknown): number {
  // Mirrors Python `int(v or 0)` for the values the data model can hold.
  if (v === null || v === undefined || v === false || v === 0 || v === '') return 0;
  if (typeof v === 'number') return Math.trunc(v);
  if (typeof v === 'string') {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

export async function registerFilesUsageListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7j (read-only, USER-SCOPED)
  app.get('/api/files/usage', async (req: FastifyRequest, reply: FastifyReply) => {
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

    // 2. USER-ONLY read (no activeCompanyId, no company_id predicate).
    //    Exact Python filter + projection + cap.
    const docs = await db
      .collection<FileUsageDoc>('files')
      .find(
        { user_id: userId, is_deleted: false } as Filter<FileUsageDoc>,
        { projection: { _id: 0, size: 1, category: 1 } },
      )
      .limit(5000)
      .toArray();

    // 3. Aggregate — verbatim Python semantics.
    let total = 0;
    const byCategory: Record<string, number> = {};
    for (const d of docs) {
      const s = toIntOrZero(d.size);
      total += s;
      // Python `d.get("category", "general")` — key-based default only.
      // Note: Mongo projection returns only requested fields; if the
      // stored doc has no `category` field, projection yields absence
      // here as well, which triggers the "general" default. If the
      // stored doc has `category: null`, projection includes `null` and
      // the Python code uses `None` as the by_cat key.
      const cKey = Object.prototype.hasOwnProperty.call(d, 'category')
        ? (d.category as unknown as string)
        : 'general';
      const key = cKey as unknown as string;
      byCategory[key] = (byCategory[key] ?? 0) + s;
    }

    const limitBytes = 500 * 1024 * 1024; // 524288000
    // pct = round(min(100, total / limit * 100), 2) if limit else 0
    // limit is always truthy here, matching Python's runtime behavior.
    const pctRaw = Math.min(100, (total / limitBytes) * 100);
    const pct = Math.round(pctRaw * 100) / 100;

    return {
      total_bytes: total,
      limit_bytes: limitBytes,
      pct,
      file_count: docs.length,
      by_category: byCategory,
    };
  });
}
