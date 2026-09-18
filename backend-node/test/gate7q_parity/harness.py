"""Phase 3 · Gate 7q · live Python↔Node parity harness for FinTxn detail.

Covers:
  * GET /api/fin/fin-txn/{txid}

Class-C stance:
  Pure-read in Python. Handler executes at most
    fin_txn.find_one({id: txid, user_id, company_id}, {_id:0, user_id:0})
    <coll_map[source_type]>.find_one({user_id, company_id, id: source_id},
                                     {_id:0, user_id:0})
  inside a best-effort try/except. Zero writes / audits / reproject.

Parity axes: auth precedence, 404 literal, all 12 coll_map targets, the
intentional `driver_payment` gap, non-string source_type / source_id through
real Mongo query semantics, cross-company source isolation, empty-segment /
encoded-slash 404.

Framework-level gaps (NOT counted; owned by the framework gate): invalid
UTF-8 escapes, trailing slash, param > 100 chars.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7q_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7q-py", "trukvia-gate7q-node"
PY_PORT, NODE_PORT = 8252, 8253
LOGDIR = Path(tempfile.gettempdir())

MAP = [("invoice", "invoices"), ("credit_debit_note", "credit_debit_notes"),
       ("supplier_payment", "supplier_payments"), ("vendor_payment", "vendor_payments"),
       ("mechanic_payment", "mechanic_payments"), ("expense", "expenses"),
       ("vendor_bill", "vendor_bills"), ("mechanic_work_order", "mechanic_work_orders"),
       ("trip_customer_receipt", "trips"), ("wallet_recharge", "wallet_recharges"),
       ("wallet_transfer", "wallet_transfers"), ("wallet_adjustment", "wallet_adjustments")]


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()

_MISSING = object()


def tx(tid: str, stype: Any = _MISSING, sid: Any = _MISSING, uid: str = "u1", company: str = "co-a", **kw: Any) -> dict[str, Any]:
    t: dict[str, Any] = {"id": tid, "user_id": uid, "company_id": company, "txn_date": "2026-05-01",
                         "status": "active", "account_code": "AR", "direction": "in", "amount": 1250.5,
                         "ref_source_key": f"k-{tid}", "created_at": "2026-05-01T10:00:00+00:00",
                         "legs": [{"account": "AR", "amt": 1250.5}], "meta": {"note": "₹ \"q\""}}
    if stype is not _MISSING:
        t["source_type"] = stype
    if sid is not _MISSING:
        t["source_id"] = sid
    t.update(kw)
    return t


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    colls: dict[str, list[dict[str, Any]]] = {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [{"user_id": u, "email": f"{u}@x", "name": u.upper(), "picture": "", "created_at": now}
                  for u in ("u1", "u2")],
        "companies": [
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        ],
        "fin_txn": [tx(f"tx-{st}", st, f"src-{st}") for st, _ in MAP] + [
            tx("tx-driver", "driver_payment", "src-driver"),
            tx("tx-unknown", "mystery", "src-x"),
            tx("tx-case", "Invoice", "src-invoice"),
            tx("tx-proto", "toString", "src-x"),
            tx("tx-nosrc", "invoice", "src-missing"),
            tx("tx-xco-src", "invoice", "src-xco"),
            tx("tx-xuser-src", "invoice", "src-xuser"),
            tx("tx-list", ["invoice"], "src-invoice"),
            tx("tx-int-type", 5, "src-invoice"),
            tx("tx-null-type", None, "src-invoice"),
            tx("tx-none"),
            tx("tx-empty-sid", "expense", ""),
            tx("tx-null-sid", "expense", None),
            tx("tx-int-sid", "expense", 7),
            tx("tx-list-sid", "expense", ["src-expense", "zzz"]),
            tx("tx-alt", "invoice", "src-alt", company="co-a-alt"),
            tx("tx-u2", "invoice", "src-invoice", uid="u2", company="co-b"),
            tx("tx-leak", "invoice", "src-invoice", uid="u2", company="co-a"),
            tx("tx ₹ 'q'", "invoice", "src-invoice"),
        ],
        "driver_payments": [{"id": "src-driver", "user_id": "u1", "company_id": "co-a", "amount": 500.0}],
    }
    for st, coll in MAP:
        colls[coll] = [{"id": f"src-{st}", "user_id": "u1", "company_id": "co-a", "label": st,
                        "amount": 1250.5, "nested": {"a": [1, 2, {"b": None}]}}]
    colls["invoices"] += [
        {"id": "src-xco", "user_id": "u1", "company_id": "co-a-alt", "label": "other company"},
        {"id": "src-xuser", "user_id": "u2", "company_id": "co-a", "label": "other user"},
        {"id": "src-alt", "user_id": "u1", "company_id": "co-a-alt", "label": "alt company invoice"},
    ]
    colls["expenses"] += [
        {"id": "", "user_id": "u1", "company_id": "co-a", "label": "empty-id expense"},
        {"id": 7, "user_id": "u1", "company_id": "co-a", "label": "int-id expense"},
        {"id": ["src-expense", "zzz"], "user_id": "u1", "company_id": "co-a", "label": "array-id expense"},
    ]
    return colls


TRACKED = ("users", "user_sessions", "companies", "fin_txn", "driver_payments", "audit_logs",
           "approvals", "counters", "fin_hook_failures") + tuple(c for _, c in MAP)


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    for coll, rows in fixtures().items():
        await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(None)
        docs.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[c] = json.dumps(docs, sort_keys=True, default=str)
    return out


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB,
                "ENABLE_DEMO_TOKEN": "0", "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0",
                "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0",
                "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open(LOGDIR / "gate7q_py.log", "wb"), stderr=subprocess.STDOUT)


def start_node():
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent",
                "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB,
                "NODE_CORS_ORIGINS": "", "NODE_REQUEST_ID_HEADER": "x-request-id",
                "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
    return subprocess.Popen(
        ["node", str(REPO / "backend-node/dist/server.js")],
        cwd=str(REPO / "backend-node"), env=env,
        stdout=open(LOGDIR / "gate7q_node.log", "wb"), stderr=subprocess.STDOUT)


def raw_get(port: int, path: str, hdr: dict[str, str]) -> tuple[int, str]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.putrequest("GET", path, skip_accept_encoding=True)
    for k, v in hdr.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    body = r.read().decode("utf-8", "replace")
    c.close()
    return r.status, body


def wait(port: int, path: str, timeout: int = 90) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if raw_get(port, path, {})[0] < 500:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def stop(p):
    if p and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM); p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


HDR = {
    "u1": {"Authorization": "Bearer tok-u1"},
    "u2": {"Authorization": "Bearer tok-u2"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad": {"Authorization": "Bearer nope"},
    "none": {},
}


def u(txid: str) -> str:
    return f"/api/fin/fin-txn/{quote(txid, safe='')}"


CASES: list[dict[str, Any]] = [
    {"d": "no bearer → 401", "url": u("tx-invoice"), "hk": "none", "expect": 401},
    {"d": "invalid bearer → 401", "url": u("tx-invoice"), "hk": "bad", "expect": 401},
    {"d": "expired bearer → 401", "url": u("tx-invoice"), "hk": "expired", "expect": 401},
    {"d": "no bearer + unknown txid → 401 (auth first)", "url": u("tx-gone"), "hk": "none", "expect": 401},
] + [
    {"d": f"source_type {st} → {coll}", "url": u(f"tx-{st}"), "hk": "u1", "expect": 200} for st, coll in MAP
] + [
    {"d": "driver_payment (intentional coll_map gap) → source {}", "url": u("tx-driver"), "hk": "u1", "expect": 200},
    {"d": "unknown source_type → {}", "url": u("tx-unknown"), "hk": "u1", "expect": 200},
    {"d": "case-sensitive 'Invoice' → {}", "url": u("tx-case"), "hk": "u1", "expect": 200},
    {"d": "prototype-name source_type 'toString' → {}", "url": u("tx-proto"), "hk": "u1", "expect": 200},
    {"d": "source doc missing → {}", "url": u("tx-nosrc"), "hk": "u1", "expect": 200},
    {"d": "source doc in other company → {}", "url": u("tx-xco-src"), "hk": "u1", "expect": 200},
    {"d": "source doc of other user → {}", "url": u("tx-xuser-src"), "hk": "u1", "expect": 200},
    {"d": "list source_type (unhashable) → {}", "url": u("tx-list"), "hk": "u1", "expect": 200},
    {"d": "int source_type → {}", "url": u("tx-int-type"), "hk": "u1", "expect": 200},
    {"d": "null source_type → {}", "url": u("tx-null-type"), "hk": "u1", "expect": 200},
    {"d": "no source fields → {}", "url": u("tx-none"), "hk": "u1", "expect": 200},
    {"d": "empty source_id → lookup id '' hits", "url": u("tx-empty-sid"), "hk": "u1", "expect": 200},
    {"d": "null source_id → lookup id '' hits", "url": u("tx-null-sid"), "hk": "u1", "expect": 200},
    {"d": "int source_id 7 → int-id doc", "url": u("tx-int-sid"), "hk": "u1", "expect": 200},
    {"d": "array source_id → Mongo array-equality semantics", "url": u("tx-list-sid"), "hk": "u1", "expect": 200},
    {"d": "special-char txid", "url": u("tx ₹ 'q'"), "hk": "u1", "expect": 200},
    {"d": "query string ignored", "url": u("tx-invoice") + "?id=tx-expense", "hk": "u1", "expect": 200},
    {"d": "unknown txid → 404", "url": u("tx-gone"), "hk": "u1", "expect": 404},
    {"d": "cross-user txid → 404", "url": u("tx-u2"), "hk": "u1", "expect": 404},
    {"d": "other-company txid under default → 404", "url": u("tx-alt"), "hk": "u1", "expect": 404},
    {"d": "u2 row with u1 company id → 404 for u1", "url": u("tx-leak"), "hk": "u1", "expect": 404},
    {"d": "encoded slash with auth → 404 Not Found", "url": "/api/fin/fin-txn/a%2Fb", "hk": "u1", "expect": 404},
    {"d": "encoded slash no auth → 404 Not Found", "url": "/api/fin/fin-txn/a%2Fb", "hk": "none", "expect": 404},
    {"d": "u1 owned X-Company-Id co-a-alt → alt txn + alt source", "url": u("tx-alt"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"d": "u1 owned alt header hides co-a txn", "url": u("tx-invoice"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 404},
    {"d": "u1 unowned X-Company-Id co-b → fallback", "url": u("tx-invoice"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},
    {"d": "u1 empty X-Company-Id → default", "url": u("tx-invoice"), "hk": "u1", "extra_hdr": {"X-Company-Id": ""}, "expect": 200},
    {"d": "u2 own txn; source scoped to u2 → {}", "url": u("tx-u2"), "hk": "u2", "expect": 200},
    {"d": "u2 X-Company-Id co-a → fallback co-b, leak txn hidden", "url": u("tx-leak"), "hk": "u2", "extra_hdr": {"X-Company-Id": "co-a"}, "expect": 404},
]

INFORMATIONAL = [
    {"d": "[framework] invalid UTF-8 %FF", "url": "/api/fin/fin-txn/%FF", "hk": "u1"},
    {"d": "[framework] trailing slash", "url": u("tx-invoice") + "/", "hk": "u1"},
    {"d": "[framework] txid > 100 chars", "url": u("t" * 101), "hk": "u1"},
]


async def run() -> int:
    print(f"[gate7q] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        py = start_py(); node = start_node()
        okp = wait(PY_PORT, "/api/"); okn = wait(NODE_PORT, "/health/live")
        print(f"[gate7q] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print((LOGDIR / "gate7q_py.log").read_text(errors="replace")[-3000:])
            if not okn: print((LOGDIR / "gate7q_node.log").read_text(errors="replace")[-3000:])
            return 2
        await asyncio.sleep(8)

        pdb = cli[DB]
        await pdb.command({"profile": 0})
        await pdb.drop_collection("system.profile")
        await pdb.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await pdb.command({"profile": 2})

        results = []; passed = failed = node_snap_writes = py_snap_writes = 0
        for i, c in enumerate(CASES, 1):
            hdr = dict(HDR[c["hk"]]); hdr.update(c.get("extra_hdr", {}))
            s0 = await snap(cli, DB)
            rp = raw_get(PY_PORT, c["url"], hdr)
            s1 = await snap(cli, DB)
            rn = raw_get(NODE_PORT, c["url"], hdr)
            s2 = await snap(cli, DB)
            py_w = [k for k in s0 if s0[k] != s1[k]]; nd_w = [k for k in s1 if s1[k] != s2[k]]
            py_snap_writes += bool(py_w); node_snap_writes += bool(nd_w)
            try: pj: Any = json.loads(rp[1])
            except Exception: pj = rp[1]
            try: nj: Any = json.loads(rn[1])
            except Exception: nj = rn[1]
            status_ok = rp[0] == rn[0] == c["expect"]
            order_ok = not (isinstance(pj, dict) and isinstance(nj, dict)) or list(pj) == list(nj)
            body_ok = pj == nj and order_ok
            ok = status_ok and body_ok and not nd_w
            passed += ok; failed += (not ok)
            src = pj.get("source") if isinstance(pj, dict) else None
            results.append({"case": i, "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                            "py_status": rp[0], "node_status": rn[0],
                            "source": (src.get("collection") if src else "{}") if isinstance(src, dict) else None,
                            "py_write_colls": py_w, "node_write_colls": nd_w,
                            "py_body": "" if body_ok else rp[1][:800], "node_body": "" if body_ok else rn[1][:800]})

        await pdb.command({"profile": 0})
        prof = await pdb["system.profile"].find({"appName": NODE_APP}, {"op": 1, "ns": 1, "command": 1}).to_list(None)
        kinds: dict[str, int] = {}; by_ns: dict[str, int] = {}; write_ops = 0
        write_names = {"insert", "update", "delete", "findAndModify", "findandmodify", "bulkWrite",
                       "create", "createIndexes", "drop", "dropIndexes", "renameCollection"}
        for p in prof:
            cmd = p.get("command") or {}
            first = next(iter(cmd), "") if isinstance(cmd, dict) else ""
            kinds[f"{p.get('op')}:{first}"] = kinds.get(f"{p.get('op')}:{first}", 0) + 1
            ns = p.get("ns", "").split(".", 1)[-1]
            by_ns[ns] = by_ns.get(ns, 0) + 1
            if p.get("op") in ("insert", "update", "remove") or first in write_names:
                write_ops += 1
        mapped_hit = sum(1 for _, c in MAP if by_ns.get(c, 0) > 0)
        zero_ok = (write_ops == 0 and node_snap_writes == 0 and by_ns.get("fin_txn", 0) > 0
                   and mapped_hit == len(MAP) and by_ns.get("driver_payments", 0) == 0)
        results.append({"case": len(CASES) + 1,
                        "desc": "zero-write — profiler + snapshots; all 12 mapped collections read; driver_payments never read",
                        "verdict": "PASS" if zero_ok else "FAIL", "node_profiled_ops": len(prof),
                        "node_op_kinds": kinds, "node_ops_by_ns": by_ns, "node_write_ops": write_ops})
        passed += zero_ok; failed += (not zero_ok)

        info = []
        for c in INFORMATIONAL:
            rp = raw_get(PY_PORT, c["url"], HDR[c["hk"]]); rn = raw_get(NODE_PORT, c["url"], HDR[c["hk"]])
            info.append({"desc": c["d"], "same": (rp[0], rp[1]) == (rn[0], rn[1]),
                         "py": [rp[0], rp[1][:140]], "node": [rn[0], rn[1][:140]]})

        print("\n" + "=" * 78)
        print("PHASE 3 · GATE 7q · LIVE PARITY MATRIX (FinTxn detail)")
        print("=" * 78)
        for r in results:
            extra = f" source={r['source']}" if r.get("source") is not None else ""
            print(f"  [{r['verdict']}] case {r['case']:>3} py={r.get('py_status', '-')} node={r.get('node_status', '-')}{extra}  {r['desc']}")
            if r["verdict"] == "FAIL" and "py_body" in r:
                print(f"      py_body  : {r['py_body']}\n      node_body: {r['node_body']}")
        print(f"  node profiled ops={len(prof)} kinds={kinds} write_ops={write_ops}")
        print(f"  node ops by collection={by_ns}")
        print("-" * 78)
        print(f"  cases: {len(results)} (fixed {len(CASES)} + zero-write 1)   passed: {passed}   failed: {failed}")
        print(f"  python snapshot-write cases: {py_snap_writes}   node snapshot-write cases: {node_snap_writes}")
        print("  informational (framework gate — NOT counted):")
        for x in info:
            print(f"    [{'SAME' if x['same'] else 'DIFF'}] {x['desc']}\n        py   {x['py']}\n        node {x['node']}")
        print("=" * 78)
        out = LOGDIR / "gate7q_parity_results.json"
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": passed, "failed": failed,
                                   "node_write_ops": write_ops, "results": results, "informational": info},
                                  indent=2, default=str), encoding="utf-8")
        print(f"[gate7q] results → {out}")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await cli[DB].command({"profile": 0})
        except Exception: pass
        try:
            await cli.drop_database(DB)
            print(f"[gate7q] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7q] drop failed: {e}")
        print(f"[gate7q] leftover gate7q DBs: {[d for d in await cli.list_database_names() if d.startswith('trukvia_gate7q_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
