/**
 * Read endpoints for the rest of the vendor module (slice 1a).
 *   GET /api/vendor-bills
 *   GET /api/vendor-bills/{bid}
 *   GET /api/vendors/{vid}/payments
 *   GET /api/vendor-payments/{pid}/corrections
 * Writes stay in Python.
 */
import { Controller, Get, Inject, Param, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { VendorBillsService } from './vendor-bills.service';
import { VendorPaymentsService } from './vendor-payments.service';
import { HttpError } from '../common/identity';
import { pyDumps } from '../common/py-json';

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
}

async function guard(res: Response, run: () => Promise<void>): Promise<void> {
  try {
    await run();
  } catch (err) {
    if (err instanceof HttpError) {
      send(res, err.status, { detail: err.detail });
      return;
    }
    throw err;
  }
}

@Controller()
export class VendorReadsController {
  constructor(
    @Inject(VendorBillsService) private readonly bills: VendorBillsService,
    @Inject(VendorPaymentsService) private readonly payments: VendorPaymentsService,
  ) {}

  @Get('api/vendor-bills')
  async listBills(
    @Query('vendor_id') vendorId: string | undefined,
    @Query('vehicle_id') vehicleId: string | undefined,
    @Query('repair_event_id') repairEventId: string | undefined,
    @Query('trip_id') tripId: string | undefined,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => {
      const rows = await this.bills.list(req, {
        vendor_id: vendorId,
        vehicle_id: vehicleId,
        repair_event_id: repairEventId,
        trip_id: tripId,
      });
      send(res, 200, rows);
    });
  }

  @Get('api/vendor-bills/:bid')
  async billDetail(
    @Param('bid') bid: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => {
      const row = await this.bills.detail(req, bid);
      if (!row) {
        send(res, 404, { detail: 'VendorBill not found' });
        return;
      }
      send(res, 200, row);
    });
  }

  @Get('api/vendors/:vid/payments')
  async vendorPayments(
    @Param('vid') vid: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => {
      send(res, 200, await this.payments.listForVendor(req, vid));
    });
  }

  @Get('api/vendor-payments/:pid/corrections')
  async corrections(
    @Param('pid') pid: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    await guard(res, async () => {
      send(res, 200, await this.payments.corrections(req, pid));
    });
  }
}
