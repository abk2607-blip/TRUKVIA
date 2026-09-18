"""Phase 3 · Gate 7o · live Python↔Node parity harness for Fin day-status.

Covers:
  * GET /api/fin/day-status?date=YYYY-MM-DD

Class-C stance:
  Pure-read in Python. Handler executes at most
    db.fin_day_closures.find_one({user_id, company_id, close_date: date},
      {_id:0, status:1, closed_at:1, closed_by:1, reopened_at:1, reopened_by:1})
    db.fin_txn.find_one({user_id, company_id, status:"active",
      txn_date:{$lte: date}, created_at:{$gt: closed_at}}, {_id:0, id:1})
  Zero writes / audits / snapshot capture / backfill.

Parity axes: auth precedence, required-`date` 422, two 400 literals, C
`date.fromisoformat`, Python truthiness on projected docs and `closed_at`
(incl. non-string BSON values), missing-vs-null response fields.

Requests use http.client RAW paths so query encoding reaches both servers
byte-for-byte.
"""
from __future__ import annotations
import asyncio, http.client, json, os, random, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7o_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7o-py", "trukvia-gate7o-node"
PY_PORT, NODE_PORT = 8244, 8245
LOGDIR = Path(tempfile.gettempdir())
P = "/api/fin/day-status"
CLOSED_AT = "2026-05-10T18:00:00.123456+00:00"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def fdc(close_date: str, uid: str = "u1", company: str = "co-a", **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": f"fdc-{uid}-{company}-{close_date}", "user_id": uid, "company_id": company,
        "close_date": close_date, "status": "closed", "closed_at": CLOSED_AT, "closed_by": uid,
        "close_notes": "", "snapshot": {"AR": {"in": 1.0, "out": 0.0, "net": 1.0}},
        "snapshot_source_count": 1, "reopened_at": "", "reopened_by": "", "reopen_reason": "",
        "history": [], "created_at": CLOSED_AT, "modified_at": "",
    }
    d.update(kw)
    return d


def txn(tid: str | None, txn_date: str, created_at: str, company: str = "co-a",
        uid: str = "u1", status: str = "active") -> dict[str, Any]:
    t: dict[str, Any] = {"user_id": uid, "company_id": company, "status": status,
                         "txn_date": txn_date, "created_at": created_at,
                         "account_code": "AR", "direction": "in", "amount": 10.0}
    if tid is not None:
        t["id"] = tid
    return t


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    bare = {"id": "bare", "user_id": "u1", "company_id": "co-a", "close_date": "2026-05-04"}
    partial = {"id": "partial", "user_id": "u1", "company_id": "co-a", "close_date": "2026-05-05",
               "status": "closed", "closed_at": CLOSED_AT, "closed_by": None}
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
        "fin_day_closures": [
            fdc("2026-05-01"),                                        # closed + late txn
            fdc("2026-04-01"),                                        # closed, no late
            fdc("2026-05-02", status="reopened", reopened_at="2026-05-11T09:00:00+00:00", reopened_by="u1"),
            fdc("2026-05-03", closed_at=""),                          # falsy closed_at
            bare,                                                     # projects to {}
            partial,                                                  # missing reopened_*, null closed_by
            fdc("2026-05-06"),                                        # only id-less late txn
            fdc("2026-05-07", company="co-a-alt"),
            fdc("2026-05-08", status="CLOSED"),                       # case-sensitive status
            fdc("2026-05-09", closed_at=0),                           # numeric falsy closed_at
            fdc("2026-05-10", closed_at=5),                           # numeric truthy closed_at
            fdc("2026-05-11", closed_at=[]),                          # empty list
            fdc("2026-05-12", closed_at={"k": 1}),                    # non-empty dict
            fdc("2026-05-13", closed_at=True),                        # bool
            fdc("2026-05-14", status=None),                           # null status
            fdc("20260515"),                                          # compact stored date
            fdc("2026-W20-5"),                                        # ISO-week stored date
            fdc("2026-05-01", uid="u2", company="co-b", status="reopened"),
            fdc("2026-05-16", uid="u2", company="co-a"),              # u2 row carrying u1's company id
        ],
        "fin_txn": [
            txn("tx-late", "2026-04-30", "2026-05-11T00:00:00+00:00"),
            txn("tx-early", "2026-03-01", "2026-05-01T00:00:00+00:00"),
            txn("tx-void", "2026-03-15", "2026-05-12T00:00:00+00:00", status="void"),
            txn(None, "2026-05-06", "2026-05-12T00:00:00+00:00", company="co-x"),
            txn("tx-u2", "2026-01-01", "2026-05-12T00:00:00+00:00", company="co-b", uid="u2"),
        ],
    }


