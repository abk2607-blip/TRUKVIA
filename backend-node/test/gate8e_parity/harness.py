"""Phase 3 · Gate 8e · live Python↔Node parity harness for the reports supplier list.

Covers:
  * GET /api/reports/suppliers   (backend/routers/reports.py::list_suppliers, L480-516)

Python: get_current_user → _active_company_id →
  READ #1 trips.distinct("supplier_name", {user_id, company_id, vehicle_type:"supplier"})
  READ #2 vehicles.distinct("supplier_name", same filter)
  per new name (de-dupe on strip().lower(), first wins):
    vehicles.find_one({..., supplier_name: {$regex: "^"+n+"$", $options: "i"}},
                      {_id:0, supplier_mobile:1, owner_phone:1})   — name NOT escaped
  → sorted by name.lower() (code-point order) → [{"name", "mobile"}]

BYTE-EXACT body; EXACT status, content-type, content-length, allow. Every
distinct / find command is compared per request, IN ORDER, key-order-
sensitively (Node findOne's extra batchSize:1 — disclosed since Gate 7y —
is not a compared field). DB activity attributed PER SERVER. Python
ApprovalGateMiddleware 500 re-dispatch (framework, Gate 8a) is accounted
against its log, never emulated.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, double slash, encoded slash, raw non-ASCII query bytes, duplicate
X-Company-Id headers.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64, ObjectId, Decimal128
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate8e_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate8e-py", "trukvia-gate8e-node"
PY_PORT, NODE_PORT = 8282, 8283
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "trips", "vehicles", "audit_logs", "save_health", "idempotency_keys"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions", "companies")]
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
PATH = "/api/reports/suppliers"


def raw(port: int, method: str, target: bytes, hdr: list[tuple[str, str]]):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    req = method.encode() + b" " + target + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
    for k, v in hdr:
        req += f"{k}: {v}\r\n".encode("utf-8")
    s.sendall(req + b"\r\n")
    r = http.client.HTTPResponse(s, method=method)
    r.begin()
    body = r.read()
    headers = {k.lower(): v for k, v in r.getheaders()}
    s.close()
    return r.status, headers, body


def wait(port: int, path: str, timeout: int = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if raw(port, "GET", path.encode(), [])[0] < 500:
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


def auth(u: str) -> list[tuple[str, str]]:
    return [("Authorization", f"Bearer tok-{u}")]


def co(u: str, cid: str) -> list[tuple[str, str]]:
    return auth(u) + [("X-Company-Id", cid)]


_n = [0]


def trip(name, uid="u1", cid="co-a", vtype="supplier") -> dict:
    _n[0] += 1
    d = {"id": f"t{_n[0]:04d}", "user_id": uid, "company_id": cid, "vehicle_type": vtype, "date": "2026-05-01"}
    if name is not ...:
        d["supplier_name"] = name
    return d


def veh(name, uid="u1", cid="co-a", vtype="supplier", **extra) -> dict:
    _n[0] += 1
    d = {"id": f"v{_n[0]:04d}", "user_id": uid, "company_id": cid, "vehicle_type": vtype, "vehicle_number": f"MH{_n[0]}"}
    if name is not ...:
        d["supplier_name"] = name
    d.update(extra)
    return d


TRIP_NAMES_A = [
    "Acme Transport", "ACME TRANSPORT", " Sharma Roadlines ", "sharma roadlines", "Zeta", "alpha", "Beta",
    "Ünïcødé Carriers", "ünïcødé carriers", "a.b", "a+b", "st*r", "q?", "x|y", "^caret", "dollar$", "b{2}",
    "a-b", "a/b", "sp ace", "ΑΣ Final", "αςσ", "Ω Omega", "É acute", "é lower", "ａbc fullwidth",
    "\U0001d504xy fraktur", " em-spaced ", " nbsp ", "Tab\tIn", "İstanbul", "straße",
    "Zeta", None, "", 0, False, {}, 0.0, ["Arr One", "Arr Two", None], "   ",
]
VEH_A = [
    veh("Acme Transport", supplier_mobile=" 98765 43210 "),
    veh("acme transport", supplier_mobile="SECOND-MATCH"),              # second match, natural order decides
    veh("sharma roadlines", supplier_mobile="", owner_phone="11111"),
    veh("Zeta", supplier_mobile=None, owner_phone=" 22222 "),
    veh("alpha"),                                                        # neither mobile field → ""
    veh("Beta", supplier_mobile=0, owner_phone="33333"),                 # falsy 0 → owner_phone
    veh("axb", supplier_mobile="REGEX-DOT-HIT"),                         # matches ^a.b$
    veh("aab", supplier_mobile="REGEX-PLUS-HIT"),                        # matches ^a+b$ (not "a+b")
    veh("a+b", supplier_mobile="LITERAL-PLUS"),                          # does NOT match ^a+b$
    veh("st*r", supplier_mobile="LITERAL-STAR"),
    veh("sttr", supplier_mobile="REGEX-STAR-HIT"),
    veh("q", supplier_mobile="REGEX-Q-HIT"),                             # ^q?$ matches "q"
    veh("x", supplier_mobile="REGEX-ALT-HIT"),                           # ^x|y$ matches "x..."
    veh("bb", supplier_mobile="REGEX-QUANT-HIT"),                        # ^b{2}$ matches "bb"
    veh("b{2}", supplier_mobile="LITERAL-BRACE"),
    veh("ÜNÏCØDÉ CARRIERS", supplier_mobile="unicode-ci"),
    veh("Vehicle Only Supplier", owner_phone="44444"),                   # defined in vehicles only
    veh("vehicle only supplier", owner_phone="dup-case-vehicle"),
    veh("Wrong Type", vtype="own", supplier_mobile="EXCLUDED"),          # vehicle_type != supplier
    veh(..., supplier_mobile="no-name"),                                 # no supplier_name
    veh("Σ Sigma", supplier_mobile="sigma"),
]


def seed_trips() -> list[dict]:
    rows = [trip(n) for n in TRIP_NAMES_A]
    rows += [trip("Own Fleet Name", vtype="own"), trip("Missing Type", vtype=None), trip(...)]
    rows += [trip("Co-B Supplier", cid="co-b"), trip("co-b supplier", cid="co-b")]
    rows += [trip("U2 Leak Supplier", uid="u2", cid="co-a"), trip("U2 Own", uid="u2", cid="co-z")]
    rows += [trip("U3 First Co", uid="u3", cid="co-u3a"), trip("U3 Second Co", uid="u3", cid="co-u3b")]
    rows += [trip("Before Bad", cid="co-badname"), trip(5, cid="co-badname"), trip("After Bad", cid="co-badname")]
    rows += [trip("Good First", cid="co-badregex"), trip("(unclosed", cid="co-badregex")]
    rows += [trip("[bad", cid="co-badregex2")]
    rows += [trip("trailing\\", cid="co-badregex3")]
    rows += [trip(True, cid="co-badbool")]
    rows += [trip(datetime(2026, 1, 1), cid="co-baddate")]
    rows += [trip(float("nan"), cid="co-badnan")]
    rows += [trip(Int64(0), cid="co-zero"), trip(Int64(7), cid="co-int64")]
    rows += [trip(ObjectId("65a000000000000000000001"), cid="co-oid")]
    rows += [trip(Decimal128("0"), cid="co-dec")]
    rows += [trip("Mob Bad", cid="co-badmob")]
    rows += [trip("Mob List", cid="co-badmob2")]
    rows += [trip("Good Before", cid="co-badquant"), trip("a{2,1}", cid="co-badquant")]
    rows += [trip("{2}", cid="co-badbrace")]
    return rows


def seed_vehicles() -> list[dict]:
    rows = list(VEH_A)
    rows += [veh("Co-B Supplier", cid="co-b", supplier_mobile="co-b-mob"),
             veh("U2 Leak Supplier", uid="u2", cid="co-a", supplier_mobile="u2-leak"),
             veh("Acme Transport", uid="u2", cid="co-a", supplier_mobile="U2-ACME"),       # other user, same company id
             veh("Acme Transport", cid="co-b", supplier_mobile="CO-B-ACME"),              # other company
             veh("U3 First Co", uid="u3", cid="co-u3a", supplier_mobile="u3a"),
             veh("Mob Bad", cid="co-badmob", supplier_mobile=12345),                     # truthy int mobile → 500
             veh("Mob List", cid="co-badmob2", supplier_mobile=["x"], owner_phone="55555"),  # truthy list mobile → 500
             veh("Only Veh", cid="co-vehonly", owner_phone=" 777 ")]
    return rows


COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    *[{"id": c, "user_id": "u1", "is_default": False, "name": c} for c in (
        "co-b", "co-empty", "co-badname", "co-badregex", "co-badregex2", "co-badregex3", "co-badbool", "co-baddate",
        "co-badnan", "co-zero", "co-int64", "co-oid", "co-dec", "co-badmob", "co-badmob2", "co-badquant",
        "co-badbrace", "co-vehonly")],
    {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
    {"id": "co-u3a", "user_id": "u3", "is_default": False, "name": "U3A"},
    {"id": "co-u3b", "user_id": "u3", "is_default": False, "name": "U3B"},
]

U1 = auth("u1")
P = PATH.encode()
CASES: list[tuple[str, bytes, list, str]] = [
    ("GET", P, [], "no auth"),
    ("GET", P, [("Authorization", "Bearer nope")], "invalid bearer"),
    ("GET", P, [("Authorization", "Bearer tok-exp")], "expired session"),
    ("GET", P, [("Cookie", "session_token=tok-u1")], "session cookie"),
    ("GET", P, U1, "u1 default co-a (full matrix of names)"),
    ("GET", P, co("u1", "co-a"), "header co-a"),
    ("GET", P, co("u1", "co-b"), "owned alternate co-b (case dup)"),
    ("GET", P, co("u1", "co-z"), "unowned header → default"),
    ("GET", P, co("u1", "co-nope"), "unknown header → default"),
    ("GET", P, co("u1", ""), "empty header"),
    ("GET", P, co("u1", "co-empty"), "company without suppliers → []"),
    ("GET", P, co("u1", "co-vehonly"), "vehicles-only supplier"),
    ("GET", P, auth("u2"), "u2 own"),
    ("GET", P, co("u2", "co-a"), "u2 supplying u1's co-a → default"),
    ("GET", P, auth("u3"), "u3 no default company (py repair)"),
    ("GET", P, co("u3", "co-u3b"), "u3 header co-u3b"),
    ("GET", P, co("u1", "co-badname"), "int name mid-stream → 500"),
    ("GET", P, co("u1", "co-badregex"), "invalid regex '(unclosed' → 500"),
    ("GET", P, co("u1", "co-badregex2"), "invalid regex '[bad' → 500"),
    ("GET", P, co("u1", "co-badregex3"), "trailing backslash escapes $ → valid (200)"),
    ("GET", P, co("u1", "co-badquant"), "invalid regex 'a{2,1}' after a good lookup"),
    ("GET", P, co("u1", "co-badmob2"), "list mobile → 500"),
    ("GET", P, co("u1", "co-badbrace"), "invalid regex '{2}' → 500"),
    ("GET", P, co("u1", "co-badbool"), "True name → 500"),
    ("GET", P, co("u1", "co-baddate"), "date name → 500"),
    ("GET", P, co("u1", "co-badnan"), "NaN name (truthy) → 500"),
    ("GET", P, co("u1", "co-zero"), "Int64(0) name (falsy) → skipped"),
    ("GET", P, co("u1", "co-int64"), "Int64(7) name → 500"),
    ("GET", P, co("u1", "co-oid"), "ObjectId name → 500"),
    ("GET", P, co("u1", "co-dec"), "Decimal128('0') name (truthy) → 500"),
    ("GET", P, co("u1", "co-badmob"), "int mobile → 500"),
    ("GET", (PATH + "?x=1&x=2&q=a").encode(), U1, "query ignored (repeated / junk)"),
    ("GET", (PATH + "?%zz=%C3").encode(), U1, "malformed query encoding ignored"),
    ("GET", (PATH + "?").encode(), U1, "empty query"),
    ("HEAD", P, U1, "HEAD auth"),
    ("HEAD", P, [], "HEAD no auth"),
] + [("GET", P, U1, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", (PATH + "/").encode(), U1, "trailing slash"),
        ("GET", b"/api//reports/suppliers", U1, "double slash"),
        ("GET", b"/api/reports%2Fsuppliers", U1, "encoded slash"),
        ("GET", b"/api/reports/suppliers%FF", U1, "invalid UTF-8 path escape"),
        ("GET", P + b"?q=\xc3\xa9", U1, "raw non-ASCII query bytes"),
        ("GET", P, U1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")], "duplicate X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:300].decode("utf-8", "replace")


def route_cmds(ops: list) -> list:
    out = []
    for o in ops:
        c = o.get("command") or {}
        if c.get("distinct") in ("trips", "vehicles"):
            out.append((f"distinct:{c['distinct']}", json.dumps([(k, c.get(k)) for k in ("key", "query")], default=repr)))
        elif c.get("find") == "vehicles":
            out.append(("find:vehicles", json.dumps([(k, c.get(k)) for k in ("filter", "sort", "projection", "skip", "limit",
                                                                              "singleBatch")], default=repr, ensure_ascii=False)))
    return out


async def run() -> int:
    print(f"[gate8e] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        now = datetime.now(timezone.utc)
        us = lambda tok, uid, exp: {"session_token": tok, "user_id": uid, "effective_role": "owner",
                                     "expires_at": exp.isoformat(), "last_refreshed_at": now.isoformat()}
        await d.user_sessions.insert_many([us(f"tok-{u}", u, now + timedelta(hours=2)) for u in ("u1", "u2", "u3")]
                                          + [us("tok-exp", "u1", now - timedelta(minutes=1))])
        await d.users.insert_many([{"user_id": u, "email": f"{u}@x", "name": u.upper()} for u in ("u1", "u2", "u3")])
        await d.companies.insert_many([dict(c) for c in COMPANIES])
        await d.trips.insert_many(seed_trips())
        await d.vehicles.insert_many(seed_vehicles())

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate8e_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate8e_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate8e] servers did not start"); return 2
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await d.command({"profile": 2})
        h_start = (await d.command("dbHash", collections=TRACKED))["collections"]

        passed = failed = 0
        rows = []
        py_writes: list = []
        node_changes: list = []
        redispatched: list = []
        pairs: list = []
        cmd_diffs: list = []
        for method, target, hdr, desc in CASES:
            n_py0 = await d["system.profile"].count_documents({"appName": PY_APP})
            h0 = (await d.command("dbHash", collections=TRACKED))["collections"]
            rp = raw(PY_PORT, method, target, hdr)
            await asyncio.sleep(0.1)
            py_ops = await d["system.profile"].find({"appName": PY_APP}).skip(n_py0).to_list(None)
            h_mid = (await d.command("dbHash", collections=TRACKED))["collections"]
            pch = [k for k in TRACKED if h0.get(k) != h_mid.get(k)]
            if pch:
                py_writes.append((desc, pch))
            n_nd0 = await d["system.profile"].count_documents({"appName": NODE_APP})
            rn = raw(NODE_PORT, method, target, hdr)
            await asyncio.sleep(0.1)
            nd_ops = await d["system.profile"].find({"appName": NODE_APP}).skip(n_nd0).to_list(None)
            h1 = (await d.command("dbHash", collections=TRACKED))["collections"]
            nch = [k for k in TRACKED if h_mid.get(k) != h1.get(k)]
            if nch:
                node_changes.append((desc, nch))
            seq_py, seq_nd = route_cmds(py_ops), route_cmds(nd_ops)
            redispatch = rp[0] == 500 and bool(seq_nd) and seq_py == seq_nd * 2
            reads_ok = seq_py == seq_nd or redispatch
            if not reads_ok:
                cmd_diffs.append((desc, seq_py, seq_nd))
            if redispatch:
                redispatched.append(desc)
            pairs.extend(zip(seq_py, seq_nd))
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and not nch and reads_ok
            passed += ok; failed += (not ok)
            n_items = len(json.loads(rp[2])) if rp[0] == 200 and rp[2][:1] == b"[" else "-"
            rows.append((ok, desc + (" [py re-dispatch]" if redispatch else ""), method, rp, rn, n_items,
                         [c.split(":")[0][0] + c.split(":")[1][0] for c, _ in seq_py], len(seq_nd), nch))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})
        kinds = {}
        for a, _ in pairs:
            kinds[a[0]] = kinds.get(a[0], 0) + 1
        cmd_same = len(pairs) > 0 and all(a == b for a, b in pairs) and not cmd_diffs
        faults = (LOGDIR / "gate8e_py.log").read_text(encoding="utf-8", errors="replace").count(
            "ApprovalGateMiddleware fault (passthrough)")

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 8e · LIVE PARITY (GET /api/reports/suppliers) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, n_items, cpy, nnd, nch in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:46} py={rp[0]} node={rn[0]} items={n_items!s:>3} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} allow={rp[1].get('allow')}/{rn[1].get('allow')} "
                  f"route-cmds py={len(cpy)} node={nnd} node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} {pretty(rn[2])!r}")
        for desc, a, b in cmd_diffs[:4]:
            print(f"  CMD DIFF {desc}:\n        py  : {a[:6]}\n        node: {b[:6]}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += cmd_same; failed += (not cmd_same)
        print(f"  [{'PASS' if cmd_same else 'FAIL'}] distinct + lookup commands identical per request, in order, "
              f"key-order-sensitive: {kinds}")
        ex = next((a[1] for a, _ in pairs if a[0] == "find:vehicles" and "a.b" in a[1]), None)
        print(f"        lookup e.g. {ex}")
        rd_ok = len(redispatched) == faults
        passed += rd_ok; failed += (not rd_ok)
        print(f"  [{'PASS' if rd_ok else 'FAIL'}] python ApprovalGateMiddleware re-dispatches (framework, NOT route) — "
              f"log faults={faults}, 500 cases with doubled command sequence={len(redispatched)}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run: {APP_COLLS}")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print(f"  u1 default body (python): {pretty(rows[4][3][2])[:300]}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:34} py={rp[0]} {rp[2][:80]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r}"
                  f" | node={rn[0]} {rn[2][:80]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 4}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate8e_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes), "kinds": kinds}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate8e] dropped {DB}; leftover gate8e DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate8e_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
