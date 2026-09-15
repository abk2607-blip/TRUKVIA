"""Phase 3 · Gate 6f · live Python↔Node parity harness for CN/DN reads.

Covers only:
  * GET /api/credit-notes
  * GET /api/credit-notes/{nid}
  * GET /api/debit-notes
  * GET /api/debit-notes/{nid}

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6f_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant/login.

Two-phase execution:
  Phase A · ENABLE_CDN=1 — full happy/auth/detail/list matrix.
  Phase B · ENABLE_CDN=0 — flag-disabled 404 "Not Found" on all four
                          endpoints.
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
DB = f"trukvia_gate6f_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8147, 8148
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _cn(**over: Any) -> dict[str, Any]:
    base = {
        "id": "cn-x", "kind": "credit", "company_id": "co-a", "user_id": "u1",
        "note_number": "CN/25-26/0001", "note_date": "2026-02-05",
        "invoice_id": "inv-a", "invoice_number_snapshot": "INV/25-26/0001",
        "customer_id": "cust-1", "reason_code": "rate_correction",
        "reason_text": "harness parity note", "lines": [],
        "subtotal": 100.0, "gst_type": "cgst_sgst",
        "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "cgst_amount": 0.0, "sgst_amount": 0.0, "igst_amount": 0.0,
        "total_tax": 0.0, "total_amount": 100.0, "round_off": 0.0, "rcm": True,
        "apply_gst": False, "status": "issued", "is_historical": False,
        "created_at": "2026-02-05T00:00:00+00:00",
        "cancelled_at": None, "cancelled_by": None, "cancelled_reason": None,
        "created_by": "u1", "approved_by": None, "approved_at": None,
        "deadline_override": False, "share_token": None,
    }
    base.update(over)
    return base


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
            {"id": "co-a", "user_id": "u1", "is_default": True,
             "state": "Karnataka", "invoice_prefix": "INV",
             "next_invoice_number": 1},
            {"id": "co-b", "user_id": "u2", "is_default": True,
             "state": "Karnataka", "invoice_prefix": "INV",
             "next_invoice_number": 1},
        ],
        "credit_debit_notes": [
            _cn(id="c1", kind="credit", customer_id="cust-1", invoice_id="inv-a", status="issued",   note_date="2026-02-10"),
            _cn(id="c2", kind="credit", customer_id="cust-1", invoice_id="inv-b", status="issued",   note_date="2026-02-08"),
            _cn(id="c3", kind="credit", customer_id="cust-2", invoice_id="inv-c", status="draft",    note_date="2026-02-12"),
            _cn(id="c4", kind="credit", customer_id="cust-2", invoice_id="inv-a", status="cancelled",note_date="2026-02-06"),
            _cn(id="c5", kind="credit", customer_id="cust-3", invoice_id="inv-d", status="issued",   note_date="2026-02-15"),
            _cn(id="d1", kind="debit",  customer_id="cust-1", invoice_id="inv-a", status="issued",   note_date="2026-02-11"),
            _cn(id="d2", kind="debit",  customer_id="cust-2", invoice_id="inv-c", status="issued",   note_date="2026-02-09"),
            _cn(id="d3", kind="debit",  customer_id="cust-2", invoice_id="inv-c", status="draft",    note_date="2026-02-13"),
            _cn(id="cU2", kind="credit", user_id="u2", company_id="co-b",
                customer_id="cust-b", invoice_id="inv-u2", status="issued"),
            _cn(id="dU2", kind="debit",  user_id="u2", company_id="co-b",
                customer_id="cust-b", invoice_id="inv-u2", status="issued"),
        ],
    }


TRACKED = ("user_sessions", "users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures")


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


def start_py(enable_cdn: str, logfile: str):
    env = os.environ.copy()
    env.update({"MONGO_URL": MONGO, "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0",
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0",
                "ENABLE_CDN": enable_cdn, "PYTHONUNBUFFERED": "1"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open(logfile, "wb"), stderr=subprocess.STDOUT,
    )


def start_node(enable_cdn: str, logfile: str):
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent",
                "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": MONGO, "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                "NODE_REQUEST_ID_HEADER": "x-request-id",
                "NODE_TRUST_INCOMING_REQUEST_ID": "false",
                "ENABLE_CDN": enable_cdn})
    return subprocess.Popen(
        ["node", str(REPO / "backend-node/dist/server.js")],
        cwd=str(REPO / "backend-node"), env=env,
        stdout=open(logfile, "wb"), stderr=subprocess.STDOUT,
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
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


CASES_ON = [
    {"n": 1,  "d": "credit list happy path",
     "url": "/api/credit-notes", "hdr_key": "owner", "expect": 200},
    {"n": 2,  "d": "credit list · customer_id filter",
     "url": "/api/credit-notes?customer_id=cust-1", "hdr_key": "owner", "expect": 200},
    {"n": 3,  "d": "credit list · invoice_id filter",
     "url": "/api/credit-notes?invoice_id=inv-a", "hdr_key": "owner", "expect": 200},
    {"n": 4,  "d": "credit list · status filter",
     "url": "/api/credit-notes?status=draft", "hdr_key": "owner", "expect": 200},
    {"n": 5,  "d": "credit list · empty filters ignored",
     "url": "/api/credit-notes?customer_id=&status=", "hdr_key": "owner", "expect": 200},
    {"n": 6,  "d": "credit list · custom limit=2",
     "url": "/api/credit-notes?limit=2", "hdr_key": "owner", "expect": 200},
    {"n": 7,  "d": "credit list · limit>500 → 422",
     "url": "/api/credit-notes?limit=1000", "hdr_key": "owner", "expect": 422},
    {"n": 8,  "d": "credit list · non-int limit → 422",
     "url": "/api/credit-notes?limit=abc", "hdr_key": "owner", "expect": 422},
    {"n": 9,  "d": "credit list · u1 does not see u2",
     "url": "/api/credit-notes", "hdr_key": "u2", "expect": 200},
    {"n": 10, "d": "debit list happy path",
     "url": "/api/debit-notes", "hdr_key": "owner", "expect": 200},
    {"n": 11, "d": "debit list · customer_id + status",
     "url": "/api/debit-notes?customer_id=cust-2&status=issued", "hdr_key": "owner", "expect": 200},
    {"n": 12, "d": "credit detail happy path",
     "url": "/api/credit-notes/c1", "hdr_key": "owner", "expect": 200},
    {"n": 13, "d": "credit detail cross-kind quirk (debit body)",
     "url": "/api/credit-notes/d1", "hdr_key": "owner", "expect": 200},
    {"n": 14, "d": "credit detail missing → 404 'Not found'",
     "url": "/api/credit-notes/does-not-exist", "hdr_key": "owner", "expect": 404},
    {"n": 15, "d": "credit detail cross-tenant → 404",
     "url": "/api/credit-notes/cU2", "hdr_key": "owner", "expect": 404},
    {"n": 16, "d": "debit detail happy path",
     "url": "/api/debit-notes/d1", "hdr_key": "owner", "expect": 200},
    {"n": 17, "d": "debit detail rejects credit-kind → 404",
     "url": "/api/debit-notes/c1", "hdr_key": "owner", "expect": 404},
    {"n": 18, "d": "no auth → 401",
     "url": "/api/credit-notes", "hdr_key": "none", "expect": 401},
    {"n": 19, "d": "invalid bearer → 401",
     "url": "/api/debit-notes/d1", "hdr_key": "bad", "expect": 401},
    {"n": 20, "d": "expired session → 401",
     "url": "/api/credit-notes/c1", "hdr_key": "expired", "expect": 401},
]


CASES_OFF = [
    {"n": 21, "d": "flag OFF · credit list → 404 'Not Found'",
     "url": "/api/credit-notes", "hdr_key": "owner", "expect": 404},
    {"n": 22, "d": "flag OFF · credit detail → 404 'Not Found'",
     "url": "/api/credit-notes/c1", "hdr_key": "owner", "expect": 404},
    {"n": 23, "d": "flag OFF · debit list → 404 'Not Found'",
     "url": "/api/debit-notes", "hdr_key": "owner", "expect": 404},
    {"n": 24, "d": "flag OFF · debit detail → 404 'Not Found'",
     "url": "/api/debit-notes/d1", "hdr_key": "owner", "expect": 404},
]


HDR_MAP = {
    "owner":   {"Authorization": "Bearer tok-owner"},
    "u2":      {"Authorization": "Bearer tok-u2"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad":     {"Authorization": "Bearer nope"},
    "none":    {},
}


async def run_phase(cli, cases, cdn_flag: str, log_suffix: str) -> tuple[list, int]:
    py = start_py(cdn_flag, f"/tmp/gate6f_py_{log_suffix}.log")
    node = start_node(cdn_flag, f"/tmp/gate6f_node_{log_suffix}.log")
    okp = wait(f"{PY_BASE}/api/", 40)
    okn = wait(f"{NODE_BASE}/health/live", 40)
    print(f"[gate6f · flag={cdn_flag}] py={okp} node={okn}")
    try:
        if not (okp and okn):
            if not okp:
                print(open(f"/tmp/gate6f_py_{log_suffix}.log").read()[-2000:])
            if not okn:
                print(open(f"/tmp/gate6f_node_{log_suffix}.log").read()[-2000:])
            return [], -1
        results = []
        node_write_events = 0
        for c in cases:
            hdr = HDR_MAP[c["hdr_key"]]
            url = c["url"]
            _ = await snap(cli, DB)
            rp = requests.get(PY_BASE + url, headers=hdr, timeout=10)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + url, headers=hdr, timeout=10)
            after_nd = await snap(cli, DB)
            nd_diff = diff_snap(after_py, after_nd)
            if nd_diff:
                node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])
            try: pjson = rp.json()
            except Exception: pjson = rp.text
            try: njson = rn.json()
            except Exception: njson = rn.text

            # 422 body-shape divergence tolerated per Gate 6c/6d convention.
            if c["expect"] == 422:
                body_ok = True
            else:
                body_ok = (pjson == njson)

            ok = status_ok and body_ok
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:400] if not body_ok else "",
                "node_body": rn.text[:400] if not body_ok else "",
            })
        return results, node_write_events
    finally:
        stop(py)
        stop(node)


async def run() -> int:
    print(f"[gate6f] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    try:
        await seed(cli, DB)
        print("[gate6f] seeded")

        phase_a, wa = await run_phase(cli, CASES_ON, "1", "on")
        phase_b, wb = await run_phase(cli, CASES_OFF, "0", "off")
        if wa < 0 or wb < 0:
            return 2

        all_results = phase_a + phase_b
        pass_count = sum(1 for r in all_results if r["verdict"] == "PASS")
        fail_count = sum(1 for r in all_results if r["verdict"] == "FAIL")
        total_writes = wa + wb

        all_results.append({
            "case": len(all_results) + 1,
            "desc": "read-only — Node write events across BOTH phases",
            "verdict": "PASS" if total_writes == 0 else "FAIL",
            "node_write_events": total_writes,
        })
        if total_writes == 0: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 72)
        print("PHASE 3 · GATE 6f · LIVE PARITY MATRIX (Credit/Debit Notes)")
        print("=" * 72)
        for r in all_results:
            py_s = r.get("py_status", "-")
            nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
            if r["verdict"] == "FAIL":
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
        print("-" * 72)
        print(f"  cases: {len(all_results)}   passed: {pass_count}   failed: {fail_count}   node write events: {total_writes}")
        print("=" * 72)

        out = Path("/tmp/gate6f_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(all_results), "passed": pass_count,
            "failed": fail_count, "node_write_events": total_writes,
            "results": all_results,
        }, indent=2, default=str))
        print(f"[gate6f] results → {out}")
        return 0 if fail_count == 0 and total_writes == 0 else 1
    finally:
        try:
            await cli.drop_database(DB)
            print(f"[gate6f] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6f] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
