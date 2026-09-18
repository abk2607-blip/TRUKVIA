"""Phase 3 · Gate 7x · live Python↔Node parity harness for the AI chat sessions list.

Covers:
  * GET /api/ai/sessions   (backend/routers/ai.py::list_sessions, L304-311)

Python: get_current_user → _active_company_id → chat_sessions.find(
{user_id, company_id}, {_id:0, user_id:0}).sort("created_at", -1).to_list(50)
— NO .limit(): the profiler shows the exact find command each server sends.

Comparison is BYTE-EXACT on the body and EXACT on status, content-type,
content-length and allow. DB activity is attributed PER SERVER (profiler
appName + dbHash taken between the two requests). Node must never write.

Tie evidence: the seeded data is also queried directly with and without a
server limit, showing where a `.limit(50)` would change selection / order.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, sub-path, raw non-ASCII query bytes, duplicate X-Company-Id headers.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64, Decimal128, ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7x_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7x-py", "trukvia-gate7x-node"
PY_PORT, NODE_PORT = 8268, 8269
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "chat_sessions", "chat_messages", "audit_logs", "save_health",
           "idempotency_keys", "trips", "invoices"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions", "companies")]
P = "/api/ai/sessions"
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}


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


def auth(tok: str) -> list[tuple[str, str]]:
    return [("Authorization", f"Bearer {tok}")]


def co(tok: str, cid: str) -> list[tuple[str, str]]:
    return auth(tok) + [("X-Company-Id", cid)]


BASE = datetime(2026, 5, 1, tzinfo=timezone.utc)


def iso(i: int) -> str:
    return (BASE + timedelta(minutes=i)).isoformat()


def cs(n: int, uid: str, cid: str, created_at, **extra) -> dict:
    d = {"id": f"chat_{cid}_{uid}_{n:04d}", "title": f"{cid} chat {n}", "created_at": created_at,
         "user_id": uid, "company_id": cid}
    d.update(extra)
    return d


def seed_rows() -> list[dict]:
    rows: list[dict] = []
    rows += [cs(n, "u1", "co-a", iso(n % 10)) for n in range(130)]            # ten 13-way tie groups
    rows += [cs(n, "u1", "co-b", iso(n // 5)) for n in range(50)]             # exactly 50, 5-way ties
    rows += [cs(n, "u1", "co-c", iso(n)) for n in range(49)]                  # 49 distinct
    rows += [cs(n, "u1", "co-d", iso(n)) for n in range(51)]                  # 51 distinct
    rows += [cs(n, "u1", "co-i", iso(0)) for n in range(70)]                  # 70 identical
    rows += [cs(n, "u1", "co-j", iso(100 - min(n, 40))) for n in range(65)]   # tie group 40..64 crosses cut
    rows += [cs(n, "u1", "co-k", iso(100 - min(n, 49))) for n in range(51)]   # rows 49,50 tied
    rows += [cs(n, "u1", "co-m", iso(n % 4)) for n in range(90)]              # 4 large tie groups
    # co-f: serialization / mixed sort types / field presence
    rows += [
        cs(0, "u1", "co-f", iso(1), extra={"f": 5.0, "g": 1e16, "h": 1.5e-7, "z": -0.0, "i64": Int64(2 ** 53 + 1),
                                           "b": False, "nil": None, "arr": [1, 2.5, "x", {"k": []}], "empty": {}}),
        cs(1, "u1", "co-f", datetime(2026, 5, 2, 10, 0, 0, 123000), title="Ünïcødé 🚚 \"q\" \\ \n\t\x01  "),
        cs(2, "u1", "co-f", datetime(2026, 5, 2, 10, 0, 0), title=None),
        {"id": "chat_co-f_min", "user_id": "u1", "company_id": "co-f"},       # no title / created_at
        {"user_id": "u1", "company_id": "co-f", "title": "no id", "created_at": iso(5)},
        cs(3, "u1", "co-f", None),
        cs(4, "u1", "co-f", 12345),
        cs(5, "u1", "co-f", ""),
        cs(6, "u1", "co-f", iso(7), big=10 ** 18, neg=-(2 ** 31)),
    ]
    rows += [cs(0, "u1", "co-g", iso(1)), cs(1, "u1", "co-g", iso(2), score=float("nan"))]      # NaN → 500
    rows += [cs(0, "u1", "co-h", iso(1), score=float("inf"))]                                     # Infinity → 500
    rows += [cs(0, "u1", "co-o", iso(1), ref=ObjectId("65a000000000000000000001"))]              # ObjectId
    rows += [cs(0, "u1", "co-q", iso(1), amt=Decimal128("12.50"))]                                # Decimal128
    # cross-user / cross-company
    rows += [cs(n, "u2", "co-a", iso(200 + n)) for n in range(5)] + [cs(n, "u2", "co-z", iso(n)) for n in range(3)]
    rows += [cs(n, "u1", "", iso(n)) for n in range(2)]
    rows += [cs(n, "u3", "co-u3a", iso(n)) for n in range(3)] + [cs(n, "u3", "co-u3b", iso(n)) for n in range(2)]
    return rows


U1_COMPANIES = ["co-b", "co-c", "co-d", "co-e", "co-f", "co-g", "co-h", "co-i", "co-j", "co-k", "co-m", "co-o", "co-q"]
COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    *[{"id": c, "user_id": "u1", "is_default": False, "name": c} for c in U1_COMPANIES],
    {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
    {"id": "co-u3a", "user_id": "u3", "is_default": False, "name": "U3A"},
    {"id": "co-u3b", "user_id": "u3", "is_default": False, "name": "U3B"},
]

A1 = auth("tok-u1")
CASES: list[tuple[str, bytes, list, str]] = [
    ("GET", P.encode(), [], "no auth"),
    ("GET", P.encode(), auth("nope"), "invalid bearer"),
    ("GET", P.encode(), auth("tok-exp"), "expired session"),
    ("GET", P.encode(), [("Cookie", "session_token=tok-u1")], "session cookie"),
    ("GET", P.encode(), A1, "u1 default co-a (130, 13-way ties) → 50"),
    ("GET", P.encode(), co("tok-u1", "co-a"), "u1 header co-a"),
    ("GET", P.encode(), co("tok-u1", "co-b"), "co-b exactly 50 (5-way ties)"),
    ("GET", P.encode(), co("tok-u1", "co-c"), "co-c 49"),
    ("GET", P.encode(), co("tok-u1", "co-d"), "co-d 51 → 50"),
    ("GET", P.encode(), co("tok-u1", "co-e"), "co-e empty"),
    ("GET", P.encode(), co("tok-u1", "co-i"), "co-i 70 identical → 50"),
    ("GET", P.encode(), co("tok-u1", "co-j"), "co-j tie group crosses cut"),
    ("GET", P.encode(), co("tok-u1", "co-k"), "co-k cut splits tied pair"),
    ("GET", P.encode(), co("tok-u1", "co-m"), "co-m multiple tie groups"),
    ("GET", P.encode(), co("tok-u1", "co-f"), "co-f serialization / mixed sort types"),
    ("GET", P.encode(), co("tok-u1", "co-g"), "co-g NaN → 500"),
    ("GET", P.encode(), co("tok-u1", "co-h"), "co-h Infinity → 500"),
    ("GET", P.encode(), co("tok-u1", "co-o"), "co-o ObjectId value"),
    ("GET", P.encode(), co("tok-u1", "co-q"), "co-q Decimal128 value"),
    ("GET", P.encode(), co("tok-u1", "co-z"), "u1 unowned header co-z → default"),
    ("GET", P.encode(), co("tok-u1", "co-nope"), "u1 unknown header → default"),
    ("GET", P.encode(), co("tok-u1", ""), "u1 empty header"),
    ("GET", P.encode(), A1 + [("x-company-id", "co-c")], "lower-case header name"),
    ("GET", P.encode(), A1 + [("X-Company-Id", "  co-c  ")], "header with surrounding spaces"),
    ("GET", P.encode(), A1 + [("X-Company-Id", "CO-C")], "header case differs"),
    ("GET", P.encode(), auth("tok-u2"), "u2 default co-z"),
    ("GET", P.encode(), co("tok-u2", "co-a"), "u2 header u1's co-a → default"),
    ("GET", P.encode(), auth("tok-u3"), "u3 no default company (py repair)"),
    ("GET", P.encode(), auth("tok-u3"), "u3 again"),
    ("GET", P.encode(), co("tok-u3", "co-u3b"), "u3 header co-u3b"),
    ("GET", (P + "?limit=5").encode(), A1, "query limit ignored"),
    ("GET", (P + "?company_id=co-b&x=1&x=2").encode(), A1, "query company_id / repeated ignored"),
    ("GET", (P + "?").encode(), A1, "empty query"),
    ("GET", (P + "?%zz=%C3").encode(), A1, "malformed query ignored"),
    ("HEAD", P.encode(), A1, "HEAD auth"),
    ("HEAD", P.encode(), [], "HEAD no auth"),
] + [("GET", P.encode(), A1, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", (P + "/").encode(), A1, "trailing slash"),
        ("GET", (P + "/x").encode(), A1, "sub-path /x"),
        ("GET", (P + "//").encode(), A1, "double slash"),
        ("GET", P.encode() + b"?q=\xc3\xa9", A1, "raw non-ASCII query bytes"),
        ("GET", P.encode(), A1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-c")], "DUPLICATE X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:300].decode("utf-8", "replace")


async def run() -> int:
    print(f"[gate7x] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        now = datetime.now(timezone.utc)
        sess = lambda tok, uid, exp: {"session_token": tok, "user_id": uid, "effective_role": "owner",
                                       "expires_at": exp.isoformat(), "last_refreshed_at": now.isoformat()}
        await d.user_sessions.insert_many([sess(f"tok-{u}", u, now + timedelta(hours=2)) for u in ("u1", "u2", "u3")]
                                          + [sess("tok-exp", "u1", now - timedelta(minutes=1))])
        await d.users.insert_many([{"user_id": u, "email": f"{u}@x", "name": u.upper()} for u in ("u1", "u2", "u3")])
        await d.companies.insert_many([dict(c) for c in COMPANIES])
        await d.chat_sessions.insert_many(seed_rows())

        tie_rows = []
        for cid in ("co-a", "co-b", "co-i", "co-j", "co-k", "co-m"):
            q = {"user_id": "u1", "company_id": cid}
            lim = [x["id"] for x in await d.chat_sessions.find(q, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)]
            unl = [x["id"] for x in await d.chat_sessions.find(q, {"_id": 0}).sort("created_at", -1).to_list(50)]
            tie_rows.append((cid, len(unl), lim == unl, set(lim) == set(unl)))

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate7x_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate7x_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate7x] servers did not start"); return 2
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await d.command({"profile": 2})
        h_start = (await d.command("dbHash", collections=TRACKED))["collections"]

        passed = failed = 0
        rows = []
        py_writes: list = []
        node_changes: list = []
        for method, target, hdr, desc in CASES:
            n_py0 = await d["system.profile"].count_documents({"appName": PY_APP})
            h0 = (await d.command("dbHash", collections=TRACKED))["collections"]
            rp = raw(PY_PORT, method, target, hdr)
            await asyncio.sleep(0.1)
            n_py1 = await d["system.profile"].count_documents({"appName": PY_APP})
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
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and not nch
            passed += ok; failed += (not ok)
            n_items = len(json.loads(rp[2])) if rp[0] == 200 and rp[2][:1] == b"[" else "-"
            rows.append((ok, desc, method, rp, rn, n_py1 - n_py0, len(nd_ops), nch, n_items))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})

        def cs_cmd(profs):
            for p in profs:
                c = p.get("command") or {}
                if c.get("find") == "chat_sessions":
                    return {k: c.get(k) for k in ("filter", "sort", "projection", "limit", "batchSize", "singleBatch")}
            return None
        cmd_py, cmd_nd = cs_cmd(prof_py), cs_cmd(prof)
        cmd_same = bool(cmd_py and cmd_nd) and all(cmd_py.get(k) == cmd_nd.get(k) for k in ("filter", "sort", "projection", "limit"))

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 7x · LIVE PARITY (GET /api/ai/sessions) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, n_items in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:42} py={rp[0]} node={rn[0]} items={n_items!s:>3} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} "
                  f"ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} db py={dpy} node={dnd} "
                  f"node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} allow={rp[1].get('allow')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} allow={rn[1].get('allow')!r} {pretty(rn[2])!r}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += cmd_same; failed += (not cmd_same)
        print(f"  [{'PASS' if cmd_same else 'FAIL'}] same find command on chat_sessions:\n        py  : {cmd_py}\n        node: {cmd_nd}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run: {APP_COLLS}")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print("  tie evidence (direct Motor, u1): cid, n, limit(50)==unlimited order, same set")
        for t in tie_rows:
            print(f"    {t}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:32} py={rp[0]} {rp[2][:70]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r}"
                  f" | node={rn[0]} {rn[2][:70]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 3}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate7x_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes), "tie": tie_rows, "cmd_py": str(cmd_py), "cmd_node": str(cmd_nd)},
            indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate7x] dropped {DB}; leftover gate7x DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate7x_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
