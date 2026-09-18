"""Phase 3 · Gate 8a · live Python↔Node parity harness for AI chat session messages.

Covers:
  * GET /api/ai/sessions/{sid}/messages   (backend/routers/ai.py::get_session_messages, L314-321)

Python: get_current_user → _active_company_id →
  READ #1 chat_sessions.find_one({id, user_id, company_id}, {_id:0}) → 404
  READ #2 chat_messages.find({session_id}, {_id:0}).sort(created_at, 1).to_list(500)

READ #2 is scoped by session_id ONLY — the seeded data deliberately places
same-sid messages under other users / companies plus orphans, so Python's
actual exposure is reproduced (not "fixed").

BYTE-EXACT body; EXACT status, content-type, content-length, allow. Each
read is compared independently (find command shape per collection) and the
number of route reads per request is compared per server. DB activity is
attributed PER SERVER. Node must never write.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, invalid UTF-8 path escape, sid > 100 chars, raw non-ASCII query
bytes, duplicate X-Company-Id headers.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64, ObjectId, Decimal128, Binary, Code
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate8a_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate8a-py", "trukvia-gate8a-node"
PY_PORT, NODE_PORT = 8274, 8275
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "chat_sessions", "chat_messages", "audit_logs", "save_health",
           "idempotency_keys"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions", "companies")]
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
LONG_SID = "s" * 120


def P(sid: str, qs: str = "") -> bytes:
    return (f"/api/ai/sessions/{sid}/messages" + (f"?{qs}" if qs else "")).encode()


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


BASE = datetime(2026, 5, 1, tzinfo=timezone.utc)


def iso(i: int) -> str:
    return (BASE + timedelta(seconds=i)).isoformat()


def sess(sid: str, uid: str, cid: str) -> dict:
    return {"id": sid, "title": f"chat {sid}", "created_at": iso(0), "user_id": uid, "company_id": cid}


def msg(sid: str, n: int, created_at, uid: str = "u1", cid: str = "co-a", **extra) -> dict:
    d = {"id": f"m-{sid}-{uid}-{n:04d}", "session_id": sid, "role": "user" if n % 2 == 0 else "assistant",
         "content": f"message {n} of {sid}", "created_at": created_at, "user_id": uid, "company_id": cid}
    d.update(extra)
    return d


SESSIONS = [
    sess("s1", "u1", "co-a"), sess("s-empty", "u1", "co-a"), sess("s-b", "u1", "co-b"), sess("s-u2", "u2", "co-z"),
    sess("s-dup", "u1", "co-a"), sess("s-dup", "u2", "co-z"),            # same id, two owners
    sess("s-big", "u1", "co-a"), sess("s-tie", "u1", "co-a"), sess("s-ser", "u1", "co-a"),
    sess("s-nan", "u1", "co-a"), sess("s-inf", "u1", "co-a"), sess("s-oid", "u1", "co-a"),
    sess("s-dec", "u1", "co-a"), sess("s-bin", "u1", "co-a"), sess("s-mixed", "u1", "co-a"),
    sess("sé", "u1", "co-a"), sess("a b", "u1", "co-a"), sess("x.y", "u1", "co-a"),
    sess("s-u3a", "u3", "co-u3a"), sess("s-u3b", "u3", "co-u3b"),
    {"id": "s-min", "user_id": "u1", "company_id": "co-a"},
]


def seed_messages() -> list[dict]:
    rows = [msg("s1", n, iso(10 - n)) for n in range(5)]                         # inserted newest-first
    rows += [msg("s1", 90, iso(3), uid="u2", cid="co-z"),                         # leak: same sid, other user
             msg("s1", 91, iso(4), uid="u1", cid="co-b"),                         # leak: same sid, other company
             {"session_id": "s1", "content": "orphan without fields"},            # orphan (no created_at)
             {"session_id": "s1", "id": "m-orphan-null", "created_at": None}]
    rows += [msg("s-b", n, iso(n), cid="co-b") for n in range(2)]
    rows += [msg("s-u2", n, iso(n), uid="u2", cid="co-z") for n in range(2)]
    rows += [msg("s-dup", n, iso(n)) for n in range(2)] + [msg("s-dup", 50 + n, iso(n), uid="u2", cid="co-z") for n in range(2)]
    rows += [msg("s-big", n, iso(n % 7)) for n in range(600)]                     # 600 msgs, 7 tie groups → cut at 500
    rows += [msg("s-tie", n, iso(0)) for n in range(60)]                          # 60 identical timestamps
    rows += [msg("s-ser", 0, iso(1), score=5.0, z=-0.0, big=Int64(2 ** 53 + 1), huge=10 ** 18, tiny=1.5e-7,
                 nil=None, flag=True, nested={"a": [1, 2.5, "x", {"k": []}], "e": {}},
                 when=datetime(2026, 5, 1, 10, 0, 0, 123000),
                 content="Ünïcødé 🚚 \"q\" \\ \n\t\x01  ", code=Code("function(){}")),
             msg("s-ser", 1, iso(2), content=None),
             {"id": "m-ser-min", "session_id": "s-ser", "created_at": iso(3)}]
    rows += [msg("s-nan", 0, iso(1)), msg("s-nan", 1, iso(2), score=float("nan"))]
    rows += [msg("s-inf", 0, iso(1), score=float("inf"))]
    rows += [msg("s-oid", 0, iso(1), ref=ObjectId("65a000000000000000000001"))]
    rows += [msg("s-dec", 0, iso(1), amt=Decimal128("12.50"))]
    rows += [msg("s-bin", 0, iso(1), blob=Binary(b"hello"))]
    rows += [msg("s-mixed", 0, iso(5)), msg("s-mixed", 1, datetime(2026, 5, 1, 0, 0, 1)), msg("s-mixed", 2, None),
             msg("s-mixed", 3, 12345), {"id": "m-mixed-missing", "session_id": "s-mixed"}, msg("s-mixed", 4, "")]
    rows += [msg("sé", 0, iso(1)), msg("a b", 0, iso(1)), msg("x.y", 0, iso(1))]
    rows += [msg("s-u3a", 0, iso(1), uid="u3", cid="co-u3a"), msg("s-u3b", 0, iso(1), uid="u3", cid="co-u3b")]
    rows += [msg("s-nosession", 0, iso(1))]                                       # messages, no session doc
    return rows


COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    {"id": "co-b", "user_id": "u1", "is_default": False, "name": "B"},
    {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
    {"id": "co-u3a", "user_id": "u3", "is_default": False, "name": "U3A"},
    {"id": "co-u3b", "user_id": "u3", "is_default": False, "name": "U3B"},
]

U1 = auth("u1")
CASES: list[tuple[str, bytes, list, str]] = [
    ("GET", P("s1"), [], "no auth"),
    ("GET", P(""), [], "no auth + empty sid"),
    ("GET", P("a%2Fb"), [], "no auth + encoded slash"),
    ("GET", P("s1"), [("Authorization", "Bearer nope")], "invalid bearer"),
    ("GET", P("s1"), [("Authorization", "Bearer tok-exp")], "expired session"),
    ("GET", P("s1"), [("Cookie", "session_token=tok-u1")], "session cookie"),
    ("GET", P("s1"), U1, "s1 owned (incl. same-sid leaks + orphans)"),
    ("GET", P("s-empty"), U1, "owned session, zero messages → []"),
    ("GET", P("s-min"), U1, "minimal session doc, no messages"),
    ("GET", P("nope"), U1, "nonexistent session → 404"),
    ("GET", P("s-nosession"), U1, "messages exist but no session → 404"),
    ("GET", P("s-u2"), U1, "another user's session → 404"),
    ("GET", P("s-b"), U1, "other company's session (default co-a) → 404"),
    ("GET", P("s-b"), co("u1", "co-b"), "owned alternate company co-b"),
    ("GET", P("s1"), co("u1", "co-b"), "s1 under header co-b → 404"),
    ("GET", P("s1"), co("u1", "co-z"), "unowned header co-z → default"),
    ("GET", P("s1"), co("u1", "co-nope"), "unknown header → default"),
    ("GET", P("s1"), co("u1", ""), "empty header"),
    ("GET", P("s-dup"), U1, "same sid two owners (u1) → both owners' msgs"),
    ("GET", P("s-dup"), auth("u2"), "same sid two owners (u2)"),
    ("GET", P("s-u2"), auth("u2"), "u2 own session"),
    ("GET", P("s1"), auth("u2"), "u2 requesting u1's s1 → 404"),
    ("GET", P("s1"), co("u2", "co-a"), "u2 supplying u1's co-a → 404"),
    ("GET", P("s-u3a"), auth("u3"), "u3 no default company (py repair)"),
    ("GET", P("s-u3b"), auth("u3"), "u3 second company without header → 404"),
    ("GET", P("s-u3b"), co("u3", "co-u3b"), "u3 header co-u3b"),
    ("GET", P("s-big"), U1, "600 msgs, 7 tie groups → 500 cut"),
    ("GET", P("s-tie"), U1, "60 identical timestamps"),
    ("GET", P("s-mixed"), U1, "mixed created_at BSON types"),
    ("GET", P("s-ser"), U1, "serialization edges"),
    ("GET", P("s-nan"), U1, "NaN → 500"),
    ("GET", P("s-inf"), U1, "Infinity → 500"),
    ("GET", P("s-oid"), U1, "ObjectId → 500"),
    ("GET", P("s-dec"), U1, "Decimal128 → 500"),
    ("GET", P("s-bin"), U1, "Binary (utf-8) value"),
    ("GET", P("s%C3%A9"), U1, "encoded Unicode sid"),
    ("GET", P("a%20b"), U1, "encoded space sid"),
    ("GET", P("x.y"), U1, "dotted sid"),
    ("GET", P(""), U1, "empty sid → 404 Not Found"),
    ("GET", P("a%2Fb"), U1, "encoded slash → 404 Not Found"),
    ("GET", P("s1", "x=1&x=2&limit=5"), U1, "query ignored (repeated / junk)"),
    ("GET", P("s1", "%zz=%C3"), U1, "malformed query encoding ignored"),
    ("HEAD", P("s1"), U1, "HEAD auth"),
    ("HEAD", P("s1"), [], "HEAD no auth"),
] + [("GET", P("s1"), U1, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", b"/api/ai/sessions/s1/messages/", U1, "trailing slash"),
        ("GET", b"/api/ai/sessions//messages", [], "double slash (no auth)"),
        ("GET", P("%FF"), U1, "invalid UTF-8 path escape"),
        ("GET", P(LONG_SID), U1, "sid > 100 chars (maxParamLength)"),
        ("GET", P("s1") + b"?q=\xc3\xa9", U1, "raw non-ASCII query bytes"),
        ("GET", P("s-b"), U1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")], "duplicate X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:260].decode("utf-8", "replace")


def find_cmds(ops: list, coll: str) -> list:
    return [o for o in ops if (o.get("command") or {}).get("find") == coll]


async def run() -> int:
    print(f"[gate8a] DB={DB} (isolated — UAT data untouched)")
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
        await d.chat_sessions.insert_many([dict(s) for s in SESSIONS] + [sess(LONG_SID, "u1", "co-a")])
        await d.chat_messages.insert_many(seed_messages())

        tie = []
        for sid in ("s-big", "s-tie"):
            lim = [x.get("id") for x in await d.chat_messages.find({"session_id": sid}, {"_id": 0}).sort("created_at", 1).limit(500).to_list(500)]
            unl = [x.get("id") for x in await d.chat_messages.find({"session_id": sid}, {"_id": 0}).sort("created_at", 1).to_list(500)]
            tie.append((sid, len(unl), lim == unl, set(lim) == set(unl)))

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate8a_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate8a_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate8a] servers did not start"); return 2
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
        r1_pairs: list = []
        r2_pairs: list = []
        keys = ("filter", "sort", "projection", "limit", "singleBatch")
        shape = lambda o: {k: (o.get("command") or {}).get(k) for k in keys}
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
            seq_py = [(c, shape(o)) for o in py_ops for c in ("chat_sessions", "chat_messages") if (o.get("command") or {}).get("find") == c]
            seq_nd = [(c, shape(o)) for o in nd_ops for c in ("chat_sessions", "chat_messages") if (o.get("command") or {}).get("find") == c]
            reads_py = (len(find_cmds(py_ops, "chat_sessions")), len(find_cmds(py_ops, "chat_messages")))
            reads_nd = (len(find_cmds(nd_ops, "chat_sessions")), len(find_cmds(nd_ops, "chat_messages")))
            # Route reads must match command-for-command, in order. The ONLY accepted
            # deviation: Python's ApprovalGateMiddleware re-dispatches the whole
            # request after an unhandled exception (framework, approval_gate.py
            # L164-167) → on a 500 its read sequence is exactly Node's, twice.
            redispatch = rp[0] == 500 and seq_nd and seq_py == seq_nd * 2
            reads_ok = seq_py == seq_nd or redispatch
            if redispatch:
                redispatched.append(desc)
            if seq_nd:
                r1_pairs.extend(zip([s for c, s in seq_py if c == "chat_sessions"], [s for c, s in seq_nd if c == "chat_sessions"]))
                r2_pairs.extend(zip([s for c, s in seq_py if c == "chat_messages"], [s for c, s in seq_nd if c == "chat_messages"]))
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and not nch and reads_ok
            passed += ok; failed += (not ok)
            n_items = len(json.loads(rp[2])) if rp[0] == 200 and rp[2][:1] == b"[" else "-"
            rows.append((ok, desc + (" [py re-dispatch]" if redispatch else ""), method, rp, rn, len(py_ops), len(nd_ops),
                         nch, n_items, reads_py, reads_nd))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})

        # Read-command parity over the COUNTED matrix only (INFO requests run after this point).
        r1_same = len(r1_pairs) > 0 and all(a == b for a, b in r1_pairs)
        r2_same = len(r2_pairs) > 0 and all(a == b for a, b in r2_pairs)
        py_log = (LOGDIR / "gate8a_py.log").read_text(encoding="utf-8", errors="replace")
        faults = py_log.count("ApprovalGateMiddleware fault (passthrough)")

        info =[(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 8a · LIVE PARITY (GET /api/ai/sessions/{sid}/messages) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, n_items, rpy, rnd in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:46} py={rp[0]} node={rn[0]} items={n_items!s:>3} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} "
                  f"ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} "
                  f"route-reads(sess,msgs) py={rpy} node={rnd} db py={dpy} node={dnd} node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} allow={rp[1].get('allow')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} allow={rn[1].get('allow')!r} {pretty(rn[2])!r}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += r1_same; failed += (not r1_same)
        print(f"  [{'PASS' if r1_same else 'FAIL'}] READ #1 chat_sessions commands identical, pairwise per request "
              f"({len(r1_pairs)} pairs):\n        e.g. {r1_pairs[0][1] if r1_pairs else None}")
        passed += r2_same; failed += (not r2_same)
        print(f"  [{'PASS' if r2_same else 'FAIL'}] READ #2 chat_messages commands identical, pairwise per request "
              f"({len(r2_pairs)} pairs):\n        e.g. {r2_pairs[0][1] if r2_pairs else None}")
        rd_ok = len(redispatched) == faults
        passed += rd_ok; failed += (not rd_ok)
        print(f"  [{'PASS' if rd_ok else 'FAIL'}] python ApprovalGateMiddleware re-dispatches (framework, NOT route) — "
              f"log faults={faults}, 500 cases with doubled read sequence={len(redispatched)}: {redispatched}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run: {APP_COLLS}")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print(f"  tie evidence (direct Motor: sid, n, limit(500)==unlimited order, same set): {tie}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:34} py={rp[0]} {rp[2][:80]!r} loc={rp[1].get('location')!r} | node={rn[0]} {rn[2][:80]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 5}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate8a_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes), "tie": tie}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate8a] dropped {DB}; leftover gate8a DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate8a_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
