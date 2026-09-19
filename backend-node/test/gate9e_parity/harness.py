"""Phase 4 · Gate 9e · live Python↔Node older-route parity.

Both servers run against one disposable DB (dropped in `finally`); raw-socket
GETs; status + content-type + raw body compared byte-exactly.

  A  GET /api/files/usage          exact Python JSON over BSON-typed data
  B  GET /api/invoices/next-preview  auth-before-422, Pydantic `missing`, last value
  C  limit parsing                 /api/audit-logs, /api/policy-changes, /api/approvals
  D  capped-list tie order         cap+15 identical sort keys on EVERY Motor/`.limit`
                                   capped list (24 routes) + limit-param caps
Case classes: PARITY (counted), KNOWN-NOT-9E (reported separately, never a pass):
  next-preview `date.fromisoformat` accepts YYYYMMDD / ISO-week (Python 200,
  Node 400) — a validation difference outside the 9e 422 scope.
Zero Node writes: profiler by appName; application collections dbHash unchanged.
"""
from __future__ import annotations
import asyncio, json, os, random, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import Int64
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate9e_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate9e-py", "trukvia-gate9e-node"
PY, ND = 8310, 8311
LOGDIR = Path(tempfile.gettempdir())
NOW = datetime.now(timezone.utc)
FUT = NOW + timedelta(days=30)
LIMIT_BYTES = 500 * 1024 * 1024
random.seed(9)

FILE_CASES = {
    "fz-zero": [dict(size=0, category="general")], "fz-small": [dict(size=12345678, category="docs")],
    "fz-tie": [dict(size=655360, category="a")], "fz-tie2": [dict(size=1966080, category="a")],
    "fz-cap": [dict(size=LIMIT_BYTES)], "fz-over": [dict(size=LIMIT_BYTES * 3)], "fz-9999": [dict(size=LIMIT_BYTES - 5000)],
    "fz-bool": [dict(size=True, category="x")], "fz-strs": [dict(size="12", category="s"), dict(size=" 34 ", category="s")],
    "fz-under": [dict(size="1_000", category="s")], "fz-uni": [dict(size="٣٤", category="u"), dict(size=" 5　", category="u")],
    "fz-badstr": [dict(size="1.5", category="s")], "fz-ctrlws": [dict(size="\x1c7", category="s")],
    "fz-float": [dict(size=12.9, category="f"), dict(size=7.0, category="f")], "fz-neg": [dict(size=-5, category="n")],
    "fz-long": [dict(size=Int64(9007199254740993), category="L")], "fz-nan": [dict(size=float("nan"), category="n")],
    "fz-inf": [dict(size=float("inf"))], "fz-emptylist": [dict(size=[], category="e")], "fz-list": [dict(size=[1])],
    "fz-emptydict": [dict(size={}, category="e")], "fz-date": [dict(size=NOW)],
    "fz-cats": [dict(size=1, category="general"), dict(size=2, category="2024"), dict(size=3, category=None), dict(size=4),
                dict(size=5, category=1), dict(size=6, category="1"), dict(size=7, category=True), dict(size=8, category=1.0),
                dict(size=9, category="é"), dict(size=10, category=False), dict(size=11, category=0), dict(size=12, category=2.5),
                dict(size=13, category=Int64(7)), dict(size=14, category=datetime(2026, 5, 1, 10, 0, 0, 123000))],
    "fz-listkey": [dict(size=1, category=["a"])], "fz-nankey": [dict(size=1, category=float("nan"))],
    "fz-many": [dict(size=i * 1000 + 7, category=f"c{i % 5}") for i in range(60)],
    "fz-empty": [],
}

