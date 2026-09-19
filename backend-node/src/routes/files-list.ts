import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Db, Filter, FindCursor } from 'mongodb';
import { authenticate } from '../auth.js';
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
 * TRUKVIA · Phase-3 · Gate-7i · Files list read-only shadow.
 *
 *   GET /api/files
 *
 * Faithful shadow of:
 *   backend/routers/files.py::list_files (L174-186)
 *
 * STRICTLY READ-ONLY. Class-C — Python executes ONLY
 *   db.files.find(q, {_id: 0, user_id: 0}).sort("created_at", -1).to_list(500)
 *
 * ── CRITICAL SCOPE RULE ─────────────────────────────────────────────
 *   USER-SCOPED ONLY. Base filter is:
 *     { user_id, is_deleted: false }
 *   There is NO `company_id` predicate. This route does NOT invoke
 *   `_active_company_id` in Python — DO NOT call `activeCompanyId` here.
 *   Same-user files across different `company_id` values MUST remain
 *   visible; cross-user files are excluded.
 *
 * ── CONTRACT ────────────────────────────────────────────────────────
 *   * Auth via locked authenticate() (401 short-circuit before any query
 *     handling — matches FastAPI solve_dependencies).
 *   * Query params: `category`, `linked_type`, `linked_id` — plain
 *     Optional[str]. NO type coercion, NO 422 surface. Blank/omitted
 *     values drop the corresponding predicate; truthy values equal-match.
 *   * `is_deleted: false` is an exact-equality Mongo filter — docs where
 *     the field is missing / null / true are all EXCLUDED (Python source
 *     uses `q = {"user_id": ..., "is_deleted": False}`; no `$ne` guard).
 *   * Projection strips `_id` AND `user_id`; every other field preserved.
 *   * Sort `created_at` DESC.
 *   * Cap `.to_list(500)`.
 *   * Response: bare JSON array. Empty → 200 [].
 *
 * Files writers (POST /files/upload, POST /files/bulk-upload,
 * DELETE /files/{fid}) and object-store egress (GET /files/{fid}/download,
 * GET /files/public/{obj_path:path}) remain Python-authoritative and
 * OUT OF SCOPE.
 */

interface FileRefDoc {
  id?: string;
  user_id?: string;
  is_deleted?: boolean;
  category?: string;
  linked_type?: string;
  linked_id?: string;
  storage_path?: string;
  original_filename?: string;
  content_type?: string;
  size?: number;
  created_at?: string;
  [k: string]: unknown;
}

export async function registerFilesListRoutes(
  app: FastifyInstance,
  deps: { db: Db },
): Promise<void> {
  const { db } = deps;

  // migration-allowlisted: phase-3-gate-7i (read-only, USER-SCOPED)
  app.get('/api/files', async (req: FastifyRequest, reply: FastifyReply) => {
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

    // 2. Raw string query params — no coercion, no case folding, no
    //    normalization; truthy => exact-equality, blank/omitted => drop.
    const q = (req.query ?? {}) as Record<string, unknown>;
    const category =
      typeof q['category'] === 'undefined' ? '' : String(q['category']);
    const linkedType =
      typeof q['linked_type'] === 'undefined' ? '' : String(q['linked_type']);
    const linkedId =
      typeof q['linked_id'] === 'undefined' ? '' : String(q['linked_id']);

    // 3. USER-ONLY filter — NO company_id. Exact `is_deleted: false`
    //    equality mirrors Python's `q = {"user_id": ..., "is_deleted": False}`.
    const filter: Record<string, unknown> = { user_id: userId, is_deleted: false };
    if (category) filter['category'] = category;
    if (linkedType) filter['linked_type'] = linkedType;
    if (linkedId) filter['linked_id'] = linkedId;

    // 4. Read — projection strips _id AND user_id, sort DESC, cap 500.
    const rows = await motorToList(
      db
      .collection<FileRefDoc>('files')
      .find(filter as Filter<FileRefDoc>, { projection: { _id: 0, user_id: 0 } })
      .sort([['created_at', -1]]),
      500,
    );

    // Bare-array response.
    return rows;
  });
}
