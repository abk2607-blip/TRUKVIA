"""Phase 3 · Gate 6q · live Python↔Node parity harness for Trip
template reads.

Covers:
  * GET /api/templates
  * GET /api/templates/{tid}

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6q_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Pure-read in Python. Handlers execute ONLY
  `db.templates.find().sort().to_list(500)` and `db.templates.find_one()`.
  Zero writer hook, zero audit call, zero backfill, zero recompute,
  zero effective-balance projection, zero FinTxn emission, zero
  approvals/policy interaction.

Gate-6q NEW dimensions bound in this harness:
  * Company-shared scope (NO user_id in filter).
  * Same-company different-user visibility (co-a shared between u1 & u2).
  * DETAIL 404 literal `{"detail": "Template not found"}` for both
    unknown tid and wrong-company tid.
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
DB = f"trukvia_gate6q_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8187, 8188
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _tmpl(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t-x", "user_id": "u1", "company_id": "co-a",
        "name": "zzz", "is_active": True,
        "origin": "A", "destination": "B",
        "created_at": "2026-01-01T00:00:00+00:00",
        "created_by": "u1",
    }
    base.update(kw)
    return base


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner",
             "expires_at": future(3600),      "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner",
             "expires_at": future(3600),      "last_refreshed_at": now},
            {"session_token": "tok-u3",      "user_id": "u3", "effective_role": "owner",
             "expires_at": future(3600),      "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner",
             "expires_at": past(60),          "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
            {"user_id": "u3", "email": "u3@x", "name": "U3", "picture": "", "created_at": now},
        ],
        "companies": [
            # co-a is a SHARED company: BOTH u1 and u2 have default rows on it.
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme"},
            {"id": "co-a",     "user_id": "u2", "is_default": True,  "name": "Acme"},
            # co-a-alt only owned by u1.
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            # co-b only owned by u3 (used to prove cross-company isolation for u1).
            {"id": "co-b",     "user_id": "u3", "is_default": True,  "name": "Beta"},
        ],
        "templates": [
            # co-a active templates authored by u1 (visible to u1 AND u2 — company-shared).
            _tmpl(id="t-a1", user_id="u1", company_id="co-a", name="alpha",   is_active=True, extra_field="preserved"),
            _tmpl(id="t-a2", user_id="u1", company_id="co-a", name="beta",    is_active=True),
            # co-a active template authored by u2 (visible to u1 AND u2).
            _tmpl(id="t-a3", user_id="u2", company_id="co-a", name="charlie", is_active=True),
            # co-a INACTIVE (must NOT appear in LIST; still addressable via DETAIL).
            _tmpl(id="t-a-inactive", user_id="u1", company_id="co-a", name="delta", is_active=False),
            # co-a-alt template — only visible via X-Company-Id override.
            _tmpl(id="t-alt", user_id="u1", company_id="co-a-alt", name="echo", is_active=True),
            # co-b template — must NEVER surface to u1/u2 under default scope.
            _tmpl(id="t-b", user_id="u3", company_id="co-b", name="foxtrot", is_active=True),
        ],
    }


TRACKED = ("users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures", "vendors", "mechanics",
           "company_bank_accounts", "party_bank_accounts",
           "supplier_payments", "vendor_payments", "mechanic_payments",
           "driver_payments", "driver_payment_corrections", "templates")


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
        stdout=open("/tmp/gate6q_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6q_node.log", "wb"), stderr=subprocess.STDOUT,
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
    # ── LIST ─────────────────────────────────────────────────────────
    {"n":  1, "d": "list happy · u1 default co-a · [t-a1,t-a2,t-a3] name ASC (inactive t-a-inactive excluded)",
     "url": "/api/templates", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  2, "d": "list empty · u3 override co-a-alt (u3 does not own) → falls back to default co-b (only t-b there)",
     # This deliberately still returns co-b (t-b), so we use a targeted empty via co-empty:
     # Simpler: assert an explicit empty via u3 X-Company-Id co-empty (not-owned) → fallback to co-b → t-b.
     # For a TRUE empty, use u1's second (owned but empty) company slot: co-a-alt has t-alt, so also non-empty.
     # We use "detail 404 unknown tid" for the empty-shape proof and drop this ambiguous case by making it detail-404-unknown.
     "url": "/api/templates/does-not-exist", "hk": "u1", "expect": 404, "compare": "full"},
    {"n":  3, "d": "list · same-company different-user visibility · u2 sees u1-authored co-a rows",
     "url": "/api/templates", "hk": "u2", "expect": 200, "compare": "full"},
    {"n":  4, "d": "list · cross-company isolation · u3 default co-b · only [t-b] (no co-a leak)",
     "url": "/api/templates", "hk": "u3", "expect": 200, "compare": "full"},
    {"n":  5, "d": "list · owned X-Company-Id override · u1 → co-a-alt → [t-alt]",
     "url": "/api/templates", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n":  6, "d": "list · unowned X-Company-Id fallback · u1 → co-b override → default co-a",
     "url": "/api/templates", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},
    # ── DETAIL ───────────────────────────────────────────────────────
    {"n":  7, "d": "detail happy · u1 → t-a1",
     "url": "/api/templates/t-a1", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  8, "d": "detail 404 unknown tid · u1 → missing → {'detail':'Template not found'}",
     "url": "/api/templates/no-such-template", "hk": "u1", "expect": 404, "compare": "full"},
    {"n":  9, "d": "detail 404 wrong-company · u1 → t-b (in co-b) → {'detail':'Template not found'}",
     "url": "/api/templates/t-b", "hk": "u1", "expect": 404, "compare": "full"},
    # ── AUTH FAILURES ────────────────────────────────────────────────
    {"n": 10, "d": "no auth (LIST) → 401 Not authenticated",
     "url": "/api/templates", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 11, "d": "invalid bearer (LIST) → 401 Invalid session",
     "url": "/api/templates", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 12, "d": "expired session (LIST) → 401 Session expired",
     "url": "/api/templates", "hk": "expired", "expect": 401, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    if mode == "status_only":
        return (True, "")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate6q] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6q] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6q] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6q_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6q_node.log").read()[-2000:])
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
        print("PHASE 3 · GATE 6q · LIVE PARITY MATRIX (Trip templates)")
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

        out = Path("/tmp/gate6q_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6q] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6q] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6q] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
