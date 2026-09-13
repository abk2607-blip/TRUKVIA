"""TRUKVIA Phase 3 / Gate 3 — live Python ↔ Node parity harness.

Purpose-built for GET /api/supplier-payments/{pid}/corrections ONLY.
See ./README.md for scope, invariants, and how to run.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from motor.motor_asyncio import AsyncIOMotorClient

# ---- fixed configuration ------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
BACKEND_NODE_DIR = REPO_ROOT / "backend-node"
NODE_DIST_ENTRY = BACKEND_NODE_DIR / "dist" / "server.js"

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = f"trukvia_gate3_parity_{int(time.time())}"

PY_PORT = 8101
NODE_PORT = 8102
PY_BASE = f"http://127.0.0.1:{PY_PORT}"
NODE_BASE = f"http://127.0.0.1:{NODE_PORT}"

READINESS_TIMEOUT_S = 25.0
POLL_INTERVAL_S = 0.25

# ---- fixture builders ---------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


IN_FUTURE = (datetime.now(timezone.utc).replace(microsecond=0)).isoformat().replace("+00:00", "+00:00")


def _future_iso(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past_iso(seconds: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def build_fixtures() -> dict[str, list[dict[str, Any]]]:
    # sessions: 4 tokens.
    # last_refreshed_at is set to now → Python's 30 s rolling-refresh
    # throttle skips the write on the very next request (matches parity
    # note documented in src/auth.ts).
    now = now_iso()
    sessions = [
        {"session_token": "tok-parity-owner", "user_id": "u1", "effective_role": "owner",
         "expires_at": _future_iso(30), "last_refreshed_at": now},
        {"session_token": "tok-parity-viewer", "user_id": "u1", "effective_role": "viewer",
         "expires_at": _future_iso(30), "last_refreshed_at": now},
        {"session_token": "tok-parity-expired", "user_id": "u1", "effective_role": "owner",
         "expires_at": _past_iso(60), "last_refreshed_at": now},
        {"session_token": "tok-parity-tenant-b", "user_id": "u2", "effective_role": "owner",
         "expires_at": _future_iso(30), "last_refreshed_at": now},
    ]
    # Python's `get_current_user` requires a matching `users` row for the
    # session's user_id (raises 401 "User not found" otherwise). It also
    # derives `effective_role` server-side from `team_members`; the raw
    # session role is ignored for authorisation. Neither has any effect on
    # the GET corrections route (no role gate), but we seed users + skip
    # team_members so Python's own auth path completes and its response
    # body remains identical to Node's.
    users = [
        {"user_id": "u1", "email": "u1@parity.local", "name": "Parity U1",
         "picture": "", "created_at": now},
        {"user_id": "u2", "email": "u2@parity.local", "name": "Parity U2",
         "picture": "", "created_at": now},
    ]
    companies = [
        {"id": "co-a",     "user_id": "u1", "is_default": True},
        {"id": "co-a-alt", "user_id": "u1", "is_default": False},
        {"id": "co-b",     "user_id": "u2", "is_default": True},
    ]
    # Corrections deliberately inserted out-of-order to prove sort-by-index parity.
    corrections = [
        {"id": "pcr_2", "user_id": "u1", "company_id": "co-a", "payment_type": "supplier",
         "payment_id": "sp_1", "correction_index": 2, "kind": "amount_reversal_new",
         "correction_reason": "reason two padded to ten"},
        {"id": "pcr_1", "user_id": "u1", "company_id": "co-a", "payment_type": "supplier",
         "payment_id": "sp_1", "correction_index": 1, "kind": "attribute",
         "correction_reason": "reason one padded to ten"},
        {"id": "pcr_3", "user_id": "u1", "company_id": "co-a", "payment_type": "supplier",
         "payment_id": "sp_1", "correction_index": 3, "kind": "attribute",
         "correction_reason": "reason three padded ten"},
        {"id": "pcr_4", "user_id": "u1", "company_id": "co-a", "payment_type": "supplier",
         "payment_id": "sp_2", "correction_index": 1, "kind": "attribute",
         "correction_reason": "reason four padded to ten"},
        {"id": "pcr_5", "user_id": "u2", "company_id": "co-b", "payment_type": "supplier",
         "payment_id": "sp_x", "correction_index": 1, "kind": "attribute",
         "correction_reason": "crossX pad to ten chars"},
        # Vendor row on the SAME pid — must NOT appear in the supplier query.
        {"id": "pcr_6", "user_id": "u1", "company_id": "co-a", "payment_type": "vendor",
         "payment_id": "sp_1", "correction_index": 9, "kind": "attribute",
         "correction_reason": "vendor row not supplier"},
    ]
    return {"user_sessions": sessions, "users": users, "companies": companies,
            "payment_corrections": corrections}


# ---- DB helpers ---------------------------------------------------------------
async def seed(client: AsyncIOMotorClient, dbname: str, fixtures: dict[str, list[dict[str, Any]]]) -> None:
    db = client[dbname]
    await db.command({"dropDatabase": 1})
    for coll_name, rows in fixtures.items():
        if rows:
            await db[coll_name].insert_many([dict(r) for r in rows])


async def snapshot(client: AsyncIOMotorClient, dbname: str) -> dict[str, list[dict[str, Any]]]:
    db = client[dbname]
    out: dict[str, list[dict[str, Any]]] = {}
    for coll in ("user_sessions", "users", "companies", "payment_corrections"):
        docs = await db[coll].find({}, {"_id": 0}).to_list(1000)
        # canonical order for stable diffing
        for d in docs:
            for k in ("last_refreshed_at",):
                if k in d and isinstance(d[k], datetime):
                    d[k] = d[k].isoformat()
        docs.sort(key=lambda d: json.dumps(d, sort_keys=True, default=str))
        out[coll] = docs
    return out


def diff_snapshots(a: dict[str, list], b: dict[str, list]) -> dict[str, dict]:
    """Return per-collection diff. Empty dict → identical."""
    d: dict[str, dict] = {}
    for coll in a:
        aj = json.dumps(a[coll], sort_keys=True, default=str)
        bj = json.dumps(b[coll], sort_keys=True, default=str)
        if aj != bj:
            d[coll] = {"before_n": len(a[coll]), "after_n": len(b[coll])}
    return d


async def drop_db(client: AsyncIOMotorClient, dbname: str) -> None:
    await client.drop_database(dbname)


# ---- process management -------------------------------------------------------
def start_python() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["MONGO_URL"] = MONGO_URL
    env["DB_NAME"] = DB_NAME
    env["ENABLE_DEMO_TOKEN"] = "0"
    env["DEMO_TOKEN_VALUE"] = ""
    env["IS_PREVIEW_ENV"] = "0"
    # unbuffered so we can drain logs
    env["PYTHONUNBUFFERED"] = "1"
    args = [
        sys.executable, "-m", "uvicorn", "server:app",
        "--host", "127.0.0.1", "--port", str(PY_PORT),
        "--log-level", "warning", "--no-access-log",
    ]
    log = open("/tmp/gate3_py.log", "wb")
    return subprocess.Popen(args, cwd=str(BACKEND_DIR), env=env, stdout=log, stderr=subprocess.STDOUT)


def start_node() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["NODE_ENV"] = "test"
    env["NODE_LOG_LEVEL"] = "silent"
    env["NODE_PORT"] = str(NODE_PORT)
    env["NODE_HOST"] = "127.0.0.1"
    env["NODE_MONGO_URL"] = MONGO_URL
    env["NODE_DB_NAME"] = DB_NAME
    env["NODE_CORS_ORIGINS"] = ""
    env["NODE_REQUEST_ID_HEADER"] = "x-request-id"
    env["NODE_TRUST_INCOMING_REQUEST_ID"] = "false"
    args = ["node", str(NODE_DIST_ENTRY)]
    log = open("/tmp/gate3_node.log", "wb")
    return subprocess.Popen(args, cwd=str(BACKEND_NODE_DIR), env=env, stdout=log, stderr=subprocess.STDOUT)


def wait_ready(url: str, timeout: float = READINESS_TIMEOUT_S) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=1.0)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    return False


def stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


# ---- test matrix --------------------------------------------------------------
CASES: list[dict[str, Any]] = [
    {"id": 1,  "desc": "owner + sp_1 (3 corrections)",           "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-owner"}},
    {"id": 2,  "desc": "viewer + sp_1 (any auth role allowed)",  "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-viewer"}},
    {"id": 3,  "desc": "owner + sp_2 (1 correction)",            "pid": "sp_2",  "headers": {"Authorization": "Bearer tok-parity-owner"}},
    {"id": 4,  "desc": "owner + non-existent pid (200 [])",      "pid": "sp_none","headers": {"Authorization": "Bearer tok-parity-owner"}},
    {"id": 5,  "desc": "u1 querying sp_x owned by u2 (200 [])",  "pid": "sp_x",  "headers": {"Authorization": "Bearer tok-parity-owner"}},
    {"id": 6,  "desc": "sp_1 (must not leak vendor row)",        "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-owner"}},
    {"id": 7,  "desc": "no auth → 401 Not authenticated",        "pid": "sp_1",  "headers": {}},
    {"id": 8,  "desc": "bad bearer → 401 Invalid session",       "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-not-issued"}},
    {"id": 9,  "desc": "expired bearer → 401 Session expired",   "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-expired"}},
    {"id": 10, "desc": "cookie session auth",                    "pid": "sp_1",  "headers": {"Cookie": "session_token=tok-parity-owner"}},
    {"id": 11, "desc": "X-Company-Id override (owned)",          "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-owner", "X-Company-Id": "co-a"}},
    {"id": 12, "desc": "X-Company-Id override (NOT owned)",      "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-owner", "X-Company-Id": "co-b"}},
    {"id": 13, "desc": "ordering: sp_1 (correction_index ASC)",  "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-owner"}},
    {"id": 14, "desc": "projection: no _id, no user_id",         "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-owner"}},
    {"id": 15, "desc": "Content-Type parity",                    "pid": "sp_1",  "headers": {"Authorization": "Bearer tok-parity-owner"}},
]


# ---- comparison ---------------------------------------------------------------
def try_json(r: requests.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return {"_non_json_": r.text}


def parity(py: requests.Response, node: requests.Response) -> dict[str, Any]:
    py_body = try_json(py)
    nd_body = try_json(node)
    status_ok = py.status_code == node.status_code
    body_ok = json.dumps(py_body, sort_keys=True) == json.dumps(nd_body, sort_keys=True)
    py_ct = (py.headers.get("content-type") or "").split(";")[0].strip().lower()
    nd_ct = (node.headers.get("content-type") or "").split(";")[0].strip().lower()
    ct_ok = py_ct == nd_ct
    return {
        "status_python": py.status_code,
        "status_node": node.status_code,
        "status_ok": status_ok,
        "body_python": py_body,
        "body_node": nd_body,
        "body_ok": body_ok,
        "content_type_python": py_ct,
        "content_type_node": nd_ct,
        "content_type_ok": ct_ok,
        "python_reqid_present": bool(py.headers.get("x-request-id") or py.headers.get("X-Request-Id")),
        "node_reqid_present": bool(node.headers.get("x-request-id") or node.headers.get("X-Request-Id")),
    }


# ---- main orchestration -------------------------------------------------------
async def run() -> int:
    print(f"[gate3] using isolated DB: {DB_NAME}")
    fixtures = build_fixtures()
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)

    py_proc = None
    node_proc = None
    exit_code = 0
    try:
        await seed(client, DB_NAME, fixtures)
        print("[gate3] seeded fixtures")

        print("[gate3] starting Python UAT (port 8101)…")
        py_proc = start_python()
        print("[gate3] starting Node UAT (port 8102)…")
        node_proc = start_node()

        py_ready = wait_ready(f"{PY_BASE}/api/", 30.0)
        node_ready = wait_ready(f"{NODE_BASE}/health/live", 30.0)
        print(f"[gate3] python_ready={py_ready}  node_ready={node_ready}")
        if not py_ready:
            print("--- python log ---")
            print(open("/tmp/gate3_py.log").read()[-2000:])
        if not node_ready:
            print("--- node log ---")
            print(open("/tmp/gate3_node.log").read()[-2000:])
        if not (py_ready and node_ready):
            return 2

        pass_count = 0
        fail_count = 0
        results: list[dict[str, Any]] = []
        node_writes_total = 0
        python_refresh_writes_total = 0

        for case in CASES:
            path = f"/api/supplier-payments/{case['pid']}/corrections"
            hdrs = case["headers"]

            snap_before = await snapshot(client, DB_NAME)
            py = requests.get(PY_BASE + path, headers=hdrs, timeout=5.0)
            snap_after_py = await snapshot(client, DB_NAME)
            nd = requests.get(NODE_BASE + path, headers=hdrs, timeout=5.0)
            snap_after_node = await snapshot(client, DB_NAME)

            # Python may write to user_sessions.last_refreshed_at.
            py_diff_colls = diff_snapshots(snap_before, snap_after_py)
            # Node MUST NOT write to any collection.
            node_diff_colls = diff_snapshots(snap_after_py, snap_after_node)

            python_refresh = "user_sessions" in py_diff_colls
            if python_refresh:
                python_refresh_writes_total += 1
            # Only user_sessions.last_refreshed_at is allowed to drift on
            # the Python side. Any other Python-side mutation → gate failure.
            for c in py_diff_colls:
                if c != "user_sessions":
                    fail_count += 1
                    results.append({"id": case["id"], "desc": case["desc"],
                                    "verdict": "FAIL — python wrote to unexpected collection",
                                    "python_write": c})
                    continue

            case_node_writes = len(node_diff_colls)
            node_writes_total += case_node_writes

            par = parity(py, nd)
            ok = par["status_ok"] and par["body_ok"] and par["content_type_ok"] and case_node_writes == 0

            if ok:
                pass_count += 1
                verdict = "PASS"
            else:
                fail_count += 1
                verdict = "FAIL"
            results.append({
                "id": case["id"],
                "desc": case["desc"],
                "verdict": verdict,
                "node_write_collections": list(node_diff_colls.keys()),
                "python_rolling_refresh": python_refresh,
                **par,
            })

        # -------- summary -------------------------------------------------------
        print("\n============================================================")
        print("PHASE 3 · GATE 3 · LIVE PARITY MATRIX")
        print("============================================================")
        for r in results:
            print(f"  [{r['verdict']:4}]  case {r['id']:>2}  py={r['status_python']:>3}  node={r['status_node']:>3}  {r['desc']}")
        print("------------------------------------------------------------")
        print(f"  Cases:                 {len(results)}")
        print(f"  Passed:                {pass_count}")
        print(f"  Failed:                {fail_count}")
        print(f"  Node writes observed:  {node_writes_total}  (expected 0)")
        print(f"  Python rolling-refresh writes: {python_refresh_writes_total}  (allowed, informational)")
        print("============================================================")

        # Persist machine-readable evidence.
        outfile = Path("/tmp/gate3_parity_results.json")
        outfile.write_text(json.dumps({
            "db_name": DB_NAME,
            "python_port": PY_PORT,
            "node_port": NODE_PORT,
            "cases": len(results),
            "passed": pass_count,
            "failed": fail_count,
            "node_writes_total": node_writes_total,
            "python_refresh_writes_total": python_refresh_writes_total,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate3] results JSON: {outfile}")

        exit_code = 0 if (fail_count == 0 and node_writes_total == 0) else 1
        return exit_code

    finally:
        if py_proc is not None:
            stop(py_proc)
        if node_proc is not None:
            stop(node_proc)
        try:
            await drop_db(client, DB_NAME)
            print(f"[gate3] dropped isolated DB {DB_NAME}")
        except Exception as exc:
            print(f"[gate3] warn: drop DB failed: {exc}")
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
