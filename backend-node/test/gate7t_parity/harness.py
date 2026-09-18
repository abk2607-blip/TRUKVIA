"""Phase 3 · Gate 7t · live route-precedence verification (Python vs Node).

Gate 7t registers static precedence guards so Node's Gate-6a parametric
`/api/trips/:tid` no longer captures:
    GET /api/trips/export
    GET /api/trips/recurring-suggestions
Python serves both with their own static handlers (declared before
/trips/{tid}). Node does NOT migrate them: after 7t it answers them with its
not-found handler — no auth, no DB — exactly like any path Node does not own.

For each request the harness records status, content-type, body, and the
Node DB operations issued while serving it (profiler, appName-attributed),
which identifies the Node handler that ran:
  * guard → 0 Node DB ops
  * :tid   → user_sessions + companies + trips reads
Write detection: MongoDB `dbHash` of every tracked collection around each
Node request + profiler write-command count.

/api/trips/:tid itself is Gate-6a and stays deferred (not cutover-eligible);
its non-legacy behaviour must be unchanged → byte parity with Python on a
normal trip and on a missing trip.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7t_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7t-py", "trukvia-gate7t-node"
PY_PORT, NODE_PORT = 8258, 8259
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "trips", "customers", "invoices", "files", "audit_logs",
           "fuel", "vehicles", "drivers", "products", "parties", "counters"]


def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = datetime.now(timezone.utc).isoformat()
    trip = {"date": "2026-05-01", "created_at": "2026-05-01T10:00:00+00:00", "lr_number": "LR-1",
            "customer_id": "c1", "vehicle_number": "AP01AB1234", "tons": 25.0, "rate_per_ton": 1200.0,
            "freight_mode": "per_ton", "supplier_diesel_entries": [], "supplier_advance_entries": []}
    return {
        "user_sessions": [{"session_token": "tok-u1", "user_id": "u1", "effective_role": "owner",
                           "expires_at": future(7200), "last_refreshed_at": now}],
        "users": [{"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now}],
        "companies": [{"id": "co-a", "user_id": "u1", "is_default": True, "name": "Acme"},
                      {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Alt"}],
        "customers": [{"id": "c1", "user_id": "u1", "company_id": "co-a", "name": "Cust"}],
        "trips": [
            {"id": "t1", "user_id": "u1", "company_id": "co-a", **trip},
            {"id": "t-alt", "user_id": "u1", "company_id": "co-a-alt", **trip},
        ],
    }


async def seed(cli):
    await cli.drop_database(DB)
    for coll, rows in fixtures().items():
        await cli[DB][coll].insert_many([dict(r) for r in rows])


async def dbhash(cli) -> dict[str, str]:
    r = await cli[DB].command("dbHash", collections=TRACKED)
    return dict(r.get("collections", {}))


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0",
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0", "DISABLE_SCHEDULER": "1",
                "REGRESSION_GUARD_PERIODIC": "0", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                             "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                            stdout=open(LOGDIR / "gate7t_py.log", "wb"), stderr=subprocess.STDOUT)


def start_node():
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
    return subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env,
                            stdout=open(LOGDIR / "gate7t_node.log", "wb"), stderr=subprocess.STDOUT)


def raw_get(port: int, path: str, hdr: dict[str, str]) -> tuple[int, str, bytes]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    c.putrequest("GET", path, skip_accept_encoding=True)
    for k, v in hdr.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    b = r.read()
    ct = r.getheader("content-type") or ""
    c.close()
    return r.status, ct, b


def wait(port: int, path: str, timeout: int = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if raw_get(port, path, {})[0] < 500:
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


AUTH = {"Authorization": "Bearer tok-u1"}
GUARD_NOT_FOUND = lambda p: json.dumps({"message": f"Route GET:{p} not found", "error": "Not Found", "statusCode": 404},
                                       separators=(",", ":")).encode()

# kind: guard → Node must hand off to not-found (0 DB ops); python must serve its static handler
#       tid   → Node :tid handler; byte parity with Python required
CASES = [
    {"k": "guard", "d": "export (auth)", "p": "/api/trips/export", "h": AUTH},
    {"k": "guard", "d": "export (no auth)", "p": "/api/trips/export", "h": {}},
    {"k": "guard", "d": "export ?format=xlsx", "p": "/api/trips/export?format=xlsx", "h": AUTH},
    {"k": "guard", "d": "export owned alt company", "p": "/api/trips/export", "h": {**AUTH, "X-Company-Id": "co-a-alt"}},
    {"k": "guard", "d": "recurring-suggestions (auth)", "p": "/api/trips/recurring-suggestions", "h": AUTH},
    {"k": "guard", "d": "recurring-suggestions (no auth)", "p": "/api/trips/recurring-suggestions", "h": {}},
    {"k": "guard", "d": "recurring-suggestions owned alt company", "p": "/api/trips/recurring-suggestions", "h": {**AUTH, "X-Company-Id": "co-a-alt"}},
    {"k": "tid", "d": "real trip t1", "p": "/api/trips/t1", "h": AUTH},
    {"k": "tid", "d": "real trip owned alt company", "p": "/api/trips/t-alt", "h": {**AUTH, "X-Company-Id": "co-a-alt"}},
    {"k": "tid", "d": "alt trip hidden under default company", "p": "/api/trips/t-alt", "h": AUTH},
    {"k": "tid", "d": "missing trip", "p": "/api/trips/nope", "h": AUTH},
    {"k": "tid", "d": "near-miss 'exports' still :tid", "p": "/api/trips/exports", "h": AUTH},
    {"k": "tid", "d": "near-miss 'import' still :tid", "p": "/api/trips/import", "h": AUTH},
    {"k": "tid", "d": "real trip no auth", "p": "/api/trips/t1", "h": {}},
]


async def run() -> int:
    print(f"[gate7t] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli)
        py = start_py(); node = start_node()
        okp = wait(PY_PORT, "/api/"); okn = wait(NODE_PORT, "/health/live")
        print(f"[gate7t] py={okp} node={okn}")
        if not (okp and okn):
            return 2
        await asyncio.sleep(6)
        pdb = cli[DB]
        await pdb.command({"profile": 0})
        await pdb.drop_collection("system.profile")
        await pdb.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await pdb.command({"profile": 2})

        results, passed, failed, node_hash_changes = [], 0, 0, 0
        for i, c in enumerate(CASES, 1):
            rp = raw_get(PY_PORT, c["p"], c["h"])
            before_n = await pdb["system.profile"].count_documents({"appName": NODE_APP})
            h0 = await dbhash(cli)
            rn = raw_get(NODE_PORT, c["p"], c["h"])
            h1 = await dbhash(cli)
            await asyncio.sleep(0.05)
            node_ops = await pdb["system.profile"].find({"appName": NODE_APP}, {"ns": 1, "op": 1}).sort("ts", 1).skip(before_n).to_list(None)
            nw = [k for k in TRACKED if h0.get(k) != h1.get(k)]
            node_hash_changes += bool(nw)
            colls = [o.get("ns", "").split(".", 1)[-1] for o in node_ops]
            try: pj: Any = json.loads(rp[2])
            except Exception: pj = None
            try: nj: Any = json.loads(rn[2])
            except Exception: nj = None
            if c["k"] == "guard":
                # Node: exact Fastify not-found body (raw path incl. query) and ZERO DB ops.
                selected = "not-found handler (guard)" if (rn[0] == 404 and rn[2] == GUARD_NOT_FOUND(c["p"]) and not colls) else "CAPTURED"
                # Python: its own static handler — served content, or its auth-first 401.
                py_route = ("static handler (200)" if rp[0] == 200 and (rp[1].startswith("text/csv")
                            or rp[1].startswith("application/vnd") or rp[2].startswith(b"["))
                            else "static handler (auth 401)" if rp[0] == 401 else "UNEXPECTED")
                ok = selected.startswith("not-found") and py_route != "UNEXPECTED" and not nw
            else:
                selected = ":tid handler" if "trips" in colls or rn[0] == 401 else "?"
                py_route = "/trips/{tid}"
                # Gate-6a lock criterion: equal status + parsed-JSON equality.
                ok = rp[0] == rn[0] and pj == nj and pj is not None and not nw and selected == ":tid handler"
            passed += ok; failed += (not ok)
            results.append({"case": i, "kind": c["k"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                            "py_route": py_route, "bytes_equal": rp[2] == rn[2],
                            "parsed_equal": pj == nj and pj is not None,
                            "py": [rp[0], rp[1], rp[2].decode("utf-8", "replace")],
                            "node": [rn[0], rn[1], rn[2].decode("utf-8", "replace")],
                            "node_route": selected, "node_db_collections": colls, "node_hash_change": nw})

        await pdb.command({"profile": 0})
        prof = await pdb["system.profile"].find({"appName": NODE_APP}, {"op": 1, "command": 1}).to_list(None)
        write_names = {"insert", "update", "delete", "findAndModify", "findandmodify", "bulkWrite", "create",
                       "createIndexes", "drop", "dropIndexes", "renameCollection"}
        write_ops = sum(1 for p in prof if p.get("op") in ("insert", "update", "remove")
                        or next(iter(p.get("command") or {}), "") in write_names)
        zero_ok = write_ops == 0 and node_hash_changes == 0
        passed += zero_ok; failed += (not zero_ok)

        print("\n" + "=" * 78 + "\nPHASE 3 · GATE 7t · LIVE ROUTE-PRECEDENCE VERIFICATION\n" + "=" * 78)
        for r in results:
            print(f"  [{r['verdict']}] {r['case']:>2} {r['kind']:5} {r['desc']}")
            print(f"        py   {r['py'][0]} {r['py'][1]!r:32} route={r['py_route']}")
            print(f"        node {r['node'][0]} {r['node'][1]!r:32} route={r['node_route']} db={r['node_db_collections']}"
                  + (f"  parsed_equal={r['parsed_equal']} bytes_equal={r['bytes_equal']}" if r["kind"] == "tid" else ""))
            if r["kind"] == "tid" and not r["bytes_equal"]:
                print(f"        py   body: {r['py'][2]}\n        node body: {r['node'][2]}")
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node profiled ops={len(prof)} write_ops={write_ops} dbHash-change cases={node_hash_changes}")
        print("-" * 78 + f"\n  cases: {len(results) + 1}   passed: {passed}   failed: {failed}\n" + "=" * 78)
        (LOGDIR / "gate7t_parity_results.json").write_text(json.dumps({"db": DB, "passed": passed, "failed": failed,
            "node_write_ops": write_ops, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await cli[DB].command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate7t] dropped {DB}; leftover gate7t DBs: "
              f"{[d for d in await cli.list_database_names() if d.startswith('trukvia_gate7t_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
