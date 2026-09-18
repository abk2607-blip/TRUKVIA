"""Phase 3 · Gate 8c · live Python↔Node parity harness for the driver shortage-policy resolver.

Covers:
  * GET /api/driver-shortage-policies/resolve?trip_date=...&product_category=...
    (backend/routers/driver_shortage_policies.py::resolve_policy_endpoint L310-324
     + resolve_policy_for_trip L32-78)

Python: get_current_user → `if not trip_date` 400 → _active_company_id →
  READ #1 (only if product_category truthy): find_one(q_base + {product_category},
          sort effective_from -1, version -1) — a hit wins
  READ #2 (fallback): find_one(q_base + $and[$or[$exists false, null, ""]], same sort)
  → {"policy": doc-without-_id | null, "trip_date": raw}

BYTE-EXACT body; EXACT status, content-type, content-length, allow. Every
driver_shortage_policies command is compared per request, in order, and
ORDER-SENSITIVELY (filter key order included). DB activity attributed PER
SERVER. Python ApprovalGateMiddleware 500 re-dispatch (framework, Gate 8a)
is accounted against its log, never emulated.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, double slash, sub-path, invalid UTF-8 path, raw non-ASCII query
bytes, duplicate X-Company-Id headers.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64, ObjectId, Decimal128
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate8c_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate8c-py", "trukvia-gate8c-node"
PY_PORT, NODE_PORT = 8278, 8279
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "driver_shortage_policies", "trips", "audit_logs", "save_health",
           "idempotency_keys"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions", "companies")]
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
COLL = "driver_shortage_policies"
PATH = "/api/driver-shortage-policies/resolve"


def P(qs: str | None) -> bytes:
    return (PATH + ("" if qs is None else f"?{qs}")).encode()


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


_MISSING = object()


def pol(pid: str, eff_from, cat=_MISSING, eff_to=_MISSING, version=1, uid="u1", cid="co-a", active=True, **extra) -> dict:
    d = {"id": pid, "user_id": uid, "company_id": cid, "name": f"policy {pid}", "shortage_limit_kg": 100.0,
         "unit": "KG", "effective_from": eff_from, "active": active, "version": version,
         "created_at": "2026-01-01T00:00:00+00:00"}
    if eff_to is not _MISSING:
        d["effective_to"] = eff_to
    if cat is not _MISSING:
        d["product_category"] = cat
    d.update(extra)
    return d


def seed() -> list[dict]:
    return [
        # catch-all candidates (u1 / co-a)
        pol("ca-old", "2026-01-01"),                                            # category missing, effective_to missing
        pol("ca-null", "2026-04-01", cat=None, eff_to=None),                   # category null, effective_to null
        pol("ca-empty-v2", "2026-04-01", cat="", version=2),                   # ties effective_from → version 2 wins
        pol("ca-expired", "2026-04-10", eff_to="2026-04-30", version=9),       # only valid up to 04-30
        pol("ca-future", "2026-06-01"),
        pol("ca-inactive", "2026-05-05", active=False),
        pol("ca-active-int", "2026-05-06", active=1),                          # 1 is not True in Mongo equality
        pol("ca-active-str", "2026-05-07", active="true"),
        pol("ca-space-cat", "2026-05-08", cat=" "),                            # " " is not catch-all
        pol("ca-effto-empty", "2026-05-09", eff_to=""),                        # "" < trip_date, not null
        pol("ca-effto-date", "2026-05-09", eff_to=datetime(2030, 1, 1)),       # Date never $gte a string
        pol("ca-efffrom-date", datetime(2026, 1, 1), version=50),              # Date never $lte a string
        pol("ca-efffrom-int", 20260101, version=51),
        # specific categories
        pol("bit-old", "2026-03-01", cat="BITUMEN"),
        pol("bit-new-v1", "2026-05-01", cat="BITUMEN", version=1),
        pol("bit-new-v2", "2026-05-01", cat="BITUMEN", version=2),
        pol("bit-novers", "2026-05-01", cat="BITUMEN", version=None),          # null version sorts lowest
        pol("emu-expired", "2026-01-01", cat="EMULSION", eff_to="2026-02-01"),
        pol("crmb-array", "2026-02-01", cat=["CRMB", "PMB"]),
        pol("num-cat", "2026-02-01", cat=5),
        pol("tie-a", "2026-02-02", cat="TIE", version=3), pol("tie-b", "2026-02-02", cat="TIE", version=3),
        pol("tie-c", "2026-02-02", cat="TIE", version=3),
        pol("edge-from", "2026-05-10", cat="EDGE", eff_to="2026-05-10"),       # inclusive both ends
        pol("ser", "2026-02-03", cat="SER", shortage_limit_kg=100.0, z=-0.0, big=Int64(2 ** 53 + 1), tiny=1.5e-7,
            huge=10 ** 18, when=datetime(2026, 5, 1, 10, 0, 0, 123000), nested={"a": [1, 2.5, {}], "e": []},
            remarks="Ünïcødé 🚚 \"q\" \\ \n\t\x01  ", nil=None, _id=ObjectId("65a0000000000000000000aa")),
        pol("nan", "2026-02-03", cat="NAN", shortage_limit_kg=float("nan")),
        pol("oid", "2026-02-03", cat="OID", ref=ObjectId("65a000000000000000000001")),
        pol("dec", "2026-02-03", cat="DEC", amt=Decimal128("12.50")),
        pol("unicode", "2026-02-03", cat="बिटुमेन"),
        # isolation
        pol("u2-in-co-a", "2026-05-09", cat="BITUMEN", uid="u2", cid="co-a", version=99),
        pol("u2-ca-in-co-a", "2026-05-09", uid="u2", cid="co-a", version=99),
        pol("u2-own", "2026-01-01", uid="u2", cid="co-z"),
        pol("u1-co-b", "2026-02-01", cid="co-b"),
        pol("u1-co-b-bit", "2026-02-01", cat="BITUMEN", cid="co-b"),
        pol("u3-first", "2026-01-01", uid="u3", cid="co-u3a"),
        pol("u3-second", "2026-01-01", uid="u3", cid="co-u3b"),
    ]


COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    {"id": "co-b", "user_id": "u1", "is_default": False, "name": "B"},
    {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
    {"id": "co-u3a", "user_id": "u3", "is_default": False, "name": "U3A"},
    {"id": "co-u3b", "user_id": "u3", "is_default": False, "name": "U3B"},
    {"id": "co-empty", "user_id": "u1", "is_default": False, "name": "E"},
]

U1 = auth("u1")
D = "trip_date=2026-05-10"
CASES: list[tuple[str, bytes, list, str]] = [
    # auth / validation precedence
    ("GET", P(D), [], "no auth"),
    ("GET", P(None), [], "no auth + missing trip_date"),
    ("GET", P(D), [("Authorization", "Bearer nope")], "invalid bearer"),
    ("GET", P(D), [("Authorization", "Bearer tok-exp")], "expired session"),
    ("GET", P(D), [("Cookie", "session_token=tok-u1")], "session cookie"),
    ("GET", P(None), U1, "missing trip_date → 400"),
    ("GET", P(""), U1, "empty query → 400"),
    ("GET", P("trip_date="), U1, "empty trip_date → 400"),
    ("GET", P("trip_date"), U1, "bare trip_date → 400"),
    ("GET", P("product_category=BITUMEN"), U1, "category only → 400"),
    ("GET", P("trip_date=2026-05-10&trip_date="), U1, "repeated → last empty → 400"),
    ("GET", P("trip_date%5B%5D=2026-05-10"), U1, "trip_date[] → 400"),
    ("GET", P("trip_date=+"), U1, "trip_date ' ' (truthy) → proceeds"),
    # catch-all branch (READ #2 only)
    ("GET", P(D), U1, "catch-all 2026-05-10 (effective_to exclusions)"),
    ("GET", P("trip_date=2026-04-15"), U1, "catch-all 2026-04-15 (expired still valid)"),
    ("GET", P("trip_date=2026-04-01"), U1, "catch-all tie on effective_from → version"),
    ("GET", P("trip_date=2026-01-01"), U1, "catch-all boundary effective_from == date"),
    ("GET", P("trip_date=2025-12-31"), U1, "no policy → null"),
    ("GET", P("trip_date=zzzz"), U1, "non-date string sorts after all dates"),
    ("GET", P("trip_date=9"), U1, "trip_date '9'"),
    ("GET", P("trip_date=2026-05-10%20"), U1, "trailing space (no strip)"),
    ("GET", P("trip_date=%D9%A2%D9%A0%D9%A2%D9%A6"), U1, "Arabic-Indic digits"),
    ("GET", P("trip_date=%C3"), U1, "invalid UTF-8 escape → U+FFFD echoed"),
    ("GET", P("trip_date=x&trip_date=2026-05-10"), U1, "repeated → last wins"),
    ("GET", P("trip_d%61te=2026-05-10"), U1, "percent-encoded key"),
    ("GET", P(D + "&foo=1&bar=2&bar=3"), U1, "unrelated params ignored"),
    # specific branch (READ #1 [+ READ #2])
    ("GET", P(D + "&product_category=BITUMEN"), U1, "specific hit wins (version tie-break)"),
    ("GET", P("trip_date=2026-04-01&product_category=BITUMEN"), U1, "specific older policy"),
    ("GET", P(D + "&product_category=EMULSION"), U1, "specific expired → catch-all fallback"),
    ("GET", P(D + "&product_category=NOPE"), U1, "no specific → catch-all fallback"),
    ("GET", P("trip_date=2025-12-31&product_category=NOPE"), U1, "neither matches → null"),
    ("GET", P(D + "&product_category="), U1, "empty category → catch-all only"),
    ("GET", P(D + "&product_category=CRMB"), U1, "array category matches element"),
    ("GET", P(D + "&product_category=5"), U1, "numeric stored category ≠ '5'"),
    ("GET", P(D + "&product_category=bitumen"), U1, "case-sensitive category"),
    ("GET", P(D + "&product_category=%20BITUMEN"), U1, "leading space category"),
    ("GET", P(D + "&product_category=%20"), U1, "category ' ' → specific ' ' policy"),
    ("GET", P(D + "&product_category=TIE"), U1, "3-way full sort tie"),
    ("GET", P("trip_date=2026-05-10&product_category=EDGE"), U1, "inclusive effective_to boundary"),
    ("GET", P(D + "&product_category=%E0%A4%AC%E0%A4%BF%E0%A4%9F%E0%A5%81%E0%A4%AE%E0%A5%87%E0%A4%A8"), U1, "Unicode category"),
    ("GET", P(D + "&product_category=X&product_category=BITUMEN"), U1, "repeated category → last"),
    ("GET", P(D + "&product_category=SER"), U1, "serialization edges"),
    ("GET", P(D + "&product_category=NAN"), U1, "NaN → 500"),
    ("GET", P(D + "&product_category=OID"), U1, "ObjectId → 500"),
    ("GET", P(D + "&product_category=DEC"), U1, "Decimal128 → 500"),
    # company / user isolation
    ("GET", P(D + "&product_category=BITUMEN"), co("u1", "co-b"), "owned alternate co-b"),
    ("GET", P(D), co("u1", "co-z"), "unowned header → default"),
    ("GET", P(D), co("u1", "co-nope"), "unknown header → default"),
    ("GET", P(D), co("u1", ""), "empty header"),
    ("GET", P(D), co("u1", "co-empty"), "owned company with no policies → null"),
    ("GET", P(D), auth("u2"), "u2 own company"),
    ("GET", P(D + "&product_category=BITUMEN"), co("u2", "co-a"), "u2 supplying u1's co-a → default"),
    ("GET", P(D), auth("u3"), "u3 no default company (py repair)"),
    ("GET", P(D), co("u3", "co-u3b"), "u3 header co-u3b"),
    # HEAD
    ("HEAD", P(D), U1, "HEAD auth"),
    ("HEAD", P(None), [], "HEAD no auth"),
] + [("GET", P(D + "&product_category=BITUMEN"), U1, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", (PATH + "/?" + D).encode(), U1, "trailing slash"),
        ("GET", ("/api//driver-shortage-policies/resolve?" + D).encode(), U1, "double slash"),
        ("GET", ("/api/driver-shortage-policies/resolve%2Fx?" + D).encode(), U1, "encoded slash sub-path"),
        ("GET", ("/api/driver-shortage-policies/%FF?" + D).encode(), U1, "invalid UTF-8 path segment"),
        ("GET", P(D) + b"&q=\xc3\xa9", U1, "raw non-ASCII query bytes"),
        ("GET", P(D + "&product_category=BITUMEN"), U1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")],
         "duplicate X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:260].decode("utf-8", "replace")


async def run() -> int:
    print(f"[gate8c] DB={DB} (isolated — UAT data untouched)")
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
        await d[COLL].insert_many(seed())

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate8c_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate8c_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate8c] servers did not start"); return 2
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await d.command({"profile": 2})
        h_start = (await d.command("dbHash", collections=TRACKED))["collections"]

        keys = ("filter", "sort", "projection", "limit", "singleBatch")
        # ORDER-SENSITIVE command shape (filter key order included).
        shape = lambda o: json.dumps([(k, (o.get("command") or {}).get(k)) for k in keys], default=str)
        passed = failed = 0
        rows = []
        py_writes: list = []
        node_changes: list = []
        redispatched: list = []
        pairs: list = []
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
            seq_py = [shape(o) for o in py_ops if (o.get("command") or {}).get("find") == COLL]
            seq_nd = [shape(o) for o in nd_ops if (o.get("command") or {}).get("find") == COLL]
            comp_py = sum(1 for o in py_ops if (o.get("command") or {}).get("find") == "companies")
            comp_nd = sum(1 for o in nd_ops if (o.get("command") or {}).get("find") == "companies")
            redispatch = rp[0] == 500 and bool(seq_nd) and seq_py == seq_nd * 2
            reads_ok = seq_py == seq_nd or redispatch
            # a 400 must not reach company resolution or the policy reads on either side
            early_ok = rp[0] != 400 or (comp_py == comp_nd == 0 and not seq_py and not seq_nd)
            if redispatch:
                redispatched.append(desc)
            pairs.extend(zip(seq_py, seq_nd))
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and not nch and reads_ok and early_ok
            passed += ok; failed += (not ok)
            pol_id = "-"
            if rp[0] == 200:
                j = json.loads(rp[2]); pol_id = (j["policy"] or {}).get("id", "null")
            rows.append((ok, desc + (" [py re-dispatch]" if redispatch else ""), method, rp, rn, len(py_ops), len(nd_ops),
                         nch, str(pol_id), len(seq_py), len(seq_nd)))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})
        cmd_same = len(pairs) > 0 and all(a == b for a, b in pairs)
        faults = (LOGDIR / "gate8c_py.log").read_text(encoding="utf-8", errors="replace").count(
            "ApprovalGateMiddleware fault (passthrough)")

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 8c · LIVE PARITY (GET /api/driver-shortage-policies/resolve) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, pol_id, npy, nnd in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:48} py={rp[0]} node={rn[0]} policy={pol_id:14} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} allow={rp[1].get('allow')}/{rn[1].get('allow')} "
                  f"ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} "
                  f"policy-reads py={npy} node={nnd} db py={dpy} node={dnd} node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} allow={rp[1].get('allow')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} allow={rn[1].get('allow')!r} {pretty(rn[2])!r}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += cmd_same; failed += (not cmd_same)
        print(f"  [{'PASS' if cmd_same else 'FAIL'}] {COLL} commands identical per request, in order, key-order-sensitive "
              f"({len(pairs)} pairs)")
        if pairs:
            print(f"        READ #2 e.g. {pairs[0][1]}")
        rd_ok = len(redispatched) == faults
        passed += rd_ok; failed += (not rd_ok)
        print(f"  [{'PASS' if rd_ok else 'FAIL'}] python ApprovalGateMiddleware re-dispatches (framework, NOT route) — "
              f"log faults={faults}, 500 cases with doubled read sequence={len(redispatched)}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run: {APP_COLLS}")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:34} py={rp[0]} {rp[2][:80]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r}"
                  f" | node={rn[0]} {rn[2][:80]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 4}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate8c_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes)}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate8c] dropped {DB}; leftover gate8c DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate8c_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
