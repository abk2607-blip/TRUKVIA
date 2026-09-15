"""Phase 3 · Gate 5 · live Python↔Node parity harness for POST /api/expenditure-types.

Path B.3-α — Bucket-B idempotency middleware is NOT wired for this endpoint;
natural (user_id, company_id, name-after-strip) dedup provides the required
idempotent semantics. Idempotency-Key headers must be a no-op on this route.
"""
from __future__ import annotations
import asyncio, json, os, signal, subprocess, sys, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import requests
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate5_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8103, 8104
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
            {"session_token": "tok-u2", "user_id": "u2", "effective_role": "owner",
             "expires_at": future(3600), "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a", "user_id": "u1", "is_default": True},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False},
            {"id": "co-b", "user_id": "u2", "is_default": True},
        ],
    }


TRACKED = ("user_sessions", "users", "companies",
           "expenditure_types",
           "audit_logs", "fin_txn", "payment_corrections",
           "saved_trip_filters", "idempotency_keys")


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
    log = open("/tmp/gate5_py.log", "wb")
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
    log = open("/tmp/gate5_node.log", "wb")
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


ID_RX = re.compile(r"etype_[a-f0-9]{16}")
TS_RX = re.compile(r'\"created_at\"\s*:\s*\"[^\"]+\"')


def norm(body):
    """Normalise server-generated id / created_at for canonical comparison."""
    s = json.dumps(body, sort_keys=True) if not isinstance(body, str) else body
    s = ID_RX.sub("<ID>", s)
    s = TS_RX.sub('"created_at":"<TS>"', s)
    return s


CASES = [
    {"n": 1, "d": "happy: valid",                        "body": {"name": "Parking"},                                             "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 2, "d": "trim: '  Toll  '",                    "body": {"name": "  Toll  "},                                            "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 3, "d": "missing name → 422",                  "body": {},                                                              "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 4, "d": "empty string → 400",                  "body": {"name": ""},                                                    "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 5, "d": "whitespace only → 400",               "body": {"name": "   "},                                                 "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 6, "d": "client-supplied server fields",       "body": {"name": "X", "id": "HACK-id-x1", "user_id": "HACK",
                                                                  "company_id": "HACK", "is_default": True,
                                                                  "created_at": "1970-01-01T00:00:00Z", "_id": "HACK"},          "hdr": {"Authorization": "Bearer tok-owner"}},
    {"n": 11, "d": "no auth",                            "body": {"name": "E"},                                                   "hdr": {}},
    {"n": 12, "d": "bad token",                          "body": {"name": "E"},                                                   "hdr": {"Authorization": "Bearer nope"}},
    {"n": 13, "d": "expired",                            "body": {"name": "E"},                                                   "hdr": {"Authorization": "Bearer tok-expired"}},
    {"n": 14, "d": "cookie auth",                        "body": {"name": "cookie"},                                              "hdr": {"Cookie": "session_token=tok-owner"}},
    {"n": 15, "d": "X-Company-Id owned",                 "body": {"name": "owned-alt"},                                           "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-alt"}},
    {"n": 16, "d": "X-Company-Id NOT owned → fallback",  "body": {"name": "fallback"},                                            "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-b"}},
]


async def count_target(cli, dbname):
    return await cli[dbname]["expenditure_types"].count_documents({})


