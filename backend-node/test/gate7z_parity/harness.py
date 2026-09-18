"""Phase 3 · Gate 7z · live Python↔Node parity harness for the driver salary-settlement hint.

Covers:
  * GET /api/drivers/{did}/salary-settlement-hint?month=...
    (backend/routers/driver_payments.py::salary_settlement_hint, L294-304)

Python: get_current_user → required `month: str` → _active_company_id →
driver_ledger_entries.find_one({user_id, company_id, driver_id, month,
kind:"settlement"}, {_id:0}) → {"possible_duplicate", "existing_settlement"}.

Seeds BOTH realistic settlements exactly as driver_ledger.py::settle writes
them (entry_type / month_key / reference.{kind,month} — which the hint's
top-level month/kind filter never matches → always false: Python behaviour,
copied not fixed) AND synthetic documents that do carry top-level month +
kind so the `true` branch and document serialization are exercised.

BYTE-EXACT body; EXACT status, content-type, content-length, allow. DB
activity attributed PER SERVER. Node must never write.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, invalid UTF-8 path escape, did > 100 chars, raw non-ASCII query
bytes, duplicate X-Company-Id headers.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64, ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7z_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7z-py", "trukvia-gate7z-node"
PY_PORT, NODE_PORT = 8272, 8273
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "drivers", "driver_ledger_entries", "driver_payments",
           "audit_logs", "save_health", "idempotency_keys", "fin_txn"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions", "companies")]
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}


def P(did: str, qs: str | None = "month=2026-04") -> bytes:
    return (f"/api/drivers/{did}/salary-settlement-hint" + ("" if qs is None else f"?{qs}")).encode()


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


def real_settlement(uid: str, cid: str, did: str, month: str, eid: str) -> dict:
    """Exactly the shape driver_ledger.py::settle inserts (L394-412)."""
    return {"user_id": uid, "company_id": cid, "driver_id": did, "entry_date": f"{month}-30", "month_key": month,
            "entry_type": "settlement", "direction": "debit", "amount": 18000.0, "source": "system",
            "reference": {"kind": "settlement", "month": month}, "remarks": f"Monthly settlement — {month}",
            "updated_at": "2026-05-01T00:00:00+00:00", "updated_by": uid, "id": eid,
            "created_at": "2026-05-01T00:00:00+00:00", "created_by": uid}


def hinted(uid: str, cid: str, did: str, month, marker: str, **extra) -> dict:
    """Synthetic document carrying the TOP-LEVEL month/kind the hint filters on."""
    d = {"id": f"dle-{marker}", "user_id": uid, "company_id": cid, "driver_id": did, "month": month,
         "kind": "settlement", "amount": 18000.0, "marker": marker}
    d.update(extra)
    return d


LONG_MONTH = "M" * 5000


def seed_entries() -> list[dict]:
    return [
        # realistic writer output — never matched by the hint (Python bug, copied)
        real_settlement("u1", "co-a", "d1", "2026-05", "dle-real-1"),
        real_settlement("u1", "co-a", "d1", "2026-04", "dle-real-2"),
        real_settlement("u1", "co-a", "d-real", "2026-04", "dle-real-3"),
        # synthetic top-level month/kind documents
        hinted("u1", "co-a", "d1", "2026-04", "u1-a-d1-apr", paid=True, note=None, amount=18000.0,
               tiny=1.5e-7, z=-0.0, big=Int64(2 ** 53 + 1), when=datetime(2026, 5, 1, 10, 0, 0, 250000),
               text="Ünïcødé 🚚 \"q\" \\ \n\t\x01  ", nested={"a": [1, 2.5, {}], "e": []}),
        hinted("u1", "co-b", "d1", "2026-04", "u1-b-d1-apr"),
        hinted("u2", "co-a", "d1", "2026-04", "u2-in-u1-company"),
        hinted("u2", "co-z", "d2", "2026-04", "u2-z-d2-apr"),
        hinted("u1", "co-a", "d1", "", "empty-month"),
        hinted("u1", "co-a", "d1", "�", "replacement-month"),
        hinted("u1", "co-a", "d1", "1.0", "month-1.0"),
        hinted("u1", "co-a", "d1", " 2026-04 ", "month-spaced"),
        hinted("u1", "co-a", "d1", "é-月", "month-unicode"),
        hinted("u1", "co-a", "d1", LONG_MONTH, "month-long"),
        hinted("u1", "co-a", "d1", "2026-04 x", "month-plus"),
        hinted("u1", "co-a", "drv-é", "2026-04", "did-unicode"),
        hinted("u1", "co-a", "a b", "2026-04", "did-space"),
        hinted("u1", "co-a", "x.y", "2026-04", "did-dot"),
        hinted("u1", "co-a", "d-tie", "2026-04", "tie-1"),
        hinted("u1", "co-a", "d-tie", "2026-04", "tie-2"),
        hinted("u1", "co-a", "d-tie", "2026-04", "tie-3"),
        hinted("u1", "co-a", "d-nan", "2026-04", "nan", amount=float("nan")),
        hinted("u1", "co-a", "d-inf", "2026-04", "inf", amount=float("-inf")),
        hinted("u1", "co-a", "d-oid", "2026-04", "oid", ref=ObjectId("65a000000000000000000001")),
        {"id": "dle-other-kind", "user_id": "u1", "company_id": "co-a", "driver_id": "d-kind", "month": "2026-04",
         "kind": "advance", "marker": "other-kind"},
        {"user_id": "u1", "company_id": "co-a", "driver_id": "d-min", "month": "2026-04", "kind": "settlement"},
        hinted("u3", "co-u3a", "d3", "2026-04", "u3-first-company"),
        hinted("u3", "co-u3b", "d3", "2026-04", "u3-second-company"),
    ]


COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    {"id": "co-b", "user_id": "u1", "is_default": False, "name": "B"},
    {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
    {"id": "co-u3a", "user_id": "u3", "is_default": False, "name": "U3A"},
    {"id": "co-u3b", "user_id": "u3", "is_default": False, "name": "U3B"},
]
DRIVERS = [{"id": "d1", "user_id": "u1", "company_id": "co-a", "name": "Driver One"},
           {"id": "d2", "user_id": "u2", "company_id": "co-z", "name": "Driver Two"}]

U1 = auth("u1")
CASES: list[tuple[str, bytes, list, str]] = [
    # auth / precedence
    ("GET", P("d1"), [], "no auth"),
    ("GET", P("d1", None), [], "no auth + missing month"),
    ("GET", P("d1"), [("Authorization", "Bearer nope")], "invalid bearer"),
    ("GET", P("d1"), [("Authorization", "Bearer tok-exp")], "expired session"),
    ("GET", P("d1"), [("Cookie", "session_token=tok-u1")], "session cookie"),
    # the Python bug: realistic settlements never match
    ("GET", P("d1", "month=2026-05"), U1, "real settlement May → false (bug)"),
    ("GET", P("d-real"), U1, "real settlement only → false (bug)"),
    ("GET", P("d-kind"), U1, "top-level month but kind advance → false"),
    ("GET", P("nope"), U1, "nonexistent driver → false (no 404)"),
    ("GET", P("d2"), U1, "another user's driver id → false"),
    # true branch
    ("GET", P("d1"), U1, "synthetic top-level match → true + doc"),
    ("GET", P("d-min"), U1, "minimal matching doc"),
    ("GET", P("d-tie"), U1, "3 matching docs (find_one tie)"),
    ("GET", P("d-nan"), U1, "NaN → 500"),
    ("GET", P("d-inf"), U1, "-Infinity → 500"),
    ("GET", P("d-oid"), U1, "ObjectId → 500"),
    # company isolation
    ("GET", P("d1"), co("u1", "co-a"), "u1 header co-a"),
    ("GET", P("d1"), co("u1", "co-b"), "u1 owned alternate co-b"),
    ("GET", P("d1"), co("u1", "co-z"), "u1 unowned header co-z → default"),
    ("GET", P("d1"), co("u1", "co-nope"), "u1 unknown header → default"),
    ("GET", P("d1"), co("u1", ""), "u1 empty header"),
    ("GET", P("d1"), auth("u2"), "u2 default co-z, driver d1"),
    ("GET", P("d1"), co("u2", "co-a"), "u2 supplying u1's co-a"),
    ("GET", P("d2"), auth("u2"), "u2 own driver d2 → true"),
    ("GET", P("d3"), auth("u3"), "u3 no default company (py repair)"),
    ("GET", P("d3"), auth("u3"), "u3 again"),
    ("GET", P("d3"), co("u3", "co-u3b"), "u3 header co-u3b"),
    # month validation / decoding
    ("GET", P("d1", None), U1, "month missing"),
    ("GET", P("d1", ""), U1, "empty query string"),
    ("GET", P("d1", "month="), U1, "month empty → matches '' doc"),
    ("GET", P("d1", "month"), U1, "month without = → ''"),
    ("GET", P("d1", "month%5B%5D=2026-04"), U1, "month[] → missing"),
    ("GET", P("d1", "Month=2026-04"), U1, "Month (case) → missing"),
    ("GET", P("d1", "mon%74h=2026-04"), U1, "percent-encoded key"),
    ("GET", P("d1", "month=x&month=2026-04"), U1, "repeated → last (match)"),
    ("GET", P("d1", "month=2026-04&month=x"), U1, "repeated → last (no match)"),
    ("GET", P("d1", "month=2026-04&month"), U1, "repeated → last bare ''"),
    ("GET", P("d1", "month=1"), U1, "month 1"),
    ("GET", P("d1", "month=01"), U1, "month 01"),
    ("GET", P("d1", "month=1.0"), U1, "month 1.0 (string match)"),
    ("GET", P("d1", "month=1_0"), U1, "month 1_0"),
    ("GET", P("d1", "month=%202026-04%20"), U1, "month with spaces (no strip)"),
    ("GET", P("d1", "month=2026-04+x"), U1, "plus as space"),
    ("GET", P("d1", "month=%C3%A9-%E6%9C%88"), U1, "Unicode month"),
    ("GET", P("d1", "month=%C3"), U1, "invalid UTF-8 escape → U+FFFD"),
    ("GET", P("d1", "month=%zz"), U1, "invalid escape kept"),
    ("GET", P("d1", "month=" + "M" * 5000), U1, "5000-char month"),
    ("GET", P("d1", "month=99999999999999999999999"), U1, "huge numeric month"),
    ("GET", P("d1", "month=2026-04&other=1"), U1, "extra params ignored"),
    # path
    ("GET", P("drv-%C3%A9"), U1, "percent-encoded Unicode did"),
    ("GET", P("a%20b"), U1, "encoded space did"),
    ("GET", P("x.y"), U1, "dotted did"),
    ("GET", P(""), U1, "empty did segment"),
    ("GET", P("", None), [], "empty did, no auth, no month"),
    ("GET", P("a%2Fb"), U1, "encoded slash in did"),
    # HEAD
    ("HEAD", P("d1"), U1, "HEAD auth"),
    ("HEAD", P("d1", None), [], "HEAD no auth, no month"),
] + [("GET", P("d1"), U1, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", b"/api/drivers/d1/salary-settlement-hint/?month=2026-04", U1, "trailing slash"),
        ("GET", P("%FF"), U1, "invalid UTF-8 path escape"),
        ("GET", P("d" * 120), U1, "did > 100 chars (maxParamLength)"),
        ("GET", P("d1") + b"&q=\xc3\xa9", U1, "raw non-ASCII query bytes"),
        ("GET", P("d1"), U1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")], "duplicate X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:260].decode("utf-8", "replace")


async def run() -> int:
    print(f"[gate7z] DB={DB} (isolated — UAT data untouched)")
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
        await d.drivers.insert_many([dict(x) for x in DRIVERS])
        await d.driver_ledger_entries.insert_many(seed_entries())

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate7z_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate7z_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate7z] servers did not start"); return 2
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
            nd_colls = sorted({(o.get("ns") or ".").split(".", 1)[1] for o in nd_ops})
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and not nch and "drivers" not in nd_colls
            passed += ok; failed += (not ok)
            val = "-"
            if rp[0] == 200:
                j = json.loads(rp[2]); val = f"{str(j['possible_duplicate']).lower()}:{(j['existing_settlement'] or {}).get('marker', '')}"
            rows.append((ok, desc, method, rp, rn, n_py1 - n_py0, len(nd_ops), nch, val, nd_colls))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})
        py_read_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if not is_write(p)})

        def dle_cmd(profs):
            for p in profs:
                c = p.get("command") or {}
                if c.get("find") == "driver_ledger_entries":
                    return {k: c.get(k) for k in ("filter", "sort", "projection", "limit", "singleBatch")}
            return None
        cmd_py, cmd_nd = dle_cmd(prof_py), dle_cmd(prof)
        cmd_same = bool(cmd_py and cmd_nd) and all(cmd_py.get(k) == cmd_nd.get(k)
                                                   for k in ("filter", "sort", "projection", "limit", "singleBatch"))

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 7z · LIVE PARITY (GET /api/drivers/{did}/salary-settlement-hint) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, val, ndc in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:40} py={rp[0]} node={rn[0]} {val:26} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} "
                  f"ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} db py={dpy} node={dnd}{ndc} "
                  f"node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} allow={rp[1].get('allow')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} allow={rn[1].get('allow')!r} {pretty(rn[2])!r}")
        zero_ok = not node_writes and not node_changes and "drivers" not in node_colls
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += cmd_same; failed += (not cmd_same)
        print(f"  [{'PASS' if cmd_same else 'FAIL'}] same find command on driver_ledger_entries:\n        py  : {cmd_py}\n        node: {cmd_nd}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run: {APP_COLLS}")
        print(f"  python read collections: {py_read_colls} (no `drivers` read ⇒ no driver existence check)")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:34} py={rp[0]} {rp[2][:80]!r} loc={rp[1].get('location')!r} | node={rn[0]} {rn[2][:80]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 3}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate7z_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes), "cmd_py": str(cmd_py), "cmd_node": str(cmd_nd)}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate7z] dropped {DB}; leftover gate7z DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate7z_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
