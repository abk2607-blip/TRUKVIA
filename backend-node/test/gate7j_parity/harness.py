"""Phase 3 · Gate 7j · live Python↔Node parity harness for Files-usage summary.

Covers:
  * GET /api/files/usage

STRICT UAT-DATA PRESERVATION:
  Isolated timestamped DB `trukvia_gate7j_parity_<ts>`, dropped in
  `finally`. Never touches `test_database` or any TRUKVIA UAT tenant.

Class-C stance:
  Pure-read in Python. Handler executes ONLY
    docs = db.files.find({user_id, is_deleted:False}, {_id:0, size:1, category:1}).to_list(5000)
    total, by_cat, pct, limit_bytes, file_count = deterministic aggregation
  Zero writes / audits / backfill / recompute / hooks / cross-collection reads.
  NO object-store call on this GET path.

USER-ONLY scope: no `activeCompanyId`; same-user rows across arbitrary
`company_id` values remain aggregated; cross-user rows excluded.

Aggregation semantics (verbatim Python):
  * `int(d.get("size", 0) or 0)` — missing/None/0/False/"" → 0; truncation toward zero
  * `d.get("category", "general")` — KEY-BASED default; null/"" preserved literally
  * `by_cat` insertion order preserved (Py 3.7+ dict)
  * `limit_bytes = 500 * 1024 * 1024`
  * `pct = round(min(100, total/limit*100), 2)` (limit truthy always)
"""
from __future__ import annotations
import asyncio, json, os, signal, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import requests
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7j_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8226, 8227
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"
LIMIT_BYTES = 500 * 1024 * 1024  # 524288000


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u3",      "user_id": "u3", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
            {"user_id": "u3", "email": "u3@x", "name": "U3", "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        ],
        "files": [
            # u1 · mixed company_id — MUST all be counted (user-only scope)
            {"id": "f1", "user_id": "u1", "is_deleted": False, "size": 1000, "category": "general",
             "company_id": "co-a", "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            {"id": "f2", "user_id": "u1", "is_deleted": False, "size": 2500, "category": "invoice",
             "company_id": "co-a", "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            {"id": "f3", "user_id": "u1", "is_deleted": False, "size": 800,  "category": "vehicle",
             "company_id": "co-a-alt", "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            {"id": "f4", "user_id": "u1", "is_deleted": False, "size": 200,  "category": "invoice",
             "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},  # no company_id
            # missing category — must default to "general"
            {"id": "f-nocat", "user_id": "u1", "is_deleted": False, "size": 700,
             "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            # size 0
            {"id": "f-zero", "user_id": "u1", "is_deleted": False, "size": 0, "category": "empty",
             "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            # missing size
            {"id": "f-nosize", "user_id": "u1", "is_deleted": False, "category": "nosize",
             "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            # empty-string category ("" — literal key)
            {"id": "f-emptycat", "user_id": "u1", "is_deleted": False, "size": 400, "category": "",
             "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            # excluded: is_deleted=true
            {"id": "f-del", "user_id": "u1", "is_deleted": True, "size": 9999, "category": "general",
             "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            # excluded: missing is_deleted field
            {"id": "f-nodel", "user_id": "u1", "size": 7777, "category": "general",
             "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            # excluded: cross-user u2
            {"id": "f-u2-1", "user_id": "u2", "is_deleted": False, "size": 5555, "category": "general",
             "company_id": "co-b", "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
            {"id": "f-u2-2", "user_id": "u2", "is_deleted": False, "size": 1111, "category": "invoice",
             "company_id": "co-b", "created_at": now, "storage_path": "x", "original_filename": "x", "content_type": "image/png"},
        ],
    }


TRACKED = ("users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "approval_revisions",
           "approval_audits", "counters",
           "fin_hook_failures", "vendors", "mechanics",
           "company_bank_accounts", "party_bank_accounts",
           "supplier_payments", "vendor_payments", "mechanic_payments",
           "driver_payments", "driver_payment_corrections", "templates",
           "repair_events", "mechanic_work_orders", "vendor_bills",
           "wallet_adjustments", "wallet_transfers", "wallet_recharges",
           "policy_change_events", "fuel_vehicle_maps", "files")


async def seed(cli, dbname, override_files: list[dict[str, Any]] | None = None):
    await cli.drop_database(dbname)
    fx = fixtures()
    if override_files is not None:
        fx["files"] = override_files
    for coll, rows in fx.items():
        if rows:
            await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        try:
            docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(6000)
        except Exception:
            docs = []
        for d in docs:
            for k, v in list(d.items()):
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
        docs.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[c] = docs
    return out


def diff_snap(a, b):
    d = {}
    for c in a:
        if json.dumps(a[c], sort_keys=True, default=str) != json.dumps(b[c], sort_keys=True, default=str):
            d[c] = {"before_n": len(a[c]), "after_n": len(b[c])}
    return d


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": MONGO, "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0",
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0", "PYTHONUNBUFFERED": "1"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open("/tmp/gate7j_py.log", "wb"), stderr=subprocess.STDOUT,
    )


def start_node():
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent",
                "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": MONGO, "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                "NODE_REQUEST_ID_HEADER": "x-request-id",
                "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
    return subprocess.Popen(
        ["node", str(REPO / "backend-node/dist/server.js")],
        cwd=str(REPO / "backend-node"), env=env,
        stdout=open("/tmp/gate7j_node.log", "wb"), stderr=subprocess.STDOUT,
    )


def wait(url, timeout=40):
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
    if p and hasattr(p, "poll") and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM); p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


HDR = {
    "u1":      {"Authorization": "Bearer tok-u1"},
    "u2":      {"Authorization": "Bearer tok-u2"},
    "u3":      {"Authorization": "Bearer tok-u3"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad":     {"Authorization": "Bearer nope"},
    "none":    {},
}


CASES: list[dict[str, Any]] = [
    # Auth
    {"n":  1, "d": "no bearer → 401 Not authenticated",
     "url": "/api/files/usage", "hk": "none", "expect": 401},
    {"n":  2, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/files/usage", "hk": "bad", "expect": 401},
    {"n":  3, "d": "expired bearer → 401 Session expired",
     "url": "/api/files/usage", "hk": "expired", "expect": 401},

    # Aggregation over full mixed fixture
    {"n":  4, "d": "u1 full aggregate — mixed categories, size defaults, deleted excl",
     "url": "/api/files/usage", "hk": "u1", "expect": 200},

    # USER-ONLY scope
    {"n":  5, "d": "u1 + X-Company-Id co-a-alt → MUST equal no-header aggregate",
     "url": "/api/files/usage", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"n":  6, "d": "u1 + X-Company-Id co-b (unowned) → MUST equal no-header aggregate",
     "url": "/api/files/usage", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},

    # Cross-user
    {"n":  7, "d": "cross-user u2 → own files only aggregate",
     "url": "/api/files/usage", "hk": "u2", "expect": 200},

    # Empty user
    {"n":  8, "d": "u3 (no files) → zero-usage response",
     "url": "/api/files/usage", "hk": "u3", "expect": 200},
]


async def run() -> int:
    print(f"[gate7j] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate7j] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate7j] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate7j_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate7j_node.log").read()[-2000:])
            return 2

        results = []
        pass_count = fail_count = node_write_events = 0
        for c in CASES:
            hdr = dict(HDR[c["hk"]])
            hdr.update(c.get("extra_hdr", {}))
            _ = await snap(cli, DB)
            rp = requests.get(PY_BASE + c["url"], headers=hdr, timeout=10)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + c["url"], headers=hdr, timeout=10)
            after_nd = await snap(cli, DB)
            nd_diff = diff_snap(after_py, after_nd)
            if nd_diff: node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])
            try: pjson = rp.json()
            except Exception: pjson = rp.text
            try: njson = rn.json()
            except Exception: njson = rn.text
            body_ok = (pjson == njson)
            ok = status_ok and body_ok
            if ok: pass_count += 1
            else: fail_count += 1
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:1500] if not body_ok else "",
                "node_body": rn.text[:1500] if not body_ok else "",
            })

        # Additional pct-cap parity via targeted refeed
        # (fresh seed with a single oversize file to hit 100% cap branch)
        oversize_files = [
            {"id": "big", "user_id": "u1", "is_deleted": False,
             "size": LIMIT_BYTES + 1_000_000, "category": "general",
             "created_at": now_iso(), "storage_path": "x",
             "original_filename": "x", "content_type": "image/png"},
        ]
        await seed(cli, DB, override_files=oversize_files)
        _ = await snap(cli, DB)
        rp = requests.get(PY_BASE + "/api/files/usage", headers=HDR["u1"], timeout=10)
        rn = requests.get(NODE_BASE + "/api/files/usage", headers=HDR["u1"], timeout=10)
        try: pjson = rp.json()
        except Exception: pjson = rp.text
        try: njson = rn.json()
        except Exception: njson = rn.text
        body_ok = (pjson == njson)
        ok = rp.status_code == rn.status_code == 200 and body_ok
        results.append({
            "case": 9, "desc": "pct capped at 100 (oversize file)",
            "verdict": "PASS" if ok else "FAIL",
            "py_status": rp.status_code, "node_status": rn.status_code,
            "status_ok": rp.status_code == rn.status_code == 200,
            "body_ok": body_ok, "py_body": rp.text[:1500] if not body_ok else "",
            "node_body": rn.text[:1500] if not body_ok else "",
        })
        if ok: pass_count += 1
        else: fail_count += 1

        # Half-limit for exact 50% deterministic pct
        half_files = [
            {"id": "half", "user_id": "u1", "is_deleted": False,
             "size": LIMIT_BYTES // 2, "category": "general",
             "created_at": now_iso(), "storage_path": "x",
             "original_filename": "x", "content_type": "image/png"},
        ]
        await seed(cli, DB, override_files=half_files)
        rp = requests.get(PY_BASE + "/api/files/usage", headers=HDR["u1"], timeout=10)
        rn = requests.get(NODE_BASE + "/api/files/usage", headers=HDR["u1"], timeout=10)
        try: pjson = rp.json()
        except Exception: pjson = rp.text
        try: njson = rn.json()
        except Exception: njson = rn.text
        body_ok = (pjson == njson)
        ok = rp.status_code == rn.status_code == 200 and body_ok
        results.append({
            "case": 10, "desc": "pct exact 50% (half-limit file)",
            "verdict": "PASS" if ok else "FAIL",
            "py_status": rp.status_code, "node_status": rn.status_code,
            "status_ok": rp.status_code == rn.status_code == 200,
            "body_ok": body_ok, "py_body": rp.text[:1500] if not body_ok else "",
            "node_body": rn.text[:1500] if not body_ok else "",
        })
        if ok: pass_count += 1
        else: fail_count += 1

        # 5000-cap smoke (5001 tiny files)
        bulk_files = [
            {"id": f"b{i}", "user_id": "u1", "is_deleted": False,
             "size": 1, "category": "bulk",
             "created_at": now_iso(), "storage_path": "x",
             "original_filename": "x", "content_type": "image/png"}
            for i in range(5001)
        ]
        await seed(cli, DB, override_files=bulk_files)
        rp = requests.get(PY_BASE + "/api/files/usage", headers=HDR["u1"], timeout=15)
        rn = requests.get(NODE_BASE + "/api/files/usage", headers=HDR["u1"], timeout=15)
        try: pjson = rp.json()
        except Exception: pjson = rp.text
        try: njson = rn.json()
        except Exception: njson = rn.text
        body_ok = (pjson == njson)
        ok = rp.status_code == rn.status_code == 200 and body_ok
        results.append({
            "case": 11, "desc": "5000 read cap (5001 tiny files → file_count 5000)",
            "verdict": "PASS" if ok else "FAIL",
            "py_status": rp.status_code, "node_status": rn.status_code,
            "status_ok": rp.status_code == rn.status_code == 200,
            "body_ok": body_ok, "py_body": rp.text[:1500] if not body_ok else "",
            "node_body": rn.text[:1500] if not body_ok else "",
        })
        if ok: pass_count += 1
        else: fail_count += 1

        # Zero-write aggregate (post-run tracked-collection snapshot)
        # We re-seed with the base fixture and issue read requests to verify no writes.
        await seed(cli, DB)
        before = await snap(cli, DB)
        for hk in ("u1", "u2", "u3", "expired", "bad", "none"):
            requests.get(NODE_BASE + "/api/files/usage", headers=dict(HDR[hk]), timeout=10)
        after = await snap(cli, DB)
        node_write_events_final = 1 if diff_snap(before, after) else 0
        node_write_events += node_write_events_final
        results.append({
            "case": 12,
            "desc": "read-only — Node write events across all cases",
            "verdict": "PASS" if node_write_events == 0 else "FAIL",
            "node_write_events": node_write_events,
        })
        if node_write_events == 0: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 72)
        print("PHASE 3 · GATE 7j · LIVE PARITY MATRIX (Files usage · USER-SCOPED)")
        print("=" * 72)
        for r in results:
            py_s = r.get("py_status", "-"); nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
            if r["verdict"] == "FAIL":
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
        print("-" * 72)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 72)

        out = Path("/tmp/gate7j_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate7j] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate7j] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7j] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
