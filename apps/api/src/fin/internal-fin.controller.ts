/**
 * Phase 6 · slice 2c — the REVERSE bridge: Python → NestJS projection.
 *
 *   POST /internal/fin/reproject
 *
 * The forward bridge (src/fin/hook-client.ts) lets NestJS delegate a projection
 * to Python. This is its mirror, so Python can delegate to NestJS once a source
 * type has a TypeScript projection. Both directions exist during the migration;
 * neither is wired to anything it did not already call.
 *
 * As of unit 3 two source types actually cross it — `mechanic_payment` and
 * `supplier_payment` — and only when Python is configured to delegate. See the
 * env-gated block in backend/services_fin_txn_hooks.py, which is OFF by
 * default; the other eleven source types never reach here. Rollback is
 * unsetting that env var.
 *
 * This is NOT a public API. Four independent restrictions, each of which alone
 * denies the request — identical to backend/routers/internal_fin.py:
 *
 *   1. Path outside /api. The ingress routes only /api to a service, so
 *      /internal/... is not reachable from outside the pod at all.
 *   2. Loopback only. Both services share a pod, so a remote peer is wrong.
 *   3. Shared secret in X-Internal-Token, compared in constant time.
 *   4. Fail closed. With the secret unset or shorter than 32 characters the
 *      endpoint refuses everything, so a misconfigured deploy cannot expose an
 *      unauthenticated projection trigger.
 *
 * The token is never logged, never echoed, and never put in an error body.
 */
import { Controller, Inject, Post, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import type { Db as MongoDb } from 'mongodb';
import { timingSafeEqual } from 'node:crypto';
import { pyDumps } from '../common/py-json';
import { hookAfterSourceWrite } from './fin-hook';
import { MONGO } from '../vendors/vendors.service';

/**
 * Mirrors internal_fin.py's allowlist, PLUS the types this side has since
 * ported. Python's own endpoint still allows only the two vendor types; that
 * asymmetry is deliberate and is what lets Python delegate mechanic_payment
 * and supplier_payment here without NestJS being able to bounce them back.
 */
const ALLOWED_SOURCE_TYPES = [
  'vendor_bill',
  'vendor_payment',
  'mechanic_payment',
  'supplier_payment',
  'driver_payment',
  'credit_debit_note',
  'expense',
  'mechanic_work_order',
  'wallet_adjustment',
  'trip_customer_receipt',
  'wallet_recharge',
  'wallet_transfer',
  'invoice',
];
const LOOPBACK = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1']);
const MIN_TOKEN_LEN = 32;

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
}

/** Constant-time compare, mirroring hmac.compare_digest. */
function tokensMatch(presented: string, expected: string): boolean {
  const a = Buffer.from(presented, 'utf8');
  const b = Buffer.from(expected, 'utf8');
  // timingSafeEqual throws on a length mismatch, which would itself leak the
  // length, so compare padded buffers and fold the length into the result.
  const len = Math.max(a.length, b.length, 1);
  const pa = Buffer.alloc(len);
  const pb = Buffer.alloc(len);
  a.copy(pa);
  b.copy(pb);
  return timingSafeEqual(pa, pb) && a.length === b.length;
}

class Denied extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

@Controller()
export class InternalFinController {
  constructor(@Inject(MONGO) private readonly mongo: MongoDb) {}

  private authorise(req: Request): void {
    const expected = (process.env.TRUKVIA_INTERNAL_TOKEN ?? '').trim();
    if (expected.length < MIN_TOKEN_LEN) throw new Denied(404, 'Not Found');

    const peer = req.socket?.remoteAddress ?? '';
    if (!LOOPBACK.has(peer)) throw new Denied(404, 'Not Found');

    const header = req.headers['x-internal-token'];
    const presented = typeof header === 'string' ? header : '';
    if (!tokensMatch(presented, expected)) throw new Denied(401, 'Invalid internal credential');
  }

  @Post('internal/fin/reproject')
  async reproject(@Req() req: Request, @Res() res: Response): Promise<void> {
    try {
      this.authorise(req);
    } catch (err) {
      if (err instanceof Denied) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }

    const body = (req.body ?? {}) as Record<string, unknown>;
    const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');
    const uid = str(body['user_id']);
    const cid = str(body['company_id']);
    const sourceType = str(body['source_type']);
    const sourceId = str(body['source_id']);

    if (!uid || !cid || !sourceId) {
      send(res, 400, { detail: 'user_id, company_id and source_id are required' });
      return;
    }
    if (!ALLOWED_SOURCE_TYPES.includes(sourceType)) {
      send(res, 400, {
        detail: `unsupported source_type. Allowed: [${[...ALLOWED_SOURCE_TYPES]
          .sort()
          .map((t) => `'${t}'`)
          .join(', ')}]`,
      });
      return;
    }

    // Delegates to the SAME canonical hook the NestJS writers use. It never
    // throws: failures land in fin_hook_failures and come back as ok=false.
    send(res, 200, await hookAfterSourceWrite(this.mongo, uid, cid, sourceType, sourceId));
  }
}