async def run() -> int:
    print(f"[gate5] DB={DB}")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB); print("[gate5] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40); okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate5] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate5_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate5_node.log").read()[-2000:])
            return 2

        # Case 17 — Fresh-tenant no-default-seeding guard.
        # Precondition: fixtures did NOT seed any expenditure_types row.
        assert await count_target(cli, DB) == 0, "harness bug: expenditure_types not empty at start"

        results = []
        node_forbidden_writes = 0
        pass_count = fail_count = 0

        for c in CASES:
            path = "/api/expenditure-types"
            body = c["body"]; hdr = c["hdr"]
            before = await snap(cli, DB)
            rp = requests.post(PY_BASE + path, json=body, headers=hdr, timeout=5)
            after_py = await snap(cli, DB)
            rn = requests.post(NODE_BASE + path, json=body, headers=hdr, timeout=5)
            after_nd = await snap(cli, DB)

            py_diff = diff(before, after_py)
            nd_diff = diff(after_py, after_nd)
            for col in nd_diff:
                if col in ("audit_logs", "fin_txn", "payment_corrections",
                           "saved_trip_filters", "user_sessions",
                           "companies", "users", "idempotency_keys"):
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

        # Case 17 — verify NO default-seeding happened as a side effect of POSTs.
        # Successful named POSTs during the matrix (natural dedup collapses the
        # py-side and nd-side requests onto ONE row per unique (uid,cid,name)):
        #   1 Parking, 2 Toll (trim), 6 X, 14 cookie, 15 owned-alt (co-a-alt), 16 fallback
        #   → 6 unique rows. Seeding path (DEFAULT_EXPENDITURE_TYPES) would
        #   produce ≥ 20 extra rows named from that list.
        DEFAULTS = {
            "Driver Food", "Parking", "Toll", "Loading Charges", "Unloading Charges",
            "Weighment", "Labour", "Detention", "Cleaning",
            "Insurance", "Road Tax", "Permit", "Fitness", "Tyres",
            "Engine Oil", "AdBlue", "Repair", "Spare Parts", "Office / General",
            "Others",
        }
        total_rows = await count_target(cli, DB)
        rows = await cli[DB]["expenditure_types"].find({}, {"_id": 0}).to_list(500)
        # A default-seed row = is_default=True AND name is in the frozen
        # DEFAULT_EXPENDITURE_TYPES list. Case 6 posts is_default=True with the
        # explicit non-default name "X", so it is not a leak. Case 1 posts
        # "Parking" (which IS in DEFAULTS) but with is_default=False, so it is
        # also not a leak.
        seeded_leak = any(
            r.get("is_default") is True and r.get("name") in DEFAULTS
            for r in rows
        )
        no_seed_ok = (total_rows == 6) and (not seeded_leak)
        results.append({"case": 17, "desc": "fresh tenant no default seeding on POST",
                        "verdict": "PASS" if no_seed_ok else "FAIL",
                        "total_rows_seen": total_rows, "seeded_leak": seeded_leak,
                        "expected_total_rows": 6})
        if no_seed_ok: pass_count += 1
        else: fail_count += 1

        # Case 18 — Forbidden-write observation summary.
        results.append({"case": 18, "desc": "forbidden-write observation",
                        "verdict": "PASS" if node_forbidden_writes == 0 else "FAIL",
                        "node_forbidden_writes": node_forbidden_writes})
        if node_forbidden_writes == 0: pass_count += 1
        else: fail_count += 1

        # Case 8 + 9 · natural duplicate returns same row + no second insert.
        # Fresh isolated names to keep this case decoupled from the earlier matrix.
        before = await snap(cli, DB)
        d1 = requests.post(PY_BASE + "/api/expenditure-types", json={"name": "DupPy"},
                           headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        d2 = requests.post(PY_BASE + "/api/expenditure-types", json={"name": "DupPy"},
                           headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        n1 = requests.post(NODE_BASE + "/api/expenditure-types", json={"name": "DupNd"},
                           headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        n2 = requests.post(NODE_BASE + "/api/expenditure-types", json={"name": "DupNd"},
                           headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        py_dup_ok = (d1.status_code == 200 and d2.status_code == 200 and d1.text == d2.text)
        nd_dup_ok = (n1.status_code == 200 and n2.status_code == 200 and n1.text == n2.text)
        py_count_ok = await cli[DB]["expenditure_types"].count_documents({"name": "DupPy"}) == 1
        nd_count_ok = await cli[DB]["expenditure_types"].count_documents({"name": "DupNd"}) == 1
        dup_ok = py_dup_ok and nd_dup_ok and py_count_ok and nd_count_ok
        results.append({"case": 8, "desc": "natural duplicate returns same row (py + node)",
                        "verdict": "PASS" if (py_dup_ok and nd_dup_ok) else "FAIL",
                        "py_body1": d1.text[:200], "py_body2": d2.text[:200],
                        "node_body1": n1.text[:200], "node_body2": n2.text[:200]})
        results.append({"case": 9, "desc": "natural duplicate does NOT insert a second row (py + node)",
                        "verdict": "PASS" if (py_count_ok and nd_count_ok) else "FAIL",
                        "py_count_DupPy": await cli[DB]["expenditure_types"].count_documents({"name": "DupPy"}),
                        "node_count_DupNd": await cli[DB]["expenditure_types"].count_documents({"name": "DupNd"})})
        if dup_ok: pass_count += 2
        else: fail_count += (0 if (py_dup_ok and nd_dup_ok) else 1) + (0 if (py_count_ok and nd_count_ok) else 1); pass_count += (1 if (py_dup_ok and nd_dup_ok) else 0) + (1 if (py_count_ok and nd_count_ok) else 0)

        # Case 10 · cross-tenant same-name does not collide.
        c1 = requests.post(PY_BASE + "/api/expenditure-types", json={"name": "SameAcross"},
                           headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        c2 = requests.post(PY_BASE + "/api/expenditure-types", json={"name": "SameAcross"},
                           headers={"Authorization": "Bearer tok-u2"}, timeout=5)
        both_ok = (c1.status_code == 200 and c2.status_code == 200)
        # Both stacks should have distinct rows for co-a and co-b, but here we test only Python
        # (cross-tenant behaviour is identical in both — Node parity covered by cases 15+16
        # and the write-observation snapshot).
        cross_rows = await cli[DB]["expenditure_types"].find(
            {"name": "SameAcross"}, {"_id": 0}
        ).to_list(10)
        cross_ok = both_ok and len(cross_rows) == 2 and {r["company_id"] for r in cross_rows} == {"co-a", "co-b"}
        results.append({"case": 10, "desc": "cross-tenant same-name does not collide",
                        "verdict": "PASS" if cross_ok else "FAIL",
                        "rows": [{"company_id": r["company_id"], "user_id": r.get("user_id")} for r in cross_rows]})
        if cross_ok: pass_count += 1
        else: fail_count += 1

        # Case 19 · Natural-dedup replay — body byte-identity after normalization.
        # Node-only: prove the second POST returns the same normalized body.
        rr1 = requests.post(NODE_BASE + "/api/expenditure-types", json={"name": "ReplayNd"},
                            headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        rr2 = requests.post(NODE_BASE + "/api/expenditure-types", json={"name": "ReplayNd"},
                            headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        replay_ok = (rr1.status_code == 200 and rr2.status_code == 200
                     and norm(rr1.text) == norm(rr2.text) and rr1.text == rr2.text)
        results.append({"case": 19, "desc": "natural-dedup replay body identity (node)",
                        "verdict": "PASS" if replay_ok else "FAIL",
                        "first": rr1.text[:200], "second": rr2.text[:200]})
        if replay_ok: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 66)
        print("PHASE 3 · GATE 5 · LIVE PARITY MATRIX (Path B.3-α, no idempotency)")
        print("=" * 66)
        for r in results:
            py_s = r.get("py_status", "-")
            nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
        print("-" * 66)
        print(f"  cases:                        {len(results)}")
        print(f"  passed:                       {pass_count}")
        print(f"  failed:                       {fail_count}")
        print(f"  node forbidden-coll writes:   {node_forbidden_writes} (expected 0)")
        print("=" * 66)

        out = Path("/tmp/gate5_parity_results.json")
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": pass_count,
                                   "failed": fail_count, "node_forbidden_writes": node_forbidden_writes,
                                   "results": results}, indent=2, default=str))
        print(f"[gate5] results → {out}")
        return 0 if fail_count == 0 and node_forbidden_writes == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB); print(f"[gate5] dropped {DB}")
        except Exception as e: print(f"[gate5] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
