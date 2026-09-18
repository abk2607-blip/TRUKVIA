"""Phase 3 · Gate 7w · live Python↔Node parity harness for the saved trip filters list.

Covers:
  * GET /api/saved-trip-filters   (backend/routers/saved_filters.py::list_saved_filters, L25-32)

Python: get_current_user → _active_company_id → saved_trip_filters.find(
{user_id, company_id}, {_id:0}).sort("created_at", -1).limit(50).to_list(50).

Comparison is BYTE-EXACT on the body and EXACT on status, content-type,
content-length and allow. Every request's DB activity is attributed PER
SERVER (profiler appName + dbHash taken between the two requests): Python's
auth rolling refresh / company repair writes are recorded, never blamed on
Node. Node must never write.

Tie evidence: the seeded data is queried directly with and without a server
limit to show whether the limit changes tie order (why Node sends `.limit(50)`).
The find commands both servers send to saved_trip_filters are compared.

Recorded separately (framework gate, NOT counted): trailing slash, sub-path
(`/x`, `//`), raw non-ASCII target bytes.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7w_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7w-py", "trukvia-gate7w-node"
PY_PORT, NODE_PORT = 8266, 8267
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "saved_trip_filters", "audit_logs", "save_health",
           "idempotency_keys", "trips", "invoices"]
P = "/api/saved-trip-filters"
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


def sf(n: int, uid: str, cid: str, created_at, **extra) -> dict:
    d = {"id": f"sf-{cid}-{uid}-{n:04d}", "user_id": uid, "company_id": cid, "name": f"{cid} view {n}",
         "filter_state": {"status": "open", "n": n}, "created_at": created_at}
    d.update(extra)
    return d


def seed_rows() -> list[dict]:
    rows: list[dict] = []
    # co-a (u1 default): 130 rows — ten 13-way tie groups, interleaved insert order
    for n in range(130):
        rows.append(sf(n, "u1", "co-a", iso(n % 10)))
    # co-b (u1 owned alt): exactly 50 rows, 5 ties per timestamp
    rows += [sf(n, "u1", "co-b", iso(n // 5)) for n in range(50)]
    # co-c: 49 rows distinct timestamps
    rows += [sf(n, "u1", "co-c", iso(n)) for n in range(49)]
    # co-d: 51 rows distinct timestamps
    rows += [sf(n, "u1", "co-d", iso(n)) for n in range(51)]
    # co-e: 0 rows (company exists)
    # co-f: typed values / serialization
    rows += [
        sf(0, "u1", "co-f", iso(1), filter_state={"f": 5.0, "g": 1e16, "h": 1.5e-7, "z": -0.0, "i32": 7,
                                                   "i64": Int64(2 ** 53 + 1), "b": True, "nil": None,
                                                   "arr": [1, 2.5, "x", {"k": []}], "empty": {}}),
        sf(1, "u1", "co-f", datetime(2026, 5, 2, 10, 0, 0, 123000), name="Ünïcødé 🚚 \"q\" \\ \n\t\x01  "),
        sf(2, "u1", "co-f", datetime(2026, 5, 2, 10, 0, 0), extra_field="kept", filter_state={}),
        {"id": "sf-co-f-min", "user_id": "u1", "company_id": "co-f", "name": "no created_at"},
        sf(3, "u1", "co-f", None),
        sf(4, "u1", "co-f", 12345),
        sf(5, "u1", "co-f", ""),
    ]
    # co-g: NaN inside filter_state → Python 500
    rows += [sf(0, "u1", "co-g", iso(1)), sf(1, "u1", "co-g", iso(2), filter_state={"x": float("nan")})]
    # co-i: 60 rows all the SAME created_at (full tie across the boundary)
    rows += [sf(n, "u1", "co-i", iso(0)) for n in range(60)]
    # co-j: 55 rows; rows 40..54 share one timestamp (tie straddles row 50)
    rows += [sf(n, "u1", "co-j", iso(100 - min(n, 40))) for n in range(55)]
    # co-k: 51 rows; top 49 distinct, rows 49 and 50 tied (the cut splits a pair)
    rows += [sf(n, "u1", "co-k", iso(100 - min(n, 49))) for n in range(51)]
    # cross-user: u2 rows under u1's company ids (must never leak to u1) and its own
    rows += [sf(n, "u2", "co-a", iso(200 + n)) for n in range(5)]
    rows += [sf(n, "u2", "co-z", iso(n)) for n in range(3)]
    # company_id "" rows for u1 and u4 (tenant fallback edge)
    rows += [sf(n, "u1", "", iso(n)) for n in range(2)] + [sf(n, "u4", "", iso(n)) for n in range(2)]
    # u3 (companies but no default): rows in its first company
    rows += [sf(n, "u3", "co-u3a", iso(n)) for n in range(3)] + [sf(n, "u3", "co-u3b", iso(n)) for n in range(2)]
    return rows


COMPANIES = [
    {"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
    *[{"id": c, "user_id": "u1", "is_default": False, "name": c} for c in
      ["co-b", "co-c", "co-d", "co-e", "co-f", "co-g", "co-i", "co-j", "co-k"]],
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
    ("GET", P.encode(), A1, "u1 default co-a (130 rows, ties) → 50"),
    ("GET", P.encode(), co("tok-u1", "co-a"), "u1 header co-a"),
    ("GET", P.encode(), co("tok-u1", "co-b"), "u1 co-b exactly 50 (ties)"),
    ("GET", P.encode(), co("tok-u1", "co-c"), "u1 co-c 49"),
    ("GET", P.encode(), co("tok-u1", "co-d"), "u1 co-d 51 → 50"),
    ("GET", P.encode(), co("tok-u1", "co-e"), "u1 co-e empty"),
    ("GET", P.encode(), co("tok-u1", "co-f"), "u1 co-f typed values / mixed sort types"),
    ("GET", P.encode(), co("tok-u1", "co-g"), "u1 co-g NaN → 500"),
    ("GET", P.encode(), co("tok-u1", "co-i"), "u1 co-i 60 all tied → 50"),
    ("GET", P.encode(), co("tok-u1", "co-j"), "u1 co-j tie straddles cut"),
    ("GET", P.encode(), co("tok-u1", "co-k"), "u1 co-k cut splits a tied pair"),
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
        ("GET", P.encode(), A1 + [("X-Company-Id", "co-b"), ("X-Company-Id", "co-c")], "duplicate company header")]


def pretty(b: bytes) -> str:
    return b[:300].decode("utf-8", "replace")


async def run() -> int:
    print(f"[gate7w] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        now = datetime.now(timezone.utc)
        sess = lambda tok, uid, exp: {"session_token": tok, "user_id": uid, "effective_role": "owner",
                                       "expires_at": exp.isoformat(), "last_refreshed_at": now.isoformat()}
        await d.user_sessions.insert_many([sess(f"tok-{u}", u, now + timedelta(hours=2)) for u in ("u1", "u2", "u3", "u4")]
                                          + [sess("tok-exp", "u1", now - timedelta(minutes=1))])
        await d.users.insert_many([{"user_id": u, "email": f"{u}@x", "name": u.upper()} for u in ("u1", "u2", "u3", "u4")])
        await d.companies.insert_many([dict(c) for c in COMPANIES])
        await d.saved_trip_filters.insert_many(seed_rows())

        # ── Tie evidence (direct Motor): limited vs unlimited order ──
        tie_rows = []
        for cid in ("co-a", "co-b", "co-i", "co-j", "co-k"):
            q = {"user_id": "u1", "company_id": cid}
            lim = [x["id"] for x in await d.saved_trip_filters.find(q, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)]
            unl = [x["id"] for x in await d.saved_trip_filters.find(q, {"_id": 0}).sort("created_at", -1).to_list(50)]
            tie_rows.append((cid, len(lim), lim == unl, set(lim) == set(unl)))

        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate7w_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate7w_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate7w] servers did not start"); return 2
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await d.command({"profile": 2})
        h_start = (await d.command("dbHash", collections=TRACKED))["collections"]

        passed = failed = 0
        rows = []
        py_writes: list = []
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

        def stf_cmd(profs):
            for p in profs:
                c = p.get("command") or {}
                if c.get("find") == "saved_trip_filters":
                    return {k: c.get(k) for k in ("filter", "sort", "projection", "limit", "batchSize", "singleBatch")}
            return None
        cmd_py, cmd_nd = stf_cmd(prof_py), stf_cmd(prof)
        cmd_same = (cmd_py or {}).get("sort") == (cmd_nd or {}).get("sort") and \
            (cmd_py or {}).get("limit") == (cmd_nd or {}).get("limit") and \
            (cmd_py or {}).get("projection") == (cmd_nd or {}).get("projection") and \
            (cmd_py or {}).get("filter") == (cmd_nd or {}).get("filter")

        info = [(desc, raw(PY_PORT, m, t, h), raw(NODE_PORT, m, t, h)) for m, t, h, desc in INFO]
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 3 · GATE 7w · LIVE PARITY (GET /api/saved-trip-filters) — BYTE-EXACT\n" + "=" * 100)
        for ok, desc, method, rp, rn, dpy, dnd, nch, n_items in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:44} py={rp[0]} node={rn[0]} items={n_items!s:>3} "
                  f"len py={rp[1].get('content-length')} node={rn[1].get('content-length')} "
                  f"ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} db py={dpy} node={dnd} "
                  f"node-changed={nch or 'none'}")
            if not ok:
                print(f"        py  : {rp[1].get('content-type')!r} allow={rp[1].get('allow')!r} {pretty(rp[2])!r}\n"
                      f"        node: {rn[1].get('content-type')!r} allow={rn[1].get('allow')!r} {pretty(rn[2])!r}")
        zero_ok = not node_writes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} collections={node_colls}")
        cmd_ok = bool(cmd_py and cmd_nd and cmd_same)
        passed += cmd_ok; failed += (not cmd_ok)
        print(f"  [{'PASS' if cmd_ok else 'FAIL'}] same find command on saved_trip_filters:\n        py  : {cmd_py}\n        node: {cmd_nd}")
        print(f"  python-side writes (auth rolling refresh / company repair — Python-only, NOT the handler): "
              f"{py_writes or 'none'}; python write collections={py_colls_w}")
        print("  tie evidence (direct Motor, u1): cid, n, limited==unlimited order, same set")
        for t in tie_rows:
            print(f"    {t}")
        print("  informational (framework gate — NOT counted):")
        for desc, rp, rn in info:
            print(f"    {desc:30} py={rp[0]} {rp[2][:70]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r}"
                  f" | node={rn[0]} {rn[2][:70]!r}")
        print(f"  saved_trip_filters checksum unchanged: {h_start.get('saved_trip_filters') == h_end.get('saved_trip_filters')}")
        print("-" * 100 + f"\n  cases: {len(rows) + 2}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        (LOGDIR / "gate7w_parity_results.json").write_text(json.dumps(
            {"db": DB, "passed": passed, "failed": failed, "node_ops": len(prof), "node_reads": len(node_reads),
             "node_writes": len(node_writes), "tie": tie_rows}, indent=2), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate7w] dropped {DB}; leftover gate7w DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate7w_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
