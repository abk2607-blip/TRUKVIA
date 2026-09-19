"""Phase 4 · Gate 9f · live routing harness (throwaway DB, local processes only).

  P_off  uvicorn :8320  routing unset (today's production default)
  P_on   uvicorn :8321  NODE_ROUTING_MODE=on, ROUTES=all, PERCENT=100 → Node :8322
  NODE   node dist/server.js :8322 (127.0.0.1 only)

Proves, with the real Python app in front:
  1. every frozen-allowlist route (GET + HEAD, several identities, CORS) is served
     by Node through P_on AND the response head/body is identical to P_off;
  2. writers / deferred / unmigrated reads / unknown / trailing-slash requests are
     NEVER forwarded;
  3. a genuine Node 500 is returned as-is (no fallback, no double dispatch);
  4. kill switch file → Python immediately, no restart;
  5. Node down → Python fallback, then the circuit opens;
  6. Node DB operations are reads only (profiler by appName).
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate9f_live_{int(time.time())}"
P_OFF, P_ON, NODE = 8320, 8321, 8322
PY_APP, NODE_APP = "trukvia-gate9f-py", "trukvia-gate9f-node"
TMP = Path(tempfile.gettempdir())
KILL = TMP / "gate9f-live-kill"
LOG_ON = TMP / "gate9f_p_on.log"

_spec = importlib.util.spec_from_file_location("g9c", HERE.parent / "gate9c_parity" / "harness.py")
g9c = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(g9c)  # type: ignore[union-attr]
ROUTES = g9c.ALLOWLIST_ROUTES


def req(port, method, target, hdr=()):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    h = b"".join(f"{k}: {v}\r\n".encode("latin-1") for k, v in hdr)
    s.sendall(method.encode() + b" " + target.encode("latin-1") + b" HTTP/1.1\r\nHost: api.example\r\nConnection: close\r\n" + h + b"\r\n")
    out = b""
    while True:
        c = s.recv(1 << 20)
        if not c:
            break
        out += c
    s.close()
    head, _, body = out.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    hs = []
    chunked = False
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        k = k.strip().lower(); v = v.strip()
        if k == "transfer-encoding":
            chunked = "chunked" in v.lower(); continue
        if k in ("date", "connection"):
            continue
        hs.append((k, v))
    if chunked:
        o, r = b"", body
        while r:
            n_, _, r = r.partition(b"\r\n"); n = int(n_.split(b";")[0] or b"0", 16)
            if n == 0:
                break
            o += r[:n]; r = r[n + 2:]
        body = o
    return lines[0], sorted(hs), body


class Log:
    def __init__(self, path):
        self.path, self.pos = path, 0

    def new(self):
        time.sleep(0.05)
        data = self.path.read_bytes()[self.pos:] if self.path.exists() else b""
        self.pos += len(data)
        out = []
        for ln in data.decode("utf-8", "replace").splitlines():
            i = ln.find('{"event": "node_router')
            if i >= 0:
                try:
                    ev = json.loads(ln[i:])
                except ValueError:
                    continue
                if ev.get("event") == "node_router":  # per-request decisions only
                    out.append(ev)
        return out


def wait(port):
    for _ in range(480):
        try:
            socket.create_connection(("127.0.0.1", port), 1).close(); return True
        except OSError:
            time.sleep(0.25)
    return False


async def main() -> int:
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    procs = {}
    results: dict[str, list[bool]] = {}
    fails: list[str] = []

    def rec(group, ok, msg):
        results.setdefault(group, []).append(bool(ok))
        if not ok:
            fails.append(f"{group}: {msg}")

    try:
        seeds = g9c.seed_docs()
        seeds["user_sessions"].append(g9c.sess("tok-500", "u-noemail"))
        seeds["users"].append({"user_id": "u-noemail", "name": "no email"})
        for coll, rows in seeds.items():
            if rows:
                await d[coll].insert_many([dict(r) for r in rows])
        if KILL.exists():
            KILL.unlink()
        base = os.environ.copy()
        base.update({"DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0", "DISABLE_SCHEDULER": "1",
                     "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        for k in ("CORS_ORIGINS", "NODE_ROUTING_MODE", "NODE_ROUTING_ROUTES", "NODE_ROUTING_PERCENT"):
            base.pop(k, None)
        env_off = {**base, "MONGO_URL": f"{MONGO}/?appName={PY_APP}-off"}
        env_on = {**base, "MONGO_URL": f"{MONGO}/?appName={PY_APP}-on", "NODE_ROUTING_MODE": "on", "NODE_ROUTING_ROUTES": "all",
                  "NODE_ROUTING_PERCENT": "100", "NODE_UPSTREAM_URL": f"http://127.0.0.1:{NODE}", "NODE_ROUTING_KILL_FILE": str(KILL)}
        env_node = {**os.environ, "NODE_ENV": "production", "NODE_LOG_LEVEL": "warn", "NODE_PORT": str(NODE), "NODE_HOST": "127.0.0.1",
                    "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                    "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "true"}

        def start_py(name, port, env, log):
            return subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port),
                                     "--log-level", "warning", "--no-access-log"], cwd=REPO / "backend", env=env,
                                    stdout=open(log, "wb"), stderr=subprocess.STDOUT)

        def start_node():
            return subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=REPO / "backend-node", env=env_node,
                                    stdout=open(TMP / "gate9f_node.log", "wb"), stderr=subprocess.STDOUT)

        procs["off"] = start_py("off", P_OFF, env_off, TMP / "gate9f_p_off.log")
        procs["on"] = start_py("on", P_ON, env_on, LOG_ON)
        procs["node"] = start_node()
        if not all(wait(p) for p in (P_OFF, P_ON, NODE)):
            print("servers did not start"); return 2
        await asyncio.sleep(8)
        # readiness (Node): mongo + all allowlisted routes registered
        st, _h, body = req(NODE, "GET", "/health/ready")
        ready = json.loads(body)
        rec("0 node readiness", "200" in st and ready["checks"]["routes"] == "ok"
            and ready["checks"]["allowlisted_routes"] == 66 == ready["checks"]["registered_routes"], body[:200])
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await d.command({"profile": 2})
        log = Log(LOG_ON)
        log.new()

        OWN = [("Authorization", "Bearer tok-owner")]
        # 1. allowlisted routes through P_on == P_off, and served by Node
        for name, target in ROUTES:
            for method, hdr in (("GET", OWN), ("HEAD", OWN), ("GET", [("Authorization", "Bearer tok-acc")]),
                                ("GET", [("Authorization", "Bearer tok-view"), ("Origin", "https://app.example")]),
                                ("GET", OWN + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")]), ("GET", [])):
                a = req(P_OFF, method, target, hdr)
                b = req(P_ON, method, target, hdr)
                lines = log.new()
                rec("1 allowlisted via P_on == P_off", a == b, f"{method} {target} {a[0]} vs {b[0]} "
                    f"py-only={sorted(set(a[1]) - set(b[1]))[:3]} on-only={sorted(set(b[1]) - set(a[1]))[:3]}")
                rec("1 allowlisted served by Node", [x["target"] for x in lines] == ["node"], f"{method} {target} {lines}")
        # 2. never forwarded: writers, deferred, unmigrated reads, unknown, trailing slash, non-/api
        never = [("POST", "/api/vendors"), ("PUT", "/api/vendors/v-b"), ("DELETE", "/api/vendors/v-b"), ("PATCH", "/api/company"),
                 ("POST", "/api/expenses"), ("POST", "/api/saved-trip-filters"), ("GET", "/api/saved-trip-filters"),
                 ("GET", "/api/trips"), ("GET", "/api/trips/trip-b"), ("GET", "/api/invoices"), ("GET", "/api/expenditure-types"),
                 ("GET", "/api/auth/me"), ("GET", "/api/companies"), ("GET", "/api/customers"), ("GET", "/api/drivers"),
                 ("GET", "/api/dashboard/summary"), ("GET", "/api/vendors/"), ("GET", "/api//vendors"), ("GET", "/api/nope"),
                 ("GET", "/api/vendors/a%2Fb"), ("OPTIONS", "/api/vendors"), ("GET", "/"), ("GET", "/docs"), ("HEAD", "/api/trips")]
        for method, target in never:
            a = req(P_OFF, method, target)
            b = req(P_ON, method, target)
            lines = log.new()
            rec("2 never forwarded", all(x["target"] != "node" for x in lines), f"{method} {target} {lines}")
            rec("2 unforwarded response unchanged", a[0] == b[0], f"{method} {target} {a[0]} vs {b[0]}")
        # 3. genuine Node 500 returned as-is (single dispatch, no fallback)
        for _name, target in ROUTES[:10]:
            if target.startswith("/api/files") or target.startswith("/api/gstin") or target == "/api/":
                continue
            a = req(P_OFF, "GET", target, [("Authorization", "Bearer tok-500")])
            b = req(P_ON, "GET", target, [("Authorization", "Bearer tok-500")])
            lines = log.new()
            rec("3 genuine Node 500 passthrough", a == b and "500" in b[0] and [(x["target"], x["status"]) for x in lines] == [("node", 500)],
                f"{target} {b[0]} {lines}")
        # 3b. parser/ingress normalisation: h11 (Python's parser) sees EVERY request first, so the
        #     llhttp grammar gaps from Gate 9d cannot occur on the routed path.
        def raw(port, data):
            s = socket.create_connection(("127.0.0.1", port), timeout=30)
            s.sendall(data)
            out = b""
            while True:
                c = s.recv(1 << 20)
                if not c:
                    break
                out += c
            s.close()
            head, _, body = out.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            keep = sorted(ln.lower() for ln in lines[1:] if not ln.lower().startswith((b"date:", b"connection:")))
            return lines[0] + b"\r\n" + b"\r\n".join(keep), body  # header SET (order is not semantic)
        big = "x" * 17000
        parser_cases = [
            ("obs-fold continuation on an allowlisted GET (forwarded, value normalised by h11)", True,
             b"GET /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\nAuthorization: Bearer tok-owner\r\n"
             b"X-Company-Id: co-b\r\n  co-a\r\n\r\n"),
            ("unknown token method FOO (Python 405, never forwarded)", False,
             b"FOO /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"),
            ("lower-case method get (Python 405, never forwarded)", False,
             b"get /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"),
            ("17 KB request target in one packet (h11 decides; forwarded head exceeds Node's 16 KB → fallback)", None,
             f"GET /api/vendors?pad={big} HTTP/1.1\r\nHost: h\r\nConnection: close\r\nAuthorization: Bearer tok-owner\r\n\r\n".encode()),
            ("non-ASCII target (h11 400, never forwarded)", False,
             b"GET /api/vendors/\xc3\xa9 HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"),
        ]
        for label, forwarded, data in parser_cases:
            a, b = raw(P_OFF, data), raw(P_ON, data)
            lines = log.new()
            targets = [x["target"] for x in lines]
            ok = a == b and (forwarded is None or (targets == ["node"]) == forwarded)
            rec("3b parser gaps closed by h11 in front", ok, f"{label}: {a[0][:60]!r} vs {b[0][:60]!r} targets={targets}")
        # 3c. client-supplied X-Forwarded-Proto never changes a routed response
        for xfp in ("https", "javascript", "https, http"):
            a = req(P_OFF, "GET", "/api/vendors", OWN + [("X-Forwarded-Proto", xfp), ("X-Forwarded-For", "6.6.6.6")])
            b = req(P_ON, "GET", "/api/vendors", OWN + [("X-Forwarded-Proto", xfp), ("X-Forwarded-For", "6.6.6.6")])
            rec("3c forwarded headers untrusted", a == b and [x["target"] for x in log.new()] == ["node"], f"{xfp}")
        # 4. kill switch: immediate, no restart
        KILL.write_text("kill")
        time.sleep(1.2)
        for _name, target in ROUTES[:20]:
            a = req(P_OFF, "GET", target, OWN)
            b = req(P_ON, "GET", target, OWN)
            lines = log.new()
            rec("4 kill switch → Python", a == b and [x["reason"] for x in lines] == ["kill-switch"]
                and all(x["target"] == "python" for x in lines), f"{target} {lines}")
        KILL.unlink()
        time.sleep(1.2)
        b = req(P_ON, "GET", "/api/vendors", OWN)
        rec("4 kill switch removed → Node again", [x["target"] for x in log.new()] == ["node"], "re-enable")
        # 5. Node down → fallback to Python, then circuit opens
        procs["node"].send_signal(signal.SIGTERM); procs["node"].wait(timeout=10)
        seen = []
        for i, (_name, target) in enumerate(ROUTES[:12]):
            a = req(P_OFF, "GET", target, OWN)
            b = req(P_ON, "GET", target, OWN)
            lines = log.new()
            seen += [(x["target"], x["reason"]) for x in lines]
            rec("5 node down → same response as Python", a == b, f"{target} {a[0]} vs {b[0]}")
        fallbacks = [s for s in seen if s[0] == "python-fallback"]
        opened = [s for s in seen if s == ("python", "circuit-open")]
        rec("5 fallback then circuit-open", len(fallbacks) == 5 and len(opened) == 7, f"{seen}")

        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        writes = [p for p in prof if p.get("op") in ("insert", "update", "remove") or
                  next(iter(p.get("command") or {}), "") in ("insert", "update", "delete", "findAndModify", "createIndexes")]
        rec("6 node reads only", not writes, f"writes={len(writes)}")
        total = sum(len(v) for v in results.values()); passed = sum(sum(v) for v in results.values())
        print("=" * 90 + "\nPHASE 4 · GATE 9f · LIVE ROUTING HARNESS (P_off vs P_on→Node)\n" + "=" * 90)
        for g, v in results.items():
            print(f"  {g}: {sum(v)}/{len(v)}")
        for f in fails[:30]:
            print("  [FAIL]", f[:300])
        print(f"  node DB ops (during matrix): {len(prof)}  writes: {len(writes)}")
        print("-" * 90 + f"\n  checks: {total}  passed: {passed}  failed: {total - passed}\n" + "=" * 90)
        return 0 if passed == total else 1
    finally:
        for p in procs.values():
            if p.poll() is None:
                try:
                    p.send_signal(signal.SIGTERM); p.wait(timeout=8)
                except Exception:
                    p.kill()
        if KILL.exists():
            KILL.unlink()
        try:
            await d.command({"profile": 0})
        except Exception:
            pass
        await cli.drop_database(DB)
        print(f"[gate9f] dropped {DB}; leftover: {[x for x in await cli.list_database_names() if x.startswith('trukvia_gate9f_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
