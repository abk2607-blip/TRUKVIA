"""Phase 3 · Gate 7p · live Python↔Node parity harness for Driver salary-masters list.

Covers:
  * GET /api/drivers/{did}/salary-masters

Class-C stance:
  Pure-read in Python. Handler executes exactly
    drivers.find_one({id, user_id, company_id}, {_id:0, user_id:0})
    driver_salary_masters.find({user_id, company_id, driver_id}, {_id:0})
      .sort([("effective_from", -1), ("version", -1)]).to_list(500)
  Zero writes / audits / backfill.

Parity axes: auth precedence, driver pre-check 404 literal, `{_id:0}`-only
projection (user_id PRESERVED), two-key DESC sort on real Mongo with mixed
BSON types, 500 cap, wrapper `{items}`, encoded-slash 404.

Framework-level gaps (NOT counted; owned by the framework gate): invalid
UTF-8 escapes, trailing slash, param > 100 chars, encoded slash decoding onto another Python route (x%2Fledger → 405).
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7p_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7p-py", "trukvia-gate7p-node"
PY_PORT, NODE_PORT = 8246, 8247
LOGDIR = Path(tempfile.gettempdir())
BIG_N = 502


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def dsm(mid: str, did: str, eff: Any, version: Any, uid: str = "u1", company: str = "co-a", **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"id": mid, "user_id": uid, "company_id": company, "driver_id": did,
                         "monthly_salary": 15000.0, "effective_to": None, "remarks": None,
                         "created_at": "2026-01-01T00:00:00+00:00", "created_by": uid,
                         "updated_at": "2026-01-01T00:00:00+00:00", "updated_by": uid}
    if eff is not ...:
        d["effective_from"] = eff
    if version is not ...:
        d["version"] = version
    d.update(kw)
    return d


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    special = "drv ₹ 'q' \"dq\""
    masters = [
        dsm("m1", "d1", "2026-01-01", 1, remarks="first"),
        dsm("m3", "d1", "2026-04-01", 3, effective_to=None, monthly_salary=18000.5),
        dsm("m2", "d1", "2026-04-01", 2, effective_to="2026-03-31"),
        dsm("m-nofrom", "d1", ..., 9),
        dsm("m-nullfrom", "d1", None, 8),
        dsm("m-numfrom", "d1", 20260101, 7),
        dsm("m-nover", "d1", "2026-04-01", ...),
        dsm("m-strver", "d1", "2026-04-01", "10"),
        dsm("m-alt", "d-alt", "2026-02-01", 1, company="co-a-alt"),
        dsm("m-u2", "d-u2", "2026-02-01", 1, uid="u2", company="co-b"),
        dsm("m-u2-same-did", "d1", "2026-02-01", 1, uid="u2", company="co-b"),
        dsm("m-orphan", "d-gone", "2026-02-01", 1),
        dsm("m-special", special, "2026-02-01", 1, remarks="नमस्ते"),
    ]
    masters += [dsm(f"big-{i:03d}", "d-big", f"2020-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}", i)
                for i in range(BIG_N)]
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [{"user_id": u, "email": f"{u}@x", "name": u.upper(), "picture": "", "created_at": now}
                  for u in ("u1", "u2")],
        "companies": [
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        ],
        "drivers": [
            {"id": "d1", "user_id": "u1", "company_id": "co-a", "name": "Ravi"},
            {"id": "d-empty", "user_id": "u1", "company_id": "co-a", "name": "No Masters"},
            {"id": "d-big", "user_id": "u1", "company_id": "co-a", "name": "Big"},
            {"id": "d-alt", "user_id": "u1", "company_id": "co-a-alt", "name": "Alt"},
            {"id": "d-u2", "user_id": "u2", "company_id": "co-b", "name": "U2"},
            {"id": "d1", "user_id": "u2", "company_id": "co-b", "name": "U2 same id"},
            {"id": "d-legacy", "user_id": "u1", "name": "Legacy no company"},
            {"id": special, "user_id": "u1", "company_id": "co-a", "name": "Special"},
            {"id": "d-leak", "user_id": "u2", "company_id": "co-a", "name": "u2 row with u1 company"},
        ],
        "driver_salary_masters": masters,
    }


TRACKED = ("users", "user_sessions", "companies", "drivers", "driver_salary_masters",
           "driver_ledger_entries", "audit_logs", "approvals", "counters", "fin_txn")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    for coll, rows in fixtures().items():
        await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(None)
        docs.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[c] = json.dumps(docs, sort_keys=True, default=str)
    return out


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB,
                "ENABLE_DEMO_TOKEN": "0", "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0",
                "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0",
                "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open(LOGDIR / "gate7p_py.log", "wb"), stderr=subprocess.STDOUT)


def start_node():
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent",
                "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB,
                "NODE_CORS_ORIGINS": "", "NODE_REQUEST_ID_HEADER": "x-request-id",
                "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
    return subprocess.Popen(
        ["node", str(REPO / "backend-node/dist/server.js")],
        cwd=str(REPO / "backend-node"), env=env,
        stdout=open(LOGDIR / "gate7p_node.log", "wb"), stderr=subprocess.STDOUT)


def raw_get(port: int, path: str, hdr: dict[str, str]) -> tuple[int, str]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.putrequest("GET", path, skip_accept_encoding=True)
    for k, v in hdr.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    body = r.read().decode("utf-8", "replace")
    c.close()
    return r.status, body


def wait(port: int, path: str, timeout: int = 90) -> bool:
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


HDR = {
    "u1": {"Authorization": "Bearer tok-u1"},
    "u2": {"Authorization": "Bearer tok-u2"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad": {"Authorization": "Bearer nope"},
    "none": {},
}


def u(did: str) -> str:
    return f"/api/drivers/{quote(did, safe='')}/salary-masters"


CASES: list[dict[str, Any]] = [
    # Auth
    {"d": "no bearer → 401", "url": u("d1"), "hk": "none", "expect": 401},
    {"d": "invalid bearer → 401", "url": u("d1"), "hk": "bad", "expect": 401},
    {"d": "expired bearer → 401", "url": u("d1"), "hk": "expired", "expect": 401},
    {"d": "no bearer + unknown driver → 401 (auth first)", "url": u("d-gone"), "hk": "none", "expect": 401},
    # Hits
    {"d": "d1 full list · mixed-type sort (missing/null/number/string, version ties)", "url": u("d1"), "hk": "u1", "expect": 200},
    {"d": "driver with no masters → {items: []}", "url": u("d-empty"), "hk": "u1", "expect": 200},
    {"d": "502-master driver → cap 500", "url": u("d-big"), "hk": "u1", "expect": 200},
    {"d": "special-char driver id (encoded)", "url": u("drv ₹ 'q' \"dq\""), "hk": "u1", "expect": 200},
    {"d": "query string ignored", "url": u("d1") + "?limit=1&driver_id=d-big", "hk": "u1", "expect": 200},
    # 404 Driver not found
    {"d": "unknown driver → 404", "url": u("d-gone"), "hk": "u1", "expect": 404},
    {"d": "cross-user driver id → 404", "url": u("d-u2"), "hk": "u1", "expect": 404},
    {"d": "other company driver under default → 404", "url": u("d-alt"), "hk": "u1", "expect": 404},
    {"d": "legacy driver without company_id → 404", "url": u("d-legacy"), "hk": "u1", "expect": 404},
    {"d": "u2 row carrying u1 company id → 404 for u1", "url": u("d-leak"), "hk": "u1", "expect": 404},
    {"d": "case-sensitive id D1 → 404", "url": u("D1"), "hk": "u1", "expect": 404},
    {"d": "space id %20 → 404", "url": "/api/drivers/%20/salary-masters", "hk": "u1", "expect": 404},
    {"d": "unicode id → 404", "url": u("चालक"), "hk": "u1", "expect": 404},
    # Encoded slash
    {"d": "encoded slash with auth → 404 Not Found", "url": "/api/drivers/d1%2Fx/salary-masters", "hk": "u1", "expect": 404},
    {"d": "encoded slash no auth → 404 Not Found", "url": "/api/drivers/d1%2Fx/salary-masters", "hk": "none", "expect": 404},
    {"d": "empty did // with auth → 404 Not Found", "url": "/api/drivers//salary-masters", "hk": "u1", "expect": 404},
    {"d": "empty did // no auth → 404 Not Found", "url": "/api/drivers//salary-masters", "hk": "none", "expect": 404},
    # Isolation
    {"d": "u2 same driver id d1 → u2's own masters", "url": u("d1"), "hk": "u2", "expect": 200},
    {"d": "u2 own driver d-u2", "url": u("d-u2"), "hk": "u2", "expect": 200},
    {"d": "u1 owned X-Company-Id co-a-alt → alt driver", "url": u("d-alt"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"d": "u1 owned alt header hides co-a driver", "url": u("d1"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 404},
    {"d": "u1 unowned X-Company-Id co-b → fallback co-a", "url": u("d1"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},
    {"d": "u1 nonexistent X-Company-Id → fallback", "url": u("d1"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-zzz"}, "expect": 200},
    {"d": "u1 empty X-Company-Id → default", "url": u("d1"), "hk": "u1", "extra_hdr": {"X-Company-Id": ""}, "expect": 200},
    {"d": "u2 X-Company-Id co-a → fallback co-b (leak row hidden)", "url": u("d-leak"), "hk": "u2", "extra_hdr": {"X-Company-Id": "co-a"}, "expect": 404},
    # Neighbour route precedence (Gate 6y) untouched
    {"d": "neighbour /drivers/d1/payments still parity (6y)", "url": "/api/drivers/d1/payments", "hk": "u1", "expect": 200},
]

INFORMATIONAL = [
    {"d": "[framework] invalid UTF-8 %FF", "url": "/api/drivers/%FF/salary-masters", "hk": "u1"},
    {"d": "[framework] trailing slash", "url": u("d1") + "/", "hk": "u1"},
    {"d": "[framework] did > 100 chars", "url": u("d" * 101), "hk": "u1"},
    {"d": "[framework] encoded slash onto DELETE route (x%2Fledger)", "url": "/api/drivers/d1%2Fledger/salary-masters", "hk": "u1"},
]


async def run() -> int:
    print(f"[gate7p] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        py = start_py(); node = start_node()
        okp = wait(PY_PORT, "/api/"); okn = wait(NODE_PORT, "/health/live")
        print(f"[gate7p] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print((LOGDIR / "gate7p_py.log").read_text(errors="replace")[-3000:])
            if not okn: print((LOGDIR / "gate7p_node.log").read_text(errors="replace")[-3000:])
            return 2
        await asyncio.sleep(8)

        pdb = cli[DB]
        await pdb.command({"profile": 0})
        await pdb.drop_collection("system.profile")
        await pdb.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await pdb.command({"profile": 2})

        results = []; passed = failed = node_snap_writes = py_snap_writes = 0
        for i, c in enumerate(CASES, 1):
            hdr = dict(HDR[c["hk"]]); hdr.update(c.get("extra_hdr", {}))
            s0 = await snap(cli, DB)
            rp = raw_get(PY_PORT, c["url"], hdr)
            s1 = await snap(cli, DB)
            rn = raw_get(NODE_PORT, c["url"], hdr)
            s2 = await snap(cli, DB)
            py_w = [k for k in s0 if s0[k] != s1[k]]; nd_w = [k for k in s1 if s1[k] != s2[k]]
            py_snap_writes += bool(py_w); node_snap_writes += bool(nd_w)
            try: pj: Any = json.loads(rp[1])
            except Exception: pj = rp[1]
            try: nj: Any = json.loads(rn[1])
            except Exception: nj = rn[1]
            status_ok = rp[0] == rn[0] == c["expect"]
            order_ok = not (isinstance(pj, dict) and isinstance(nj, dict)) or list(pj) == list(nj)
            body_ok = pj == nj and order_ok
            ok = status_ok and body_ok and not nd_w
            passed += ok; failed += (not ok)
            n_items = len(pj["items"]) if isinstance(pj, dict) and isinstance(pj.get("items"), list) else None
            order = [x.get("id") for x in pj["items"]][:12] if n_items else None
            results.append({"case": i, "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                            "py_status": rp[0], "node_status": rn[0], "items": n_items, "order": order,
                            "py_write_colls": py_w, "node_write_colls": nd_w,
                            "py_body": "" if body_ok else rp[1][:800], "node_body": "" if body_ok else rn[1][:800]})

        await pdb.command({"profile": 0})
        prof = await pdb["system.profile"].find({"appName": NODE_APP}, {"op": 1, "ns": 1, "command": 1}).to_list(None)
        kinds: dict[str, int] = {}; by_ns: dict[str, int] = {}; write_ops = 0
        write_names = {"insert", "update", "delete", "findAndModify", "findandmodify", "bulkWrite",
                       "create", "createIndexes", "drop", "dropIndexes", "renameCollection"}
        for p in prof:
            cmd = p.get("command") or {}
            first = next(iter(cmd), "") if isinstance(cmd, dict) else ""
            kinds[f"{p.get('op')}:{first}"] = kinds.get(f"{p.get('op')}:{first}", 0) + 1
            ns = p.get("ns", "").split(".", 1)[-1]
            by_ns[ns] = by_ns.get(ns, 0) + 1
            if p.get("op") in ("insert", "update", "remove") or first in write_names:
                write_ops += 1
        zero_ok = (write_ops == 0 and node_snap_writes == 0
                   and by_ns.get("drivers", 0) > 0 and by_ns.get("driver_salary_masters", 0) > 0)
        results.append({"case": len(CASES) + 1, "desc": "zero-write — profiler + snapshots across full live matrix",
                        "verdict": "PASS" if zero_ok else "FAIL", "node_profiled_ops": len(prof),
                        "node_op_kinds": kinds, "node_ops_by_ns": by_ns, "node_write_ops": write_ops})
        passed += zero_ok; failed += (not zero_ok)

        info = []
        for c in INFORMATIONAL:
            rp = raw_get(PY_PORT, c["url"], HDR[c["hk"]]); rn = raw_get(NODE_PORT, c["url"], HDR[c["hk"]])
            info.append({"desc": c["d"], "same": (rp[0], rp[1]) == (rn[0], rn[1]),
                         "py": [rp[0], rp[1][:140]], "node": [rn[0], rn[1][:140]]})

        print("\n" + "=" * 78)
        print("PHASE 3 · GATE 7p · LIVE PARITY MATRIX (Driver salary-masters list)")
        print("=" * 78)
        for r in results:
            extra = f" items={r['items']}" if r.get("items") is not None else ""
            print(f"  [{r['verdict']}] case {r['case']:>3} py={r.get('py_status', '-')} node={r.get('node_status', '-')}{extra}  {r['desc']}")
            if r.get("case") == 5 and r.get("order"):
                print(f"      d1 order: {r['order']}")
            if r["verdict"] == "FAIL" and "py_body" in r:
                print(f"      py_body  : {r['py_body']}\n      node_body: {r['node_body']}")
        print(f"  node profiled ops={len(prof)} kinds={kinds} by_ns={by_ns} write_ops={write_ops}")
        print("-" * 78)
        print(f"  cases: {len(results)} (fixed {len(CASES)} + zero-write 1)   passed: {passed}   failed: {failed}")
        print(f"  python snapshot-write cases: {py_snap_writes}   node snapshot-write cases: {node_snap_writes}")
        print("  informational (framework gate — NOT counted):")
        for x in info:
            print(f"    [{'SAME' if x['same'] else 'DIFF'}] {x['desc']}\n        py   {x['py']}\n        node {x['node']}")
        print("=" * 78)
        out = LOGDIR / "gate7p_parity_results.json"
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": passed, "failed": failed,
                                   "node_write_ops": write_ops, "results": results, "informational": info},
                                  indent=2, default=str), encoding="utf-8")
        print(f"[gate7p] results → {out}")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await cli[DB].command({"profile": 0})
        except Exception: pass
        try:
            await cli.drop_database(DB)
            print(f"[gate7p] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7p] drop failed: {e}")
        print(f"[gate7p] leftover gate7p DBs: {[d for d in await cli.list_database_names() if d.startswith('trukvia_gate7p_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
