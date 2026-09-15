"""Phase 3 · Gate 4 · live Python↔Node parity harness for POST /api/saved-trip-filters."""
from __future__ import annotations
import asyncio, json, os, signal, subprocess, sys, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import requests
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate4_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8101, 8102
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-owner", "user_id": "u1", "effective_role": "owner",
             "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner",
             "expires_at": past(60), "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a", "user_id": "u1", "is_default": True},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False},
            {"id": "co-b", "user_id": "u2", "is_default": True},
        ],
    }


TRACKED = ("user_sessions", "users", "companies", "saved_trip_filters",
           "audit_logs", "fin_txn", "payment_corrections", "idempotency_keys")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    fx = fixtures()
    for coll, rows in fx.items():
        if rows: await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(2000)
        for d in docs:
            for k, v in list(d.items()):
                if isinstance(v, datetime): d[k] = v.isoformat()
        docs.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[c] = docs
    return out


def diff(a, b):
    d = {}
    for c in a:
        if json.dumps(a[c], sort_keys=True, default=str) != json.dumps(b[c], sort_keys=True, default=str):
            d[c] = {"before_n": len(a[c]), "after_n": len(b[c])}
    return d


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": MONGO, "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0",
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0", "PYTHONUNBUFFERED": "1"})
    log = open("/tmp/gate4_py.log", "wb")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def start_node():
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent",
                "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": MONGO, "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
    log = open("/tmp/gate4_node.log", "wb")
    return subprocess.Popen(
        ["node", str(REPO / "backend-node/dist/server.js")],
        cwd=str(REPO / "backend-node"), env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def wait(url, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(url, timeout=1).status_code < 500: return True
        except Exception: pass
        time.sleep(0.25)
    return False


def stop(p):
    if p and p.poll() is None:
        p.send_signal(signal.SIGTERM)
        try: p.wait(timeout=5)
        except Exception: p.kill()


ID_RX = re.compile(r"sf[a-f0-9]{16}")
TS_RX = re.compile(r'\"created_at\"\s*:\s*\"[^\"]+\"')


def norm(body):
    """Normalise server-generated id / created_at for canonical comparison."""
    s = json.dumps(body, sort_keys=True) if not isinstance(body, str) else body
    s = ID_RX.sub("<ID>", s)
    s = TS_RX.sub('"created_at":"<TS>"', s)
    return s


CASES = [
    {"n": 1, "d": "happy: valid body", "body": {"name": "A", "filter_state": {"k": 1}}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 2, "d": "trim: '  spaced  '", "body": {"name": "  spaced  "}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 3, "d": "truncate: 65 chars → 422", "body": {"name": "x" * 65}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 4, "d": "missing name → 422", "body": {}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 5, "d": "whitespace name → 400", "body": {"name": "   "}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 6, "d": "no filter_state → {}", "body": {"name": "B"}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 7, "d": "deep filter_state", "body": {"name": "C", "filter_state": {"a": {"b": [1, 2, {"c": None}]}}}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 8, "d": "client-supplied server fields ignored", "body": {"name": "D", "id": "HACK", "user_id": "HACK", "_id": "HACK"}, "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 9, "d": "no auth", "body": {"name": "E"}, "hdr": {}},
    {"n": 10, "d": "bad token", "body": {"name": "E"}, "hdr": {"Authorization": "Bearer nope"}},
    {"n": 11, "d": "expired", "body": {"name": "E"}, "hdr": {"Authorization": "Bearer tok-expired"}},
    {"n": 12, "d": "cookie auth", "body": {"name": "F"}, "hdr": {"Cookie": "session_token=tok-owner"}},
    {"n": 13, "d": "X-Company-Id owned", "body": {"name": "G"}, "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-alt"}},
    {"n": 14, "d": "X-Company-Id NOT owned → fallback", "body": {"name": "H"}, "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-b"}},
]


async def run() -> int:
    print(f"[gate4] DB={DB}")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB); print("[gate4] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40); okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate4] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate4_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate4_node.log").read()[-2000:])
            return 2

        results = []
        node_forbidden_writes = 0
        pass_count = fail_count = 0

        for c in CASES:
            path = "/api/saved-trip-filters"
            body = c["body"]; hdr = c["hdr"]
            before = await snap(cli, DB)
            rp = requests.post(PY_BASE + path, json=body, headers=hdr, timeout=5)
            after_py = await snap(cli, DB)
            rn = requests.post(NODE_BASE + path, json=body, headers=hdr, timeout=5)
            after_nd = await snap(cli, DB)

            py_diff = diff(before, after_py)
            nd_diff = diff(after_py, after_nd)
            for col in nd_diff:
                if col in ("audit_logs", "fin_txn", "payment_corrections", "user_sessions", "companies", "users"):
                    node_forbidden_writes += 1

            ok = (rp.status_code == rn.status_code) and (
                rp.status_code == 422  # FastAPI vs Zod 422 detail-array shapes intentionally differ
                or norm(rp.text) == norm(rn.text)
            )
            verdict = "PASS" if ok else "FAIL"
            if ok: pass_count += 1
            else: fail_count += 1
            results.append({"case": c["n"], "desc": c["d"], "verdict": verdict,
                            "py_status": rp.status_code, "node_status": rn.status_code,
                            "py_body": rp.text[:500], "node_body": rn.text[:500],
                            "py_write_colls": list(py_diff.keys()),
                            "node_write_colls": list(nd_diff.keys())})

        # Idempotency: same key → replay
        key = "gate4-idem-k-01"
        before = await snap(cli, DB)
        r1 = requests.post(NODE_BASE + "/api/saved-trip-filters", json={"name": "idem"},
                           headers={"Authorization": "Bearer tok-owner", "Idempotency-Key": key}, timeout=5)
        mid = await snap(cli, DB)
        r2 = requests.post(NODE_BASE + "/api/saved-trip-filters", json={"name": "idem"},
                           headers={"Authorization": "Bearer tok-owner", "Idempotency-Key": key}, timeout=5)
        after = await snap(cli, DB)
        replay_hdr = r2.headers.get("x-idempotent-replay") == "1"
        first_stf_delta = len(mid["saved_trip_filters"]) - len(before["saved_trip_filters"])
        replay_stf_delta = len(after["saved_trip_filters"]) - len(mid["saved_trip_filters"])
        idem_ok = (r1.status_code == 200 and r2.status_code == 200
                   and first_stf_delta == 1 and replay_stf_delta == 0
                   and replay_hdr and r1.text == r2.text)
        results.append({"case": 15, "desc": "idempotency replay",
                        "verdict": "PASS" if idem_ok else "FAIL",
                        "py_status": 200, "node_status": r2.status_code,
                        "first_delta": first_stf_delta, "replay_delta": replay_stf_delta,
                        "replay_hdr": replay_hdr})
        if idem_ok: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 62)
        print("PHASE 3 · GATE 4 · LIVE PARITY MATRIX")
        print("=" * 62)
        for r in results:
            print(f"  [{r['verdict']}] case {r['case']:>2} py={r.get('py_status'):>3} node={r.get('node_status'):>3}  {r['desc']}")
        print("-" * 62)
        print(f"  cases:                        {len(results)}")
        print(f"  passed:                       {pass_count}")
        print(f"  failed:                       {fail_count}")
        print(f"  node forbidden-coll writes:   {node_forbidden_writes} (expected 0)")
        print("=" * 62)

        out = Path("/tmp/gate4_parity_results.json")
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": pass_count,
                                   "failed": fail_count, "node_forbidden_writes": node_forbidden_writes,
                                   "results": results}, indent=2, default=str))
        print(f"[gate4] results → {out}")
        return 0 if fail_count == 0 and node_forbidden_writes == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB); print(f"[gate4] dropped {DB}")
        except Exception as e: print(f"[gate4] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
