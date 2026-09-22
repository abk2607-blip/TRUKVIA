/**
 * Phase 6 · slice 2a — Finance read endpoints served from PostgreSQL.
 *
 *   GET /api/fin/day-book                   (Gate 7s contract)
 *   GET /api/fin/day-closures               (Gate 7m)
 *   GET /api/fin/day-closures/{close_date}  (Gate 7n)
 *
 * NOT served here, deliberately:
 *   • GET /api/fin/accounts — calls ensure_system_accounts on every request,
 *     so it is a GET-time writer and stays in Python;
 *   • GET /api/fin/fin-txn/{txid} — joins 13 source collections that still
 *     live in MongoDB, so it cannot be Postgres-backed in this slice;
 *   • every write, the projection, and reconciliation.
 *
 * Validation order is the one Gate 7s verified against the live server:
 * auth (401) → query validation (422, declaration order) → active company →
 * handler 400.
 */
import { Controller, Get, Inject, Param, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { FinReadsService } from './fin-reads.service';
import { HttpError } from '../common/identity';
import { pyDumps } from '../common/py-json';

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
}

interface Issue {
  type: string;
  loc: string[];
  msg: string;
  input: unknown;
  url: string;
}

const missing = (name: string): Issue => ({
  type: 'missing',
  loc: ['query', name],
  msg: 'Field required',
  input: null,
  url: 'https://errors.pydantic.dev/2.13/v/missing',
});

/**
 * Pydantic v2 integer parsing for a query string. Values beyond the parser's
 * size limit are a distinct error type, which the Gate 7s shadow verified.
 */
export function parsePydanticInt(
  rawValue: string,
): { ok: true; value: bigint } | { ok: false; type: string } {
  const trimmed = rawValue.trim();
  if (trimmed.length > 4300) return { ok: false, type: 'int_parsing_size' };
  if (!/^[+-]?\d+$/.test(trimmed)) return { ok: false, type: 'int_parsing' };
  try {
    return { ok: true, value: BigInt(trimmed) };
  } catch {
    return { ok: false, type: 'int_parsing' };
  }
}

@Controller()
export class FinReadsController {
  constructor(@Inject(FinReadsService) private readonly fin: FinReadsService) {}

  @Get('api/fin/day-book')
  async dayBook(
    @Query() query: Record<string, string | string[] | undefined>,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    // Repeated query keys: FastAPI takes the last occurrence.
    const last = (v: string | string[] | undefined): string | undefined =>
      Array.isArray(v) ? v[v.length - 1] : v;

    try {
      // 1. auth
      await this.fin.assertAuthenticated(req);
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }

    // 2. query validation, in declaration order
    const dateFrom = last(query['date_from']);
    const dateTo = last(query['date_to']);
    const limitRaw = last(query['limit']);
    const errors: Issue[] = [];
    if (dateFrom === undefined) errors.push(missing('date_from'));
    if (dateTo === undefined) errors.push(missing('date_to'));

    let limit = 5000;
    if (limitRaw !== undefined) {
      const parsed = parsePydanticInt(limitRaw);
      if (!parsed.ok) {
        errors.push({
          type: parsed.type,
          loc: ['query', 'limit'],
          msg:
            parsed.type === 'int_parsing'
              ? 'Input should be a valid integer, unable to parse string as an integer'
              : 'Unable to parse input string as an integer, exceeded maximum size',
          input: limitRaw,
          url: `https://errors.pydantic.dev/2.13/v/${parsed.type}`,
        });
      } else {
        limit = parsed.value < 1n ? 1 : parsed.value > 20000n ? 20000 : Number(parsed.value);
      }
    }
    if (errors.length) {
      send(res, 422, { detail: errors });
      return;
    }

    // 3 + 4. active company, then the handler's own 400 for empty values
    try {
      const result = await this.fin.dayBook(req, {
        date_from: dateFrom as string,
        date_to: dateTo as string,
        account_code: last(query['account_code']),
        account_id: last(query['account_id']),
        source_type: last(query['source_type']),
        party_id: last(query['party_id']),
        vehicle_id: last(query['vehicle_id']),
        trip_id: last(query['trip_id']),
        limit,
      });
      send(res, 200, result);
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }

  @Get('api/fin/day-closures')
  async dayClosures(
    @Query('limit') limitRaw: string | undefined,
    @Query('date_from') dateFrom: string | undefined,
    @Query('date_to') dateTo: string | undefined,
    @Query('status') status: string | undefined,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    try {
      await this.fin.assertAuthenticated(req);
      let limit = 500; // Python's default
      if (limitRaw !== undefined) {
        const parsed = parsePydanticInt(limitRaw);
        if (!parsed.ok) {
          send(res, 422, {
            detail: [
              {
                type: parsed.type,
                loc: ['query', 'limit'],
                msg:
                  parsed.type === 'int_parsing'
                    ? 'Input should be a valid integer, unable to parse string as an integer'
                    : 'Unable to parse input string as an integer, exceeded maximum size',
                input: limitRaw,
                url: `https://errors.pydantic.dev/2.13/v/${parsed.type}`,
              },
            ],
          });
          return;
        }
        // The handler clamps to [1, 5000]; a huge value is not a 422.
        limit = parsed.value < 1n ? 1 : parsed.value > 5000n ? 5000 : Number(parsed.value);
      }
      send(
        res,
        200,
        await this.fin.dayClosures(req, {
          date_from: dateFrom,
          date_to: dateTo,
          status,
          limit,
        }),
      );
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }

  @Get('api/fin/day-closures/:close_date')
  async dayClosure(
    @Param('close_date') closeDate: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    try {
      const row = await this.fin.dayClosure(req, closeDate);
      if (!row) {
        send(res, 404, { detail: `No closure exists for ${closeDate}` });
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
