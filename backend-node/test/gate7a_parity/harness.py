"""Phase 3 · Gate 7a · live Python↔Node parity harness for
WalletAdjustments list reads.

Covers:
  * GET /api/wallet-adjustments

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate7a_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Pure-read in Python. Handler executes ONLY
  `db.wallet_adjustments.find(q, {_id:0, user_id:0}).sort("date", -1).to_list(5000)`.
  Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
  policy / counters / idempotency / cross-collection reads on the GET
  path.

Gate-7a NEW parity axis:
  * Query-string parsing.
  * Pydantic v2 bool coercion for `include_deleted` (True set:
    true/True/TRUE/1/yes/Yes/YES/on/On/ON — False set: false/False/
    FALSE/0/no/No/NO/off/Off/OFF — invalid: '' / FOO / other → 422
    with EXACT Pydantic v2 bool_parsing envelope).
  * `wallet_code` truthy → exact string equality.
  * `date_from` / `date_to` truthy → lexicographic `$gte` / `$lte`.
  * Empty query values omitted per Python truthy semantics.
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
DB = f"trukvia_gate7a_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8208, 8209
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


D1, D2, D3, D4 = "2026-05-04", "2026-05-03", "2026-05-02", "2026-05-01"


def _wa(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "wa-x", "user_id": "u1", "company_id": "co-a",
        "wallet_code": "FUEL", "direction": "debit", "amount": 500.0,
        "date": D1, "reason": "top-up", "reference": "RN-1",
        "reverses_id": "", "created_by": "u1",
        "created_at": "2026-05-04T00:00:00+00:00",
        "is_deleted": False,
    }
    base.update(kw)
    return base


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta"},
        ],
        "wallet_adjustments": [
            _wa(id="a1", wallet_code="FUEL", date=D1),
            _wa(id="a2", wallet_code="TOLL", date=D2),
            _wa(id="a3", wallet_code="FUEL", date=D3),
            _wa(id="a4", wallet_code="FUEL", date=D4),
            _wa(id="a-del", wallet_code="FUEL", date=D1, is_deleted=True),
            _wa(id="a-alt", wallet_code="FUEL", company_id="co-a-alt", date=D1),
            _wa(id="a-u2",  wallet_code="FUEL", user_id="u2", company_id="co-b", date=D1),
        ],
    }


TRACKED = ("users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures", "vendors", "mechanics",
           "company_bank_accounts", "party_bank_accounts",
           "supplier_payments", "vendor_payments", "mechanic_payments",
           "driver_payments", "driver_payment_corrections", "templates",
           "repair_events", "mechanic_work_orders", "vendor_bills",
           "wallet_adjustments", "wallet_transfers", "wallet_recharges")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    for coll, rows in fixtures().items():
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
        stdout=open("/tmp/gate7a_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate7a_node.log", "wb"), stderr=subprocess.STDOUT,
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
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad":     {"Authorization": "Bearer nope"},
    "none":    {},
}


CASES: list[dict[str, Any]] = [
    # ── default & include_deleted axis ─────────────────────────────
    {"n":  1, "d": "default · u1 · co-a · four active rows DESC",
     "url": "/api/wallet-adjustments", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  2, "d": "include_deleted=true · deleted included",
     "url": "/api/wallet-adjustments?include_deleted=true", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  3, "d": "include_deleted=false · deleted excluded",
     "url": "/api/wallet-adjustments?include_deleted=false", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  4, "d": "include_deleted=TRUE (uppercase) · deleted included",
     "url": "/api/wallet-adjustments?include_deleted=TRUE", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  5, "d": "include_deleted=1 · deleted included",
     "url": "/api/wallet-adjustments?include_deleted=1", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  6, "d": "include_deleted=yes · deleted included",
     "url": "/api/wallet-adjustments?include_deleted=yes", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  7, "d": "include_deleted=off · deleted excluded",
     "url": "/api/wallet-adjustments?include_deleted=off", "hk": "u1", "expect": 200, "compare": "full"},
    # ── invalid bool → 422 (exact Pydantic envelope) ───────────────
    {"n":  8, "d": "include_deleted='' → 422 bool_parsing envelope",
     "url": "/api/wallet-adjustments?include_deleted=", "hk": "u1", "expect": 422, "compare": "full"},
    {"n":  9, "d": "include_deleted=FOO → 422 bool_parsing envelope",
     "url": "/api/wallet-adjustments?include_deleted=FOO", "hk": "u1", "expect": 422, "compare": "full"},
    # ── wallet_code filter ─────────────────────────────────────────
    {"n": 10, "d": "wallet_code=FUEL · only FUEL rows",
     "url": "/api/wallet-adjustments?wallet_code=FUEL", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 11, "d": "wallet_code='' (blank) · omitted → all codes",
     "url": "/api/wallet-adjustments?wallet_code=", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 12, "d": "wallet_code=DOES_NOT_EXIST · 200 []",
     "url": "/api/wallet-adjustments?wallet_code=DOES_NOT_EXIST", "hk": "u1", "expect": 200, "compare": "full"},
    # ── date range ─────────────────────────────────────────────────
    {"n": 13, "d": "date_from only · rows >= 2026-05-03",
     "url": "/api/wallet-adjustments?date_from=2026-05-03", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 14, "d": "date_to only · rows <= 2026-05-02",
     "url": "/api/wallet-adjustments?date_to=2026-05-02", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 15, "d": "both bounds · inclusive lexicographic range",
     "url": "/api/wallet-adjustments?date_from=2026-05-02&date_to=2026-05-03", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 16, "d": "blank date bounds · both omitted",
     "url": "/api/wallet-adjustments?date_from=&date_to=", "hk": "u1", "expect": 200, "compare": "full"},
    # ── auth (auth precedes query 422) ─────────────────────────────
    {"n": 17, "d": "no auth → 401 Not authenticated (precedes bool 422)",
     "url": "/api/wallet-adjustments?include_deleted=FOO", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 18, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/wallet-adjustments", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 19, "d": "expired bearer → 401 Session expired",
     "url": "/api/wallet-adjustments", "hk": "expired", "expect": 401, "compare": "full"},
    # ── X-Company-Id semantics ─────────────────────────────────────
    {"n": 20, "d": "owned X-Company-Id · co-a-alt → [a-alt]",
     "url": "/api/wallet-adjustments", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 21, "d": "unowned X-Company-Id · co-b for u1 → fallback co-a",
     "url": "/api/wallet-adjustments", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},
    {"n": 22, "d": "cross-user · u2 · own rows only",
     "url": "/api/wallet-adjustments", "hk": "u2", "expect": 200, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    if mode == "status_only":
        return (True, "")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate7a] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate7a] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate7a] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate7a_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate7a_node.log").read()[-2000:])
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
                "py_body": rp.text[:1200] if not body_ok else "",
                "node_body": rn.text[:1200] if not body_ok else "",
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
        print("PHASE 3 · GATE 7a · LIVE PARITY MATRIX (WalletAdjustments list)")
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

        out = Path("/tmp/gate7a_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate7a] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate7a] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7a] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
