import type { Request, Response, NextFunction } from 'express';

/**
 * Starlette's `redirect_slashes` behaviour, which Express does not have.
 *
 * A request to "/api/vendors/" is answered by Starlette with
 *   307 Temporary Redirect
 *   location: <absolute url without the trailing slash, query preserved>
 * while Express silently treats it as "/api/vendors" and returns 200.
 * Verified against the live Python backend on 2026-09-21.
 *
 * Only paths that this app actually serves are redirected; everything else
 * falls through so the 404 path stays unchanged.
 */
export function starletteTrailingSlash(knownPaths: () => Set<string>) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const path = req.path;
    if (path.length > 1 && path.endsWith('/')) {
      const stripped = path.slice(0, -1);
      if (knownPaths().has(stripped)) {
        const query = req.originalUrl.includes('?')
          ? req.originalUrl.slice(req.originalUrl.indexOf('?'))
          : '';
        const host = req.headers.host ?? '';
        res.status(307).set('location', `http://${host}${stripped}${query}`).send('');
        return;
      }
    }
    next();
  };
}
