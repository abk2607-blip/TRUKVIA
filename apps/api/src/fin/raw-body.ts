import type { NextFunction, Request, Response } from 'express';

/**
 * Capture the untouched request bytes for the two slice-2b write routes.
 *
 * Nest installs body-parser's JSON middleware, which answers invalid JSON with
 * its own 400 before any controller runs. Python answers 422 with CPython's
 * decoder message and character offset, so the raw bytes have to survive.
 *
 * Rather than replace the global parser — which would change behaviour for the
 * frozen slice-1 routes — this runs only on the two paths below, buffers the
 * body itself, and sets body-parser's documented `_body` flag so the parser
 * skips a request whose body has already been consumed.
 *
 * It must be registered with app.use() BEFORE listen(), because Nest installs
 * its parser during init(), which runs after user middleware.
 */
export const RAW_BODY = Symbol('rawBody');

const OWNED = /^\/api\/fin\/day-closures(\/[^/]+\/reopen)?\/?$/;

export function captureRawBody() {
  return (req: Request, res: Response, next: NextFunction): void => {
    const path = (req.url ?? '').split('?')[0] ?? '';
    if (req.method !== 'POST' || !OWNED.test(path)) {
      next();
      return;
    }
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      (req as Request & { [RAW_BODY]?: Buffer })[RAW_BODY] = Buffer.concat(chunks);
      // Tell body-parser the body is already read, so it does not try again.
      (req as Request & { _body?: boolean })._body = true;
      req.body = {};
      next();
    });
    req.on('error', () => next());
  };
}
