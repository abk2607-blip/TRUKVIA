/**
 * Phase 6 · slice 2b — Finance day-closure writes.
 *
 *   POST /api/fin/day-closures
 *   POST /api/fin/day-closures/{close_date}/reopen
 *
 * The pipeline order below was established against the running Python server,
 * and it is NOT the order the handler source suggests:
 *
 *   1. JSON PARSE of the body      -> 422 json_invalid
 *   2. authentication              -> 401
 *   3. body structure (must be a dict) -> 422 missing / dict_type
 *   4. handler                     -> 403 / 400 / 404 / 409 / 422
 *
 * Step 1 precedes auth because FastAPI calls `await request.json()` in the
 * route wrapper, outside solve_dependencies; step 3 is inside it, hence after
 * auth. Verified: a bad token with unparseable JSON gives 422, while the same
 * token with `[1,2]` gives 401.
 */
import { Controller, Inject, Param, Post, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { FinWritesService } from './fin-writes.service';
import { HttpError } from '../common/identity';
import { pyDumps } from '../common/py-json';
import {
  bodyMissingIssue,
  bodyNotDictIssue,
  jsonInvalidIssue,
  pyJsonLoads,
  PyJsonError,
  type Issue,
} from '../common/py-body';
import { RAW_BODY } from './raw-body';

function send(res: Response, status: number, body: unknown): void {
  res.status(status).type('application/json').send(pyDumps(body));
}

/**
 * FastAPI's rule, from `get_request_handler`: a non-empty body is parsed as
 * JSON when there is NO content-type header at all, or when the media type is
 * `application/json` / `application/*+json`. For any other media type the raw
 * bytes are handed to the field as-is — which for a `dict` field means a
 * `dict_type` error whose `input` is the undecoded body text, not a `missing`.
 */
function shouldParseJson(req: Request): boolean {
  const ct = req.headers['content-type'];
  if (typeof ct !== 'string' || ct.trim() === '') return true;
  const media = (ct.split(';')[0] ?? '').trim().toLowerCase();
  const [maintype, subtype = ''] = media.split('/');
  if (maintype !== 'application') return false;
  return subtype === 'json' || subtype.endsWith('+json');
}

type ParsedBody =
  | { kind: 'ok'; value: Record<string, unknown> }
  | { kind: 'issue'; issue: Issue; beforeAuth: boolean };

function parseBody(req: Request): ParsedBody {
  const raw = (req as Request & { [RAW_BODY]?: Buffer })[RAW_BODY];
  const text = raw ? raw.toString('utf8') : '';

  // An empty body never reaches the parser, so it is the `missing` field
  // error, which happens AFTER auth.
  if (text.length === 0) {
    return { kind: 'issue', issue: bodyMissingIssue(), beforeAuth: false };
  }
  // A non-JSON media type: the raw text becomes the field value, so a `dict`
  // field reports dict_type with that text as `input`.
  if (!shouldParseJson(req)) {
    return { kind: 'issue', issue: bodyNotDictIssue(text), beforeAuth: false };
  }
  let value: unknown;
  try {
    value = pyJsonLoads(text);
  } catch (err) {
    if (err instanceof PyJsonError) {
      return { kind: 'issue', issue: jsonInvalidIssue(err), beforeAuth: true };
    }
    throw err;
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return { kind: 'issue', issue: bodyNotDictIssue(value), beforeAuth: false };
  }
  return { kind: 'ok', value: value as Record<string, unknown> };
}

@Controller()
export class FinWritesController {
  constructor(@Inject(FinWritesService) private readonly fin: FinWritesService) {}

  @Post('api/fin/day-closures')
  async closeDay(@Req() req: Request, @Res() res: Response): Promise<void> {
    const parsed = parseBody(req);
    if (parsed.kind === 'issue' && parsed.beforeAuth) {
      send(res, 422, { detail: [parsed.issue] });
      return;
    }
    try {
      await this.fin.assertAuthenticated(req);
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
    if (parsed.kind === 'issue') {
      send(res, 422, { detail: [parsed.issue] });
      return;
    }
    try {
      send(res, 200, await this.fin.closeDay(req, parsed.value));
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }

  @Post('api/fin/day-closures/:close_date/reopen')
  async reopenDay(
    @Param('close_date') closeDate: string,
    @Req() req: Request,
    @Res() res: Response,
  ): Promise<void> {
    const parsed = parseBody(req);
    if (parsed.kind === 'issue' && parsed.beforeAuth) {
      send(res, 422, { detail: [parsed.issue] });
      return;
    }
    try {
      await this.fin.assertAuthenticated(req);
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
    if (parsed.kind === 'issue') {
      send(res, 422, { detail: [parsed.issue] });
      return;
    }
    try {
      send(res, 200, await this.fin.reopenDay(req, closeDate, parsed.value));
    } catch (err) {
      if (err instanceof HttpError) {
        send(res, err.status, { detail: err.detail });
        return;
      }
      throw err;
    }
  }
}
