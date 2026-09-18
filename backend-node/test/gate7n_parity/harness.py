"""Phase 3 · Gate 7n · live Python↔Node parity harness for Fin day-closure detail.

Covers:
  * GET /api/fin/day-closures/{close_date}

Class-C stance:
  Pure-read in Python. Handler executes exactly one
    db.fin_day_closures.find_one({user_id, company_id, close_date},
                                 {_id:0, user_id:0})
  after auth and CPython 3.11 C `date.fromisoformat` validation.
  Zero writes / audits / snapshot capture / FinTxn reads / backfill.

Requests are sent with http.client using RAW paths so percent-encoding
reaches both servers byte-for-byte.

Framework-level gaps (pre-existing on locked Gate 7l, owned by the future
framework gate, reported but NOT counted): invalid UTF-8 percent-escapes,
trailing-slash 307 redirects, path params > 100 chars (Fastify
maxParamLength), encoded slash that decodes onto another Python route.
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
DB = f"trukvia_gate7n_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7n-py", "trukvia-gate7n-node"
PY_PORT, NODE_PORT = 8242, 8243
LOGDIR = Path(tempfile.gettempdir())
P = "/api/fin/day-closures/"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def closure(cid: str, uid: str, company: str, close_date: str, **kw: Any) -> dict[str, Any]:
    snap = {"AR": {"in": 1000.0, "out": 250.5, "net": 749.5},
            "BANK_DEFAULT": {"in": 0.0, "out": 12.25, "net": -12.25}}
    d: dict[str, Any] = {
        "id": cid, "user_id": uid, "company_id": company, "close_date": close_date,
        "status": "closed", "closed_at": "2026-05-10T18:00:00.123456+00:00",
        "closed_by": uid, "close_notes": "", "snapshot": snap,
        "snapshot_source_count": 7, "reopened_at": "", "reopened_by": "",
        "reopen_reason": "",
        "history": [{"event": "closed", "at": "2026-05-10T18:00:00.123456+00:00",
                     "by": uid, "notes": "", "snapshot": snap, "snapshot_source_count": 7}],
        "created_at": "2026-05-10T18:00:00.123456+00:00", "modified_at": "",
    }
    d.update(kw)
    return d


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
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
            closure("fdc-1", "u1", "co-a", "2026-05-01"),
            closure("fdc-2", "u1", "co-a", "2026-05-02", status="reopened",
                    reopened_at="2026-05-11T09:00:00+00:00", reopened_by="u1",
                    reopen_reason="late entry — ₹ adj \"quoted\" \\ back",
                    history=[{"event": "closed", "at": "2026-05-10T18:00:00+00:00", "by": "u1"},
                             {"event": "reopened", "at": "2026-05-11T09:00:00+00:00", "by": "u1",
                              "reason": "late entry"}]),
            closure("fdc-3", "u1", "co-a", "2026-05-03", close_notes="नमस्ते · తెలుగు", snapshot={}),
            closure("fdc-compact", "u1", "co-a", "20260504"),
            closure("fdc-week", "u1", "co-a", "2026-W18-5"),
            closure("fdc-alt", "u1", "co-a-alt", "2026-05-05"),
            closure("fdc-u2", "u2", "co-b", "2026-05-01", close_notes="u2 row"),
            closure("fdc-u2-leak", "u2", "co-a", "2026-05-06"),
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
        stdout=open(LOGDIR / "gate7n_py.log", "wb"), stderr=subprocess.STDOUT)


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
        stdout=open(LOGDIR / "gate7n_node.log", "wb"), stderr=subprocess.STDOUT)


def raw_get(port: int, path: str, hdr: dict[str, str]) -> tuple[int, str, str]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.putrequest("GET", path, skip_accept_encoding=True)
    for k, v in hdr.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    body = r.read().decode("utf-8", "replace")
    ctype = r.getheader("content-type") or ""
    c.close()
    return r.status, body, ctype


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


def seg(raw: str) -> str:
    return P + quote(raw, safe="")


CASES: list[dict[str, Any]] = [
    # Auth + precedence over date validation
    {"d": "no bearer → 401", "url": seg("2026-05-01"), "hk": "none", "expect": 401},
    {"d": "invalid bearer → 401", "url": seg("2026-05-01"), "hk": "bad", "expect": 401},
    {"d": "expired bearer → 401", "url": seg("2026-05-01"), "hk": "expired", "expect": 401},
    {"d": "no bearer + invalid date → 401 (auth first)", "url": seg("not-a-date"), "hk": "none", "expect": 401},
    {"d": "expired + invalid date → 401", "url": seg("2026-13-01"), "hk": "expired", "expect": 401},
    # Hits
    {"d": "hit 2026-05-01 full doc", "url": seg("2026-05-01"), "hk": "u1", "expect": 200},
    {"d": "hit reopened row with history + unicode reason", "url": seg("2026-05-02"), "hk": "u1", "expect": 200},
    {"d": "hit row with empty snapshot + unicode notes", "url": seg("2026-05-03"), "hk": "u1", "expect": 200},
    {"d": "hit compact raw 20260504", "url": seg("20260504"), "hk": "u1", "expect": 200},
    {"d": "hit ISO-week raw 2026-W18-5", "url": seg("2026-W18-5"), "hk": "u1", "expect": 200},
    {"d": "percent-encoded dashes decode to hit", "url": P + "2026%2D05%2D01", "hk": "u1", "expect": 200},
    {"d": "query string ignored", "url": seg("2026-05-01") + "?x=1&close_date=2026-05-02", "hk": "u1", "expect": 200},
    # 404 literal (raw segment echoed)
    {"d": "valid missing 2026-05-31", "url": seg("2026-05-31"), "hk": "u1", "expect": 404},
    {"d": "valid compact missing 20260501 (raw ≠ stored)", "url": seg("20260501"), "hk": "u1", "expect": 404},
    {"d": "valid week missing 2026-W18", "url": seg("2026-W18"), "hk": "u1", "expect": 404},
    {"d": "valid week compact 2026W185", "url": seg("2026W185"), "hk": "u1", "expect": 404},
    {"d": "10-byte trailing-ignored 2026050112", "url": seg("2026050112"), "hk": "u1", "expect": 404},
    {"d": "week-53 year 2026-W53", "url": seg("2026-W53"), "hk": "u1", "expect": 404},
    {"d": "leap day 2024-02-29", "url": seg("2024-02-29"), "hk": "u1", "expect": 404},
    {"d": "min 0001-01-01", "url": seg("0001-01-01"), "hk": "u1", "expect": 404},
    {"d": "max 9999-12-31", "url": seg("9999-12-31"), "hk": "u1", "expect": 404},
    {"d": "max week 9999-W52-5", "url": seg("9999-W52-5"), "hk": "u1", "expect": 404},
    # 400
    {"d": "not-a-date", "url": seg("not-a-date"), "hk": "u1", "expect": 400},
    {"d": "2026-5-1", "url": seg("2026-5-1"), "hk": "u1", "expect": 400},
    {"d": "2026-02-29 non-leap", "url": seg("2026-02-29"), "hk": "u1", "expect": 400},
    {"d": "2026-13-01", "url": seg("2026-13-01"), "hk": "u1", "expect": 400},
    {"d": "0000-01-01", "url": seg("0000-01-01"), "hk": "u1", "expect": 400},
    {"d": "9999-W52-6 overflow", "url": seg("9999-W52-6"), "hk": "u1", "expect": 400},
    {"d": "2015-W54", "url": seg("2015-W54"), "hk": "u1", "expect": 400},
    {"d": "inconsistent separator 2026-0501", "url": seg("2026-0501"), "hk": "u1", "expect": 400},
    {"d": "space-leading year", "url": seg(" 026-05-01"), "hk": "u1", "expect": 400},
    {"d": "fullwidth digits", "url": seg("２０２６-05-01"), "hk": "u1", "expect": 400},
    {"d": "arabic-indic digit (11 bytes)", "url": seg("2026-05-0١"), "hk": "u1", "expect": 400},
    {"d": "trailing NUL %00", "url": P + "2026-05-01%00", "hk": "u1", "expect": 400},
    {"d": "euro sign", "url": P + "%E2%82%AC", "hk": "u1", "expect": 400},
    {"d": "datetime form", "url": seg("2026-05-01T00"), "hk": "u1", "expect": 400},
    {"d": "%20 single space", "url": P + "%20", "hk": "u1", "expect": 400},
    # Encoded slash → Python route miss
    {"d": "encoded slash with auth → 404 Not Found", "url": P + "2026%2F05%2F01", "hk": "u1", "expect": 404},
    {"d": "encoded slash no auth → 404 Not Found", "url": P + "2026%2F05%2F01", "hk": "none", "expect": 404},
    {"d": "encoded slash deep a%2Fb%2Fc", "url": P + "a%2Fb%2Fc", "hk": "u1", "expect": 404},
    # Isolation
    {"d": "cross-user u2 same date → own row", "url": seg("2026-05-01"), "hk": "u2", "expect": 200},
    {"d": "u2 cannot see u1 compact row", "url": seg("20260504"), "hk": "u2", "expect": 404},
    {"d": "u1 default hides co-a-alt row", "url": seg("2026-05-05"), "hk": "u1", "expect": 404},
    {"d": "u1 owned X-Company-Id co-a-alt", "url": seg("2026-05-05"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"d": "u1 unowned X-Company-Id co-b → fallback co-a", "url": seg("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},
    {"d": "u1 nonexistent X-Company-Id → fallback", "url": seg("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-zzz"}, "expect": 200},
    {"d": "u1 empty X-Company-Id → default", "url": seg("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": ""}, "expect": 200},
    {"d": "u2 X-Company-Id co-a → fallback co-b, leak row hidden", "url": seg("2026-05-06"), "hk": "u2", "extra_hdr": {"X-Company-Id": "co-a"}, "expect": 404},
    {"d": "u1 alt company header, upper-case name", "url": seg("2026-05-05"), "hk": "u1", "extra_hdr": {"X-COMPANY-ID": "co-a-alt"}, "expect": 200},
]

INFORMATIONAL = [
    {"d": "[framework] invalid UTF-8 %FF", "url": P + "%FF", "hk": "u1"},
    {"d": "[framework] trailing slash", "url": seg("2026-05-01") + "/", "hk": "u1"},
    {"d": "[framework] segment > 100 chars", "url": seg("2" * 101), "hk": "u1"},
    {"d": "[framework] encoded slash onto late-entries", "url": P + "2026-05-01%2Flate-entries", "hk": "u1"},
]


def fuzz_segments(n: int = 400) -> list[str]:
    rnd = random.Random(7_000_014)
    out: list[str] = []
    alphabet = list("0123456789") * 3 + ["-", "-", "W", "w", " ", "+", ".", "x", "é", "١"]
    for _ in range(n // 2):
        out.append("".join(rnd.choice(alphabet) for _ in range(rnd.choice([6, 7, 7, 8, 8, 9, 10, 10, 11]))))
    for _ in range(n // 2):
        y = rnd.choice(["0000", "0001", "1999", "2015", "2020", "2024", "2026", "9999", f"{rnd.randint(0, 9999):04d}"])
        sep = rnd.choice(["-", ""])
        if rnd.random() < 0.5:
            s = f"{y}{sep}{rnd.randint(0, 14):02d}{rnd.choice([sep, '-', ''])}{rnd.randint(0, 33):02d}"
        else:
            w = f"{rnd.randint(0, 55):02d}"
            tail = rnd.choice(["", f"{sep}{rnd.randint(0, 9)}", f"{rnd.choice(['-', ''])}{rnd.randint(0, 9)}",
                               f"{rnd.randint(0, 9)}{rnd.randint(0, 99)}"])
            s = f"{y}{sep}W{w}{tail}"
        out.append(s)
    return out


async def run() -> int:
    print(f"[gate7n] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        py = start_py(); node = start_node()
        okp = wait(PY_PORT, "/api/"); okn = wait(NODE_PORT, "/health/live")
        print(f"[gate7n] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print((LOGDIR / "gate7n_py.log").read_text(errors="replace")[-3000:])
            if not okn: print((LOGDIR / "gate7n_node.log").read_text(errors="replace")[-3000:])
            return 2
        await asyncio.sleep(8)

        pdb = cli[DB]
        await pdb.command({"profile": 0})
        await pdb.drop_collection("system.profile")
        await pdb.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await pdb.command({"profile": 2})

        matrix = list(CASES)
        for s in fuzz_segments():
            matrix.append({"d": f"fuzz {json.dumps(s)}", "url": seg(s), "hk": "u1", "expect": None, "fuzz": True})

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
            body_ok = pj == nj
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
        target_reads = sum(1 for p in prof if p.get("ns") == f"{DB}.fin_day_closures")
        zero_ok = write_ops == 0 and node_snap_writes == 0 and target_reads > 0
        results.append({"case": len(matrix) + 1, "desc": "zero-write — profiler + snapshots across full live matrix",
                        "verdict": "PASS" if zero_ok else "FAIL", "node_profiled_ops": len(prof),
                        "node_op_kinds": kinds, "node_write_ops": write_ops,
                        "node_reads_on_fin_day_closures": target_reads})
        passed += zero_ok; failed += (not zero_ok)

        info = []
        for c in INFORMATIONAL:
            rp = raw_get(PY_PORT, c["url"], HDR[c["hk"]]); rn = raw_get(NODE_PORT, c["url"], HDR[c["hk"]])
            info.append({"desc": c["d"], "same": (rp[0], rp[1]) == (rn[0], rn[1]),
                         "py": [rp[0], rp[1][:160]], "node": [rn[0], rn[1][:160]]})

        print("\n" + "=" * 78)
        print("PHASE 3 · GATE 7n · LIVE PARITY MATRIX (Fin day-closure detail)")
        print("=" * 78)
        for r in results:
            if r.get("fuzz") and r["verdict"] == "PASS":
                continue
            print(f"  [{r['verdict']}] case {r['case']:>3} py={r.get('py_status', '-')} node={r.get('node_status', '-')}  {r['desc']}")
            if r["verdict"] == "FAIL" and "py_body" in r:
                print(f"      py_body  : {r['py_body']}\n      node_body: {r['node_body']}")
        fz = [r for r in results if r.get("fuzz")]
        by = {s: sum(r["py_status"] == s for r in fz) for s in (200, 400, 404)}
        print(f"  fuzz: {sum(r['verdict'] == 'PASS' for r in fz)}/{len(fz)} PASS  (py status mix {by})")
        print(f"  node profiled ops={len(prof)} kinds={kinds} write_ops={write_ops}")
        print("-" * 78)
        print(f"  cases: {len(results)} (fixed {len(CASES)} + fuzz {len(fz)} + zero-write 1)   passed: {passed}   failed: {failed}")
        print(f"  python snapshot-write cases: {py_snap_writes}   node snapshot-write cases: {node_snap_writes}")
        print("  informational (framework gate — NOT counted):")
        for x in info:
            print(f"    [{'SAME' if x['same'] else 'DIFF'}] {x['desc']}\n        py  {x['py']}\n        node {x['node']}")
        print("=" * 78)
        out = LOGDIR / "gate7n_parity_results.json"
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": passed, "failed": failed,
                                   "node_write_ops": write_ops, "results": results, "informational": info},
                                  indent=2, default=str), encoding="utf-8")
        print(f"[gate7n] results → {out}")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await cli[DB].command({"profile": 0})
        except Exception: pass
        try:
            await cli.drop_database(DB)
            print(f"[gate7n] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7n] drop failed: {e}")
        print(f"[gate7n] leftover gate7n DBs: {[d for d in await cli.list_database_names() if d.startswith('trukvia_gate7n_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
