import type { FastifyError, FastifyInstance, FastifyReply, FastifyRequest, RouteOptions } from 'fastify';
import type { IncomingMessage } from 'node:http';
import { STATUS_CODES } from 'node:http';
import type { Socket } from 'node:net';
import { PYTHON_ROUTES } from './python-route-table.js';

/**
 * TRUKVIA Node · Phase-4 · Gate-9d · HTTP-edge parity with the pinned Python stack
 * (uvicorn 0.25 + h11 0.16, Starlette 0.37.2 / FastAPI, backend/server.py).
 *
 * Python request path (outermost first):
 *   h11 parser → ServerErrorMiddleware → save-health → idempotency → ApprovalGate
 *   → security headers (setdefault) → CORSMiddleware → Router → route.
 *
 * Reproduced here, framework-level only (no route logic changes):
 *   1. h11 request-target grammar: only \x21-\x7e → else bare 400
 *      "Invalid HTTP request received." (text/plain, connection: close, no app headers).
 *   2. CORS preflight (Origin present + OPTIONS + Access-Control-Request-Method present)
 *      answered before routing, exactly like starlette CORSMiddleware.preflight_response.
 *   3. uvicorn path decoding `unquote(raw_path.decode("ascii"))` (utf-8, errors=replace),
 *      then Starlette Router over the REAL Python route table (python-route-table.ts):
 *        FULL match of a route Node serves → dispatched via a canonical URL (params
 *          re-encoded), so Node's handler sees exactly Python's decoded params;
 *        FULL match of a route Node does NOT serve → 404 {"detail":"Not Found"} + warn
 *          log (outside Node's cutover surface; ingress must not send it here);
 *        first PARTIAL match → 405 {"detail":"Method Not Allowed"} + `allow`;
 *        trailing slash toggled matches anything → 307 + Starlette `location`;
 *        otherwise 404 {"detail":"Not Found"}.
 *      FastAPI APIRoutes never add HEAD, so HEAD on a GET route is 405 `allow: GET`.
 *   4. onSend: `application/json; charset=utf-8` → `application/json`; CORS simple-response
 *      headers; the six security headers with setdefault semantics. Unhandled 500s
 *      (Python's ServerErrorMiddleware is outermost) get neither.
 *   5. Unhandled errors → 500 text/plain "Internal Server Error".
 * Node-only infrastructure (`/health/live`, `/health/ready`) bypasses the Python router.
 * Read-only: nothing here touches the database.
 */

const EDGE = Symbol('trukvia.httpEdge');
const SENTINEL = '/__trukvia_http_edge__';
const ALL_METHODS = ['DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT'];
// uvicorn h11_impl.send_400_response, byte-exact (close-delimited, no date / server / length).
const H11_BAD_REQUEST =
  'HTTP/1.1 400 Bad Request\r\ncontent-type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n' +
  'Invalid HTTP request received.';
const SERVER_ERROR_BODY = 'Internal Server Error';
const REDIRECT_SAFE = new Set(":/%#?=@[]!$&'()*+,;");
const TRUSTED_PROXY_HOSTS = new Set(['127.0.0.1']); // uvicorn FORWARDED_ALLOW_IPS default
const NODE_ONLY_PATHS = new Set(['/health/live', '/health/ready']);

export const SECURITY_HEADERS: ReadonlyArray<readonly [string, string]> = [
  ['x-content-type-options', 'nosniff'],
  ['x-frame-options', 'DENY'],
  ['referrer-policy', 'strict-origin-when-cross-origin'],
  ['strict-transport-security', 'max-age=31536000; includeSubDomains'],
  ['permissions-policy', 'camera=(), microphone=(self), geolocation=()'],
  ['content-security-policy',
    "default-src 'self' https:; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https:; " +
    "script-src 'self' 'unsafe-inline' https:; connect-src 'self' https: wss:; font-src 'self' data: https:; " +
    "frame-ancestors 'none'"],
];

type Decision =
  | { kind: 'bypass' }
  | { kind: 'h11-400' }
  | { kind: 'preflight'; status: number; body: string; headers: Array<[string, string]> }
  | { kind: 'not-found'; unserved?: string }
  | { kind: 'method-not-allowed'; allow: string }
  | { kind: 'redirect'; location: string }
  | { kind: 'serve'; nodeUrl: string; template: string };

const EDGE_ORIGIN = Symbol('trukvia.httpEdge.origin');
type EdgeMessage = IncomingMessage & { [EDGE]?: Decision; [EDGE_ORIGIN]?: string | undefined };

