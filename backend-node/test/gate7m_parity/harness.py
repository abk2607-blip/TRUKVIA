"""Phase 3 · Gate 7m · live Python↔Node parity harness for Fin day-closures list.

Covers:
  * GET /api/fin/day-closures

Class-C stance:
  Pure-read in Python. Handler executes exactly one
    db.fin_day_closures.find(q, {_id:0, user_id:0})
      .sort("close_date", -1).to_list(int(max(1, min(limit, 5000))))
  Zero writes / audits / snapshot capture / FinTxn reads / backfill.

Parity axes: auth precedence over `limit` validation, pydantic-core 2.46.4
str→int coercion (int_parsing / int_parsing_size), handler clamp, filter
assembly, projection strips `_id` AND `user_id`, wrapper `{rows, count}`.

Zero-write proof is two-fold:
  1. per-case collection snapshots before/after the Node request;
  2. MongoDB profiler (level 2) on the disposable DB, attributed by the
     driver `appName` — every Node-originated op across the live matrix is
     enumerated and must contain no write command.
"""
from __future__ import annotations
import asyncio, json, os, random, signal, subprocess, sys, tempfile, time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
import requests
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7m_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7m-py", "trukvia-gate7m-node"
PY_PORT, NODE_PORT = 8240, 8241
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"
LOGDIR = Path(tempfile.gettempdir())
BIG_N = 5002  # > 5000 so the clamp is observable on real rows


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def closure(cid: str, uid: str, company: str, close_date: str | None, **kw: Any) -> dict[str, Any]:
    snap = {"AR": {"in": 1000.0, "out": 250.5, "net": 749.5},
            "BANK_DEFAULT": {"in": 0.0, "out": 12.25, "net": -12.25}}
    d: dict[str, Any] = {
        "id": cid, "user_id": uid, "company_id": company,
        "status": "closed", "closed_at": "2026-05-10T18:00:00.123456+00:00",
        "closed_by": uid, "close_notes": "", "snapshot": snap,
        "snapshot_source_count": 7, "reopened_at": "", "reopened_by": "",
        "reopen_reason": "",
        "history": [{"event": "closed", "at": "2026-05-10T18:00:00.123456+00:00",
                     "by": uid, "notes": "", "snapshot": snap, "snapshot_source_count": 7}],
        "created_at": "2026-05-10T18:00:00.123456+00:00", "modified_at": "",
    }
    if close_date is not None:
        d["close_date"] = close_date
    d.update(kw)
    return d


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    rows = [
        closure("fdc-1", "u1", "co-a", "2026-05-01"),
        closure("fdc-2", "u1", "co-a", "2026-05-02", status="reopened",
                reopened_at="2026-05-11T09:00:00+00:00", reopened_by="u1",
                reopen_reason="late entry — ₹ adj \"quoted\" \\ back"),
        closure("fdc-3", "u1", "co-a", "2026-05-03", close_notes="नमस्ते · తెలుగు"),
        closure("fdc-4", "u1", "co-a", "2026-05-04", snapshot={}, history=[]),
        closure("fdc-5", "u1", "co-a", "2026-04-30"),
        closure("fdc-np", "u1", "co-a", "2026-5-9"),          # non-padded, sorts lexically
        closure("fdc-nodate", "u1", "co-a", None),            # legacy: close_date missing
        closure("fdc-alt", "u1", "co-a-alt", "2026-05-05"),
        closure("fdc-u2", "u2", "co-b", "2026-05-01"),
        closure("fdc-u2-leak", "u2", "co-a", "2026-05-06"),   # u2 row carrying u1's company id
    ]
    start = date(2000, 1, 1)
    rows += [closure(f"big-{i:05d}", "u4", "co-d", (start + timedelta(days=i)).isoformat())
             for i in range(BIG_N)]
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u3",      "user_id": "u3", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u4",      "user_id": "u4", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": u, "email": f"{u}@x", "name": u.upper(), "picture": "", "created_at": now}
            for u in ("u1", "u2", "u3", "u4")
        ],
        "companies": [
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
            {"id": "co-c",     "user_id": "u3", "is_default": True,  "name": "Empty Co"},
            {"id": "co-d",     "user_id": "u4", "is_default": True,  "name": "Big Co"},
        ],
        "fin_day_closures": rows,
        "fin_txn": [
            {"id": "tx-1", "user_id": "u1", "company_id": "co-a", "status": "active",
             "txn_date": "2026-05-01", "created_at": "2026-05-12T00:00:00+00:00",
             "account_code": "AR", "direction": "in", "amount": 10.0},
        ],
    }