CAPPED = [  # (label, collection, base doc, path, cap)
    ("company-bank-accounts", "company_bank_accounts", {"company_id": "co-a", "created_at": "T"}, "/api/company-bank-accounts", 500),
    ("party-bank-accounts", "party_bank_accounts", {"party_type": "vendor", "party_id": "v1", "created_at": "T"},
     "/api/party-bank-accounts?party_type=vendor&party_id=v1", 500),
    ("driver-payments-corrections", "driver_payment_corrections", {"company_id": "co-a", "payment_id": "pay-1", "correction_index": 1},
     "/api/driver-payments/pay-1/corrections", 1000),
    ("mechanic-payments-corrections", "payment_corrections", {"company_id": "co-a", "payment_type": "mechanic", "payment_id": "pay-m", "correction_index": 1},
     "/api/mechanic-payments/pay-m/corrections", 1000),
    ("vendor-payments-corrections", "payment_corrections", {"company_id": "co-a", "payment_type": "vendor", "payment_id": "pay-v", "correction_index": 1},
     "/api/vendor-payments/pay-v/corrections", 1000),
    ("driver-payments-list", "driver_payments", {"company_id": "co-a", "driver_id": "d1", "date": "2026-05-01"}, "/api/drivers/d1/payments", 5000),
    ("driver-salary-masters", "driver_salary_masters", {"company_id": "co-a", "driver_id": "d1", "effective_from": "2026-01-01", "version": 1},
     "/api/drivers/d1/salary-masters", 500),
    ("files-list", "files", {"company_id": "co-a", "is_deleted": False, "created_at": "T", "size": 1}, "/api/files", 500),
    ("fuel-vehicle-maps", "fuel_vehicle_maps", {"company_id": "co-a", "source_vehicle_ref": "R"}, "/api/fuel/vehicle-maps", 5000),
    ("mechanic-payments-list", "mechanic_payments", {"company_id": "co-a", "mechanic_id": "m1", "date": "2026-05-01"}, "/api/mechanics/m1/payments", 5000),
    ("mechanic-work-orders", "mechanic_work_orders", {"company_id": "co-a", "work_date": "2026-05-01"}, "/api/mechanic-work-orders", 5000),
    ("repair-events", "repair_events", {"company_id": "co-a", "event_date": "2026-05-01"}, "/api/repair-events", 5000),
    ("supplier-payments-list", "supplier_payments", {"company_id": "co-a", "supplier_id": "s1", "date": "2026-05-01"}, "/api/suppliers/s1/payments", 5000),
    ("supplier-vehicles", "vehicles", {"company_id": "co-a", "vehicle_type": "supplier", "supplier_id": "s1", "vehicle_number": "KA01"},
     "/api/suppliers/s1/vehicles", 500),
    ("templates", "templates", {"company_id": "co-a", "is_active": True, "name": "T"}, "/api/templates", 500),
    ("vendor-bills", "vendor_bills", {"company_id": "co-a", "bill_date": "2026-05-01"}, "/api/vendor-bills", 5000),
    ("vendor-payments-list", "vendor_payments", {"company_id": "co-a", "vendor_id": "v1", "date": "2026-05-01"}, "/api/vendors/v1/payments", 5000),
    ("wallet-adjustments", "wallet_adjustments", {"company_id": "co-a", "date": "2026-05-01"}, "/api/wallet-adjustments", 5000),
    ("wallet-recharges", "wallet_recharges", {"company_id": "co-a", "date": "2026-05-01"}, "/api/wallet-recharges", 5000),
    ("wallet-transfers", "wallet_transfers", {"company_id": "co-a", "date": "2026-05-01"}, "/api/wallet-transfers", 5000),
    ("approval-detail", "approval_revisions", {"company_id": "co-a", "approval_id": "apr1", "revision_index": 0}, "/api/approvals/apr1", 500),
    ("audit-logs", "audit_logs", {"timestamp": "2026-05-01T00:00:00"}, "/api/audit-logs", 500),
    ("policy-changes", "policy_change_events", {"company_id": "co-a", "created_at": "T"}, "/api/policy-changes", 200),
    ("approvals-list", "approvals", {"company_id": "co-a", "created_at": "T", "status": "PENDING_APPROVAL"}, "/api/approvals", 500),
]
INT_VALS = ["1", "0", "-1", "+5", "%207%20", "1.0", "1.00", "-0.0", "1_000", "1.", "1__0", "_1", "1_", "1.5", "1e3", "abc", "",
            "0x10", "9" * 25, "-" + "9" * 25, "501", "500", "0.0", "2.0", "%FF", "1%2E0", "+", "1+", "%C2%A05", "5%C2%A0", "00012",
            "0_0", "-0", "+0", "%E2%80%83" + "3", "3%0A", "%0A3", "1" * 4301, "--1", "+-1", "0_1", "1_0.0", "0.00", "-1_0"]


def sess(tok, uid):
    return {"user_id": uid, "session_token": tok, "expires_at": FUT, "created_at": NOW, "last_refreshed_at": NOW}


def get(port, target, hdr=()):
    s = socket.create_connection(("127.0.0.1", port), timeout=60)
    h = b"".join(f"{k}: {v}\r\n".encode("latin-1") for k, v in hdr)
    s.sendall(b"GET " + target.encode("latin-1") + b" HTTP/1.1\r\nHost: t\r\nConnection: close\r\n" + h + b"\r\n")
    out = b""
    while True:
        c = s.recv(1 << 20)
        if not c:
            break
        out += c
    s.close()
    head, _, body = out.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    ct = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("content-type:")), None)
    if any(l.lower().startswith("transfer-encoding: chunked") for l in lines):
        o, r = b"", body
        while r:
            n_, _, r = r.partition(b"\r\n")
            n = int(n_ or b"0", 16)
            if n == 0:
                break
            o += r[:n]; r = r[n + 2:]
        body = o
    return lines[0][9:12], ct, body


