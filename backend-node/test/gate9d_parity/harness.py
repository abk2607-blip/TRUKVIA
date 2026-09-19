"""Phase 4 · Gate 9d · live Python↔Node HTTP-edge parity.

Both servers run against the same disposable DB (dropped in `finally`), twice:
pass A with CORS_ORIGINS / NODE_CORS_ORIGINS unset (Python falls back to "*"),
pass B with an explicit origin list.

Per case the FULL response head is compared: status line, raw body bytes and the
header multiset (lower-cased names, exact values, content-length included).
Excluded as transport-level (reported, not hidden): date, server (uvicorn),
connection, keep-alive, transfer-encoding, and Node's own x-request-id.
Parser-level cases compare the raw bytes.

Case classes:
  PARITY      must match exactly (counted pass/fail);
  PARSER-GAP  llhttp vs h11 grammar differences that no app-level code can reach
              (documented; counted separately, never as pass);
  NOT-SERVED  (method, path) that Python FULL-matches with a NON-migrated handler
              (a writer or an unmigrated read) — outside Node's cutover surface
              (routing, Gate 9f). Sent UNAUTHENTICATED only so Python never writes.
Zero Node writes: profiler by appName; application collections dbHash unchanged.
"""
from __future__ import annotations
import asyncio, importlib.util, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MONGO = "mongodb://localhost:27017"
PY_APP, NODE_APP = "trukvia-gate9d-py", "trukvia-gate9d-node"
PY_PORT, NODE_PORT = 8302, 8303
LOGDIR = Path(tempfile.gettempdir())
TRANSPORT = {"date", "server", "connection", "keep-alive", "transfer-encoding", "x-request-id"}
WRITE_OPS = ("insert", "update", "remove")

# Reuse the Gate 9c seed + allowlisted route list (test tooling only).
_spec = importlib.util.spec_from_file_location("g9c", HERE.parent / "gate9c_parity" / "harness.py")
g9c = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(g9c)  # type: ignore[union-attr]
ROUTES = g9c.ALLOWLIST_ROUTES + [("DEFERRED saved-trip-filters", "/api/saved-trip-filters"),
                                 ("DEFERRED trips list", "/api/trips"), ("DEFERRED trip detail", "/api/trips/trip-b")]

# Python route table for NOT-SERVED classification (import the real app).
sys.path.insert(0, str(REPO / "backend"))
_cwd = os.getcwd(); os.chdir(REPO / "backend")
os.environ.setdefault("MONGO_URL", MONGO); os.environ.setdefault("DB_NAME", "trukvia_gate9d_import_unused")
import server as py_server  # noqa: E402
os.chdir(_cwd)
from starlette.routing import Match  # noqa: E402
from urllib.parse import unquote  # noqa: E402

NODE_SERVED: set[tuple[str, str]] = set()  # (METHOD, python template) that Node registers


def load_node_served():
    # Node registers GET for every allowlist ∪ deferred path, plus exactly two parked POST
    # writers (Gates 4/5: saved-trip-filters, expenditure-types).
    allow = [l.strip() for l in (REPO / "backend-node/.migration-allowlist").read_text().splitlines() if l.strip() and not l.startswith("#")]
    deferred = [l.strip() for l in (REPO / "backend-node/.migration-deferred").read_text().splitlines() if l.strip() and not l.startswith("#")]
    for p in allow + deferred:
        NODE_SERVED.add(("GET", _norm_node(p)))
    NODE_SERVED.add(("POST", _norm_node("/api/saved-trip-filters")))
    NODE_SERVED.add(("POST", _norm_node("/api/expenditure-types")))


def _norm_node(p: str) -> str:
    return "/".join("{}" if s.startswith(":") else s for s in p.split("/"))


def _norm_py(p: str) -> str:
    import re
    return re.sub(r"\{[^}]*\}", "{}", p)


def python_decision(method: str, target: str) -> str:
    """'served' | 'not-served' | 'edge' (405/307/404 framework answer) for a request."""
    raw_path = target.split("?", 1)[0]
    path = unquote(raw_path)
    scope = {"type": "http", "path": path, "root_path": "", "method": method, "headers": []}
    for r in py_server.app.routes:
        m, _ = r.matches(scope)
        if m == Match.FULL:
            return "served" if (method, _norm_py(r.path)) in NODE_SERVED else "not-served"
    return "edge"


