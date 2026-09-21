/**
 * Slice 1b — vendor bill and payment write endpoints. Each fires the ported
 * fin_txn projection (src/fin/projection.ts). See vendor-txn-writes.service.ts.
 */
import { Body, Controller, Delete, Inject, Param, Post, Put, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { VendorTxnWritesService } from './vendor-txn-writes.service';
import { ValidationError } from './vendor-writes.service';
import { HttpError } from '../common/identity';
import { pyDumps } from '../common/py-json';

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
}

/** FastAPI Query(..., min_length=3): a missing or short `reason` is a 422. */
function requireReason(reason: string | undefined, res: Response): string | null {
  if (reason === undefined) {
    send(res, 422, {
      detail: [
        {
          type: 'missing',
          loc: ['query', 'reason'],
          msg: 'Field required',
          input: null,
          url: 'https://errors.pydantic.dev/2.13/v/missing',
        },
      ],
    });
    return null;
  }
  if (reason.length < 3) {
    send(res, 422, {
      detail: [
        {
          type: 'string_too_short',
          loc: ['query', 'reason'],
          msg: 'String should have at least 3 characters',
          input: reason,
          ctx: { min_length: 3 },
          url: 'https://errors.pydantic.dev/2.13/v/string_too_short',
        },
      ],
    });
    return null;
  }
  return reason;
}

async function guard(res: Response, run: () => Promise<void>): Promise<void> {
  try {
    await run();
  } catch (err) {
    if (err instanceof ValidationError) {
      send(res, 422, { detail: err.issues });
      return;
    }
    if (err instanceof HttpError) {
      send(res, err.status, { detail: err.detail });
      return;
    }
    throw err;
  }
}

@Controller()
export class VendorTxnWritesController {
  constructor(@Inject(VendorTxnWritesService) private readonly svc: VendorTxnWritesService) {}

  @Post('api/vendor-bills')
  async createBill(@Body() body: Record<string, unknown>, @Req() req: Request, @Res() res: Response): Promise<void> {
    await guard(res, async () => send(res, 200, await this.svc.createBill(req, body ?? {})));
  }

  @Put('api/vendor-bills/:bid')
  async updateBill(
    @Param('bid') bid: string,
    @Body() body: Record<string, unknown>,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => send(res, 200, await this.svc.updateBill(req, bid, body ?? {})));
  }

  @Delete('api/vendor-bills/:bid')
  async deleteBill(
    @Param('bid') bid: string,
    @Query('reason') reason: string | undefined,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    const clean = requireReason(reason, res);
    if (clean === null) return;
    await guard(res, async () => send(res, 200, await this.svc.deleteBill(req, bid, clean)));
  }

  @Post('api/vendors/:vid/payments')
  async createPayment(
    @Param('vid') vid: string,
    @Body() body: Record<string, unknown>,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => send(res, 200, await this.svc.createPayment(req, vid, body ?? {})));
  }

  @Put('api/vendors/:vid/payments/:pid')
  async updatePayment(
    @Param('vid') vid: string,
    @Param('pid') pid: string,
    @Body() body: Record<string, unknown>,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => send(res, 200, await this.svc.updatePayment(req, vid, pid, body ?? {})));
  }

  @Delete('api/vendors/:vid/payments/:pid')
  async deletePayment(
    @Param('vid') vid: string,
    @Param('pid') pid: string,
    @Query('reason') reason: string | undefined,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    const clean = requireReason(reason, res);
    if (clean === null) return;
    await guard(res, async () => send(res, 200, await this.svc.deletePayment(req, vid, pid, clean)));
  }
}