async def main() -> int:
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        users = ["u1"] + list(FILE_CASES)
        await d.user_sessions.insert_many([sess("tok-" + u, u) for u in users])
        await d.users.insert_many([{"user_id": u, "email": u + "@x"} for u in users])
        await d.companies.insert_one({"id": "co-a", "user_id": "u1", "is_default": True, "invoice_prefix": "A-"})
        await d.drivers.insert_one({"id": "d1", "user_id": "u1", "company_id": "co-a", "name": "D"})
        await d.mechanics.insert_one({"id": "m1", "user_id": "u1", "company_id": "co-a", "name": "M"})
        await d.suppliers.insert_one({"id": "s1", "user_id": "u1", "company_id": "co-a", "name": "S"})
        await d.vendors.insert_one({"id": "v1", "user_id": "u1", "company_id": "co-a", "name": "V"})
        await d.approvals.insert_one({"id": "apr1", "user_id": "u1", "company_id": "co-a", "status": "APPROVED", "created_at": "A"})
        for u, docs in FILE_CASES.items():
            for i, fd in enumerate(docs):
                await d.files.insert_one({"id": f"{u}-{i:03d}", "user_id": u, "is_deleted": False, **fd})
        for label, coll, base, _p, cap in CAPPED:
            ids = [f"{label[:6]}-{i:05d}" for i in range(cap + 15)]
            random.shuffle(ids)
            await d[coll].insert_many([{"id": x, "user_id": "u1", **base} for x in ids])
        await d.approval_audits.insert_many([{"id": f"aa-{i:04d}", "user_id": "u1", "company_id": "co-a", "approval_id": "apr1",
                                              "at": "Z"} for i in random.sample(range(515), 515)])
        tracked = sorted(await d.list_collection_names())
        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "DISABLE_SCHEDULER": "1", "PYTHONIOENCODING": "utf-8",
                    "REGRESSION_GUARD_PERIODIC": "0", "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0"})
        env.pop("CORS_ORIGINS", None)
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY),
                               "--log-level", "warning", "--no-access-log"], cwd=REPO / "backend", env=env,
                              stdout=open(LOGDIR / "gate9e_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(ND), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": ""})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=REPO / "backend-node", env=env2,
                                stdout=open(LOGDIR / "gate9e_node.log", "wb"), stderr=subprocess.STDOUT)
        for port in (PY, ND):
            for _ in range(480):
                try:
                    socket.create_connection(("127.0.0.1", port), 1).close(); break
                except OSError:
                    time.sleep(0.25)
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=256 * 1024 * 1024)
        await d.command({"profile": 2})
        app_colls = [c for c in tracked if c not in ("companies", "user_sessions")]
        h0 = (await d.command("dbHash", collections=app_colls))["collections"]

        A = [("Authorization", "Bearer tok-u1")]
        cases: list[tuple[str, str, str, list]] = []  # (class, group, target, headers)
        for u in FILE_CASES:
            cases.append(("PARITY", f"A files/usage {u}", "/api/files/usage", [("Authorization", "Bearer tok-" + u)]))
        for name, t, h in [("missing authed", "", A), ("missing unauth", "", []), ("other param only", "?x=1", A),
                           ("empty value", "?invoice_date=", A), ("bare key", "?invoice_date", A),
                           ("repeated bad,good", "?invoice_date=x&invoice_date=2026-05-01", A),
                           ("repeated good,bad", "?invoice_date=2026-05-01&invoice_date=x", A),
                           ("valid", "?invoice_date=2026-05-01", A), ("invalid day", "?invoice_date=2026-02-30", A),
                           ("future", "?invoice_date=2999-01-01", A), ("encoded key", "?invoice%5Fdate=2026-05-01", A),
                           ("plus", "?invoice_date=2026-05-01+", A), ("pct-FF", "?invoice_date=%FF", A),
                           ("unauth valid", "?invoice_date=2026-05-01", [])]:
            cases.append(("PARITY", f"B next-preview {name}", "/api/invoices/next-preview" + t, h))
        for name, t in [("basic YYYYMMDD", "?invoice_date=20260501"), ("ISO week", "?invoice_date=2026-W18-5")]:
            cases.append(("KNOWN-NOT-9E", f"B next-preview {name}", "/api/invoices/next-preview" + t, A))
        for route in ("/api/audit-logs", "/api/policy-changes", "/api/approvals"):
            for v in INT_VALS:
                cases.append(("PARITY", f"C {route} limit={v[:30]!r}", f"{route}?limit={v}", A))
            cases.append(("PARITY", f"C {route} repeated abc,2", f"{route}?limit=abc&limit=2", A))
            cases.append(("PARITY", f"C {route} repeated 2,abc", f"{route}?limit=2&limit=abc", A))
            cases.append(("PARITY", f"C {route} unauth bad", f"{route}?limit=abc", []))
            cases.append(("PARITY", f"C {route} no limit", route, A))
        for label, _c, _b, path, _cap in CAPPED:
            cases.append(("PARITY", f"D tie@cap {label}", path, A))
        for v in ("1", "5", "37", "199", "200", "500"):
            cases.append(("PARITY", f"D audit limit={v}", f"/api/audit-logs?limit={v}", A))
            cases.append(("PARITY", f"D policy limit={v}", f"/api/policy-changes?limit={v}", A))

        passed = failed = 0
        fails, known = [], []
        for cls, name, target, hdr in cases:
            a, b = get(PY, target, hdr), get(ND, target, hdr)
            same = a == b
            if cls == "PARITY":
                passed += same; failed += (not same)
                if not same:
                    fails.append((name, a, b))
            else:
                known.append((name, same, a, b))

        await asyncio.sleep(1)
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        writes = [p for p in prof if p.get("op") in ("insert", "update", "remove") or
                  next(iter(p.get("command") or {}), "") in ("insert", "update", "delete", "findAndModify")]
        # Gate 9e changed ONLY the routes with a verified tie-order mismatch; the others
        # (Python server-side .limit, or verified identical at the cap) keep `.limit`.
        fixed = {"company_bank_accounts", "party_bank_accounts", "driver_salary_masters", "files", "fuel_vehicle_maps",
                 "supplier_payments", "vehicles", "templates", "wallet_adjustments", "wallet_recharges", "wallet_transfers",
                 "approval_revisions", "approval_audits", "audit_logs", "policy_change_events"}
        cmd = lambda p: p.get("command") or {}
        limited = [p for p in prof if cmd(p).get("find") in fixed and "limit" in cmd(p)]
        kept = sorted({cmd(p).get("find") for p in prof if "limit" in cmd(p) and cmd(p).get("find") not in fixed})
        h1 = (await d.command("dbHash", collections=app_colls))["collections"]
        changed = [k for k in app_colls if h0.get(k) != h1.get(k)]

        print("=" * 100 + "\nPHASE 4 · GATE 9e · OLDER-ROUTE PARITY (Python vs Node, raw sockets)\n" + "=" * 100)
        groups: dict[str, list[int]] = {}
        for cls, name, *_ in cases:
            if cls == "PARITY":
                g = name.split(" ")[0]
                groups.setdefault(g, [0, 0])[1] += 1
        for name, *_ in fails:
            groups[name.split(" ")[0]][0] += 1
        for g, (f_, n_) in sorted(groups.items()):
            print(f"  group {g}: {n_ - f_}/{n_} pass")
        for name, a, b in fails[:40]:
            print(f"  [FAIL] {name}\n      py={a[0]} {a[1]} {a[2][:200]!r}\n      nd={b[0]} {b[1]} {b[2][:200]!r}")
        for name, same, a, b in known:
            print(f"  [KNOWN-NOT-9E{' (now equal)' if same else ''}] {name}: py={a[0]} {a[2][:80]!r} nd={b[0]} {b[2][:80]!r}")
        zero_ok = not writes and not changed
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} writes={len(writes)} "
              f"app collections changed={changed}")
        print(f"  [{'PASS' if not limited else 'FAIL'}] 9e-fixed capped lists sent with a server-side limit: {len(limited)} "
              f"({sorted({cmd(p).get('find') for p in limited})})")
        print(f"         unchanged (verified identical) routes still using .limit: {kept}")
        print("-" * 100 + f"\n  PARITY cases: {passed + failed}  passed: {passed}  failed: {failed}   KNOWN-NOT-9E: {len(known)}\n" + "=" * 100)
        return 0 if failed == 0 and zero_ok and not limited else 1
    finally:
        for p in (py, node):
            if p and p.poll() is None:
                try:
                    p.send_signal(signal.SIGTERM); p.wait(timeout=5)
                except Exception:
                    p.kill()
        try:
            await d.command({"profile": 0})
        except Exception:
            pass
        await cli.drop_database(DB)
        print(f"[gate9e] dropped {DB}; leftover gate9e DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate9e_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
