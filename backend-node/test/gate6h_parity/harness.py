"""Phase 3 · Gate 6h · live Python↔Node parity harness for company + supplier reads.

Covers:
  * GET /api/company
  * GET /api/suppliers/{sid}

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6h_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Special parity rule:
  On /api/company MISS path (no company row for the user), the Python
  `Company().model_dump()` regenerates `id` = `co_<16 hex>` per call.
  Node port does the same. Byte parity of that ONE field is impossible
  by design. Harness compares every OTHER field byte-identical and
  asserts both stacks emit `id` matching `^co_[0-9a-f]{16}$`.
"""
from __future__ import annotations
import asyncio, json, os, re, signal, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import requests
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate6h_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8167, 8168
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"

ID_RE = re.compile(r"^co_[0-9a-f]{16}$")


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
            {"session_token": "tok-nocompany", "user_id": "u-nocompany", "effective_role": "owner",
             "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2", "user_id": "u2", "effective_role": "owner",
             "expires_at": future(3600), "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u-nocompany", "email": "nc@x", "name": "NC", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
        ],
        # Full-field company docs so the projection strips only _id + user_id.
        "companies": [
            {"id": "co-a", "user_id": "u1", "is_default": True,
             "name": "Acme Ltd", "address": "12 MG Rd", "phone": "9911",
             "email": "biz@acme.in", "gstin": "29ABCDE1234F1Z5",
             "pan": "ABCDE1234F", "state": "Karnataka", "pincode": "560001",
             "bank_name": "HDFC", "account_number": "1111", "ifsc": "HDFC0000123",
             "branch": "MG", "hsn_sac": "996791", "invoice_prefix": "INV",
             "next_invoice_number": 5, "next_invoice_number_by_fy": {"25-26": 5},
             "lr_prefix": "LR", "next_lr_number": 1, "logo": "",
             "udyam_registration": "UDYAM-KR-01-0000000",
             "signature_file_id": "", "authorised_signatory_name": "Alice",
             "authorised_signatory_designation": "Director",
             "signature_mode": "none", "jurisdiction": "Bangalore",
             "system_generated_note": "",
             "credit_note_prefix": "CN", "next_credit_note_number": 1,
             "debit_note_prefix": "DN", "next_debit_note_number": 1,
             "require_cdn_approval": False,
             "require_approval_trip": False,
             "require_approval_invoice": False,
             "require_approval_payment": False,
             "extra_field": "kept"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False,
             "name": "Acme Alt", "hsn_sac": "996791", "invoice_prefix": "INV",
             "next_invoice_number": 1},
            {"id": "co-b", "user_id": "u2", "is_default": True,
             "name": "Beta", "hsn_sac": "996791"},
        ],
        "suppliers": [
            {"id": "sup-1", "user_id": "u1", "company_id": "co-a",
             "name": "Diesel Vendor", "mobile": "9998887777",
             "contact_person": "Bob", "address": "Yard 3",
             "gstin": "29XXX", "pan": "XX", "state": "Karnataka",
             "opening_balance": 0.0, "is_active": True,
             "created_at": now, "extra_field": "kept"},
            {"id": "sup-2", "user_id": "u1", "company_id": "co-a-alt",
             "name": "Alt Vendor", "mobile": "8887776666",
             "is_active": True, "created_at": now},
            {"id": "sup-b", "user_id": "u2", "company_id": "co-b",
             "name": "U2 Vendor", "mobile": "7776665555",
             "is_active": True, "created_at": now},
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


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": MONGO, "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0",
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0",
                "PYTHONUNBUFFERED": "1"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open("/tmp/gate6h_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6h_node.log", "wb"), stderr=subprocess.STDOUT,
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


HDR = {"owner":     {"Authorization": "Bearer tok-owner"},
       "nocompany": {"Authorization": "Bearer tok-nocompany"},
       "u2":        {"Authorization": "Bearer tok-u2"},
       "expired":   {"Authorization": "Bearer tok-expired"},
       "bad":       {"Authorization": "Bearer nope"},
       "none":      {}}


CASES = [
    # Company
    {"n": 1,  "d": "existing default company (hit)",
     "url": "/api/company", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 2,  "d": "owned X-Company-Id → alt company (hit)",
     "url": "/api/company", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 3,  "d": "unowned X-Company-Id → default fallback",
     "url": "/api/company", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},
    {"n": 4,  "d": "missing company → 200 default body (id-tolerated)",
     "url": "/api/company", "hk": "nocompany", "expect": 200, "compare": "default_company"},
    {"n": 5,  "d": "/api/company no auth → 401",
     "url": "/api/company", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 6,  "d": "/api/company invalid bearer → 401",
     "url": "/api/company", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 7,  "d": "/api/company expired → 401",
     "url": "/api/company", "hk": "expired", "expect": 401, "compare": "full"},
    # Supplier
    {"n": 8,  "d": "existing supplier under default company (hit)",
     "url": "/api/suppliers/sup-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 9,  "d": "missing supplier → 404",
     "url": "/api/suppliers/does-not-exist", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 10, "d": "cross-user supplier → 404",
     "url": "/api/suppliers/sup-b", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 11, "d": "cross-company supplier → 404",
     "url": "/api/suppliers/sup-2", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 12, "d": "no X-Company-Id header → default company scope",
     "url": "/api/suppliers/sup-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 13, "d": "owned override → alt-company supplier accessible",
     "url": "/api/suppliers/sup-2", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 14, "d": "unowned override → default fallback (sup-1 under co-a)",
     "url": "/api/suppliers/sup-1", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},
    {"n": 15, "d": "/api/suppliers no auth → 401",
     "url": "/api/suppliers/sup-1", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 16, "d": "/api/suppliers invalid bearer → 401",
     "url": "/api/suppliers/sup-1", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 17, "d": "/api/suppliers expired → 401",
     "url": "/api/suppliers/sup-1", "hk": "expired", "expect": 401, "compare": "full"},
]


def compare_bodies(compare_mode: str, py, nd) -> tuple[bool, str]:
    if compare_mode == "full":
        return (py == nd, "")
    if compare_mode == "default_company":
        # Assert id shape on both stacks; compare all other fields byte-identically.
        if not isinstance(py, dict) or not isinstance(nd, dict):
            return (False, "non-dict body on default_company")
        py_id, nd_id = py.get("id"), nd.get("id")
        if not (isinstance(py_id, str) and ID_RE.match(py_id)):
            return (False, f"py id shape mismatch: {py_id!r}")
        if not (isinstance(nd_id, str) and ID_RE.match(nd_id)):
            return (False, f"node id shape mismatch: {nd_id!r}")
        py_no_id = {k: v for k, v in py.items() if k != "id"}
        nd_no_id = {k: v for k, v in nd.items() if k != "id"}
        if py_no_id != nd_no_id:
            missing_py = set(nd_no_id) - set(py_no_id)
            missing_nd = set(py_no_id) - set(nd_no_id)
            return (False, f"non-id fields diverge; py-only={missing_nd} node-only={missing_py}")
        return (True, "")
    return (False, f"unknown compare mode {compare_mode}")


async def run() -> int:
    print(f"[gate6h] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6h] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6h] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6h_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6h_node.log").read()[-2000:])
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
                "py_body": rp.text[:400] if not body_ok else "",
                "node_body": rn.text[:400] if not body_ok else "",
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
        print("PHASE 3 · GATE 6h · LIVE PARITY MATRIX (Company / Supplier reads)")
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

        out = Path("/tmp/gate6h_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6h] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6h] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6h] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