TRACKED = ("users", "user_sessions", "companies", "fin_day_closures", "fin_txn",
           "audit_logs", "approvals", "counters", "fin_hook_failures")


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
        stdout=open(LOGDIR / "gate7o_py.log", "wb"), stderr=subprocess.STDOUT)


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
        stdout=open(LOGDIR / "gate7o_node.log", "wb"), stderr=subprocess.STDOUT)


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


def qd(raw: str) -> str:
    return f"{P}?date={quote(raw, safe='')}"


CASES: list[dict[str, Any]] = [
    # Auth + precedence
    {"d": "no bearer → 401", "url": qd("2026-05-01"), "hk": "none", "expect": 401},
    {"d": "invalid bearer → 401", "url": qd("2026-05-01"), "hk": "bad", "expect": 401},
    {"d": "expired bearer → 401", "url": qd("2026-05-01"), "hk": "expired", "expect": 401},
    {"d": "no bearer + missing date → 401", "url": P, "hk": "none", "expect": 401},
    {"d": "no bearer + blank date → 401", "url": P + "?date=", "hk": "none", "expect": 401},
    {"d": "expired + invalid date → 401", "url": qd("bad"), "hk": "expired", "expect": 401},
    # Validation
    {"d": "missing date → 422 missing", "url": P, "hk": "u1", "expect": 422},
    {"d": "other key only → 422 missing", "url": P + "?day=2026-05-01", "hk": "u1", "expect": 422},
    {"d": "blank date → 400 required", "url": P + "?date=", "hk": "u1", "expect": 400},
    {"d": "bare ?date → 400 required", "url": P + "?date", "hk": "u1", "expect": 400},
    {"d": "invalid text → 400 ISO", "url": qd("bad"), "hk": "u1", "expect": 400},
    {"d": "unpadded → 400", "url": qd("2026-5-1"), "hk": "u1", "expect": 400},
    {"d": "non-leap Feb 29 → 400", "url": qd("2026-02-29"), "hk": "u1", "expect": 400},
    {"d": "year 0000 → 400", "url": qd("0000-01-01"), "hk": "u1", "expect": 400},
    {"d": "single space → 400", "url": qd(" "), "hk": "u1", "expect": 400},
    {"d": "raw '+' decodes to space → 400", "url": P + "?date=+", "hk": "u1", "expect": 400},
    {"d": "datetime form → 400", "url": qd("2026-05-01T00"), "hk": "u1", "expect": 400},
    {"d": "invalid UTF-8 in query %FF → 400", "url": P + "?date=%FF", "hk": "u1", "expect": 400},
    {"d": "invalid UTF-8 inside date → 400", "url": P + "?date=2026-05-%FF", "hk": "u1", "expect": 400},
    {"d": "NUL suffix → 400", "url": P + "?date=2026-05-01%00", "hk": "u1", "expect": 400},
    # Response shapes
    {"d": "no closure → {date, is_closed:false}", "url": qd("2026-06-01"), "hk": "u1", "expect": 200},
    {"d": "closed + late txn → has_late true", "url": qd("2026-05-01"), "hk": "u1", "expect": 200},
    {"d": "closed, no late txn", "url": qd("2026-04-01"), "hk": "u1", "expect": 200},
    {"d": "reopened → is_closed false", "url": qd("2026-05-02"), "hk": "u1", "expect": 200},
    {"d": "closed_at '' → no probe", "url": qd("2026-05-03"), "hk": "u1", "expect": 200},
    {"d": "closure projecting to {} → not-found shape", "url": qd("2026-05-04"), "hk": "u1", "expect": 200},
    {"d": "missing reopened_* → '' · null closed_by", "url": qd("2026-05-05"), "hk": "u1", "expect": 200},
    {"d": "id-less late txn (other company) → false", "url": qd("2026-05-06"), "hk": "u1", "expect": 200},
    {"d": "status CLOSED case-sensitive → is_closed false", "url": qd("2026-05-08"), "hk": "u1", "expect": 200},
    {"d": "closed_at 0 → falsy, no probe", "url": qd("2026-05-09"), "hk": "u1", "expect": 200},
    {"d": "closed_at 5 → truthy, probe with number", "url": qd("2026-05-10"), "hk": "u1", "expect": 200},
    {"d": "closed_at [] → falsy", "url": qd("2026-05-11"), "hk": "u1", "expect": 200},
    {"d": "closed_at {k:1} → truthy, probe with object", "url": qd("2026-05-12"), "hk": "u1", "expect": 200},
    {"d": "closed_at true → truthy", "url": qd("2026-05-13"), "hk": "u1", "expect": 200},
    {"d": "status null → is_closed false, status null", "url": qd("2026-05-14"), "hk": "u1", "expect": 200},
    {"d": "compact stored date queried raw", "url": qd("20260515"), "hk": "u1", "expect": 200},
    {"d": "compact query ≠ ISO stored → not found", "url": qd("20260501"), "hk": "u1", "expect": 200},
    {"d": "ISO-week stored date queried raw", "url": qd("2026-W20-5"), "hk": "u1", "expect": 200},
    {"d": "valid week date not stored", "url": qd("2026-W53"), "hk": "u1", "expect": 200},
    {"d": "unknown extra key ignored", "url": qd("2026-05-01") + "&x=1", "hk": "u1", "expect": 200},
    {"d": "repeated date → last wins (valid)", "url": P + "?date=bad&date=2026-05-01", "hk": "u1", "expect": 200},
    {"d": "repeated date → last wins (invalid)", "url": P + "?date=2026-05-01&date=bad", "hk": "u1", "expect": 400},
    {"d": "repeated date → last blank", "url": P + "?date=2026-05-01&date=", "hk": "u1", "expect": 400},
    # Isolation
    {"d": "cross-user u2 same date → own reopened row", "url": qd("2026-05-01"), "hk": "u2", "expect": 200},
    {"d": "u1 default hides co-a-alt", "url": qd("2026-05-07"), "hk": "u1", "expect": 200},
    {"d": "u1 owned X-Company-Id co-a-alt", "url": qd("2026-05-07"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"d": "u1 unowned X-Company-Id co-b → fallback", "url": qd("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},
    {"d": "u1 empty X-Company-Id → default", "url": qd("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": ""}, "expect": 200},
    {"d": "u2 X-Company-Id co-a → fallback co-b, leak row hidden", "url": qd("2026-05-16"), "hk": "u2", "extra_hdr": {"X-Company-Id": "co-a"}, "expect": 200},
    {"d": "u2 late probe scoped to u2 (reopened → no probe)", "url": qd("2026-05-01"), "hk": "u2", "expect": 200},
]


def fuzz_dates(n: int = 300) -> list[str]:
    rnd = random.Random(7_000_015)
    out: list[str] = []
    alphabet = list("0123456789") * 3 + ["-", "-", "W", " ", "+", ".", "x", "é"]
    for _ in range(n // 2):
        out.append("".join(rnd.choice(alphabet) for _ in range(rnd.choice([6, 7, 8, 9, 10, 10, 11]))))
    for _ in range(n // 2):
        y = rnd.choice(["2026", "2024", "2015", "0000", "9999", f"{rnd.randint(0, 9999):04d}"])
        sep = rnd.choice(["-", ""])
        if rnd.random() < 0.6:
            out.append(f"{y}{sep}{rnd.randint(0, 13):02d}{rnd.choice([sep, '-', ''])}{rnd.randint(0, 32):02d}")
        else:
            out.append(f"{y}{sep}W{rnd.randint(0, 54):02d}{rnd.choice(['', f'{sep}{rnd.randint(0, 8)}'])}")
    return out


async def run() -> int:
    print(f"[gate7o] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        py = start_py(); node = start_node()
        okp = wait(PY_PORT, "/api/"); okn = wait(NODE_PORT, "/health/live")
        print(f"[gate7o] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print((LOGDIR / "gate7o_py.log").read_text(errors="replace")[-3000:])
            if not okn: print((LOGDIR / "gate7o_node.log").read_text(errors="replace")[-3000:])
            return 2
        await asyncio.sleep(8)

        pdb = cli[DB]
        await pdb.command({"profile": 0})
        await pdb.drop_collection("system.profile")
        await pdb.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await pdb.command({"profile": 2})

        matrix = list(CASES)
        for s in fuzz_dates():
            matrix.append({"d": f"fuzz {json.dumps(s)}", "url": qd(s), "hk": "u1", "expect": None, "fuzz": True})

        results = []; passed = failed = node_snap_writes = py_snap_writes = 0
        for i, c in enumerate(matrix, 1):
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
            exp = c["expect"]
            status_ok = rp[0] == rn[0] and (exp is None or rp[0] == exp)
            # dict equality ignores key order — check it explicitly for 200 bodies
            order_ok = not (isinstance(pj, dict) and isinstance(nj, dict)) or list(pj) == list(nj)
            body_ok = pj == nj and order_ok
            ok = status_ok and body_ok and not nd_w
            passed += ok; failed += (not ok)
            results.append({"case": i, "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                            "fuzz": c.get("fuzz", False), "py_status": rp[0], "node_status": rn[0],
                            "py_write_colls": py_w, "node_write_colls": nd_w,
                            "py_body": "" if body_ok else rp[1][:800], "node_body": "" if body_ok else rn[1][:800]})

        await pdb.command({"profile": 0})
        prof = await pdb["system.profile"].find({"appName": NODE_APP}, {"op": 1, "ns": 1, "command": 1}).to_list(None)
        kinds: dict[str, int] = {}; write_ops = 0
        write_names = {"insert", "update", "delete", "findAndModify", "findandmodify", "bulkWrite",
                       "create", "createIndexes", "drop", "dropIndexes", "renameCollection"}
        for p in prof:
            cmd = p.get("command") or {}
            first = next(iter(cmd), "") if isinstance(cmd, dict) else ""
            kinds[f"{p.get('op')}:{first}"] = kinds.get(f"{p.get('op')}:{first}", 0) + 1
            if p.get("op") in ("insert", "update", "remove") or first in write_names:
                write_ops += 1
        by_ns: dict[str, int] = {}
        for p in prof:
            by_ns[p.get("ns", "")] = by_ns.get(p.get("ns", ""), 0) + 1
        zero_ok = (write_ops == 0 and node_snap_writes == 0
                   and by_ns.get(f"{DB}.fin_day_closures", 0) > 0 and by_ns.get(f"{DB}.fin_txn", 0) > 0)
        results.append({"case": len(matrix) + 1, "desc": "zero-write — profiler + snapshots across full live matrix",
                        "verdict": "PASS" if zero_ok else "FAIL", "node_profiled_ops": len(prof),
                        "node_op_kinds": kinds, "node_ops_by_ns": by_ns, "node_write_ops": write_ops})
        passed += zero_ok; failed += (not zero_ok)

        print("\n" + "=" * 78)
        print("PHASE 3 · GATE 7o · LIVE PARITY MATRIX (Fin day-status)")
        print("=" * 78)
        for r in results:
            if r.get("fuzz") and r["verdict"] == "PASS":
                continue
            print(f"  [{r['verdict']}] case {r['case']:>3} py={r.get('py_status', '-')} node={r.get('node_status', '-')}  {r['desc']}")
            if r["verdict"] == "FAIL" and "py_body" in r:
                print(f"      py_body  : {r['py_body']}\n      node_body: {r['node_body']}")
        fz = [r for r in results if r.get("fuzz")]
        mix = {s: sum(r["py_status"] == s for r in fz) for s in (200, 400)}
        print(f"  fuzz: {sum(r['verdict'] == 'PASS' for r in fz)}/{len(fz)} PASS  (py status mix {mix})")
        print(f"  node profiled ops={len(prof)} kinds={kinds} by_ns={ {k.split('.')[-1]: v for k, v in by_ns.items()} } write_ops={write_ops}")
        print("-" * 78)
        print(f"  cases: {len(results)} (fixed {len(CASES)} + fuzz {len(fz)} + zero-write 1)   passed: {passed}   failed: {failed}")
        print(f"  python snapshot-write cases: {py_snap_writes}   node snapshot-write cases: {node_snap_writes}")
        print("=" * 78)
        out = LOGDIR / "gate7o_parity_results.json"
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": passed, "failed": failed,
                                   "node_write_ops": write_ops, "results": results}, indent=2, default=str),
                       encoding="utf-8")
        print(f"[gate7o] results → {out}")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await cli[DB].command({"profile": 0})
        except Exception: pass
        try:
            await cli.drop_database(DB)
            print(f"[gate7o] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7o] drop failed: {e}")
        print(f"[gate7o] leftover gate7o DBs: {[d for d in await cli.list_database_names() if d.startswith('trukvia_gate7o_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