TRACKED = ("users", "user_sessions", "companies", "fin_day_closures", "fin_txn",
           "audit_logs", "approvals", "counters", "fin_hook_failures")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    for coll, rows in fixtures().items():
        if rows:
            await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(None)
        docs.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[c] = json.dumps(docs, sort_keys=True, default=str)
    return out


def diff_snap(a, b):
    return [c for c in a if a[c] != b[c]]


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
        stdout=open(LOGDIR / "gate7m_py.log", "wb"), stderr=subprocess.STDOUT,
    )


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
        stdout=open(LOGDIR / "gate7m_node.log", "wb"), stderr=subprocess.STDOUT,
    )


def wait(url, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(url, timeout=1).status_code < 500:
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
    "u3": {"Authorization": "Bearer tok-u3"},
    "u4": {"Authorization": "Bearer tok-u4"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad": {"Authorization": "Bearer nope"},
    "none": {},
}

P = "/api/fin/day-closures"


def q(**params: str) -> str:
    return P + "?" + "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())


def lim(v: str) -> str:
    return f"{P}?limit={quote(v, safe='')}"


CASES: list[dict[str, Any]] = [
    # Auth + precedence over query validation
    {"d": "no bearer → 401 Not authenticated", "url": P, "hk": "none", "expect": 401},
    {"d": "invalid bearer → 401 Invalid session", "url": P, "hk": "bad", "expect": 401},
    {"d": "expired bearer → 401 Session expired", "url": P, "hk": "expired", "expect": 401},
    {"d": "no bearer + limit=abc → 401 (auth precedes 422)", "url": lim("abc"), "hk": "none", "expect": 401},
    {"d": "expired + limit=abc → 401", "url": lim("abc"), "hk": "expired", "expect": 401},
    # Primary reads
    {"d": "u1 default → full wrapper, close_date DESC, missing close_date last", "url": P, "hk": "u1", "expect": 200},
    {"d": "u3 owner with no closures → {rows:[],count:0}", "url": P, "hk": "u3", "expect": 200},
    {"d": "u4 big tenant default limit 500", "url": P, "hk": "u4", "expect": 200},
    # Date range + status
    {"d": "date_from only", "url": q(date_from="2026-05-02"), "hk": "u1", "expect": 200},
    {"d": "date_to only", "url": q(date_to="2026-05-02"), "hk": "u1", "expect": 200},
    {"d": "both bounds inclusive", "url": q(date_from="2026-05-01", date_to="2026-05-03"), "hk": "u1", "expect": 200},
    {"d": "inverted range → empty", "url": q(date_from="2026-05-04", date_to="2026-05-01"), "hk": "u1", "expect": 200},
    {"d": "blank date_from/date_to/status ignored", "url": P + "?date_from=&date_to=&status=", "hk": "u1", "expect": 200},
    {"d": "non-ISO lexical bound catches non-padded row", "url": q(date_from="2026-5"), "hk": "u1", "expect": 200},
    {"d": "unicode / quote bound", "url": q(date_from="2026-05-0\"'é"), "hk": "u1", "expect": 200},
    {"d": "status=closed", "url": q(status="closed"), "hk": "u1", "expect": 200},
    {"d": "status=reopened", "url": q(status="reopened"), "hk": "u1", "expect": 200},
    {"d": "status=CLOSED case-sensitive → empty", "url": q(status="CLOSED"), "hk": "u1", "expect": 200},
    {"d": "status + range combined", "url": q(status="closed", date_to="2026-05-03"), "hk": "u1", "expect": 200},
    {"d": "unknown query key ignored", "url": q(foo="bar"), "hk": "u1", "expect": 200},
    # Repeated keys (last wins)
    {"d": "status repeated → last wins", "url": P + "?status=reopened&status=closed", "hk": "u1", "expect": 200},
    {"d": "limit repeated abc then 2 → last wins (200)", "url": P + "?limit=abc&limit=2", "hk": "u1", "expect": 200},
    {"d": "limit repeated 2 then abc → last wins (422)", "url": P + "?limit=2&limit=abc", "hk": "u1", "expect": 422},
    # Limit clamp on the big tenant (real 5002 rows)
    {"d": "u4 limit=1", "url": lim("1"), "hk": "u4", "expect": 200},
    {"d": "u4 limit=0 → clamp 1", "url": lim("0"), "hk": "u4", "expect": 200},
    {"d": "u4 limit=-5 → clamp 1", "url": lim("-5"), "hk": "u4", "expect": 200},
    {"d": "u4 limit=5000", "url": lim("5000"), "hk": "u4", "expect": 200},
    {"d": "u4 limit=5001 → clamp 5000", "url": lim("5001"), "hk": "u4", "expect": 200},
    {"d": "u4 limit=99999999999999999999 → clamp 5000", "url": lim("99999999999999999999"), "hk": "u4", "expect": 200},
    {"d": "u4 limit=-99999999999999999999 → clamp 1", "url": lim("-99999999999999999999"), "hk": "u4", "expect": 200},
    {"d": "u4 limit=1_000.0 → 1000", "url": lim("1_000.0"), "hk": "u4", "expect": 200},
    # Limit coercion (u1)
    {"d": "limit=2", "url": lim("2"), "hk": "u1", "expect": 200},
    {"d": "limit=' 2 '", "url": lim(" 2 "), "hk": "u1", "expect": 200},
    {"d": "limit raw '+2' (form-decoded to ' 2')", "url": P + "?limit=+2", "hk": "u1", "expect": 200},
    {"d": "limit=%2B2 → '+2'", "url": lim("+2"), "hk": "u1", "expect": 200},
    {"d": "limit=1.0", "url": lim("1.0"), "hk": "u1", "expect": 200},
    {"d": "limit=05", "url": lim("05"), "hk": "u1", "expect": 200},
    {"d": "limit=NBSP 2", "url": lim(" 2"), "hk": "u1", "expect": 200},
    {"d": "limit=2 U+0085", "url": lim("2"), "hk": "u1", "expect": 200},
    {"d": "limit=abc → 422 int_parsing", "url": lim("abc"), "hk": "u1", "expect": 422},
    {"d": "limit='' → 422 int_parsing", "url": P + "?limit=", "hk": "u1", "expect": 422},
    {"d": "bare ?limit (no '=') → 422 int_parsing", "url": P + "?limit", "hk": "u1", "expect": 422},
    {"d": "limit=1.5 → 422", "url": lim("1.5"), "hk": "u1", "expect": 422},
    {"d": "limit=1e3 → 422", "url": lim("1e3"), "hk": "u1", "expect": 422},
    {"d": "limit=U+FEFF 2 → 422", "url": lim("﻿2"), "hk": "u1", "expect": 422},
    {"d": "limit=Arabic-Indic digits → 422", "url": lim("١٢"), "hk": "u1", "expect": 422},
    {"d": "limit 4301 digits → 422 int_parsing_size", "url": lim("1" * 4301), "hk": "u1", "expect": 422},
    {"d": "limit '-'+4300 digits → 422 int_parsing_size", "url": lim("-" + "1" * 4300), "hk": "u1", "expect": 422},
    {"d": "limit '+'+4301 digits → 422 int_parsing", "url": lim("+" + "1" * 4301), "hk": "u1", "expect": 422},
    {"d": "limit 4300 digits → clamp 5000", "url": lim("1" * 4300), "hk": "u1", "expect": 200},
    {"d": "limit 4300 zeros + '5' → 5", "url": lim("0" * 4300 + "5"), "hk": "u1", "expect": 200},
    # Isolation
    {"d": "cross-user u2 → own co-b rows only", "url": P, "hk": "u2", "expect": 200},
    {"d": "u1 owned X-Company-Id co-a-alt", "url": P, "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"d": "u1 unowned X-Company-Id co-b → fallback co-a", "url": P, "hk": "u1", "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},
    {"d": "u1 nonexistent X-Company-Id → fallback co-a", "url": P, "hk": "u1", "extra_hdr": {"X-Company-Id": "co-zzz"}, "expect": 200},
    {"d": "u1 empty X-Company-Id → default co-a", "url": P, "hk": "u1", "extra_hdr": {"X-Company-Id": ""}, "expect": 200},
    {"d": "u2 X-Company-Id co-a (u1's company) → fallback co-b, u2 leak row hidden", "url": P, "hk": "u2", "extra_hdr": {"X-Company-Id": "co-a"}, "expect": 200},
    {"d": "u1 X-COMPANY-ID upper-case header name", "url": P, "hk": "u1", "extra_hdr": {"X-COMPANY-ID": "co-a-alt"}, "expect": 200},
]


def fuzz_limits(n: int = 300) -> list[str]:
    """Deterministic corpus around the pydantic-core int grammar."""
    rnd = random.Random(7_000_013)
    alphabet = list("0123456789") * 3 + list("+-._ eE") + ["\t", " ", "", "　", "﻿", "x"]
    out: list[str] = []
    for _ in range(n):
        out.append("".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 8))))
    for s in ("0", "-0", "+0", "00", "0.", ".", "-.0", "0_1", "1_0_0", "_", "1__1", "01.00",
              "-1_0", "+-1", "-+1", "--1", "++1", "0-5", "00-5", "-0-5", "0_.0", "1.0.0", "1.00_0"):
        out.append(s)
    return out


