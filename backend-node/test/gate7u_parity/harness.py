"""Phase 3 · Gate 7u · live Python↔Node parity harness for the API root ping.

Covers:
  * GET /api/   (backend/server.py::root, L92-94)

Python: no auth dependency, no DB access, constant JSONResponse.
Comparison is BYTE-EXACT on the body and EXACT on status, the full
content-type header and content-length. Each request's DB operations are
counted for BOTH servers (profiler, appName-attributed) — expected 0.

Informational (framework gate, NOT counted): GET /api (no trailing slash,
Starlette 307 redirect), POST /api/ (Starlette 405), and the global security
headers Python's middleware adds to every response.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7u_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7u-py", "trukvia-gate7u-node"
PY_PORT, NODE_PORT = 8262, 8263
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "audit_logs", "save_health", "idempotency_keys", "trips"]


def raw(port: int, method: str, path: str, hdr: dict[str, str]):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.putrequest(method, path, skip_accept_encoding=True)
    for k, v in hdr.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    headers = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, headers, body


def wait(port: int, path: str, timeout: int = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if raw(port, "GET", path, {})[0] < 500:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def stop(p):
    if p and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM); p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


CASES = [
    ("GET", "/api/", {}, "plain"),
    ("GET", "/api/", {"Authorization": "Bearer tok-u1"}, "valid bearer"),
    ("GET", "/api/", {"Authorization": "Bearer nope"}, "invalid bearer"),
    ("GET", "/api/", {"Cookie": "session_token=tok-u1"}, "session cookie"),
    ("GET", "/api/?x=1", {}, "query string"),
    ("GET", "/api/?x=1&x=2&limit=abc", {}, "repeated / junk query"),
    ("GET", "/api/?", {}, "empty query"),
    ("GET", "/api/", {"X-Company-Id": "co-zzz", "Accept": "text/html", "Idempotency-Key": "k-12345678",
                     "X-Request-Id": "rid-1", "Origin": "https://example.test"}, "irrelevant headers"),
    ("HEAD", "/api/", {}, "HEAD"),
] + [("GET", "/api/", {}, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", "/api", "no trailing slash"), ("POST", "/api/", "POST method")]
SEC_HEADERS = ["x-content-type-options", "x-frame-options", "referrer-policy", "strict-transport-security",
               "content-security-policy", "permissions-policy"]


async def run() -> int:
    print(f"[gate7u] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        now = datetime.now(timezone.utc)
        await d.user_sessions.insert_one({"session_token": "tok-u1", "user_id": "u1", "effective_role": "owner",
                                          "expires_at": (now + timedelta(hours=2)).isoformat(), "last_refreshed_at": now.isoformat()})
        await d.users.insert_one({"user_id": "u1", "email": "u1@x", "name": "U1"})
        await d.companies.insert_one({"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"})
        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate7u_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate7u_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            return 2
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=16 * 1024 * 1024)
        await d.command({"profile": 2})

        passed = failed = 0
        rows = []
        for method, path, hdr, desc in CASES:
            n_py0 = await d["system.profile"].count_documents({"appName": PY_APP})
            h0 = (await d.command("dbHash", collections=TRACKED))["collections"]
            rp = raw(PY_PORT, method, path, hdr)
            await asyncio.sleep(0.15)
            n_py1 = await d["system.profile"].count_documents({"appName": PY_APP})
            n_nd0 = await d["system.profile"].count_documents({"appName": NODE_APP})
            rn = raw(NODE_PORT, method, path, hdr)
            await asyncio.sleep(0.15)
            n_nd1 = await d["system.profile"].count_documents({"appName": NODE_APP})
            h1 = (await d.command("dbHash", collections=TRACKED))["collections"]
            changed = [k for k in TRACKED if h0.get(k) != h1.get(k)]
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length"))
            ok = same and n_nd1 - n_nd0 == 0 and not changed
            passed += ok; failed += (not ok)
            rows.append((ok, desc, method, path, rp, rn, n_py1 - n_py0, n_nd1 - n_nd0, changed))

        info = []
        for method, path, desc in INFO:
            rp = raw(PY_PORT, method, path, {}); rn = raw(NODE_PORT, method, path, {})
            info.append((desc, method, path, rp, rn))
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        wn = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
        node_writes = [p for p in prof if p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in wn]

        print("\n" + "=" * 78 + "\nPHASE 3 · GATE 7u · LIVE PARITY (GET /api/) — BYTE-EXACT + FULL CONTENT-TYPE\n" + "=" * 78)
        for ok, desc, method, path, rp, rn, dpy, dnd, changed in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {path:28} {desc:22} py={rp[0]} node={rn[0]} "
                  f"ctype py={rp[1].get('content-type')!r} node={rn[1].get('content-type')!r} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} db py={dpy} node={dnd} changed={changed or 'none'}")
            if not ok:
                print(f"        py  : {rp[2]!r}\n        node: {rn[2]!r}")
        zero_ok = not node_writes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node profiled ops during matrix={len(prof)} writes={len(node_writes)}")
        print(f"  body bytes (both): {rows[0][4][2]!r}")
        print("-" * 78 + f"\n  cases: {len(rows) + 1}   passed: {passed}   failed: {failed}")
        print("  informational (framework gate — NOT counted):")
        for desc, method, path, rp, rn in info:
            print(f"    {method:4} {path:6} ({desc}): py={rp[0]} {rp[2][:60]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r} | node={rn[0]} {rn[2][:60]!r}")
        sec = {h: (rows[0][4][1].get(h) is not None, rows[0][5][1].get(h) is not None) for h in SEC_HEADERS}
        print(f"    global security headers present (py, node): {sec}")
        print("=" * 78)
        (LOGDIR / "gate7u_parity_results.json").write_text(json.dumps({"db": DB, "passed": passed, "failed": failed,
                                                                        "node_writes": len(node_writes)}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate7u] dropped {DB}; leftover gate7u DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate7u_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
