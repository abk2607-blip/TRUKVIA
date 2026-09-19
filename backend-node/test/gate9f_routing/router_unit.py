"""Phase 4 · Gate 9f · node_router unit checks (no servers; httpx.MockTransport as Node).

Covers the forwarding contract that the live harness can only observe indirectly:
outbound request line/headers, response header hygiene, fallback classification,
circuit breaker, single dispatch, HEAD, kill-switch caching and default-off.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "trukvia_gate9f_import_unused")
import server  # noqa: E402
import node_router  # noqa: E402

KILL = Path(tempfile.gettempdir()) / "gate9f-unit-kill"
ON = {"NODE_ROUTING_MODE": "on", "NODE_ROUTING_ROUTES": "all", "NODE_ROUTING_PERCENT": "100",
      "NODE_UPSTREAM_URL": "http://node.internal:8002", "NODE_ROUTING_KILL_FILE": str(KILL)}
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


class Inner:
    """Stands in for the Python app below the router; records dispatches."""
    def __init__(self):
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await send({"type": "http.response.start", "status": 299, "headers": [(b"x-python", b"1")]})
        await send({"type": "http.response.body", "body": b"python"})


def scope(method="GET", path="/api/vendors", qs=b"", headers=None, scheme="http"):
    return {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": qs,
            "root_path": "", "scheme": scheme, "headers": headers or []}


async def run(router, sc):
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    await router(sc, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], start["headers"], body


def make(env, handler):
    inner = Inner()
    r = node_router.NodeRouter(inner, fastapi_app=server.app, config=node_router.RouterConfig(env))
    if handler is not None:
        r._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return r, inner


async def main() -> int:
    seen: list[httpx.Request] = []

    def node_ok(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, headers=[("content-type", "application/json"), ("x-request-id", "abc"), ("date", "x"),
                                            ("server", "node"), ("connection", "keep-alive"), ("x-frame-options", "DENY"),
                                            ("vary", "Origin"), ("vary", "Accept")], content=b'[{"id":"v"}]')

    # 1. outbound request is exactly what Python received (+ trusted XFP, request id, minus hop-by-hop)
    r, inner = make(ON, node_ok)
    hdrs = [(b"host", b"api.example"), (b"authorization", b"Bearer t1"), (b"x-company-id", b"co-b"), (b"x-company-id", b"co-a"),
            (b"connection", b"keep-alive"), (b"te", b"trailers"), (b"x-forwarded-proto", b"https"), (b"x-request-id", b"spoof"),
            (b"x-forwarded-for", b"6.6.6.6"), (b"cookie", b"session_token=a; session_token=b")]
    st, h, body = await run(r, scope(path="/api/vendors", qs=b"a=1&a=2&b=%20", headers=hdrs, scheme="http"))
    q = seen[-1]
    out = [(k.lower(), v) for k, v in q.headers.raw]
    check("1 method/path/query verbatim", q.method == "GET" and q.url.raw_path == b"/api/vendors?a=1&a=2&b=%20", str(q.url))
    check("1 host = node upstream; original Host kept", (b"host", b"api.example") in out, str(out))
    check("1 duplicate X-Company-Id order kept", [v for k, v in out if k == b"x-company-id"] == [b"co-b", b"co-a"], str(out))
    check("1 hop-by-hop dropped", not any(k in (b"connection", b"te") for k, _ in out), str(out))
    check("1 XFP replaced by uvicorn scheme", [v for k, v in out if k == b"x-forwarded-proto"] == [b"http"], str(out))
    check("1 client X-Request-Id replaced", [v for k, v in out if k == b"x-request-id"] != [b"spoof"]
          and len([v for k, v in out if k == b"x-request-id"]) == 1, str(out))
    check("1 cookie/authorization passed unchanged", (b"cookie", b"session_token=a; session_token=b") in out
          and (b"authorization", b"Bearer t1") in out, "")
    check("1 response: node body/status", st == 200 and body == b'[{"id":"v"}]' and inner.calls == 0, f"{st} {body}")
    names = [k for k, _ in h]
    check("1 response: date/server/connection/x-request-id stripped", not {b"date", b"server", b"connection", b"x-request-id"} & set(names), str(names))
    check("1 response: repeated headers kept", [v for k, v in h if k == b"vary"] == [b"Origin", b"Accept"], str(h))
    # percent-encoded path kept raw (never re-encoded or decoded)
    await run(r, {**scope(path="/api/vendors/a?b"), "raw_path": b"/api/vendors/a%3Fb"})
    check("1 raw path not re-encoded", seen[-1].url.raw_path == b"/api/vendors/a%3Fb", str(seen[-1].url.raw_path))

    # 2. HEAD forwarded as HEAD
    await run(r, scope(method="HEAD"))
    check("2 HEAD forwarded as HEAD", seen[-1].method == "HEAD", seen[-1].method)

    # 3. genuine Node statuses returned as-is — single dispatch, no fallback
    for code in (400, 401, 404, 405, 422, 500):
        r3, inner3 = make(ON, lambda req, c=code: httpx.Response(c, content=b"node"))
        st, _h, body = await run(r3, scope())
        check(f"3 genuine node {code} passthrough", st == code and body == b"node" and inner3.calls == 0, f"{st} {inner3.calls}")

    # 4. infrastructure failures → Python fallback (exactly one Python dispatch)
    def boom(exc):
        def h(req):
            raise exc
        return h
    for label, handler in [("connect error", boom(httpx.ConnectError("x"))), ("connect timeout", boom(httpx.ConnectTimeout("x"))),
                           ("read timeout", boom(httpx.ReadTimeout("x"))), ("protocol error", boom(httpx.RemoteProtocolError("x"))),
                           ("502", lambda req: httpx.Response(502)), ("503", lambda req: httpx.Response(503)),
                           ("504", lambda req: httpx.Response(504)), ("431", lambda req: httpx.Response(431))]:
        r4, inner4 = make(ON, handler)
        st, _h, body = await run(r4, scope())
        check(f"4 fallback on {label}", st == 299 and body == b"python" and inner4.calls == 1, f"{st} {inner4.calls}")

    # 5. circuit breaker: 5 consecutive infra failures open the circuit (Node not contacted)
    hits = []

    def failing(req):
        hits.append(1)
        raise httpx.ConnectError("down")
    r5, inner5 = make(ON, failing)
    for _ in range(9):
        await run(r5, scope())
    check("5 circuit opens after 5 failures", len(hits) == 5 and inner5.calls == 9, f"node hits={len(hits)} python={inner5.calls}")

    # 6. kill switch file, default-off, non-GET, not-eligible
    KILL.write_text("1")
    try:
        r6, inner6 = make(ON, node_ok)
        before = len(seen)
        await run(r6, scope())
        check("6 kill switch → python", inner6.calls == 1 and len(seen) == before, "")
    finally:
        KILL.unlink()
    r7, inner7 = make({}, node_ok)
    before = len(seen)
    for sc in (scope(), scope(method="POST"), scope(path="/api/trips")):
        await run(r7, sc)
    check("6 default env: nothing forwarded", inner7.calls == 3 and len(seen) == before, "")
    r8, inner8 = make(ON, node_ok)
    before = len(seen)
    for sc in (scope(method="POST"), scope(method="PUT", path="/api/vendors/v1"), scope(path="/api/trips"),
               scope(path="/api/auth/me"), scope(path="/api/vendors/"), scope(method="OPTIONS")):
        await run(r8, sc)
    check("6 writers/deferred/unmigrated/trailing-slash never forwarded", inner8.calls == 6 and len(seen) == before, "")

    passed = sum(ok for _, ok, _ in results)
    print("=" * 80 + "\nPHASE 4 · GATE 9f · node_router UNIT CHECKS\n" + "=" * 80)
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"  — {detail[:200]}"))
    print("-" * 80 + f"\n  checks: {len(results)}  passed: {passed}  failed: {len(results) - passed}\n" + "=" * 80)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
