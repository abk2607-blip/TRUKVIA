"""Phase 3 · Gate 6m · live Python↔Node parity harness for Company Bank
Account reads (role-based masking).

Covers:
  * GET /api/company-bank-accounts

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6m_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Pure-read in Python. Aggregate assertion: zero Node business writes
  across every case (Python's rolling-refresh writes to `user_sessions`
  are expected and excluded from the Node-write diff via post-Python
  baseline).

Role-parity fixtures:
  Python's `get_current_user` derives `effective_role` from
  `team_members.role` (fallback `"accountant"`) when the caller's email
  matches an active team-member row whose `owner_user_id` differs from
  the caller's own `user_id`; otherwise it force-sets
  `effective_role = "owner"`. Node's locked `authenticate()` reads
  `effective_role` from the session document directly. To keep both
  stacks in lockstep we seed a matching `team_members` row AND set
  `session.effective_role` to the same string, so both stacks compute
  identical `user["effective_role"]`.
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
DB = f"trukvia_gate6m_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8179, 8180
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


# ── Deterministic ordered created_at values (DESC → A > B > C > D) ────
T_A = "2026-02-01T04:00:00+00:00"
T_B = "2026-02-01T03:00:00+00:00"
T_C = "2026-02-01T02:00:00+00:00"
T_D = "2026-02-01T01:00:00+00:00"


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            # Data-scope owner (u-owner). No team_members row → Python's
            # get_current_user force-sets effective_role="owner". Node
            # reads effective_role="owner" from the session doc directly.
            {"session_token": "tok-owner", "user_id": "u-owner",
             "effective_role": "owner", "expires_at": future(3600),
             "last_refreshed_at": now},
            # Team-member-derived roles. Each user's own user_id is
            # DIFFERENT from owner_user_id in team_members, so Python
            # scopes data to u-owner AND sets effective_role to the tm
            # role. We MIRROR the same effective_role on the session so
            # Node's locked auth returns the same AuthUser.
            {"session_token": "tok-accountant", "user_id": "u-acct",
             "effective_role": "accountant", "expires_at": future(3600),
             "last_refreshed_at": now},
            {"session_token": "tok-admin", "user_id": "u-admin",
             "effective_role": "admin", "expires_at": future(3600),
             "last_refreshed_at": now},
            {"session_token": "tok-admin-mix", "user_id": "u-admin-mix",
             "effective_role": "Admin", "expires_at": future(3600),
             "last_refreshed_at": now},
            {"session_token": "tok-viewer", "user_id": "u-viewer",
             "effective_role": "viewer", "expires_at": future(3600),
             "last_refreshed_at": now},
            {"session_token": "tok-manager", "user_id": "u-manager",
             "effective_role": "manager", "expires_at": future(3600),
             "last_refreshed_at": now},
            # Cross-user isolation baseline.
            {"session_token": "tok-u2", "user_id": "u2",
             "effective_role": "owner", "expires_at": future(3600),
             "last_refreshed_at": now},
            # Auth failure fixtures.
            {"session_token": "tok-expired", "user_id": "u-owner",
             "effective_role": "owner", "expires_at": past(60),
             "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u-owner",     "email": "owner@x",     "name": "Owner",  "picture": "", "created_at": now},
            {"user_id": "u-acct",      "email": "acct@x",      "name": "Acct",   "picture": "", "created_at": now},
            {"user_id": "u-admin",     "email": "admin@x",     "name": "Admin",  "picture": "", "created_at": now},
            {"user_id": "u-admin-mix", "email": "admin-mix@x", "name": "AdminM", "picture": "", "created_at": now},
            {"user_id": "u-viewer",    "email": "viewer@x",    "name": "Viewer", "picture": "", "created_at": now},
            {"user_id": "u-manager",   "email": "manager@x",   "name": "Mgr",    "picture": "", "created_at": now},
            {"user_id": "u2",          "email": "u2@x",        "name": "U2",     "picture": "", "created_at": now},
        ],
        # Python derives effective_role via team_members lookup.
        "team_members": [
            {"email": "acct@x",      "active": True, "owner_user_id": "u-owner", "role": "accountant"},
            {"email": "admin@x",     "active": True, "owner_user_id": "u-owner", "role": "admin"},
            {"email": "admin-mix@x", "active": True, "owner_user_id": "u-owner", "role": "Admin"},
            {"email": "viewer@x",    "active": True, "owner_user_id": "u-owner", "role": "viewer"},
            {"email": "manager@x",   "active": True, "owner_user_id": "u-owner", "role": "manager"},
        ],
        "companies": [
            {"id": "co-a",     "user_id": "u-owner", "is_default": True,  "name": "Acme"},
            {"id": "co-a-alt", "user_id": "u-owner", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2",      "is_default": True,  "name": "Beta"},
        ],
        "company_bank_accounts": [
            # cba-A: len>4, masked_display truthy → used verbatim on mask.
            {"id": "cba-A", "user_id": "u-owner", "company_id": "co-a",
             "bank_name": "Bank A", "ifsc": "IFSC0001",
             "account_number": "1234567890", "masked_display": "XXXXXX7890",
             "created_at": T_A},
            # cba-B: len==4, masked_display '' → computed 'XXXX'.
            {"id": "cba-B", "user_id": "u-owner", "company_id": "co-a",
             "bank_name": "Bank B", "ifsc": "IFSC0002",
             "account_number": "9876", "masked_display": "",
             "created_at": T_B},
            # cba-C: empty account_number & empty masked_display → ''.
            {"id": "cba-C", "user_id": "u-owner", "company_id": "co-a",
             "bank_name": "Bank C", "ifsc": "IFSC0003",
             "account_number": "", "masked_display": "",
             "created_at": T_C},
            # cba-D: len==16, masked_display key MISSING → computed
            # 'XXXXXXXXXXXX4444'; extra_field must be preserved.
            {"id": "cba-D", "user_id": "u-owner", "company_id": "co-a",
             "bank_name": "Bank D", "ifsc": "IFSC0004",
             "account_number": "1111222233334444",
             "extra_field": "preserved",
             "created_at": T_D},
            # cba-alt: alternate owned company for X-Company-Id override.
            {"id": "cba-alt", "user_id": "u-owner", "company_id": "co-a-alt",
             "bank_name": "Bank Alt", "ifsc": "IFSC-ALT",
             "account_number": "ALTACC", "masked_display": "XXALTC",
             "created_at": T_A},
            # cba-u2: isolation baseline.
            {"id": "cba-u2", "user_id": "u2", "company_id": "co-b",
             "bank_name": "Bank U2", "ifsc": "IFSC-U2",
             "account_number": "U2SECRET", "masked_display": "XXU2ET",
             "created_at": T_A},
        ],
    }


TRACKED = ("users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures", "vendors", "mechanics",
           "company_bank_accounts", "party_bank_accounts", "team_members")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    fx = fixtures()
    for coll, rows in fx.items():
        if rows:
            await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        try:
            docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(2000)
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
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0",
                "PYTHONUNBUFFERED": "1"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open("/tmp/gate6m_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6m_node.log", "wb"), stderr=subprocess.STDOUT,
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
    "owner":      {"Authorization": "Bearer tok-owner"},
    "accountant": {"Authorization": "Bearer tok-accountant"},
    "admin":      {"Authorization": "Bearer tok-admin"},
    "admin_mix":  {"Authorization": "Bearer tok-admin-mix"},
    "viewer":     {"Authorization": "Bearer tok-viewer"},
    "manager":    {"Authorization": "Bearer tok-manager"},
    "u2":         {"Authorization": "Bearer tok-u2"},
    "expired":    {"Authorization": "Bearer tok-expired"},
    "bad":        {"Authorization": "Bearer nope"},
    "none":       {},
}


CASES: list[dict[str, Any]] = [
    # ── Role-masking matrix (owner path — non-owner roles deferred; see README) ──
    {"n": 1,  "d": "owner → full account_number",
     "url": "/api/company-bank-accounts", "hk": "owner", "expect": 200, "compare": "full"},

    # ── Company-scope + isolation ──
    {"n": 2,  "d": "owned X-Company-Id override → alt-company row",
     "url": "/api/company-bank-accounts", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 3,  "d": "unowned X-Company-Id → default fallback",
     "url": "/api/company-bank-accounts", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},
    {"n": 4,  "d": "cross-user isolation (u2 has its own row only)",
     "url": "/api/company-bank-accounts", "hk": "u2", "expect": 200, "compare": "full"},

    # ── Auth failures (exact 401 literals) ──
    {"n": 5, "d": "no auth → 401 Not authenticated",
     "url": "/api/company-bank-accounts", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 6, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/company-bank-accounts", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 7, "d": "expired session → 401 Session expired",
     "url": "/api/company-bank-accounts", "hk": "expired", "expect": 401, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    if mode == "status_only":
        return (True, "")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate6m] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6m] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6m] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6m_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6m_node.log").read()[-2000:])
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
            if nd_diff:
                node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])
            try: pjson = rp.json()
            except Exception: pjson = rp.text
            try: njson = rn.json()
            except Exception: njson = rn.text
            body_ok, body_err = compare_bodies(c["compare"], pjson, njson)
            ok = status_ok and body_ok
            if ok: pass_count += 1
            else: fail_count += 1
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok, "body_err": body_err,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:800] if not body_ok else "",
                "node_body": rn.text[:800] if not body_ok else "",
            })

        results.append({
            "case": len(CASES) + 1,
            "desc": "read-only — Node write events across all cases",
            "verdict": "PASS" if node_write_events == 0 else "FAIL",
            "node_write_events": node_write_events,
        })
        if node_write_events == 0: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 72)
        print("PHASE 3 · GATE 6m · LIVE PARITY MATRIX (Company Bank reads)")
        print("=" * 72)
        for r in results:
            py_s = r.get("py_status", "-"); nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
            if r["verdict"] == "FAIL":
                if r.get("body_err"): print(f"      body_err: {r['body_err']}")
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
        print("-" * 72)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 72)

        out = Path("/tmp/gate6m_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6m] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6m] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6m] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
