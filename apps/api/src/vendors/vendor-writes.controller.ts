/**
 * Slice 1b — vendor master write endpoints. MongoDB stays authoritative;
 * Postgres is refreshed from the written document. See vendor-writes.service.ts.
 */
import { Body, Controller, Delete, Get, Inject, Param, Post, Put, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { ValidationError, VendorWritesService } from './vendor-writes.service';
import { HttpError } from '../common/identity';
import { pyDumps } from '../common/py-json';

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
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
export class VendorWritesController {
  constructor(@Inject(VendorWritesService) private readonly writes: VendorWritesService) {}

  @Post('api/vendors')
  async create(
    @Body() body: Record<string, unknown>,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => send(res, 200, await this.writes.create(req, body ?? {})));
  }

  @Put('api/vendors/:vid')
  async update(
    @Param('vid') vid: string,
    @Body() body: Record<string, unknown>,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => send(res, 200, await this.writes.update(req, vid, body ?? {})));
  }

  @Delete('api/vendors/:vid')
  async remove(
    @Param('vid') vid: string,
    @Query('reason') reason: string | undefined,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () =>
      send(res, 200, await this.writes.deactivate(req, vid, reason ?? '')),
    );
  }

  @Post('api/vendors/:vid/reactivate')
  async reactivate(
    @Param('vid') vid: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => send(res, 200, await this.writes.reactivate(req, vid)));
  }
}