interface CompiledRoute { re: RegExp; methods: ReadonlySet<string> | null; path: string; norm: string }
const ROUTES: CompiledRoute[] = PYTHON_ROUTES.map(([re, methods, template]) => ({
  re: new RegExp(re),
  methods: methods ? new Set(methods) : null,
  path: '/' + template,
  norm: ('/' + template).replace(/\{[^}]*\}/g, '{}'),
}));

// ── raw header access (first / last occurrence, case-insensitive name) ──
function rawHeader(msg: IncomingMessage, name: string, which: 'first' | 'last'): string | undefined {
  const raw = msg.rawHeaders;
  let found: string | undefined;
  for (let i = 0; i + 1 < raw.length; i += 2) {
    if ((raw[i] as string).toLowerCase() === name) {
      found = raw[i + 1] as string;
      if (which === 'first') return found;
    }
  }
  return found;
}

// ── Python urllib.parse.unquote(ascii, 'utf-8', 'replace') ──
const UTF8 = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true });
const HEX = /^[0-9A-Fa-f]{2}$/;
export function pyUnquote(s: string): string {
  if (!s.includes('%')) return s;
  const bytes: number[] = [];
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c === 37 && HEX.test(s.slice(i + 1, i + 3))) {
      bytes.push(parseInt(s.slice(i + 1, i + 3), 16));
      i += 2;
    } else {
      bytes.push(c);
    }
  }
  return UTF8.decode(Uint8Array.from(bytes));
}

// ── Python urllib.parse.quote(str, safe=":/%#?=@[]!$&'()*+,;") (utf-8) ──
export function pyQuoteLocation(s: string): string {
  let out = '';
  for (const b of Buffer.from(s, 'utf8')) {
    const ch = String.fromCharCode(b);
    if ((b >= 0x30 && b <= 0x39) || (b >= 0x41 && b <= 0x5a) || (b >= 0x61 && b <= 0x7a) || '_.-~'.includes(ch) ||
      REDIRECT_SAFE.has(ch)) out += ch;
    else out += '%' + b.toString(16).toUpperCase().padStart(2, '0');
  }
  return out;
}

// Python str.strip() whitespace set (latin-1 range suffices: header values are latin-1).
const PY_WS = new Set([0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0]);
function pyStrip(s: string): string {
  let a = 0;
  let b = s.length;
  while (a < b && PY_WS.has(s.charCodeAt(a))) a++;
  while (b > a && PY_WS.has(s.charCodeAt(b - 1))) b--;
  return s.slice(a, b);
}

function clientHost(msg: IncomingMessage): string {
  const a = msg.socket?.remoteAddress ?? '';
  return a.startsWith('::ffff:') ? a.slice(7) : a;
}

export interface HttpEdgeOptions { corsOrigins: readonly string[] }

export interface HttpEdge {
  rewriteUrl: (this: unknown, req: IncomingMessage) => string;
  clientErrorHandler: (err: Error & { code?: string }, socket: Socket) => void;
  register: (app: FastifyInstance) => void;
}

/**
 * llhttp parse failures (HPE_*) reach Node before any request exists; uvicorn answers
 * every h11 RemoteProtocolError with the fixed 400 above. Header overflow and request
 * timeouts keep Fastify's default 431 / 408 (size/timing limits differ by design).
 */
function clientErrorHandler(err: Error & { code?: string }, socket: Socket): void {
  const code = err.code ?? '';
  if (code === 'ECONNRESET' || socket.destroyed) return;
  if (code.startsWith('HPE_') && code !== 'HPE_HEADER_OVERFLOW') {
    if (socket.writable) socket.end(H11_BAD_REQUEST, 'latin1'); else socket.destroy(err);
    return;
  }
  const status = code === 'ERR_HTTP_REQUEST_TIMEOUT' ? 408 : code === 'HPE_HEADER_OVERFLOW' ? 431 : 400;
  const body = JSON.stringify({ error: STATUS_CODES[status], message: 'Client Error', statusCode: status });
  if (socket.writable) {
    socket.write(`HTTP/1.1 ${String(status)} ${String(STATUS_CODES[status])}\r\nContent-Length: ${String(body.length)}` +
      `\r\nContent-Type: application/json\r\n\r\n${body}`);
  }
  socket.destroy(err);
}

