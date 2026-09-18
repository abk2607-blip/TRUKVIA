"""Phase 3 · Gate 8d · live Python↔Node parity harness for the driver shortage-policy list.

Covers:
  * GET /api/driver-shortage-policies?q=&active_only=&limit=&offset=
    (backend/routers/driver_shortage_policies.py::list_policies, L186-216)

Python: get_current_user → FastAPI validation (q str, active_only bool,
limit int, offset int) → _active_company_id → count_documents(filter) →
find(filter, {_id:0}).sort(effective_from -1, version -1).skip(o).limit(l)
→ {"items", "total", "limit", "offset"}.

BYTE-EXACT body; EXACT status, content-type, content-length, allow. The
count (aggregate) and find commands are compared per request, in order,
key-order-sensitively (filter / pipeline / sort / projection / skip / limit).
DB activity attributed PER SERVER. Python ApprovalGateMiddleware 500
re-dispatch (framework, Gate 8a) is accounted against its log.

Recorded separately (framework / tenant cleanup, NOT counted): trailing
slash, sibling dynamic route /{pid}, raw non-ASCII query bytes, duplicate
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
DB = f"trukvia_gate8d_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate8d-py", "trukvia-gate8d-node"
PY_PORT, NODE_PORT = 8280, 8281
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "driver_shortage_policies", "trips", "audit_logs", "save_health",
           "idempotency_keys"]
APP_COLLS = [c for c in TRACKED if c not in ("user_sessions", "companies")]
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
COLL = "driver_shortage_policies"
PATH = "/api/driver-shortage-policies"


def P(qs: str | None = None) -> bytes:
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


def pol(pid: str, name: str, eff: str = "2026-01-01", version=1, uid="u1", cid="co-a", active=True, **extra) -> dict:
    d = {"id": pid, "user_id": uid, "company_id": cid, "name": name, "shortage_limit_kg": 100.0, "unit": "KG",
         "effective_from": eff, "active": active, "version": version}
    d.update(extra)
    return d


NAMES = ["Bitumen Standard", "bitumen PREMIUM", "CRMB (special)", "a.b*c+d?", "[x]{y}", "back\\slash", "^start$",
         "Ünïcødé Pølicy", "tab\there", "50% off", "a|b", "#hash", "~tilde", "&amp", "a-b", "plain space test",
         "dot.dot", "ÄÖÜ upper", "straße", "ǅ title", "emoji 🚚 x"]


def seed() -> list[dict]:
    rows = [pol(f"n{i:02d}", n, eff=f"2026-02-{(i % 9) + 1:02d}", version=i % 3) for i, n in enumerate(NAMES)]
    rows += [pol("rm1", "remarks hit", remarks="has Bitumen in remarks"),
             pol("pc1", "category hit", product_category="EMULSION grade"),
             pol("inact", "Bitumen inactive", active=False), pol("act-int", "Bitumen active-int", active=1),
             pol("act-str", "Bitumen active-str", active="true"),
             pol("nonstr", 12345, remarks=None, product_category=["Bitumen", "x"]),   # non-string name, array category
             {"id": "min", "user_id": "u1", "company_id": "co-a"}]                     # sparse doc (sorts last)
    rows += [pol(f"t{i:02d}", f"tie {i}", eff="2026-03-01", version=7) for i in range(60)]   # 60-way tie
    rows += [pol("ser", "serialization", eff="2026-04-01", z=-0.0, big=Int64(2 ** 53 + 1), tiny=1.5e-7, huge=10 ** 18,
                 when=datetime(2026, 5, 1, 10, 0, 0, 123000), nested={"a": [1, 2.5, {}], "e": []},
                 remarks="Ünïcødé 🚚 \"q\" \\ \n\t\x01  ", nil=None)]
    # other scopes
    rows += [pol("u2-in-co-a", "Bitumen u2 leak", uid="u2", cid="co-a"), pol("u2-own", "u2 own", uid="u2", cid="co-z"),
             pol("u1-co-b", "Bitumen co-b", cid="co-b"),
             pol("nan", "nan policy", cid="co-nan", shortage_limit_kg=float("nan")),
             pol("oid", "oid policy", cid="co-oid", ref=ObjectId("65a000000000000000000001")),
             pol("dec", "dec policy", cid="co-dec", amt=Decimal128("12.50")),
             pol("u3-first", "u3 first", uid="u3", cid="co-u3a"), pol("u3-second", "u3 second", uid="u3", cid="co-u3b")]
    return rows


COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    *[{"id": c, "user_id": "u1", "is_default": False, "name": c} for c in ("co-b", "co-nan", "co-oid", "co-dec", "co-empty")],
    {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
    {"id": "co-u3a", "user_id": "u3", "is_default": False, "name": "U3A"},
    {"id": "co-u3b", "user_id": "u3", "is_default": False, "name": "U3B"},
]

U1 = auth("u1")
INTS = ["", "0", "1", "01", "-1", "1.0", "1_0", "%201%20", "+1", "1.5", "1e3", "%EF%BC%91", "%D9%A3", "abc", "%C2%A01",
        "99999999999999999999999", "-99999999999999999999999", "1__0", "0x10", "1.000"]
BOOLS = ["", "true", "false", "True", "FALSE", "1", "0", "yes", "no", "on", "off", "t", "f", "y", "n", "tRuE",
         "%20true", "2", "1.0", "none"]
SEARCH = ["bitumen", "BITUMEN", "Bitumen+Standard", "%20bitumen%20", "+", "%09%0A", "a.b*c%2Bd%3F", "%5Bx%5D%7By%7D",
          "back%5Cslash", "%5Estart%24", ".", "*", "%2B", "%3F", "(", ")", "%5B", "%5D", "%7B", "%7D", "%5C", "%5E", "%24",
          "%7C", "-", "%26", "~", "%23", "50%25", "%C3%BCn%C3%AFc%C3%B8d%C3%A9", "%C3%84%C3%96%C3%9C", "stra%C3%9Fe",
          "STRASSE", "%C7%85", "%F0%9F%9A%9A", "tab%09here", "remarks", "EMULSION", "12345", "zzz-nomatch", "a" * 3000,
          "%E2%80%83bitumen", "%C3"]

CASES: list[tuple[str, bytes, list, str]] = [
    ("GET", P(), [], "no auth"),
    ("GET", P("limit=abc"), [], "no auth + invalid limit"),
    ("GET", P(), [("Authorization", "Bearer nope")], "invalid bearer"),
    ("GET", P(), [("Authorization", "Bearer tok-exp")], "expired session"),
    ("GET", P(), [("Cookie", "session_token=tok-u1")], "session cookie"),
    ("GET", P(), U1, "defaults"),
    ("GET", P(""), U1, "empty query"),
    ("GET", P("active_only=x&limit=y&offset=z"), U1, "3 validation errors (order)"),
    ("GET", P("offset=z&limit=y&active_only=x"), U1, "3 errors, reversed query order"),
    ("GET", P("limit=" + "1" * 4301), U1, "limit int_parsing_size"),
    ("GET", P("limit=1&limit=abc"), U1, "repeated limit → last invalid"),
    ("GET", P("limit=abc&limit=2"), U1, "repeated limit → last valid"),
    ("GET", P("active_only=true&active_only=false"), U1, "repeated bool → last"),
    ("GET", P("q=x&q=bitumen"), U1, "repeated q → last"),
    ("GET", P("lim%69t=3"), U1, "percent-encoded key"),
    ("GET", P("limit[]=3"), U1, "limit[] ignored"),
] + [("GET", P(f"limit={v}"), U1, f"limit={v[:24]}") for v in INTS] \
  + [("GET", P(f"offset={v}"), U1, f"offset={v[:24]}") for v in INTS] \
  + [("GET", P(f"active_only={v}"), U1, f"active_only={v}") for v in BOOLS] \
  + [("GET", P(f"q={v}"), U1, f"q={v[:24]}") for v in SEARCH] + [
    ("GET", P("limit=2"), U1, "limit 2"),
    ("GET", P("limit=10"), U1, "limit 10"),
    ("GET", P("limit=500"), U1, "limit 500 (max)"),
    ("GET", P("limit=501"), U1, "limit 501 → 500"),
    ("GET", P("limit=-5"), U1, "limit -5 → 1"),
    ("GET", P("offset=1"), U1, "offset 1"),
    ("GET", P("offset=25&limit=10"), U1, "offset 25 limit 10 (through tie group)"),
    ("GET", P("offset=40&limit=7"), U1, "offset 40 limit 7 (tie boundary)"),
    ("GET", P("offset=21&limit=60"), U1, "window over the whole 60-tie"),
    ("GET", P("offset=80"), U1, "offset past end → []"),
    ("GET", P("offset=2147483648"), U1, "offset 2^31"),
    ("GET", P("offset=9007199254740993"), U1, "offset 2^53+1"),
    ("GET", P("offset=9223372036854775807"), U1, "offset 2^63-1"),
    ("GET", P("offset=9223372036854775808"), U1, "offset 2^63 → py OverflowError 500"),
    ("GET", P("active_only=1&q=bitumen&limit=3&offset=1"), U1, "all params combined"),
    ("GET", P("q=bitumen"), co("u1", "co-b"), "owned alternate company co-b"),
    ("GET", P("q=bitumen"), co("u1", "co-z"), "unowned header → default"),
    ("GET", P("q=bitumen"), co("u1", "co-nope"), "unknown header → default"),
    ("GET", P("q=bitumen"), co("u1", ""), "empty header"),
    ("GET", P(), co("u1", "co-empty"), "owned company without policies → []"),
    ("GET", P(), auth("u2"), "u2 own"),
    ("GET", P("q=bitumen"), co("u2", "co-a"), "u2 supplying u1's co-a → default"),
    ("GET", P(), auth("u3"), "u3 no default company (py repair)"),
    ("GET", P(), co("u3", "co-u3b"), "u3 header co-u3b"),
    ("GET", P(), co("u1", "co-nan"), "NaN → 500"),
    ("GET", P(), co("u1", "co-oid"), "ObjectId → 500"),
    ("GET", P(), co("u1", "co-dec"), "Decimal128 → 500"),
    ("GET", P("q=serialization"), U1, "serialization edges"),
    ("GET", b"/api/driver-shortage-policies/resolve?trip_date=2026-05-10", U1, "precedence: static /resolve (8c route)"),
    ("HEAD", P(), U1, "HEAD auth"),
    ("HEAD", P(), [], "HEAD no auth"),
] + [("GET", P("q=bitumen&limit=5"), U1, f"repeat #{i}") for i in range(1, 6)]

INFO = [("GET", (PATH + "/").encode(), U1, "trailing slash"),
        ("GET", (PATH + "/p-123").encode(), U1, "sibling dynamic GET /{pid} (unmigrated)"),
        ("GET", (PATH + "/resolve/").encode(), U1, "resolve trailing slash"),
        ("GET", P("q=a") + b"&x=\xc3\xa9", U1, "raw non-ASCII query bytes"),
        ("GET", P("q=bitumen"), U1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")], "duplicate X-Company-Id (tenant)")]


def pretty(b: bytes) -> str:
    return b[:260].decode("utf-8", "replace")


def route_cmds(ops: list, batch: bool = True) -> list:
    # `batch=False` only for the precedence probe into the locked Gate-8c route: Node's
    # findOne adds batchSize:1 (disclosed since Gate 7y); everything else is still compared.
    fkeys = ("filter", "sort", "projection", "skip", "limit", "singleBatch") + (("batchSize",) if batch else ())
    out = []
    for o in ops:
        c = o.get("command") or {}
        if c.get("aggregate") == COLL:
            out.append(("count", json.dumps([(k, c.get(k)) for k in ("pipeline",)], default=str)))
        elif c.get("find") == COLL:
            out.append(("find", json.dumps([(k, c.get(k)) for k in fkeys], default=repr)))
    return out


async def run() -> int:
    print(f"[gate8d] DB={DB} (isolated — UAT data untouched)")
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
                              stdout=open(LOGDIR / "gate8d_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate8d_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate8d] servers did not start"); return 2
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
            batch = not desc.startswith("precedence:")
            seq_py, seq_nd = route_cmds(py_ops, batch), route_cmds(nd_ops, batch)
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
            summary = "-"
            if rp[0] == 200 and rp[2][:9] == b'{"items":':
                j = json.loads(rp[2]); summary = f"n={len(j['items'])} tot={j['total']} l={j['limit']} o={str(j['offset'])[:6]}"
            elif rp[0] == 422:
                summary = ",".join(e["loc"][1] + ":" + e["type"] for e in json.loads(rp[2])["detail"])[:40]
            rows.append((ok, desc + (" [py re-dispatch]" if redispatch else ""), method, rp, rn, len(py_ops), len(nd_ops),
                         nch, summary, [c for c, _ in seq_py], [c for c, _ in seq_nd]))

        prof_py = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        py_colls_w = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof_py if is_write(p)})
        n_count = sum(1 for a, _ in pairs if a[0] == "count")
        n_find = sum(1 for a, _ in pairs if a[0] == "find")
        cmd_same = len(pairs) > 0 and all(a == b for a, b in pairs) and not cmd_diffs
        faults = (LOGDIR / "gate8d_py.log").read_text(encoding="utf-8", errors="replace").count(
            "ApprovalGateMiddleware fault (passthrough)")

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 8d · LIVE PARITY (GET /api/driver-shortage-policies) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, summary, cpy, cnd in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:44} py={rp[0]} node={rn[0]} {summary:40} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} allow={rp[1].get('allow')}/{rn[1].get('allow')} "
                  f"cmds py={cpy} node={cnd} node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} {pretty(rn[2])!r}")
        for desc, a, b in cmd_diffs[:6]:
            print(f"  CMD DIFF {desc}:\n        py  : {a}\n        node: {b}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls} node-attributed changes={node_changes or 'none'}")
        passed += cmd_same; failed += (not cmd_same)
        print(f"  [{'PASS' if cmd_same else 'FAIL'}] count + find commands identical per request, key-order-sensitive "
              f"(count pairs={n_count}, find pairs={n_find})")
        ex_c = next((a for a, _ in pairs if a[0] == "count"), None)
        ex_f = next((a for a, _ in pairs if a[0] == "find" and '"$or"' in a[1]), None)
        print(f"        count e.g. {ex_c[1] if ex_c else None}\n        find  e.g. {ex_f[1] if ex_f else None}")
        rd_ok = len(redispatched) == faults
        passed += rd_ok; failed += (not rd_ok)
        print(f"  [{'PASS' if rd_ok else 'FAIL'}] python ApprovalGateMiddleware re-dispatches (framework, NOT route) — "
              f"log faults={faults}, 500 cases with doubled command sequence={len(redispatched)}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged over the whole run: {APP_COLLS}")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print("  informational (framework / tenant cleanup — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:40} py={rp[0]} {rp[2][:80]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r}"
                  f" | node={rn[0]} {rn[2][:80]!r}")
        print("-" * 100 + f"\n  cases: {len(rows) + 4}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate8d_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes)}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate8d] dropped {DB}; leftover gate8d DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate8d_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
