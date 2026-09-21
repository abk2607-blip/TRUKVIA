/**
 * Phase 6 — the two Finance reads deferred out of slice 2a.
 *
 *   GET /api/fin/day-status
 *   GET /api/fin/day-closures/{close_date}/late-entries
 *
 * Validation order, per Gates 7o and 7r (both verified live):
 *
 *   day-status    auth 401 → `date` required, FastAPI 422 `missing`
 *                 → `if not date` 400 → date.fromisoformat 400
 *                 → active company → reads
 *   late-entries  auth 401 → date.fromisoformat 400 → active company
 *                 → closure probe → 404 → fin_txn read
 *
 * Note the asymmetry: day-status validates the date AFTER auth because it is a
 * query parameter, while late-entries takes it from the path and validates it
 * before resolving the company. Both 400 literals name their own field.
 */
import { Controller, Get, Inject, Param, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { FinStatusReadsService } from './fin-status-reads.service';
import { HttpError } from '../common/identity';
import { pyDumps } from '../common/py-json';
import { pyIsoDateValid } from '../common/py-date';

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
}

/** Repeated query keys: Starlette's MultiDict.get returns the LAST one. */
const last = (v: string | string[] | undefined): string | undefined =>
  Array.isArray(v) ? v[v.length - 1] : v;

@Controller()
export class FinStatusReadsController {
  constructor(@Inject(FinStatusReadsService) private readonly fin: FinStatusReadsService) {}

  @Get('api/fin/day-status')
  async dayStatus(
    @Query() query: Record<string, string | string[] | undefined>,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    try {
      await this.fin.assertAuthenticated(req);
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }

    const date = last(query['date']);
    if (date === undefined) {
      send(res, 422, {
        detail: [
          {
            type: 'missing',
            loc: ['query', 'date'],
            msg: 'Field required',
            input: null,
            url: 'https://errors.pydantic.dev/2.13/v/missing',
          },
        ],
      });
      return;
    }
    if (!date) {
      send(res, 400, { detail: 'date is required (YYYY-MM-DD)' });
      return;
    }
    if (!pyIsoDateValid(date)) {
      send(res, 400, { detail: 'date must be ISO YYYY-MM-DD' });
      return;
    }

    try {
      send(res, 200, await this.fin.dayStatus(req, date));
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }

  @Get('api/fin/day-closures/:close_date/late-entries')
  async lateEntries(
    @Param('close_date') closeDate: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    try {
      await this.fin.assertAuthenticated(req);
      if (!pyIsoDateValid(closeDate)) {
        send(res, 400, { detail: 'close_date must be ISO YYYY-MM-DD' });
        return;
      }
      send(res, 200, await this.fin.lateEntries(req, closeDate));
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }
}
