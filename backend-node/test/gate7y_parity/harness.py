"""Phase 3 · Gate 7y · live Python↔Node parity harness for the reminder digest.

Covers:
  * GET /api/reminders/digest   (backend/routers/customers.py::get_reminder_digest, L1395-1401)

Python: get_current_user → reminder_digests.find_one({user_id}, {_id:0},
sort=[("generated_at", -1)]) → {"digest": null, "message": ...} | {"digest": doc}.
USER-ONLY scope: no `_active_company_id`, no company_id filter.

Comparison is BYTE-EXACT on the body and EXACT on status, content-type,
content-length and allow. DB activity is attributed PER SERVER (profiler
appName + dbHash taken between the two requests). Node must never write and
must never read `companies` for this route. Python's scheduler is disabled
(DISABLE_SCHEDULER=1) so no cron writes reminder_digests during the run.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, sub-paths, raw non-ASCII query bytes, duplicate X-Company-Id headers.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64, ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7y_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7y-py", "trukvia-gate7y-node"
PY_PORT, NODE_PORT = 8270, 8271
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "reminder_digests", "invoices", "customers", "audit_logs",
           "save_health", "idempotency_keys", "notifications"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions",)]
P = "/api/reminders/digest"
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
USERS = [f"u{i}" for i in range(1, 12)]


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


def digest(uid: str, day: str, gen, entries=None, **extra) -> dict:
    entries = entries if entries is not None else [
        {"company_id": "co-a", "customer_id": "cust-1", "balance": 1500.0, "invoices": 2, "oldest_days": 12},
        {"company_id": "co-b", "customer_id": "cust-2", "balance": 249.75, "invoices": 1, "oldest_days": 0},
    ]
    d = {"user_id": uid, "date": day, "generated_at": gen, "entries": entries, "total_customers": len(entries),
         "total_outstanding": round(sum(float(e.get("balance", 0)) for e in entries), 2)}
    d.update(extra)
    return d


def iso(day: int, hour: int = 12) -> str:
    return datetime(2026, 5, day, hour, 30, tzinfo=timezone.utc).isoformat()


def seed_digests() -> list[dict]:
    rows = [
        # u1 — normal: three digests, latest (May 3) must win regardless of insert order
        digest("u1", "2026-05-02", iso(2)), digest("u1", "2026-05-03", iso(3), marker="latest-u1"),
        digest("u1", "2026-05-01", iso(1)),
        # u2 — other user, newer digest whose entries name u1's companies (must never leak to u1)
        digest("u2", "2026-05-09", iso(9), entries=[{"company_id": "co-a", "customer_id": "cust-9", "balance": 10.0,
                                                    "invoices": 1, "oldest_days": 1}], marker="u2-only"),
        # u3 — owns companies but has no default (Python company helper is NOT called here)
        digest("u3", "2026-05-04", iso(4), marker="u3"),
        # u6 — mixed generated_at BSON types (Date sorts above strings; null/missing lowest)
        digest("u6", "2026-05-05", iso(5), marker="string-gen"),
        digest("u6", "2026-05-01", datetime(2026, 5, 1, 1, 2, 3, 456000), marker="date-gen"),
        digest("u6", "2026-05-06", None, marker="null-gen"),
        {"user_id": "u6", "date": "2026-05-07", "marker": "missing-gen"},
        digest("u6", "2026-05-08", 20260508, marker="number-gen"),
        # u7 — serialization edge values
        digest("u7", "2026-05-02", iso(2), entries=[
            {"company_id": "co-a", "customer_id": "c", "balance": 0.1 + 0.2, "invoices": Int64(2 ** 53 + 1),
             "oldest_days": -0.0, "big": 1e16, "tiny": 1.5e-7, "whole": 1500.0, "i": 7, "nil": None, "flag": True,
             "nested": {"arr": [1, 2.5, "x", {}], "empty": []}}],
            note="Ünïcødé 🚚 \"q\" \\ \n\t\x01  ", when=datetime(2026, 5, 2, 10, 0, 0)),
        # u8 — NaN inside the latest digest → Python 500
        digest("u8", "2026-05-02", iso(2), total_outstanding=float("nan")),
        digest("u8", "2026-05-01", iso(1)),
        # u9 — the only digest lacks generated_at
        {"user_id": "u9", "date": "2026-05-01", "entries": [], "total_customers": 0, "total_outstanding": 0.0},
        # u10 — ObjectId value → Python 500
        digest("u10", "2026-05-01", iso(1), ref=ObjectId("65a000000000000000000001")),
    ]
    # u4 — 5 digests with IDENTICAL generated_at (tie), distinct markers
    rows += [digest("u4", f"2026-05-{d:02d}", iso(10), marker=f"tie-{d}") for d in (3, 1, 5, 2, 4)]
    # u11 — 60 identical generated_at plus older ones
    rows += [digest("u11", "2026-05-10", iso(10), marker=f"tie60-{n}") for n in range(60)]
    rows += [digest("u11", "2026-05-01", iso(1), marker=f"old-{n}") for n in range(5)]
    # u5 has NO digests → null shape
    return rows


COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    {"id": "co-b", "user_id": "u1", "is_default": False, "name": "B"},
    {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
    {"id": "co-u3a", "user_id": "u3", "is_default": False, "name": "U3A"},
    {"id": "co-u3b", "user_id": "u3", "is_default": False, "name": "U3B"},
]

CASES: list[tuple[str, bytes, list, str]] = [
    ("GET", P.encode(), [], "no auth"),
    ("GET", P.encode(), [("Authorization", "Bearer nope")], "invalid bearer"),
    ("GET", P.encode(), [("Authorization", "Bearer tok-exp")], "expired session"),
    ("GET", P.encode(), [("Cookie", "session_token=tok-u1")], "session cookie"),
    ("GET", P.encode(), auth("u1"), "u1 latest digest (default co-a)"),
    ("GET", P.encode(), co("u1", "co-b"), "u1 owned alternate company"),
    ("GET", P.encode(), co("u1", "co-z"), "u1 unowned header (u2's co-z)"),
    ("GET", P.encode(), co("u1", "co-nope"), "u1 unknown header"),
    ("GET", P.encode(), co("u1", ""), "u1 empty header"),
    ("GET", P.encode(), auth("u2"), "u2 own digest"),
    ("GET", P.encode(), co("u2", "co-a"), "u2 with u1's company header"),
    ("GET", P.encode(), auth("u3"), "u3 no default company"),
    ("GET", P.encode(), co("u3", "co-u3b"), "u3 header co-u3b"),
    ("GET", P.encode(), auth("u4"), "u4 5-way generated_at tie"),
    ("GET", P.encode(), auth("u5"), "u5 no digest → null shape"),
    ("GET", P.encode(), co("u5", "co-a"), "u5 null shape + foreign header"),
    ("GET", P.encode(), auth("u6"), "u6 mixed generated_at types"),
    ("GET", P.encode(), auth("u7"), "u7 serialization edges"),
    ("GET", P.encode(), auth("u8"), "u8 NaN → 500"),
    ("GET", P.encode(), auth("u9"), "u9 digest without generated_at"),
    ("GET", P.encode(), auth("u10"), "u10 ObjectId → 500"),
    ("GET", P.encode(), auth("u11"), "u11 60-way tie"),
    ("GET", (P + "?user_id=u2").encode(), auth("u1"), "query user_id ignored"),
    ("GET", (P + "?x=1&x=2&limit=5").encode(), auth("u1"), "repeated / junk query ignored"),
    ("GET", (P + "?").encode(), auth("u1"), "empty query"),
    ("GET", (P + "?%zz=%C3").encode(), auth("u1"), "malformed query encoding ignored"),
    ("HEAD", P.encode(), auth("u1"), "HEAD auth"),
    ("HEAD", P.encode(), [], "HEAD no auth"),
] + [("GET", P.encode(), auth("u1"), f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", (P + "/").encode(), auth("u1"), "trailing slash"),
        ("GET", (P + "/x").encode(), auth("u1"), "sub-path /x"),
        ("GET", (P + "/run").encode(), auth("u1"), "GET on POST-only /run (no write)"),
        ("GET", P.encode() + b"?q=\xc3\xa9", auth("u1"), "raw non-ASCII query bytes"),
        ("GET", P.encode(), auth("u1") + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-z")],
         "duplicate X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:300].decode("utf-8", "replace")


async def run() -> int:
    print(f"[gate7y] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        now = datetime.now(timezone.utc)
        sess = lambda tok, uid, exp: {"session_token": tok, "user_id": uid, "effective_role": "owner",
                                       "expires_at": exp.isoformat(), "last_refreshed_at": now.isoformat()}
        await d.user_sessions.insert_many([sess(f"tok-{u}", u, now + timedelta(hours=2)) for u in USERS]
                                          + [sess("tok-exp", "u1", now - timedelta(minutes=1))])
        await d.users.insert_many([{"user_id": u, "email": f"{u}@x", "name": u.upper()} for u in USERS])
        await d.companies.insert_many([dict(c) for c in COMPANIES])
        await d.reminder_digests.insert_many(seed_digests())

        tie = []
        for u in ("u4", "u6", "u11"):
            fo = await d.reminder_digests.find_one({"user_id": u}, {"_id": 0}, sort=[("generated_at", -1)])
            first = (await d.reminder_digests.find({"user_id": u}, {"_id": 0}).sort("generated_at", -1).to_list(1))[0]
            tie.append((u, fo.get("marker"), first.get("marker"), fo == first))

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate7y_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate7y_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate7y] servers did not start"); return 2
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
            nd_colls = sorted({(o.get("ns") or ".").split(".", 1)[1] for o in nd_ops})
            py_colls = sorted({(o.get("ns") or ".").split(".", 1)[1] for o in py_ops})
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and not nch and "companies" not in nd_colls
            passed += ok; failed += (not ok)
            shape = "-"
            if rp[0] == 200:
                j = json.loads(rp[2]); shape = "null" if j.get("digest") is None else f"doc:{(j['digest'] or {}).get('marker', '')}"
            rows.append((ok, desc, method, rp, rn, len(py_ops), len(nd_ops), nch, shape, py_colls, nd_colls))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})

        def rd_cmd(profs):
            for p in profs:
                c = p.get("command") or {}
                if c.get("find") == "reminder_digests":
                    return {k: c.get(k) for k in ("filter", "sort", "projection", "limit", "singleBatch", "batchSize")}
            return None
        cmd_py, cmd_nd = rd_cmd(prof_py), rd_cmd(prof)
        cmd_same = bool(cmd_py and cmd_nd) and all(cmd_py.get(k) == cmd_nd.get(k)
                                                   for k in ("filter", "sort", "projection", "limit", "singleBatch"))

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 7y · LIVE PARITY (GET /api/reminders/digest) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, shape, pyc, ndc in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:38} py={rp[0]} node={rn[0]} {shape:16} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} "
                  f"ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} db py={dpy}{pyc} node={dnd}{ndc} "
                  f"node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} allow={rp[1].get('allow')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} allow={rn[1].get('allow')!r} {pretty(rn[2])!r}")
        zero_ok = not node_writes and not node_changes and "companies" not in node_colls
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write / user-only: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += cmd_same; failed += (not cmd_same)
        print(f"  [{'PASS' if cmd_same else 'FAIL'}] same find command on reminder_digests:\n        py  : {cmd_py}\n        node: {cmd_nd}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run (incl. companies): {APP_COLLS}")
        print(f"  python-side writes (auth rolling refresh — Python-only, NOT the handler): {py_writes or 'none'}; "
              f"python write collections={py_colls_w}")
        print(f"  tie evidence (direct Motor: find_one marker, find().sort()[0] marker, equal): {tie}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:34} py={rp[0]} {rp[2][:70]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r}"
                  f" | node={rn[0]} {rn[2][:70]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 3}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate7y_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes), "tie": tie, "cmd_py": str(cmd_py), "cmd_node": str(cmd_nd)},
            indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate7y] dropped {DB}; leftover gate7y DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate7y_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