def raw_exchange(port: int, data: bytes, timeout: float = 20) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(data)
    out = b""
    try:
        while True:
            c = s.recv(65536)
            if not c:
                break
            out += c
    except socket.timeout:
        out += b"<<timeout>>"
    s.close()
    return out


def build(method: str, target: bytes | str, headers, host: str = "edge.test:8080", version: str = "HTTP/1.1") -> bytes:
    t = target if isinstance(target, bytes) else target.encode("latin-1")
    h = b"".join(f"{k}: {v}\r\n".encode("latin-1") for k, v in headers)
    host_line = f"Host: {host}\r\n".encode("latin-1") if host is not None else b""
    return method.encode("latin-1") + b" " + t + b" " + version.encode() + b"\r\n" + host_line + b"Connection: close\r\n" + h + b"\r\n"


def parse(raw: bytes):
    head, sep, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0]
    hs = []
    chunked = False
    for l in lines[1:]:
        k, _, v = l.partition(":")
        k = k.strip().lower(); v = v.strip()
        if k == "transfer-encoding" and "chunked" in v.lower():
            chunked = True
        if k in TRANSPORT:
            continue
        hs.append((k, v))
    if chunked:  # de-chunk (framing is transport-level)
        out, rest = b"", body
        while rest:
            size_line, _, rest = rest.partition(b"\r\n")
            n = int(size_line.split(b";")[0] or b"0", 16)
            if n == 0:
                break
            out += rest[:n]; rest = rest[n + 2:]
        body = out
    return status, sorted(hs), body