export function createHttpEdge(opts: HttpEdgeOptions): HttpEdge {
  // backend/server.py: `[o.strip() for o in env.split(",") if o.strip()] or ["*"]`
  const origins = opts.corsOrigins.length > 0 ? [...opts.corsOrigins] : ['*'];
  const allowAllOrigins = origins.includes('*');
  const isAllowedOrigin = (o: string): boolean => allowAllOrigins || origins.includes(o);
  // METHOD + normalised template → Node route url (filled by onRoute before routes mount).
  const served = new Map<string, string>();

  function preflight(msg: IncomingMessage, origin: string): Decision {
    const headers: Array<[string, string]> = [];
    const set = (k: string, v: string): void => {
      const i = headers.findIndex(([n]) => n === k);
      if (i >= 0) headers[i] = [k, v]; else headers.push([k, v]);
    };
    if (!allowAllOrigins) set('vary', 'Origin'); else set('access-control-allow-origin', '*');
    set('access-control-allow-methods', ALL_METHODS.join(', '));
    set('access-control-max-age', '600');
    const failures: string[] = [];
    if (isAllowedOrigin(origin)) {
      if (!allowAllOrigins) set('access-control-allow-origin', origin);
    } else {
      failures.push('origin');
    }
    const requestedMethod = rawHeader(msg, 'access-control-request-method', 'first') ?? '';
    if (!ALL_METHODS.includes(requestedMethod)) failures.push('method');
    const requestedHeaders = rawHeader(msg, 'access-control-request-headers', 'first');
    if (requestedHeaders !== undefined) set('access-control-allow-headers', requestedHeaders);
    return failures.length > 0
      ? { kind: 'preflight', status: 400, body: 'Disallowed CORS ' + failures.join(', '), headers }
      : { kind: 'preflight', status: 200, body: 'OK', headers };
  }

  function redirectLocation(msg: IncomingMessage, path: string, query: string): string {
    let scheme = 'http';
    if (TRUSTED_PROXY_HOSTS.has(clientHost(msg))) {
      const xfp = rawHeader(msg, 'x-forwarded-proto', 'last'); // dict(scope["headers"]) → last wins
      if (xfp !== undefined) scheme = pyStrip(xfp);
    }
    const host = rawHeader(msg, 'host', 'first');
    let url: string;
    if (host !== undefined) {
      url = `${scheme}://${host}${path}`;
    } else {
      const port = msg.socket?.localPort;
      const addr = msg.socket?.localAddress ?? '';
      const def = scheme === 'https' ? 443 : 80;
      url = port === def ? `${scheme}://${addr}${path}` : `${scheme}://${addr}:${String(port)}${path}`;
    }
    if (query) url += '?' + query;
    return pyQuoteLocation(url);
  }

  function decide(msg: IncomingMessage): Decision {
    const target = msg.url ?? '/';
    const method = msg.method ?? 'GET';
    const qi = target.indexOf('?');
    const rawPath = qi >= 0 ? target.slice(0, qi) : target;
    if (NODE_ONLY_PATHS.has(rawPath)) return { kind: 'bypass' };
    // h11: request-target = vchar+ (\x21-\x7e)
    if (!/^[\x21-\x7e]+$/.test(target)) return { kind: 'h11-400' };
    // h11 Request(): HTTP/1.1 needs exactly one Host; any version rejects several.
    let hosts = 0;
    for (let i = 0; i < msg.rawHeaders.length; i += 2) if ((msg.rawHeaders[i] as string).toLowerCase() === 'host') hosts++;
    if ((msg.httpVersion === '1.1' && hosts === 0) || hosts > 1) return { kind: 'h11-400' };

    const origin = rawHeader(msg, 'origin', 'first');
    if (origin !== undefined && method === 'OPTIONS' &&
      rawHeader(msg, 'access-control-request-method', 'first') !== undefined) {
      return preflight(msg, origin);
    }

    const query = qi >= 0 ? target.slice(qi + 1) : '';
    const path = pyUnquote(rawPath);
    let partial: CompiledRoute | null = null;
    for (const r of ROUTES) {
      const m = r.re.exec(path);
      if (!m) continue;
      if (r.methods === null || r.methods.has(method)) {
        const nodeUrl = served.get(`${method} ${r.norm}`);
        if (nodeUrl === undefined) return { kind: 'not-found', unserved: `${method} ${r.path}` };
        const params = m.slice(1);
        let k = 0;
        const canonical = nodeUrl.split('/').map((seg) =>
          seg.startsWith(':') ? encodeURIComponent(params[k++] ?? '') : seg).join('/');
        return { kind: 'serve', nodeUrl: canonical + (qi >= 0 ? '?' + query : ''), template: nodeUrl };
      }
      partial ??= r;
    }
    if (partial) return { kind: 'method-not-allowed', allow: [...(partial.methods ?? [])].join(', ') };
    if (path !== '/') {
      const toggled = path.endsWith('/') ? path.replace(/\/+$/, '') : path + '/';
      if (ROUTES.some((r) => r.re.test(toggled))) {
        return { kind: 'redirect', location: redirectLocation(msg, toggled, query) };
      }
    }
    return { kind: 'not-found' };
  }

  function rewriteUrl(this: unknown, req: IncomingMessage): string {
    const msg = req as EdgeMessage;
    const d = decide(msg);
    msg[EDGE] = d;
    msg[EDGE_ORIGIN] = rawHeader(msg, 'origin', 'first');
    if (d.kind === 'bypass') return msg.url ?? '/';
    if (d.kind === 'serve') return d.nodeUrl;
    return SENTINEL;
  }

  function register(app: FastifyInstance): void {
    app.addHook('onRoute', (route: RouteOptions) => {
      const methods = Array.isArray(route.method) ? route.method : [route.method];
      const norm = route.url.split('/').map((s) => (s.startsWith(':') ? '{}' : s)).join('/');
      for (const m of methods) if (!served.has(`${m} ${norm}`)) served.set(`${m} ${norm}`, route.url);
    });

    app.addHook('onRequest', async (req: FastifyRequest, reply: FastifyReply) => {
      const msg = req.raw as EdgeMessage;
      const d = msg[EDGE];
      if (!d || d.kind === 'bypass') return;
      switch (d.kind) {
        case 'serve': {
          // Defence in depth: find-my-way must land on the route Starlette chose.
          if (req.routeOptions.url === d.template && req.routeOptions.method === req.method) return;
          req.log.warn({ expected: d.template, matched: req.routeOptions.url ?? null }, 'http_edge_route_mismatch');
          return reply.code(404).header('content-type', 'application/json').send('{"detail":"Not Found"}');
        }
        case 'h11-400': {
          reply.hijack();
          reply.raw.socket?.end(H11_BAD_REQUEST, 'latin1');
          return;
        }
        case 'preflight': {
          for (const [k, v] of d.headers) reply.header(k, v);
          return reply.code(d.status).header('content-type', 'text/plain; charset=utf-8').send(d.body);
        }
        case 'method-not-allowed':
          return reply.code(405).header('allow', d.allow).header('content-type', 'application/json')
            .send('{"detail":"Method Not Allowed"}');
        case 'redirect':
          return reply.code(307).header('location', d.location).header('content-length', '0').send();
        case 'not-found':
          if (d.unserved) req.log.warn({ python_route: d.unserved }, 'http_edge_python_route_not_served');
          return reply.code(404).header('content-type', 'application/json').send('{"detail":"Not Found"}');
      }
    });

    app.addHook('onSend', async (req: FastifyRequest, reply: FastifyReply, payload: unknown) => {
      const msg = req.raw as EdgeMessage;
      if (reply.getHeader('content-type') === 'application/json; charset=utf-8') {
        reply.header('content-type', 'application/json');
      }
      // Python's ServerErrorMiddleware 500 is produced OUTSIDE the CORS / security middlewares.
      const text = typeof payload === 'string' ? payload : Buffer.isBuffer(payload) ? payload.toString('latin1') : null;
      if (reply.statusCode === 500 && text === SERVER_ERROR_BODY &&
        reply.getHeader('content-type') === 'text/plain; charset=utf-8') return payload;
      const origin = msg[EDGE_ORIGIN];
      if (origin !== undefined && msg[EDGE]?.kind !== 'preflight') {
        if (allowAllOrigins) reply.header('access-control-allow-origin', '*');
        reply.header('access-control-expose-headers', 'Content-Disposition');
        const hasCookie = rawHeader(msg, 'cookie', 'first') !== undefined;
        if ((allowAllOrigins && hasCookie) || (!allowAllOrigins && isAllowedOrigin(origin))) {
          reply.header('access-control-allow-origin', origin);
          const vary = reply.getHeader('vary');
          reply.header('vary', vary === undefined ? 'Origin' : `${String(vary)}, Origin`);
        }
      }
      for (const [k, v] of SECURITY_HEADERS) if (!reply.hasHeader(k)) reply.header(k, v);
      return payload;
    });

    app.setNotFoundHandler((_req, reply) => {
      void reply.code(404).header('content-type', 'application/json').send('{"detail":"Not Found"}');
    });

    const fallback = app.errorHandler;
    app.setErrorHandler(function (this: FastifyInstance, err: FastifyError, req, reply) {
      const status = err.statusCode ?? (err as { status?: number }).status;
      if (typeof status === 'number' && status >= 400 && status < 500) return fallback.call(this, err, req, reply);
      req.log.error({ err }, 'unhandled_error');
      void reply.code(500).header('content-type', 'text/plain; charset=utf-8').send(SERVER_ERROR_BODY);
    });
  }

  return { rewriteUrl, clientErrorHandler, register };
}
