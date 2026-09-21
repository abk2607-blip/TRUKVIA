/**
 * TRUKVIA · Phase 6 · slice 1a — GET /api/vendors, GET /api/vendors/{vid}
 * served from PostgreSQL.
 *
 * Faithful shadow of backend/routers/vendors.py::list_vendors / get_vendor,
 * cross-checked against the gate-locked Fastify shadow
 * backend-node/src/routes/vendors.ts (Gate 6j).
 *
 * Preserved semantics:
 *   • query validation runs BEFORE auth, so a bad `active_only` is 422 even
 *     without a session (FastAPI parses params first);
 *   • `active_only` uses Pydantic v2 boolean-string tokens, and only literal
 *     `is_active = true` matches when set;
 *   • `q` filters name/mobile/contact_person case-insensitively;
 *   • the response omits `_id` and `user_id`, sorts by name ascending, caps at
 *     20,000 rows;
 *   • detail scopes on (id, user_id, company_id) only — no is_active filter,
 *     so inactive vendors are still returned; a miss is
 *     404 {"detail":"Vendor not found"}.
 */
import { Controller, Get, Inject, Param, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { VendorsService } from './vendors.service';
import { HttpError } from '../common/identity';
import { pyDumps } from '../common/py-json';

const BOOL_TRUE = new Set(['1', 't', 'true', 'on', 'yes']);
const BOOL_FALSE = new Set(['0', 'f', 'false', 'off', 'n', 'no']);

/** Pydantic v2 boolean-string coercion (verbatim token set). */
export function coerceFastapiBool(v: unknown): boolean | 'invalid' {
  if (typeof v !== 'string') return 'invalid';
  const s = v.trim().toLowerCase();
  if (BOOL_TRUE.has(s)) return true;
  if (BOOL_FALSE.has(s)) return false;
  return 'invalid';
}

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
}

@Controller()
export class VendorsController {
  // Explicit token: esbuild/tsx does not emit decorator metadata, so Nest
  // cannot infer constructor parameter types in dev. tsc builds do emit it;
  // naming the token keeps both paths working.
  constructor(@Inject(VendorsService) private readonly vendors: VendorsService) {}

  @Get('api/vendors')
  async list(
    @Query('q') q: string | undefined,
    @Query('active_only') activeOnly: string | undefined,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    let activeOnlyValue = false;
    if (activeOnly !== undefined) {
      const coerced = coerceFastapiBool(activeOnly);
      if (coerced === 'invalid') {
        // Pydantic 2.13 error shape, verbatim (key order included).
        send(res, 422, {
          detail: [
            {
              type: 'bool_parsing',
              loc: ['query', 'active_only'],
              msg: 'Input should be a valid boolean, unable to interpret input',
              input: activeOnly,
              url: 'https://errors.pydantic.dev/2.13/v/bool_parsing',
            },
          ],
        });
        return;
      }
      activeOnlyValue = coerced;
    }

    try {
      const rows = await this.vendors.list(req, { q, activeOnly: activeOnlyValue });
      send(res, 200, rows);
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }

  @Get('api/vendors/:vid')
  async detail(
    @Param('vid') vid: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    try {
      const row = await this.vendors.detail(req, vid);
      if (!row) {
        send(res, 404, { detail: 'Vendor not found' });
        return;
      }
      send(res, 200, row);
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }
}