async def run_pass(label: str, cors_env: str | None, cli) -> dict:
    db_name = f"trukvia_gate9d_parity_{label}_{int(time.time())}"
    d = cli[db_name]
    py = node = None
    res = {"label": label, "parity_pass": 0, "parity_fail": 0, "parser_gap": [], "not_served": 0, "fails": [],
           "node_ops": 0, "node_writes": 0, "app_changed": [], "cases": 0}
    try:
        seeds = g9c.seed_docs()
        seeds["user_sessions"].append(g9c.sess("tok-500", "u-noemail"))
        seeds["users"].append({"user_id": "u-noemail", "name": "no email"})
        seeds["user_sessions"].append({"session_token": "tok-ghost", "user_id": "ghost", "expires_at": g9c.FUT,
                                       "created_at": g9c.NOW, "last_refreshed_at": g9c.NOW})
        for coll, rows in seeds.items():
            if rows:
                await d[coll].insert_many([dict(r) for r in rows])
        tracked = sorted(seeds.keys())
        app_colls = [c for c in tracked if c not in ("companies", "user_sessions", "trips", "invoices", "customers",
                                                        "vehicles", "drivers", "files", "audit_logs")]
        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": db_name, "ENABLE_DEMO_TOKEN": "0",
                    "IS_PREVIEW_ENV": "0", "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        env.pop("CORS_ORIGINS", None)
        if cors_env is not None:
            env["CORS_ORIGINS"] = cors_env
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / f"gate9d_py_{label}.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": db_name,
                     "NODE_CORS_ORIGINS": cors_env or "", "NODE_REQUEST_ID_HEADER": "x-request-id",
                     "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / f"gate9d_node_{label}.log", "wb"), stderr=subprocess.STDOUT)
        for port in (PY_PORT, NODE_PORT):
            for _ in range(480):
                try:
                    socket.create_connection(("127.0.0.1", port), 1).close(); break
                except OSError:
                    time.sleep(0.25)
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=128 * 1024 * 1024)
        await d.command({"profile": 2})
        h_start = (await d.command("dbHash", collections=tracked))["collections"]

        OWN = [("Authorization", "Bearer tok-owner")]
        ORIGIN_OK = "https://app.example"
        ORIGIN_BAD = "https://evil.example"
        cases: list[tuple[str, str, bytes, str]] = []  # (class, desc, bytes, method+target for classification)

        def add(desc, method, target, headers, host="edge.test:8080", version="HTTP/1.1", cls=None):
            data = build(method, target, headers, host, version)
            if cls is None:
                tgt = target if isinstance(target, str) else target.decode("latin-1")
                dec = python_decision(method, tgt) if all(0x21 <= ord(c) <= 0x7e for c in tgt) else "edge"
                cls = "NOT-SERVED" if dec == "not-served" else "PARITY"
                if cls == "NOT-SERVED" and any(k.lower() in ("authorization", "cookie") for k, _ in headers):
                    return  # never let Python run a non-migrated (possibly writing) handler with credentials
            cases.append((cls, desc, data, method))

        # 1 · all routes × methods (unauthenticated → framework decisions; GET also owner/staff/viewer)
        for name, target in ROUTES:
            for m in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "PROPFIND"):
                add(f"{name} · {m} · anon", m, target, [])
            for tok in ("tok-owner", "tok-acc", "tok-view"):
                add(f"{name} · GET · {tok}", "GET", target, [("Authorization", f"Bearer {tok}")])
            add(f"{name} · HEAD · owner", "HEAD", target, OWN)
            add(f"{name} · GET · owner +Origin", "GET", target, OWN + [("Origin", ORIGIN_OK)])
            add(f"{name} · GET · owner +bad Origin +Cookie", "GET", target, OWN + [("Origin", ORIGIN_BAD), ("Cookie", "a=1")])
            add(f"{name} · GET · 500 (user w/o email) +Origin", "GET", target, [("Authorization", "Bearer tok-500"), ("Origin", ORIGIN_OK)])
            base, _, q = target.partition("?")
            add(f"{name} · GET · trailing slash", "GET", base + "/" + ("?" + q if q else ""), OWN)
            add(f"{name} · GET · slash x3 +Origin", "GET", base + "///", OWN + [("Origin", ORIGIN_OK)])

        # 2 · identities on representative routes
        REP = ["/api/vendors", "/api/vendors/v-b", "/api/fin/fin-txn/tx-b", "/api/company-bank-accounts",
               "/api/party-bank-accounts?party_type=vendor&party_id=v-b", "/api/files", "/api/reminders/digest",
               "/api/customers/cus-b/ship-sites", "/api/suppliers"]
        for t in REP:
            for tok in ("tok-owner", "tok-acc", "tok-view", "tok-expired", "nope", "tok-ghost"):
                for hv in ([], [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")], [("X-Company-Id", "co-b, co-a")]):
                    add(f"{t} · {tok} · xcid={len(hv)}", "GET", t, [("Authorization", f"Bearer {tok}")] + hv)

        # 3 · path / query edge cases
        for desc, t in [("%2F in param", "/api/vendors/a%2Fb"), ("%FF param", "/api/vendors/%FF"),
                        ("%ED%A0%80 param", "/api/vendors/%ED%A0%80"), ("%0A after list", "/api/vendors%0A"),
                        ("%0A in param", "/api/vendors/v-b%0A"), ("%3F in param", "/api/vendors/a%3Fb"),
                        ("%23 in param", "/api/vendors/a%23b"), ("%25 in param", "/api/vendors/100%25"),
                        ("bad escape %zz", "/api/vendors/%zz"), ("lone %", "/api/vendors/%"), ("semicolon", "/api/vendors;x"),
                        ("semicolon param", "/api/vendors/v-b;x"), ("double slash", "/api//vendors"),
                        ("empty segment", "/api/drivers//payments"), ("long param 150", "/api/vendors/" + "x" * 150),
                        ("long param 5000", "/api/vendors/" + "y" * 5000), ("upper-case path", "/API/VENDORS"),
                        ("dot segment", "/api/vendors/../vendors"), ("encoded dot", "/api/vendors/%2E%2E"),
                        ("bare ?", "/api/vendors?"), ("double ??", "/api/vendors??a=1"), ("hash in target", "/api/vendors#frag"),
                        ("query only slash", "/api/vendors/?"), ("root /api", "/api"), ("root /api/", "/api/"),
                        ("/ root", "/"), ("unknown", "/api/definitely-not-a-route"), ("unknown slash", "/api/definitely-not/"),
                        ("docs slash", "/docs/"), ("absolute-form", "http://edge.test/api/vendors"),
                        ("encoded space", "/api/vendors/a%20b"), ("plus", "/api/vendors/a+b"), ("unicode %E2%82%AC", "/api/vendors/%E2%82%AC"),
                        ("%00", "/api/vendors/%00"), ("tab-escaped", "/api/vendors/%09")]:
            add(f"edge · {desc}", "GET", t, OWN)
            add(f"edge · {desc} · HEAD +Origin", "HEAD", t, OWN + [("Origin", ORIGIN_OK)])
        add("edge · X-Forwarded-Proto on redirect (loopback trusted)", "GET", "/api/vendors/", [("X-Forwarded-Proto", "https"), ("X-Forwarded-Proto", " wss ")])
        add("edge · no Host HTTP/1.0 list", "GET", "/api/vendors", OWN, host=None, version="HTTP/1.0")
        add("edge · HTTP/1.0 redirect w/ Host", "GET", "/api/vendors/", OWN, version="HTTP/1.0")
        add("edge · Host with spaces-free odd chars", "GET", "/api/vendors/", [], host="Ex-Ample.test:1")

        # 4 · CORS preflight matrix
        for origin in (ORIGIN_OK, ORIGIN_BAD, "", "null", "https://other.example"):
            for acrm in ("GET", "PUT", "get", "FOO", ""):
                for acrh in (None, "authorization, x-company-id", "X-Custom,Content-Type", ""):
                    for t in ("/api/vendors", "/nowhere", "/api/vendors/"):
                        hs = [("Origin", origin), ("Access-Control-Request-Method", acrm)]
                        if acrh is not None:
                            hs.append(("Access-Control-Request-Headers", acrh))
                        add(f"preflight · o={origin!r} m={acrm!r} h={acrh!r} {t}", "OPTIONS", t, hs, cls="PARITY")
        add("preflight · duplicate Origin", "OPTIONS", "/api/vendors", [("Origin", ORIGIN_BAD), ("Origin", ORIGIN_OK),
                                                                       ("Access-Control-Request-Method", "GET")], cls="PARITY")
        add("preflight · +Cookie", "OPTIONS", "/api/vendors", [("Origin", ORIGIN_OK), ("Cookie", "a=1"),
                                                               ("Access-Control-Request-Method", "GET")], cls="PARITY")
        add("simple · OPTIONS no ACRM +Origin", "OPTIONS", "/api/vendors", [("Origin", ORIGIN_OK)])
        add("simple · Origin + existing Vary? (401)", "GET", "/api/vendors", [("Origin", ORIGIN_OK), ("Cookie", "x=1")])

        # 5 · parser level (raw bytes)
        PARSER = [
            ("PARITY", "non-ASCII target", b"GET /api/vendors/\xc3\xa9 HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"),
            ("PARITY", "DEL in target", b"GET /api/vendors/\x7f HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"),
            ("PARITY", "garbage request line", b"GARBAGE\r\n\r\n"),
            ("PARITY", "HTTP/1.1 missing Host", b"GET /api/vendors HTTP/1.1\r\nConnection: close\r\n\r\n"),
            ("PARITY", "duplicate Host (1.1)", b"GET /api/vendors HTTP/1.1\r\nHost: a\r\nHost: b\r\nConnection: close\r\n\r\n"),
            ("PARITY", "duplicate Host (1.0)", b"GET /api/vendors HTTP/1.0\r\nHost: a\r\nhost: a\r\n\r\n"),
            ("PARITY", "space before colon", b"GET /api/vendors HTTP/1.1\r\nHost: h\r\nX-A : 1\r\nConnection: close\r\n\r\n"),
            ("PARITY", "VT in header value", b"GET /api/vendors HTTP/1.1\r\nHost: h\r\nX-A: 1\x0b\r\nConnection: close\r\n\r\n"),
            ("PARSER-GAP", "obs-fold continuation line (h11 accepts, llhttp rejects)",
             b"GET /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\nAuthorization: Bearer tok-owner\r\nX-Company-Id: co-b\r\n  co-a\r\n\r\n"),
            ("PARSER-GAP", "unknown token method FOO (h11 → Starlette 405, llhttp → 400)",
             b"FOO /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"),
            ("PARSER-GAP", "lower-case method get (h11 → 405, llhttp → 400)",
             b"get /api/vendors HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"),
        ]
        for cls, desc, data in PARSER:
            cases.append((cls, f"parser · {desc}", data, "RAW"))

        passed = failed = 0
        for cls, desc, data, _m in cases:
            rp = raw_exchange(PY_PORT, data)
            rn = raw_exchange(NODE_PORT, data)
            if _m == "RAW":
                same = rp == rn
                a, b = (rp, rn)
            else:
                a, b = parse(rp), parse(rn)
                same = a == b
            if cls == "PARITY":
                if same:
                    passed += 1
                else:
                    failed += 1
                    res["fails"].append((desc, a, b))
            elif cls == "PARSER-GAP":
                res["parser_gap"].append((desc, same, rp[:120], rn[:120]))
            else:
                res["not_served"] += 1
        res["parity_pass"], res["parity_fail"], res["cases"] = passed, failed, len(cases)

        await asyncio.sleep(1)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        res["node_ops"] = len(prof)
        res["node_writes"] = sum(1 for p in prof if p.get("op") in WRITE_OPS or
                                 next(iter(p.get("command") or {}), "") in ("insert", "update", "delete", "findAndModify"))
        res["node_colls"] = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        h_end = (await d.command("dbHash", collections=tracked))["collections"]
        res["app_changed"] = [k for k in app_colls if h_start.get(k) != h_end.get(k)]
        return res
    finally:
        for p in (py, node):
            if p and p.poll() is None:
                try:
                    p.send_signal(signal.SIGTERM); p.wait(timeout=5)
                except Exception:
                    p.kill()
        try:
            await d.command({"profile": 0})
        except Exception:
            pass
        await cli.drop_database(db_name)


async def main() -> int:
    load_node_served()
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    results = []
    try:
        for label, cors in (("star", None), ("list", "https://app.example, https://other.example")):
            results.append(await run_pass(label, cors, cli))
    finally:
        left = [x for x in await cli.list_database_names() if x.startswith("trukvia_gate9d_parity_")]
        cli.close()
    print("=" * 110 + "\nPHASE 4 · GATE 9d · HTTP-EDGE PARITY (Python vs Node, raw sockets)\n" + "=" * 110)
    total_fail = 0
    for r in results:
        print(f"\n-- pass {r['label']}: cases={r['cases']}  PARITY {r['parity_pass']}/{r['parity_pass'] + r['parity_fail']} pass"
              f"  · NOT-SERVED (unauth, routing scope 9f) {r['not_served']}  · PARSER-GAP {len(r['parser_gap'])}")
        for desc, a, b in r["fails"][:40]:
            print(f"  [FAIL] {desc}\n      py={a if isinstance(a, bytes) else (a[0], a[2][:100])}\n      nd={b if isinstance(b, bytes) else (b[0], b[2][:100])}")
            if not isinstance(a, bytes):
                for x in sorted(set(a[1]) - set(b[1])): print(f"        py-only header: {x}")
                for x in sorted(set(b[1]) - set(a[1])): print(f"        nd-only header: {x}")
        for desc, same, rp, rn in r["parser_gap"]:
            print(f"  [PARSER-GAP{' (now equal)' if same else ''}] {desc}\n      py={rp!r}\n      nd={rn!r}")
        zero = r["node_writes"] == 0 and not r["app_changed"]
        print(f"  [{'PASS' if zero else 'FAIL'}] zero-write: node ops={r['node_ops']} writes={r['node_writes']} "
              f"app collections changed={r['app_changed']}")
        print(f"         node collections read: {r.get('node_colls')}")
        total_fail += r["parity_fail"] + (0 if zero else 1)
    print(f"\n  leftover gate9d DBs: {left}")
    print("-" * 110 + f"\n  TOTAL parity cases: {sum(r['parity_pass'] + r['parity_fail'] for r in results)}  "
          f"passed: {sum(r['parity_pass'] for r in results)}  failed: {sum(r['parity_fail'] for r in results)}\n" + "=" * 110)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
