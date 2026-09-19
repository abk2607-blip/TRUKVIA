"""Phase 4 · Gate 9f · Node migration router (infrastructure only — NO business logic).

Architecture (verified against the repository/platform):
  The production ingress (Emergent / Kubernetes, platform-managed, NOT in this
  repository) sends every `/api/*` request to this Python process (uvicorn
  :8001, supervisord program `backend`). Python therefore stays the front
  door and forwards ONLY frozen-allowlist GET/HEAD requests to the Node
  backend on a private upstream. Everything else is served by Python exactly
  as before.

Safety properties:
  * DEFAULT OFF. Nothing is forwarded unless NODE_ROUTING_MODE=on AND the
    route is listed in NODE_ROUTING_ROUTES AND the request's stable bucket is
    below NODE_ROUTING_PERCENT (all three default to "nothing").
  * Kill switch: if the file NODE_ROUTING_KILL_FILE exists, every request is
    served by Python (checked on every request, cached <= 1 s). No restart.
  * Only routes in backend-node/.migration-allowlist are eligible; entries in
    .migration-deferred are never eligible. The eligibility test uses
    Starlette's OWN router: a request is forwarded only when the FIRST route
    Python itself would dispatch it to (FULL match for GET) is an allowlisted
    route — no prefix matching, no catch-all, never a writer or an
    unmigrated read, and a Python-owned route never reaches Node.
  * Startup validation: every allowlist entry must map to exactly one Python
    GET route; otherwise routing is disabled (fail-safe Python) and logged.
  * Fallback: infrastructure failures (connect error/timeout, read timeout,
    protocol error, open circuit, Node 502/503/504/431) → the request is
    served by Python in-process. A genuine Node response (any other status,
    including 4xx and 500) is returned as-is — never re-dispatched (the
    ApprovalGate double-dispatch is not reproduced).
  * The request reaches Node exactly as Python received it: raw path + raw
    query, raw headers in order with duplicates (auth, X-Company-Id, Origin
    semantics preserved). X-Forwarded-Proto is replaced by the scheme uvicorn
    resolved for this request (so Node, which trusts only 127.0.0.1, sees the
    same scheme Python would), hop-by-hop headers are dropped, and a fresh
    X-Request-Id is attached for correlation.
  * Response: hop-by-hop, `date`, `server` and Node's `x-request-id` are
    dropped; uvicorn adds its own `date` / `server: uvicorn` exactly as for a
    Python response.
  * Observability: one structured `node_router` log line per routed decision
    (request id, method, route template, target, status, latency, reason).
    Never logs headers, cookies, tokens, query strings or bodies.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import httpx
from starlette.routing import Match

logger = logging.getLogger("node_router")


class _UpstreamRequestLogFilter(logging.Filter):
    """Gate 9g F3: httpx logs 'HTTP Request: <METHOD> <full URL incl. query> ...' at INFO.
    Drop ONLY those records for the Node upstream (other httpx users keep their logging);
    the router's own `node_router` line already records request id / route / target /
    status / latency / reason without the query string."""

    def __init__(self, upstream: str) -> None:
        super().__init__()
        self.prefix = upstream.rstrip("/") + "/"

    def filter(self, record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith("HTTP Request:"):
            return True
        args = record.args if isinstance(record.args, tuple) else ()
        return not (len(args) >= 2 and str(args[1]).startswith(self.prefix))


_filtered_upstreams: set[str] = set()


def _suppress_upstream_request_logs(upstream: str) -> None:
    if upstream not in _filtered_upstreams:
        logging.getLogger("httpx").addFilter(_UpstreamRequestLogFilter(upstream))
        _filtered_upstreams.add(upstream)

HOP_BY_HOP = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization", b"te", b"trailer",
              b"transfer-encoding", b"upgrade", b"proxy-connection"}
DROP_FROM_NODE = HOP_BY_HOP | {b"date", b"server", b"x-request-id"}
INFRA_STATUS = {502, 503, 504, 431}
REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_list(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _norm_node(path: str) -> str:
    return "/".join("{}" if seg.startswith(":") else seg for seg in path.split("/"))


def _norm_py(path: str) -> str:
    import re
    return re.sub(r"\{[^}]*\}", "{}", path)


class RouterConfig:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        e = os.environ if env is None else env
        self.mode = (e.get("NODE_ROUTING_MODE") or "off").strip().lower()
        self.upstream = (e.get("NODE_UPSTREAM_URL") or "http://127.0.0.1:8002").strip().rstrip("/")
        raw_routes = (e.get("NODE_ROUTING_ROUTES") or "").strip()
        self.routes_all = raw_routes == "all"
        self.routes = set() if self.routes_all else {r.strip() for r in raw_routes.split(",") if r.strip()}
        try:
            self.percent = max(0, min(100, int((e.get("NODE_ROUTING_PERCENT") or "0").strip())))
        except ValueError:
            self.percent = 0
        self.kill_file = Path(e.get("NODE_ROUTING_KILL_FILE") or str(REPO_ROOT / "backend" / ".node-routing-kill"))
        self.allowlist_path = Path(e.get("NODE_ALLOWLIST_PATH") or str(REPO_ROOT / "backend-node" / ".migration-allowlist"))
        self.deferred_path = Path(e.get("NODE_DEFERRED_PATH") or str(REPO_ROOT / "backend-node" / ".migration-deferred"))
        try:
            self.connect_timeout = float(e.get("NODE_ROUTING_CONNECT_TIMEOUT_S") or "0.5")
            self.read_timeout = float(e.get("NODE_ROUTING_READ_TIMEOUT_S") or "15")
        except ValueError:
            self.connect_timeout, self.read_timeout = 0.5, 15.0
        self.circuit_failures = 5
        self.circuit_cooldown_s = 30.0

    @property
    def enabled(self) -> bool:
        return self.mode == "on" and self.percent > 0 and (self.routes_all or bool(self.routes))


class NodeRouter:
    """Pure ASGI middleware. Installed OUTERMOST (after every other middleware)."""

    def __init__(self, app: Any, fastapi_app: Any, config: RouterConfig | None = None) -> None:
        self.app = app
        self.fastapi_app = fastapi_app
        self.cfg = config or RouterConfig()
        self.eligible: dict[int, str] | None = None  # id(route) -> allowlist template (Node spelling)
        self.disabled_reason: str | None = None if self.cfg.enabled else "routing off (default)"
        self._kill_cached_at = 0.0
        self._kill_cached = False
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._client: httpx.AsyncClient | None = None
        self.counters: dict[str, int] = {"python": 0, "node": 0, "fallback": 0, "killed": 0}

    # ── configuration / validation ────────────────────────────────────────
    def _build_eligible(self) -> None:
        if self.eligible is not None:
            return
        self.eligible = {}
        if not self.cfg.enabled:
            return
        try:
            allow = _read_list(self.cfg.allowlist_path)
            deferred = set(_read_list(self.cfg.deferred_path))
        except OSError as exc:
            self.disabled_reason = f"allowlist unreadable: {exc.__class__.__name__}"
            logger.error(json.dumps({"event": "node_router_disabled", "reason": self.disabled_reason}))
            return
        by_norm: dict[str, list[Any]] = {}
        for r in self.fastapi_app.router.routes:
            methods = getattr(r, "methods", None) or set()
            if "GET" in methods and hasattr(r, "path"):
                by_norm.setdefault(_norm_py(r.path), []).append(r)
        eligible: dict[int, str] = {}
        problems: list[str] = []
        for tpl in allow:
            if tpl in deferred:
                problems.append(f"{tpl}: listed as deferred")
                continue
            if not self.cfg.routes_all and tpl not in self.cfg.routes:
                continue
            matches = by_norm.get(_norm_node(tpl), [])
            if len(matches) != 1:
                problems.append(f"{tpl}: {len(matches)} Python GET routes")
                continue
            eligible[id(matches[0])] = tpl
        unknown = [r for r in self.cfg.routes if r not in allow]
        if unknown:
            problems.append(f"NODE_ROUTING_ROUTES not on the frozen allowlist: {sorted(unknown)}")
        if problems:
            self.disabled_reason = "; ".join(problems)
            logger.error(json.dumps({"event": "node_router_disabled", "reason": self.disabled_reason}))
            return
        self.eligible = eligible
        self.disabled_reason = None
        logger.info(json.dumps({"event": "node_router_enabled", "routes": len(eligible), "percent": self.cfg.percent,
                                "upstream": self.cfg.upstream}))

    def _killed(self) -> bool:
        now = time.monotonic()
        if now - self._kill_cached_at > 1.0:
            self._kill_cached = self.cfg.kill_file.exists()
            self._kill_cached_at = now
        return self._kill_cached

    # ── decision ──────────────────────────────────────────────────────────
    def route_for(self, scope: dict) -> str | None:
        """Allowlist template of the route Python would dispatch this GET/HEAD to, if eligible."""
        self._build_eligible()
        if not self.eligible:
            return None
        probe = dict(scope)
        probe["method"] = "GET"  # HEAD is eligible exactly when GET would hit an allowlisted route
        for r in self.fastapi_app.router.routes:
            m, _ = r.matches(probe)
            if m == Match.FULL:
                return self.eligible.get(id(r))
        return None

    def bucket(self, scope: dict, template: str) -> int:
        token = b""
        for k, v in scope.get("headers") or []:
            if k in (b"authorization", b"cookie"):
                token += v
                break
        h = hashlib.sha256(token + b"|" + template.encode()).digest()
        return int.from_bytes(h[:4], "big") % 100

    def decide(self, scope: dict) -> tuple[str, str | None, str]:
        """(target, template, reason) where target is 'python' or 'node'."""
        if scope.get("type") != "http" or scope.get("method") not in ("GET", "HEAD"):
            return "python", None, "method"
        if not self.cfg.enabled:
            return "python", None, "off"
        if self._killed():
            return "python", None, "kill-switch"
        tpl = self.route_for(scope)
        if tpl is None:
            return "python", None, "not-eligible" if self.disabled_reason is None else "disabled"
        if self.bucket(scope, tpl) >= self.cfg.percent:
            return "python", tpl, "percent"
        if time.monotonic() < self._circuit_open_until:
            return "python", tpl, "circuit-open"
        return "node", tpl, "eligible"

    # ── ASGI ──────────────────────────────────────────────────────────────
    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not self.cfg.enabled:
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        target, tpl, reason = self.decide(scope)
        if target == "python":
            if reason == "kill-switch":
                self.counters["killed"] += 1
            if tpl is not None or reason == "kill-switch":
                self._log(scope, None, tpl, "python", None, t0, reason)
            self.counters["python"] += 1
            await self.app(scope, receive, send)
            return
        rid = str(uuid.uuid4())
        try:
            status, headers, body = await self._forward(scope, rid)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            self._infra_failure()
            self.counters["fallback"] += 1
            self._log(scope, rid, tpl, "python-fallback", None, t0, exc.__class__.__name__)
            await self.app(scope, receive, send)
            return
        if status in INFRA_STATUS:
            self._infra_failure()
            self.counters["fallback"] += 1
            self._log(scope, rid, tpl, "python-fallback", status, t0, f"node-{status}")
            await self.app(scope, receive, send)
            return
        self._consecutive_failures = 0
        self.counters["node"] += 1
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
        self._log(scope, rid, tpl, "node", status, t0, "eligible")

    def _infra_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.cfg.circuit_failures:
            self._circuit_open_until = time.monotonic() + self.cfg.circuit_cooldown_s
            self._consecutive_failures = 0
            logger.warning(json.dumps({"event": "node_router_circuit_open", "cooldown_s": self.cfg.circuit_cooldown_s}))

    async def _forward(self, scope: dict, rid: str) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        _suppress_upstream_request_logs(self.cfg.upstream)
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.cfg.read_timeout, connect=self.cfg.connect_timeout),
                follow_redirects=False, trust_env=False, http2=False)
        raw_path: bytes = scope.get("raw_path") or scope["path"].encode("latin-1")
        qs: bytes = scope.get("query_string") or b""
        target = raw_path + (b"?" + qs if qs else b"")
        url = httpx.URL(self.cfg.upstream).copy_with(raw_path=target)
        headers: list[tuple[bytes, bytes]] = []
        for k, v in scope.get("headers") or []:
            if k in HOP_BY_HOP or k in (b"x-forwarded-proto", b"x-request-id", b"content-length"):
                continue
            headers.append((k, v))
        headers.append((b"x-forwarded-proto", str(scope.get("scheme", "http")).encode("latin-1")))
        headers.append((b"x-request-id", rid.encode()))
        # A bare Request (not client.build_request): no client default headers
        # (accept / accept-encoding / connection / user-agent) are merged in.
        req = httpx.Request(scope["method"], url, headers=headers)
        resp = await self._client.send(req)
        try:
            body = await resp.aread()
        finally:
            await resp.aclose()
        out = [(k.lower(), v) for k, v in resp.headers.raw if k.lower() not in DROP_FROM_NODE]
        return resp.status_code, out, body

    def _log(self, scope: dict, rid: str | None, tpl: str | None, target: str, status: int | None,
             t0: float, reason: str) -> None:
        logger.info(json.dumps({
            "event": "node_router", "request_id": rid, "method": scope.get("method"), "route": tpl,
            "target": target, "status": status, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "reason": reason,
        }))


def install_node_router(fastapi_app: Any, config: RouterConfig | None = None) -> None:
    """Attach the router as the OUTERMOST user middleware. Call after every other add_middleware."""
    fastapi_app.add_middleware(NodeRouter, fastapi_app=fastapi_app, config=config)


def routing_matrix(fastapi_app: Any, cases: Iterable[tuple[str, str]], env: dict[str, str]) -> list[tuple[str, str, str, str | None]]:
    """Test helper: [(method, path, target, template)] for (method, raw_path?query) cases."""
    r = NodeRouter(app=None, fastapi_app=fastapi_app, config=RouterConfig(env))
    out = []
    for method, target in cases:
        path, _, qs = target.partition("?")
        from urllib.parse import unquote
        scope = {"type": "http", "method": method, "path": unquote(path), "raw_path": path.encode("latin-1"),
                 "query_string": qs.encode("latin-1"), "root_path": "", "headers": [], "scheme": "http"}
        t, tpl, _ = r.decide(scope)
        out.append((method, target, t, tpl))
    return out
