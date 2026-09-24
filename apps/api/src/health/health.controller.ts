import { Controller, Get, Inject, Res } from '@nestjs/common';
import type { Response } from 'express';
import type { Db } from 'mongodb';
import { MONGO } from '../vendors/vendors.service';
import { liveReport, readyReport } from './health';

/**
 * `GET /health/live` and `GET /health/ready`.
 *
 * These are NOT under `/api/*`: the production ingress sends `/api/*` to
 * Python, and nothing here is added to any routing allowlist. They are reachable
 * on the same loopback interface the process already binds, and that binding is
 * unchanged.
 *
 * Readiness uses the SAME `MONGO` provider every other service in this
 * application injects, so there is exactly one Mongo connection and one place
 * the Finance-writer authorisation guard runs. A second client here would be a
 * second architecture — and one that bypassed that guard.
 */
@Controller()
export class HealthController {
  constructor(@Inject(MONGO) private readonly mongo: Db) {}

  @Get('health/live')
  live(@Res() res: Response): void {
    res.status(200).json(liveReport());
  }

  @Get('health/ready')
  async ready(@Res() res: Response): Promise<void> {
    const { status, body } = await readyReport(this.mongo);
    res.status(status).json(body);
  }
}
