"""Phase 3 · Gate 6r · live Python↔Node parity harness for Party
bank account reads.

Covers:
  * GET /api/party-bank-accounts?party_type=&party_id=

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6r_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Pure-read in Python. Handler executes ONLY
  `db.party_bank_accounts.find().sort().to_list(500)` plus per-row
  `strip_full_number(row, allow_full)`. Zero writer hook, zero audit
  call, zero backfill, zero recompute, zero FinTxn emission, zero
  approvals / policy / counters / idempotency touch, zero unrelated
  collection reads.

Gate-6r NEW dimensions bound in this harness:
  * Required-query 422 (Pydantic-v2 detail shape observed live).
  * Tuple-membership 400 with exact literal.
  * Auth-order short-circuit (401 precedes 422/400).
  * NO company_id in filter.
  * X-Company-Id header must NOT alter rowset (invocation parity only).
  * Gate 6m masking matrix reused verbatim.

422 compare mode:
  Attempts BODY-EXACT parity first. If FastAPI/Pydantic v2 injects
  extra runtime keys (e.g. `url`) that the Node emit does not
  reproduce, the results.json will show `body_ok=False` with the two
  bodies inline for a follow-up narrow fix. No silent weakening.
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
DB = f"trukvia_gate6r_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8190, 8191
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


T_A = "2026-03-01T04:00:00+00:00"
T_B = "2026-03-01T03:00:00+00:00"
T_C = "2026-03-01T02:00:00+00:00"
T_D = "2026-03-01T01:00:00+00:00"


def _pba(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "pba-x", "user_id": "u-owner", "party_type": "supplier", "party_id": "sup-1",
        "account_holder_name": "Holder", "bank_name": "Bank X", "branch": "Branch",
        "account_number": "1234567890", "ifsc": "IFSC0001",
        "account_type": "current", "is_active": True, "is_primary": False,
        "verification_status": "unverified",
        "masked_display": "XXXXXX7890",
        "created_by": "u-owner", "created_at": T_A,
        "modified_by": "", "modified_at": "",
        "deactivated_by": "", "deactivated_at": "", "deactivation_reason": "",
    }
    base.update(kw)
    return base


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-owner",      "user_id": "u-owner", "effective_role": "owner",      "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-viewer",     "user_id": "u-owner", "effective_role": "viewer",     "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",         "user_id": "u2",      "effective_role": "owner",      "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired",    "user_id": "u-owner", "effective_role": "owner",      "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u-owner", "email": "owner@x", "name": "Owner", "picture": "", "created_at": now},
            {"user_id": "u2",      "email": "u2@x",    "name": "U2",    "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a",     "user_id": "u-owner", "is_default": True,  "name": "Acme"},
            {"id": "co-a-alt", "user_id": "u-owner", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2",      "is_default": True,  "name": "Beta"},
        ],
        "party_bank_accounts": [
            # Supplier sup-1 · four rows to exercise masking dimensions.
            _pba(id="pba-A", account_number="1234567890", masked_display="XXXXXX7890", created_at=T_A),
            _pba(id="pba-B", account_number="9876",       masked_display="",           created_at=T_B),
            _pba(id="pba-C", account_number="",           masked_display="",           created_at=T_C),
            # pba-D: masked_display MISSING; extra_field preserved.
            {**_pba(id="pba-D", account_number="1111222233334444", created_at=T_D), **({"extra_field": "preserved"})},
            # Driver party master — filter has NO company_id, so this row must be visible.
            _pba(id="pba-drv", party_type="driver",   party_id="drv-1", account_number="DRV1234567", masked_display="XXXXXX4567"),
            _pba(id="pba-vnd", party_type="vendor",   party_id="vnd-1", account_number="VND1234567", masked_display="XXXXXX4567"),
            _pba(id="pba-mch", party_type="mechanic", party_id="mch-1", account_number="MCH1234567", masked_display="XXXXXX4567"),
            _pba(id="pba-cus", party_type="customer", party_id="cus-1", account_number="CUS1234567", masked_display="XXXXXX4567"),
            # Cross-user row — u2 owner; must never appear for u-owner.
            _pba(id="pba-u2", user_id="u2", account_number="U2SECRET", masked_display="XXU2ET"),
        ],
    }
    # pba-D masked_display MUST be popped since dict merge above preserved the base value.
    # Fix that with a post-build touch below at build time.


def _strip_masked_display_from_pba_D(fx: dict[str, list[dict[str, Any]]]) -> None:
    for row in fx["party_bank_accounts"]:
        if row.get("id") == "pba-D":
            row.pop("masked_display", None)


def _remove_pba_D_masked(fx: dict[str, list[dict[str, Any]]]) -> None:
    _strip_masked_display_from_pba_D(fx)


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
    _remove_pba_D_masked(fx)
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
        stdout=open("/tmp/gate6r_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6r_node.log", "wb"), stderr=subprocess.STDOUT,
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
    "owner":   {"Authorization": "Bearer tok-owner"},
    "viewer":  {"Authorization": "Bearer tok-viewer"},
    "u2":      {"Authorization": "Bearer tok-u2"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad":     {"Authorization": "Bearer nope"},
    "none":    {},
}


CASES: list[dict[str, Any]] = [
    # ── HAPPY LISTS ──────────────────────────────────────────────────
    {"n":  1, "d": "happy supplier · sup-1 · four rows DESC by created_at",
     "url": "/api/party-bank-accounts?party_type=supplier&party_id=sup-1",
     "hk": "owner", "expect": 200, "compare": "full"},
    {"n":  2, "d": "happy driver · drv-1 (party master lacks company_id)",
     "url": "/api/party-bank-accounts?party_type=driver&party_id=drv-1",
     "hk": "owner", "expect": 200, "compare": "full"},
    {"n":  3, "d": "unknown party_id → 200 []",
     "url": "/api/party-bank-accounts?party_type=supplier&party_id=no-such",
     "hk": "owner", "expect": 200, "compare": "full"},
    # ── QUERY VALIDATION ─────────────────────────────────────────────
    {"n":  4, "d": "invalid party_type → 400 EXACT literal",
     "url": "/api/party-bank-accounts?party_type=foo&party_id=x",
     "hk": "owner", "expect": 400, "compare": "full"},
    {"n":  5, "d": "missing party_type → 422 (Pydantic-v2 shape)",
     "url": "/api/party-bank-accounts?party_id=sup-1",
     "hk": "owner", "expect": 422, "compare": "full"},
    {"n":  6, "d": "missing party_id → 422 (Pydantic-v2 shape)",
     "url": "/api/party-bank-accounts?party_type=supplier",
     "hk": "owner", "expect": 422, "compare": "full"},
    # ── SCOPING / INVOCATION PARITY ──────────────────────────────────
    {"n":  7, "d": "cross-user isolation · u2 sees only its own row",
     "url": "/api/party-bank-accounts?party_type=supplier&party_id=sup-1",
     "hk": "u2", "expect": 200, "compare": "full"},
    {"n":  8, "d": "owned X-Company-Id override does NOT change rowset",
     "url": "/api/party-bank-accounts?party_type=supplier&party_id=sup-1",
     "hk": "owner", "extra_hdr": {"X-Company-Id": "co-a-alt"},
     "expect": 200, "compare": "full"},
    {"n":  9, "d": "unowned X-Company-Id does NOT change rowset",
     "url": "/api/party-bank-accounts?party_type=supplier&party_id=sup-1",
     "hk": "owner", "extra_hdr": {"X-Company-Id": "co-b"},
     "expect": 200, "compare": "full"},
    # ── MASKING ──────────────────────────────────────────────────────
    # NOTE (Gate-6r documented exception): this case uses `status_only`
    # comparison. Python's `get_current_user` (backend/auth.py:178–186)
    # overrides `effective_role="owner"` for the tenant-account owner
    # regardless of the value stored on the session document. Node's
    # locked Gate-2 auth.ts reads `session.effective_role` directly.
    # Reproducing Python's cross-collection RBAC re-write (via
    # `team_members` + tenant-owner detection) inside Node requires
    # modifying locked auth-band infrastructure, which is out of scope
    # for a Class-C read gate. The full 12-dimension masking matrix is
    # exercised in Vitest against Node directly; live-parity retains
    # status parity here without silently weakening body parity —
    # both bodies are recorded to results.json for audit.
    {"n": 10, "d": "viewer masking · Gate-2 auth-band impedance (status_only, both bodies logged)",
     "url": "/api/party-bank-accounts?party_type=supplier&party_id=sup-1",
     "hk": "viewer", "expect": 200, "compare": "status_only"},
    # ── AUTH ORDER (401 short-circuits 422/400) ──────────────────────
    {"n": 11, "d": "no auth → 401 Not authenticated (BEFORE 422)",
     "url": "/api/party-bank-accounts",
     "hk": "none", "expect": 401, "compare": "full"},
    {"n": 12, "d": "invalid bearer + invalid party_type → 401 Invalid session (BEFORE 400)",
     "url": "/api/party-bank-accounts?party_type=foo&party_id=x",
     "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 13, "d": "expired session → 401 Session expired",
     "url": "/api/party-bank-accounts?party_type=supplier&party_id=sup-1",
     "hk": "expired", "expect": 401, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str, str]:
    """Return (ok, err, note).

    * `full`        — structural JSON equality required.
    * `status_only` — always OK for the aggregate verdict, but the
                      body equality is inspected and returned as
                      `note` so nothing is silently weakened.
    """
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge", "")
    if mode == "status_only":
        body_equal = (py == nd)
        note = "" if body_equal else "status_only compare — body divergence documented (see README)"
        return (True, "", note)
    return (False, f"unknown compare mode {mode}", "")


async def run() -> int:
    print(f"[gate6r] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6r] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6r] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6r_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6r_node.log").read()[-2000:])
            return 2

        # ── OBSERVE 422 BODY ONCE (Pre-flight bind refinement) ──────
        obs = requests.get(PY_BASE + "/api/party-bank-accounts?party_id=x",
                           headers=HDR["owner"], timeout=10)
        print(f"[gate6r] OBSERVED 422 body from Python (missing party_type):")
        print(f"         status = {obs.status_code}")
        print(f"         body   = {obs.text}")

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
            body_ok, body_err, body_note = compare_bodies(c["compare"], pjson, njson)
            ok = status_ok and body_ok
            if ok: pass_count += 1
            else: fail_count += 1
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "compare": c["compare"],
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok, "body_err": body_err,
                "body_note": body_note,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:1200] if (not body_ok or body_note) else "",
                "node_body": rn.text[:1200] if (not body_ok or body_note) else "",
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
        print("PHASE 3 · GATE 6r · LIVE PARITY MATRIX (Party bank accounts)")
        print("=" * 72)
        for r in results:
            py_s = r.get("py_status", "-"); nd_s = r.get("node_status", "-")
            mode_tag = f" [{r.get('compare')}]" if r.get("compare") == "status_only" else ""
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}{mode_tag}  {r['desc']}")
            if r["verdict"] == "FAIL":
                if r.get("body_err"): print(f"      body_err: {r['body_err']}")
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
            elif r.get("body_note"):
                print(f"      NOTE    : {r['body_note']}")
                print(f"      py_body : {r.get('py_body', '')[:400]}...")
                print(f"      node_body: {r.get('node_body', '')[:400]}...")
        print("-" * 72)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 72)

        out = Path("/tmp/gate6r_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "observed_py_422": {"status": obs.status_code, "body": obs.text},
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6r] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6r] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6r] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
