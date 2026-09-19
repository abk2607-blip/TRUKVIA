import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter, FindCursor } from 'mongodb';
import { authenticate } from '../auth.js';
import { activeCompanyId } from '../tenant.js';
import { HttpError } from '../errors.js';

// ── Gate 9e · Motor `to_list(n)` (route-local) ────────────────────────
// Motor sends NO server-side limit for `to_list(n)`; a `.limit(n)` turns the
// sort into a top-k whose tie order at the cap differs (verified live). Read
// the sorted cursor and stop after n documents, exactly like Motor.
async function motorToList<T>(cursor: FindCursor<T>, n: number): Promise<T[]> {
  const out: T[] = [];
  try {
    if (n <= 0) {
      await cursor.hasNext(); // to_list(0) still issues the find, returns []
      return out;
    }
    for await (const doc of cursor) {
      out.push(doc);
      if (out.length >= n) break;
    }
  } finally {
    await cursor.close();
  }
  return out;
}

/**
 * TRUKVIA · Phase-3 · Gate-7l · Approval detail read-only shadow.
 *
 *   GET /api/approvals/{aid}
 *
 * Faithful shadow of:
 *   backend/routers/approvals.py::api_get_approval (L59-63)
 *   backend/services_approvals.py::get_approval_detail (L544-560)
 *
 * Python (verbatim):
 * ```
 * @router.get("/approvals/{aid}")
 * async def api_get_approval(aid: str, request: Request,
 *                            user=Depends(get_current_user)):
 *     cid = await _active_company_id(request, user)
 *     return await get_approval_detail(user=user, company_id=cid, approval_id=aid)
 *
 * async def get_approval_detail(*, user, company_id, approval_id):
 *     uid = user["user_id"]
 *     apr = await db.approvals.find_one(
 *         {"id": approval_id, "user_id": uid, "company_id": company_id}, {"_id": 0})
 *     if not apr:
 *         raise HTTPException(status_code=404, detail="Approval not found")
 *     revisions = await db.approval_revisions.find(
 *         {"approval_id": approval_id, "user_id": uid, "company_id": company_id},
 *         {"_id": 0}).sort("revision_index", 1).to_list(200)
 *     audits = await db.approval_audits.find(
 *         {"approval_id": approval_id, "user_id": uid, "company_id": company_id},
 *         {"_id": 0}).sort("at", 1).to_list(500)
 *     return {"approval": apr, "revisions": revisions, "audits": audits}
 * ```
 *
 * ── SEMANTICS PRESERVED ─────────────────────────────────────────────
 *   * Auth (401 short-circuit) → activeCompanyId → primary approval read
 *     → 404 if missing → revisions read (sort revision_index ASC, cap 200)
 *     → audits read (sort at ASC, cap 500) → `{approval, revisions, audits}`.
 *   * Path param `aid: str` — no validation surface; any non-empty
 *     segment reaches the handler; empty segment cannot reach the route
 *     (Fastify would 404 on missing param).
 *   * Projections strip ONLY `_id` — `user_id` is PRESERVED in all three
 *     collections (contrast with Gates 7a–7f which stripped both).
 *   * All three reads are tenant-scoped: `{user_id, company_id}`
 *     (approvals uses `id`, revisions/audits use `approval_id`).
 *   * 404 detail exact literal: `"Approval not found"`.
 *
 * Approval writers (`POST /approvals`, `POST /approvals/{aid}/{approve|reject|withdraw|resubmit}`)
 * remain Python-authoritative and OUT OF SCOPE.
 */

interface ApprovalDoc {
  id?: string;
  user_id?: string;
  company_id?: string;
  status?: string;
  entity_kind?: string;
  entity_id?: string;
  [k: string]: unknown;
}

interface ApprovalRevisionDoc {
  approval_id?: string;
  user_id?: string;
  company_id?: string;
  revision_index?: number;
  [k: string]: unknown;
}

interface ApprovalAuditDoc {
  approval_id?: string;
  user_id?: string;
  company_id?: string;
  at?: string;
  [k: string]: unknown;
}

export async function registerApprovalDetailRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7l (read-only)
  app.get('/api/approvals/:aid', async (req: FastifyRequest, reply: FastifyReply) => {
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

    // 3. Path param.
    const aid = (req.params as { aid: string }).aid;

    // 4. Primary approval read.
    const approval = await db
      .collection<ApprovalDoc>('approvals')
      .findOne(
        { id: aid, user_id: userId, company_id: cid } as Filter<ApprovalDoc>,
        { projection: { _id: 0 } },
      );

    // 5. 404 verbatim.
    if (!approval) {
      reply.code(404);
      return { detail: 'Approval not found' };
    }

    // 6. Revisions read (sort revision_index ASC, cap 200).
    const revisions = await motorToList(
      db
      .collection<ApprovalRevisionDoc>('approval_revisions')
      .find(
        { approval_id: aid, user_id: userId, company_id: cid } as Filter<ApprovalRevisionDoc>,
        { projection: { _id: 0 } },
      )
      .sort([['revision_index', 1]]),
      200,
    );

    // 7. Audits read (sort at ASC, cap 500).
    const audits = await motorToList(
      db
      .collection<ApprovalAuditDoc>('approval_audits')
      .find(
        { approval_id: aid, user_id: userId, company_id: cid } as Filter<ApprovalAuditDoc>,
        { projection: { _id: 0 } },
      )
      .sort([['at', 1]]),
      500,
    );

    // 8. Wrapper response.
    return { approval, revisions, audits };
  });
}
