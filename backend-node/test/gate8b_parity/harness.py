"""Phase 3 · Gate 8b · live Python↔Node parity harness for the vehicle status-audit list.

Covers:
  * GET /api/vehicles/{vid}/status-audit   (backend/routers/vehicles.py::list_vehicle_status_audit, L181-200)

Python: get_current_user → _active_company_id →
  READ #1 vehicles.find_one({id, user_id, company_id}, {_id:0, user_id:0}) → 404 "Vehicle not found"
  READ #2 vehicle_status_audit_log.find({user_id, company_id, vehicle_id}, {_id:0, user_id:0})
          .sort(changed_at, -1).to_list(500)
  → {"vehicle": {id, vehicle_number, is_active}, "items": docs, "total": len(docs)}

Seeds conflicting audit rows (other user / other company / missing scope
fields / other vehicle / orphans) that Python's scoped READ #2 must exclude,
wrapper edge values (is_active false / 0 / null / "false" / missing,
vehicle_number missing / numeric, array id), limit boundaries and ties.

BYTE-EXACT body; EXACT status, content-type, content-length, allow. READ #1
and READ #2 commands compared pairwise per request. DB activity attributed
PER SERVER. Python's ApprovalGateMiddleware re-dispatch on 500 (framework,
Gate 8a finding) is accounted against its log, never emulated by Node.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, invalid UTF-8 path escape, vid > 100 chars, raw non-ASCII query
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
DB = f"trukvia_gate8b_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate8b-py", "trukvia-gate8b-node"
PY_PORT, NODE_PORT = 8276, 8277
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "vehicles", "vehicle_status_audit_log", "audit_logs", "save_health",
           "idempotency_keys", "trips"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions", "companies")]
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
LONG_VID = "v" * 120
R1, R2 = "vehicles", "vehicle_status_audit_log"


def P(vid: str, qs: str = "") -> bytes:
    return (f"/api/vehicles/{vid}/status-audit" + (f"?{qs}" if qs else "")).encode()


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


def veh(vid, uid="u1", cid="co-a", **extra) -> dict:
    d = {"id": vid, "user_id": uid, "company_id": cid, "vehicle_number": f"MH12-{vid}", "type": "tanker"}
    d.update(extra)
    return d


def aud(vid: str, n: int, changed_at, uid="u1", cid="co-a", **extra) -> dict:
    d = {"id": f"vsa-{vid}-{uid}-{cid}-{n:04d}", "user_id": uid, "company_id": cid, "vehicle_id": vid,
         "vehicle_number": f"MH12-{vid}", "action": "deactivated" if n % 2 == 0 else "reactivated",
         "reason": f"reason {n}", "effective_date": "2026-05-01", "prev_is_active": n % 2 == 1,
         "new_is_active": n % 2 == 0, "changed_by": uid, "changed_by_email": f"{uid}@x", "changed_at": changed_at}
    d.update(extra)
    return d


def seed_vehicles() -> list[dict]:
    rows = [veh(v) for v in ("v1", "v-empty", "v-big", "v-50", "v-49", "v-51", "v-tie", "v-ser", "v-nan", "v-inf",
                             "v-oid", "v-dec", "v-bin", "v-mixed", "vé", "a b", "x.y", LONG_VID)]
    rows += [
        veh("v-inactive", is_active=False), veh("v-active", is_active=True), veh("v-zero", is_active=0),
        veh("v-null", is_active=None), veh("v-str", is_active="false"), veh("v-dbl0", is_active=0.0),
        {"id": "v-nonum", "user_id": "u1", "company_id": "co-a"},
        veh("v-numnum", vehicle_number=Int64(1234567890123)), veh("v-numflt", vehicle_number=5.0),
        veh("v-numnull", vehicle_number=None), veh("v-numobj", vehicle_number={"a": [1, 2.5]}),
        veh("v-vehnan", notes_score=float("nan")),                 # NaN in a field the wrapper never outputs
        veh("v-vnumnan", vehicle_number=float("nan")),             # NaN in vehicle_number → 500
        {"id": ["v-arr", "v-arr2"], "user_id": "u1", "company_id": "co-a", "vehicle_number": "ARR"},
        veh("v-b", cid="co-b"), veh("v2", uid="u2", cid="co-z"),
        veh("v1", uid="u2", cid="co-z", vehicle_number="U2-SAME-ID"),       # same id, other user
        veh("v1", uid="u1", cid="co-b", vehicle_number="U1-CO-B-SAME-ID"),  # same id, other company
        veh("v3", uid="u3", cid="co-u3a"), veh("v3b", uid="u3", cid="co-u3b"),
    ]
    return rows


def seed_audit() -> list[dict]:
    rows = [aud("v1", n, iso(10 - n)) for n in range(5)]                      # inserted newest-first
    rows += [aud("v1", 90, iso(50), uid="u2", cid="co-a"),                   # conflict: other user, same company id
             aud("v1", 91, iso(51), uid="u2", cid="co-z"),                   # conflict: other user + company
             aud("v1", 92, iso(52), uid="u1", cid="co-b"),                   # conflict: other company
             {"vehicle_id": "v1", "company_id": "co-a", "changed_at": iso(53)},   # missing user_id
             {"vehicle_id": "v1", "user_id": "u1", "changed_at": iso(54)},        # missing company_id
             {"vehicle_id": "v1", "changed_at": iso(55)},                          # orphan
             aud("v-other", 0, iso(56))]                                      # other vehicle
    rows += [aud("v-big", n, iso(n % 7)) for n in range(600)]                 # 600 rows, 7 tie groups → cut 500
    rows += [aud("v-50", n, iso(n // 5)) for n in range(50)]
    rows += [aud("v-49", n, iso(n)) for n in range(49)]
    rows += [aud("v-51", n, iso(n)) for n in range(51)]
    rows += [aud("v-tie", n, iso(0)) for n in range(60)]
    rows += [aud("v-ser", 0, iso(1), score=5.0, z=-0.0, big=Int64(2 ** 53 + 1), huge=10 ** 18, tiny=1.5e-7,
                 nil=None, nested={"a": [1, 2.5, "x", {"k": []}], "e": {}}, when=datetime(2026, 5, 1, 10, 0, 0, 123000),
                 reason="Ünïcødé 🚚 \"q\" \\ \n\t\x01  ", code=Code("function(){}"), blob=Binary(b"ok")),
             {"id": "vsa-min", "user_id": "u1", "company_id": "co-a", "vehicle_id": "v-ser"}]
    rows += [aud("v-nan", 0, iso(1), score=float("nan"))]
    rows += [aud("v-inf", 0, iso(1), score=float("-inf"))]
    rows += [aud("v-oid", 0, iso(1), ref=ObjectId("65a000000000000000000001"))]
    rows += [aud("v-dec", 0, iso(1), amt=Decimal128("12.50"))]
    rows += [aud("v-bin", 0, iso(1), blob=Binary(b"\xff\xfe"))]               # invalid UTF-8 bytes → 500
    rows += [aud("v-mixed", 0, iso(5)), aud("v-mixed", 1, datetime(2026, 5, 1, 0, 0, 1)), aud("v-mixed", 2, None),
             aud("v-mixed", 3, 12345), {"id": "vsa-mixed-missing", "user_id": "u1", "company_id": "co-a",
                                        "vehicle_id": "v-mixed"}, aud("v-mixed", 4, "")]
    rows += [aud("v-inactive", 0, iso(1)), aud("v-b", 0, iso(1), cid="co-b"), aud("v2", 0, iso(1), uid="u2", cid="co-z"),
             aud("v1", 0, iso(1), uid="u2", cid="co-z"), aud("v3", 0, iso(1), uid="u3", cid="co-u3a"),
             aud("v3b", 0, iso(1), uid="u3", cid="co-u3b"), aud("vé", 0, iso(1)), aud("a b", 0, iso(1)),
             aud("x.y", 0, iso(1)), aud("v-arr", 0, iso(1))]
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
    ("GET", P("v1"), [], "no auth"),
    ("GET", P(""), [], "no auth + empty vid"),
    ("GET", P("a%2Fb"), [], "no auth + encoded slash"),
    ("GET", P("v1"), [("Authorization", "Bearer nope")], "invalid bearer"),
    ("GET", P("v1"), [("Authorization", "Bearer tok-exp")], "expired session"),
    ("GET", P("v1"), [("Cookie", "session_token=tok-u1")], "session cookie"),
    ("GET", P("v1"), U1, "v1 owned (conflicting rows excluded)"),
    ("GET", P("v-empty"), U1, "zero audit rows"),
    ("GET", P("nope"), U1, "missing vehicle → 404"),
    ("GET", P("v-other"), U1, "audit rows but no vehicle → 404"),
    ("GET", P("v2"), U1, "another user's vehicle → 404"),
    ("GET", P("v-b"), U1, "another company's vehicle → 404"),
    ("GET", P("v-b"), co("u1", "co-b"), "owned alternate company co-b"),
    ("GET", P("v1"), co("u1", "co-b"), "v1 under co-b (same id, other company)"),
    ("GET", P("v1"), co("u1", "co-z"), "unowned header → default"),
    ("GET", P("v1"), co("u1", "co-nope"), "unknown header → default"),
    ("GET", P("v1"), co("u1", ""), "empty header"),
    ("GET", P("v1"), auth("u2"), "u2 same vehicle id in own company"),
    ("GET", P("v1"), co("u2", "co-a"), "u2 supplying u1's co-a"),
    ("GET", P("v2"), auth("u2"), "u2 own vehicle"),
    ("GET", P("v3"), auth("u3"), "u3 no default company (py repair)"),
    ("GET", P("v3b"), auth("u3"), "u3 second company without header → 404"),
    ("GET", P("v3b"), co("u3", "co-u3b"), "u3 header co-u3b"),
    ("GET", P("v-inactive"), U1, "is_active false → false"),
    ("GET", P("v-active"), U1, "is_active true"),
    ("GET", P("v-zero"), U1, "is_active 0 → true (is not False)"),
    ("GET", P("v-dbl0"), U1, "is_active 0.0 → true"),
    ("GET", P("v-null"), U1, "is_active null → true"),
    ("GET", P("v-str"), U1, "is_active 'false' → true"),
    ("GET", P("v-nonum"), U1, "vehicle_number missing → null"),
    ("GET", P("v-numnull"), U1, "vehicle_number null"),
    ("GET", P("v-numnum"), U1, "vehicle_number int64"),
    ("GET", P("v-numflt"), U1, "vehicle_number 5.0"),
    ("GET", P("v-numobj"), U1, "vehicle_number object"),
    ("GET", P("v-vehnan"), U1, "NaN in unreturned vehicle field → 200"),
    ("GET", P("v-vnumnan"), U1, "NaN vehicle_number → 500"),
    ("GET", P("v-arr"), U1, "array-valued vehicle id"),
    ("GET", P("v-big"), U1, "600 rows, 7 tie groups → 500 cut"),
    ("GET", P("v-50"), U1, "exactly 50 (5-way ties)"),
    ("GET", P("v-49"), U1, "49 rows"),
    ("GET", P("v-51"), U1, "51 rows"),
    ("GET", P("v-tie"), U1, "60 identical changed_at"),
    ("GET", P("v-mixed"), U1, "mixed changed_at BSON types"),
    ("GET", P("v-ser"), U1, "serialization edges"),
    ("GET", P("v-nan"), U1, "NaN → 500"),
    ("GET", P("v-inf"), U1, "-Infinity → 500"),
    ("GET", P("v-oid"), U1, "ObjectId → 500"),
    ("GET", P("v-dec"), U1, "Decimal128 → 500"),
    ("GET", P("v-bin"), U1, "invalid UTF-8 Binary → 500"),
    ("GET", P("v%C3%A9"), U1, "encoded Unicode vid"),
    ("GET", P("a%20b"), U1, "encoded space vid"),
    ("GET", P("x.y"), U1, "dotted vid"),
    ("GET", P(""), U1, "empty vid → 404 Not Found"),
    ("GET", P("a%2Fb"), U1, "encoded slash → 404 Not Found"),
    ("GET", P("v1", "x=1&x=2&limit=5"), U1, "query ignored (repeated / junk)"),
    ("GET", P("v1", "%zz=%C3"), U1, "malformed query encoding ignored"),
    ("HEAD", P("v1"), U1, "HEAD auth"),
    ("HEAD", P("v1"), [], "HEAD no auth"),
] + [("GET", P("v1"), U1, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", b"/api/vehicles/v1/status-audit/", U1, "trailing slash"),
        ("GET", b"/api/vehicles//status-audit", [], "double slash (no auth)"),
        ("GET", P("%FF"), U1, "invalid UTF-8 path escape"),
        ("GET", P(LONG_VID), U1, "vid > 100 chars (maxParamLength)"),
        ("GET", P("v1") + b"?q=\xc3\xa9", U1, "raw non-ASCII query bytes"),
        ("GET", P("v-b"), U1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")], "duplicate X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:260].decode("utf-8", "replace")


async def run() -> int:
    print(f"[gate8b] DB={DB} (isolated — UAT data untouched)")
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
        await d.vehicles.insert_many(seed_vehicles())
        await d.vehicle_status_audit_log.insert_many(seed_audit())

        tie = []
        for vid in ("v-big", "v-tie", "v-50"):
            q = {"user_id": "u1", "company_id": "co-a", "vehicle_id": vid}
            lim = [x.get("id") for x in await d.vehicle_status_audit_log.find(q, {"_id": 0}).sort("changed_at", -1).limit(500).to_list(500)]
            unl = [x.get("id") for x in await d.vehicle_status_audit_log.find(q, {"_id": 0}).sort("changed_at", -1).to_list(500)]
            tie.append((vid, len(unl), lim == unl, set(lim) == set(unl)))

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate8b_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate8b_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate8b] servers did not start"); return 2
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
            seq_py = [(c, shape(o)) for o in py_ops for c in (R1, R2) if (o.get("command") or {}).get("find") == c]
            seq_nd = [(c, shape(o)) for o in nd_ops for c in (R1, R2) if (o.get("command") or {}).get("find") == c]
            # Only accepted deviation: Python ApprovalGateMiddleware re-dispatch on a 500
            # (framework finding, Gate 8a) → Python's read sequence is exactly Node's, twice.
            redispatch = rp[0] == 500 and bool(seq_nd) and seq_py == seq_nd * 2
            reads_ok = seq_py == seq_nd or redispatch
            if redispatch:
                redispatched.append(desc)
            r1_pairs.extend(zip([s for c, s in seq_py if c == R1], [s for c, s in seq_nd if c == R1]))
            r2_pairs.extend(zip([s for c, s in seq_py if c == R2], [s for c, s in seq_nd if c == R2]))
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and not nch and reads_ok
            passed += ok; failed += (not ok)
            summary = "-"
            if rp[0] == 200:
                j = json.loads(rp[2]); summary = f"total={j['total']} active={j['vehicle']['is_active']}"
            nr = lambda seq: (sum(1 for c, _ in seq if c == R1), sum(1 for c, _ in seq if c == R2))
            rows.append((ok, desc + (" [py re-dispatch]" if redispatch else ""), method, rp, rn, len(py_ops), len(nd_ops),
                         nch, summary, nr(seq_py), nr(seq_nd)))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})
        r1_same = len(r1_pairs) > 0 and all(a == b for a, b in r1_pairs)
        r2_same = len(r2_pairs) > 0 and all(a == b for a, b in r2_pairs)
        faults = (LOGDIR / "gate8b_py.log").read_text(encoding="utf-8", errors="replace").count(
            "ApprovalGateMiddleware fault (passthrough)")

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 8b · LIVE PARITY (GET /api/vehicles/{vid}/status-audit) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, summary, rpy, rnd in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:46} py={rp[0]} node={rn[0]} {summary:22} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} "
                  f"ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} "
                  f"route-reads(veh,audit) py={rpy} node={rnd} db py={dpy} node={dnd} node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} allow={rp[1].get('allow')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} allow={rn[1].get('allow')!r} {pretty(rn[2])!r}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += r1_same; failed += (not r1_same)
        print(f"  [{'PASS' if r1_same else 'FAIL'}] READ #1 vehicles commands identical pairwise ({len(r1_pairs)} pairs)"
              f"\n        e.g. {r1_pairs[0][1] if r1_pairs else None}")
        passed += r2_same; failed += (not r2_same)
        print(f"  [{'PASS' if r2_same else 'FAIL'}] READ #2 vehicle_status_audit_log commands identical pairwise ({len(r2_pairs)} pairs)"
              f"\n        e.g. {r2_pairs[0][1] if r2_pairs else None}")
        rd_ok = len(redispatched) == faults
        passed += rd_ok; failed += (not rd_ok)
        print(f"  [{'PASS' if rd_ok else 'FAIL'}] python ApprovalGateMiddleware re-dispatches (framework, NOT route) — "
              f"log faults={faults}, 500 cases with doubled read sequence={len(redispatched)}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run: {APP_COLLS}")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print(f"  tie evidence (direct Motor: vid, n, limit(500)==unlimited order, same set): {tie}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:34} py={rp[0]} {rp[2][:80]!r} loc={rp[1].get('location')!r} | node={rn[0]} {rn[2][:80]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 5}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate8b_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes), "tie": tie}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate8b] dropped {DB}; leftover gate8b DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate8b_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