async def run() -> int:
    print(f"[gate7m] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print(f"[gate7m] seeded ({BIG_N + 10} closures)")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 90)
        okn = wait(f"{NODE_BASE}/health/live", 60)
        print(f"[gate7m] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print((LOGDIR / "gate7m_py.log").read_text(errors="replace")[-3000:])
            if not okn: print((LOGDIR / "gate7m_node.log").read_text(errors="replace")[-3000:])
            return 2
        await asyncio.sleep(8)  # let Python background startup migrations settle

        # Profiler — big capped collection so nothing rolls over.
        pdb = cli[DB]
        await pdb.command({"profile": 0})
        await pdb.drop_collection("system.profile")
        await pdb.create_collection("system.profile", capped=True, size=256 * 1024 * 1024)
        await pdb.command({"profile": 2})

        matrix = list(CASES)
        for s in fuzz_limits():
            matrix.append({"d": f"fuzz limit={json.dumps(s)}", "url": lim(s), "hk": "u1", "expect": None, "fuzz": True})

        results = []
        passed = failed = node_snap_writes = py_snap_writes = 0
        ctype_mismatch = 0
        for i, c in enumerate(matrix, 1):
            hdr = dict(HDR[c["hk"]]); hdr.update(c.get("extra_hdr", {}))
            s0 = await snap(cli, DB)
            rp = requests.get(PY_BASE + c["url"], headers=hdr, timeout=30)
            s1 = await snap(cli, DB)
            rn = requests.get(NODE_BASE + c["url"], headers=hdr, timeout=30)
            s2 = await snap(cli, DB)
            py_w, nd_w = diff_snap(s0, s1), diff_snap(s1, s2)
            if py_w: py_snap_writes += 1
            if nd_w: node_snap_writes += 1

            exp = c["expect"]
            status_ok = rp.status_code == rn.status_code and (exp is None or rp.status_code == exp)
            try: pj = rp.json()
            except Exception: pj = rp.text
            try: nj = rn.json()
            except Exception: nj = rn.text
            body_ok = pj == nj
            ok = status_ok and body_ok and not nd_w
            passed += ok; failed += (not ok)
            pct, nct = rp.headers.get("content-type", ""), rn.headers.get("content-type", "")
            if pct.split(";")[0] != nct.split(";")[0]: ctype_mismatch += 1
            rows = pj.get("rows") if isinstance(pj, dict) else None
            results.append({
                "case": i, "desc": c["d"], "verdict": "PASS" if ok else "FAIL", "fuzz": c.get("fuzz", False),
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok,
                "rows": len(rows) if isinstance(rows, list) else None,
                "py_ctype": pct, "node_ctype": nct,
                "py_write_colls": py_w, "node_write_colls": nd_w,
                "py_body": "" if body_ok else rp.text[:1500],
                "node_body": "" if body_ok else rn.text[:1500],
            })

        await pdb.command({"profile": 0})
        prof = await pdb["system.profile"].find(
            {"appName": NODE_APP}, {"op": 1, "ns": 1, "command": 1}).to_list(None)
        kinds: dict[str, int] = {}
        write_ops = 0
        write_names = {"insert", "update", "delete", "findAndModify", "findandmodify",
                       "bulkWrite", "create", "createIndexes", "drop", "dropIndexes", "renameCollection"}
        for p in prof:
            cmd = p.get("command") or {}
            first = next(iter(cmd), "") if isinstance(cmd, dict) else ""
            key = f"{p.get('op')}:{first}"
            kinds[key] = kinds.get(key, 0) + 1
            if p.get("op") in ("insert", "update", "remove") or first in write_names:
                write_ops += 1
        node_reads_on_target = sum(
            1 for p in prof if p.get("ns") == f"{DB}.fin_day_closures")

        zero_write_ok = write_ops == 0 and node_snap_writes == 0 and node_reads_on_target > 0
        results.append({"case": len(matrix) + 1, "desc": "zero-write — profiler + snapshots across full live matrix",
                        "verdict": "PASS" if zero_write_ok else "FAIL",
                        "node_profiled_ops": len(prof), "node_op_kinds": kinds,
                        "node_write_ops": write_ops, "node_snapshot_write_cases": node_snap_writes,
                        "node_reads_on_fin_day_closures": node_reads_on_target})
        passed += zero_write_ok; failed += (not zero_write_ok)

        n_fixed = len(CASES); n_fuzz = len(matrix) - n_fixed
        print("\n" + "=" * 78)
        print("PHASE 3 · GATE 7m · LIVE PARITY MATRIX (Fin day-closures list)")
        print("=" * 78)
        for r in results:
            if r.get("fuzz") and r["verdict"] == "PASS":
                continue
            print(f"  [{r['verdict']}] case {r['case']:>3} py={r.get('py_status', '-')} "
                  f"node={r.get('node_status', '-')} rows={r.get('rows', '-')}  {r['desc']}")
            if r["verdict"] == "FAIL" and "py_body" in r:
                print(f"      py_body  : {r['py_body']}")
                print(f"      node_body: {r['node_body']}")
                print(f"      node_writes: {r['node_write_colls']}")
        fz = [r for r in results if r.get("fuzz")]
        fz_pass = sum(r["verdict"] == "PASS" for r in fz)
        fz_422 = sum(r["py_status"] == 422 for r in fz)
        print(f"  fuzz: {fz_pass}/{len(fz)} PASS  (py 200={len(fz) - fz_422}, py 422={fz_422})")
        print(f"  node profiled ops={len(prof)} kinds={kinds} write_ops={write_ops}")
        print("-" * 78)
        print(f"  cases: {len(results)} (fixed {n_fixed} + fuzz {n_fuzz} + zero-write 1)   "
              f"passed: {passed}   failed: {failed}")
        print(f"  python snapshot-write cases: {py_snap_writes}   node snapshot-write cases: {node_snap_writes}")
        print(f"  content-type base mismatch (informational): {ctype_mismatch}")
        print("=" * 78)

        out = LOGDIR / "gate7m_parity_results.json"
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": passed, "failed": failed,
                                   "node_write_ops": write_ops, "results": results},
                                  indent=2, default=str), encoding="utf-8")
        print(f"[gate7m] results → {out}")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli[DB].command({"profile": 0})
        except Exception:
            pass
        try:
            await cli.drop_database(DB)
            print(f"[gate7m] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7m] drop failed: {e}")
        left = [d for d in await cli.list_database_names() if d.startswith("trukvia_gate7m_parity_")]
        print(f"[gate7m] leftover gate7m DBs: {left}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
