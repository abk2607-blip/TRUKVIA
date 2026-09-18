"""Phase 4 · Gate 9b · live Python↔Node parity for the shared LOGIN IDENTITY context.

Python authority: backend/auth.py::get_current_user (L115-188) — session →
expires_at → (rolling-refresh WRITE, Python only) → users → team_members →
staff owner-scope remap / effective_role / is_staff.

Every session is shaped EXACTLY as routers/auth_router.py writes it at login
(user_id, session_token, expires_at as BSON Date, created_at,
last_refreshed_at — NO role). Roles come only from users / team_members.

Matrix: identities × already-locked Class-C routes, plus auth edge cases.
Comparison: status + raw body BYTE-EXACT for every case. Two KNOWN framework
differences reserved for Gate 9d are reported separately and never hide a
body/status mismatch: (1) older routes send `application/json;
charset=utf-8`; (2) Python's 500 body is ServerErrorMiddleware text, Node's
is the Fastify default (status must still match).

Auth read sequence is compared per request from the profiler
(user_sessions → users → team_members filters). DB activity attributed PER
SERVER; Node must never write.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate9b_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate9b-py", "trukvia-gate9b-node"
PY_PORT, NODE_PORT = 8292, 8293
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "companies", "team_members", "vendors", "suppliers", "customers", "files", "fin_txn",
           "company_bank_accounts", "party_bank_accounts", "reminder_digests", "audit_logs", "save_health",
           "idempotency_keys"]
APP_COLLS = [c for c in TRACKED if c != "companies"]
AUTH_COLLS = ("user_sessions", "users", "team_members")
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}


def raw(port, method, target: bytes, hdr):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    req = method.encode() + b" " + target + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
    for k, v in hdr:
        req += f"{k}: {v}\r\n".encode("latin-1")
    s.sendall(req + b"\r\n")
    r = http.client.HTTPResponse(s, method=method)
    r.begin()
    b = r.read()
    h = {k.lower(): v for k, v in r.getheaders()}
    s.close()
    return r.status, h, b


def wait(port, path):
    for _ in range(480):
        try:
            if raw(port, "GET", path.encode(), [])[0] < 500:
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


NOW = datetime.now(timezone.utc)


def sess(tok, uid=..., exp=...):
    d = {"session_token": tok, "created_at": NOW, "last_refreshed_at": NOW}
    if uid is not ...:
        d["user_id"] = uid
    if exp is not ...:
        d["expires_at"] = exp
    return d


FUT = NOW + timedelta(days=30)
SESSIONS = [
    sess("tok-owner", "u1", FUT), sess("tok-acc", "s-acc", FUT), sess("tok-view", "s-view", FUT),
    sess("tok-inactive", "s-inactive", FUT), sess("tok-norole", "s-norole", FUT), sess("tok-multi", "s-multi", FUT),
    sess("tok-self", "u-self", FUT), sess("tok-ghost", "ghost", FUT), sess("tok-noemail", "u-noemail", FUT),
    sess("tok-nulluid", None, FUT), sess("tok-nouid", ..., FUT), sess("tok-u2", "u2", FUT),
    sess("tok-nodefault", "u-nodef", FUT), sess("tok-expired", "u1", NOW - timedelta(minutes=1)),
    sess("tok-str-naive", "u1", "2999-01-01T00:00:00"), sess("tok-str-tz-past", "u1", "2001-01-01T00:00:00+05:30"),
    sess("tok-str-week", "u1", "2999-W01-1"), sess("tok-str-sep", "u1", "2999-01-01é10:00"),
    sess("tok-str-bad", "u1", "not-a-date"), sess("tok-nullexp", "u1", None), sess("tok-noexp", "u1", ...),
    sess("tok-intexp", "u1", 12345), sess("tok space", "u1", FUT), sess('tok"q', "u1", FUT),
]
USERS = [
    {"user_id": "u1", "email": "owner@x", "name": "Owner", "role": "owner"},
    {"user_id": "u2", "email": "u2@x"}, {"user_id": "s-acc", "email": "acc@x"}, {"user_id": "s-view", "email": "view@x"},
    {"user_id": "s-inactive", "email": "inactive@x"}, {"user_id": "s-norole", "email": "norole@x"},
    {"user_id": "s-multi", "email": "multi@x"}, {"user_id": "u-self", "email": "self@x"},
    {"user_id": "u-noemail", "name": "No Email"}, {"user_id": "u-nodef", "email": "nodef@x"},
    {"name": "no user_id field"},   # matched by {user_id: null}; projects to {"name":…} → then KeyError email
]
TEAM = [
    {"id": "tm1", "owner_user_id": "u1", "email": "acc@x", "role": "accountant", "active": True},
    {"id": "tm2", "owner_user_id": "u1", "email": "view@x", "role": "viewer", "active": True},
    {"id": "tm3", "owner_user_id": "u1", "email": "inactive@x", "role": "accountant", "active": False},
    {"id": "tm4", "owner_user_id": "u1", "email": "norole@x", "active": True},
    {"id": "tm5", "owner_user_id": "u1", "email": "multi@x", "role": "viewer", "active": True},
    {"id": "tm6", "owner_user_id": "u2", "email": "multi@x", "role": "accountant", "active": True},
    {"id": "tm7", "owner_user_id": "u-self", "email": "self@x", "role": "viewer", "active": True},
]
COMPANIES = [{"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"},
             {"id": "co-b", "user_id": "u1", "is_default": False, "name": "B"},
             {"id": "co-z", "user_id": "u2", "is_default": True, "name": "Z"},
             {"id": "co-n1", "user_id": "u-nodef", "name": "N1"}, {"id": "co-n2", "user_id": "u-nodef", "name": "N2"}]
T = NOW.isoformat()
BUSINESS = {
    "vendors": [{"id": "v1", "user_id": "u1", "company_id": "co-a", "name": "Acme"},
                {"id": "v2", "user_id": "u1", "company_id": "co-b", "name": "Beta"},
                {"id": "vz", "user_id": "u2", "company_id": "co-z", "name": "Zed"},
                {"id": "vn", "user_id": "u-nodef", "company_id": "co-n1", "name": "NoDef"},
                {"id": "vs", "user_id": "s-acc", "company_id": "", "name": "staff own id — must never show"}],
    "suppliers": [{"id": "sp1", "user_id": "u1", "company_id": "co-a", "name": "Supplier One"},
                  {"id": "spz", "user_id": "u2", "company_id": "co-z", "name": "Supplier Z"}],
    "customers": [{"id": "c1", "user_id": "u1", "company_id": "co-a", "name": "Cust One",
                   "ship_sites": [{"id": "ss1", "label": "Plant"}]}],
    "files": [{"id": "f1", "user_id": "u1", "company_id": "co-a", "filename": "a.pdf", "is_deleted": False, "created_at": T},
              {"id": "f2", "user_id": "s-acc", "filename": "staff-own.pdf", "is_deleted": False, "created_at": T}],
    "fin_txn": [{"id": "tx1", "user_id": "u1", "company_id": "co-a", "amount": 10, "direction": "in",
                 "source_type": "invoice", "source_id": "inv-missing", "status": "active", "txn_date": "2026-05-01"}],
    "company_bank_accounts": [{"id": "cba1", "user_id": "u1", "company_id": "co-a", "account_number": "123456789012",
                               "masked_display": "XXXXXXXX9012", "created_at": T}],
    "party_bank_accounts": [{"id": "pba1", "user_id": "u1", "party_type": "vendor", "party_id": "v1",
                             "account_number": "998877665544", "masked_display": "XXXXXXXX5544", "created_at": T}],
    "reminder_digests": [{"user_id": "u1", "date": "2026-05-01", "generated_at": T, "entries": [], "total_customers": 0}],
}

ROUTES = [
    ("list", b"/api/vendors"), ("detail", b"/api/vendors/v1"), ("finance", b"/api/fin/fin-txn/tx1"),
    ("supplier", b"/api/suppliers"), ("customer", b"/api/customers/c1/ship-sites"),
    ("bank-company", b"/api/company-bank-accounts"),
    ("bank-party", b"/api/party-bank-accounts?party_type=vendor&party_id=v1"),
    ("files(user-only)", b"/api/files"), ("digest(user-only)", b"/api/reminders/digest"),
]
IDENTITIES = ["tok-owner", "tok-acc", "tok-view", "tok-inactive", "tok-norole", "tok-multi", "tok-self", "tok-ghost",
              "tok-noemail", "tok-nulluid", "tok-nouid", "tok-u2", "tok-nodefault", "tok-expired"]
B = lambda tok: [("Authorization", f"Bearer {tok}")]

CASES = [(f"{tok} · {rname}", t, B(tok)) for tok in IDENTITIES for rname, t in ROUTES]
CASES += [
    (f"{tok} · list", b"/api/vendors", B(tok)) for tok in
    ["tok-str-naive", "tok-str-tz-past", "tok-str-week", "tok-str-sep", "tok-str-bad", "tok-nullexp", "tok-noexp", "tok-intexp"]
]
CASES += [
    ("no token", b"/api/vendors", []), ("invalid bearer", b"/api/vendors", B("nope")),
    ("'Bearer ' empty", b"/api/vendors", [("Authorization", "Bearer ")]),
    ("lower-case 'bearer'", b"/api/vendors", [("Authorization", "bearer tok-owner")]),
    ("bearer double space (untrimmed)", b"/api/vendors", [("Authorization", "Bearer  tok-owner")]),
    ("token with space", b"/api/vendors", [("Authorization", "Bearer tok space")]),
    ("cookie only", b"/api/vendors", [("Cookie", "session_token=tok-acc")]),
    ("cookie last duplicate wins", b"/api/vendors", [("Cookie", "a=1; session_token=nope; session_token=tok-view")]),
    ("cookie quoted _unquote", b"/api/vendors", [("Cookie", 'session_token="tok\\"q"')]),
    ("cookie empty → bearer", b"/api/vendors", [("Cookie", "session_token="), ("Authorization", "Bearer tok-owner")]),
    ("cookie beats bearer", b"/api/company-bank-accounts", [("Cookie", "session_token=tok-view"), ("Authorization", "Bearer tok-owner")]),
    ("staff · owned alt header", b"/api/vendors", B("tok-acc") + [("X-Company-Id", "co-b")]),
    ("staff · unowned header", b"/api/vendors", B("tok-view") + [("X-Company-Id", "co-z")]),
    ("staff · unknown header", b"/api/vendors", B("tok-view") + [("X-Company-Id", "co-nope")]),
    ("staff · empty header", b"/api/vendors", B("tok-view") + [("X-Company-Id", "")]),
    ("owner · owned alt header", b"/api/vendors", B("tok-owner") + [("X-Company-Id", "co-b")]),
    ("u2 · u1's company header", b"/api/vendors", B("tok-u2") + [("X-Company-Id", "co-a")]),
    ("staff · detail other company", b"/api/vendors/v2", B("tok-acc")),
    ("staff · finance bank via alt", b"/api/company-bank-accounts", B("tok-acc") + [("X-Company-Id", "co-b")]),
]


def auth_seq(ops):
    seq = []
    for o in ops:
        c = o.get("command") or {}
        coll = c.get("find")
        if coll in AUTH_COLLS:
            seq.append((coll, json.dumps(c.get("filter"), default=str, sort_keys=False)))
    return seq


async def run() -> int:
    print(f"[gate9b] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        await d.user_sessions.insert_many([dict(s) for s in SESSIONS])
        await d.users.insert_many([dict(u) for u in USERS])
        await d.team_members.insert_many([dict(t) for t in TEAM])
        await d.companies.insert_many([dict(c) for c in COMPANIES])
        for coll, rows in BUSINESS.items():
            await d[coll].insert_many([dict(r) for r in rows])
        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate9b_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate9b_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate9b] servers did not start"); return 2
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        await d.command({"profile": 2})
        h_start = (await d.command("dbHash", collections=TRACKED))["collections"]

        passed = failed = 0
        rows, py_writes, node_changes, charset_only, body500 = [], [], [], [], []
        auth_pairs = 0
        for desc, target, hdr in CASES:
            n_py0 = await d["system.profile"].count_documents({"appName": PY_APP})
            h0 = (await d.command("dbHash", collections=TRACKED + ["user_sessions"]))["collections"]
            rp = raw(PY_PORT, "GET", target, hdr)
            # Quiesce: Python's rolling-refresh write can land after the response bytes;
            # wait until its profiler count is stable so it is never attributed to Node.
            last, stable = -1, 0
            while stable < 4:
                await asyncio.sleep(0.08)
                cur = await d["system.profile"].count_documents({"appName": PY_APP})
                stable = stable + 1 if cur == last else 0
                last = cur
            py_ops = await d["system.profile"].find({"appName": PY_APP}).skip(n_py0).to_list(None)
            h_mid = (await d.command("dbHash", collections=TRACKED + ["user_sessions"]))["collections"]
            pch = [k for k in TRACKED + ["user_sessions"] if h0.get(k) != h_mid.get(k)]
            if pch:
                py_writes.append((desc, pch))
            n_nd0 = await d["system.profile"].count_documents({"appName": NODE_APP})
            rn = raw(NODE_PORT, "GET", target, hdr)
            await asyncio.sleep(0.08)
            nd_ops = await d["system.profile"].find({"appName": NODE_APP}).skip(n_nd0).to_list(None)
            h1 = (await d.command("dbHash", collections=TRACKED + ["user_sessions"]))["collections"]
            nch = [k for k in TRACKED + ["user_sessions"] if h_mid.get(k) != h1.get(k)]
            if nch:
                node_changes.append((desc, nch))
            sp, sn = auth_seq(py_ops), auth_seq(nd_ops)
            # Python re-dispatches on 500 (framework, Gate 8a) → its auth sequence may be doubled.
            seq_ok = sp == sn or (rp[0] == 500 and sp == sn * 2)
            auth_pairs += len(sn)
            status_ok = rp[0] == rn[0]
            if rp[0] == 500:
                body_ok = status_ok  # 500 body format = framework (Gate 9d); status must match
                if rp[2] != rn[2]:
                    body500.append(desc)
            else:
                body_ok = status_ok and rp[2] == rn[2]
            ct_p = (rp[1].get("content-type") or "").replace("; charset=utf-8", "")
            ct_n = (rn[1].get("content-type") or "").replace("; charset=utf-8", "")
            if rp[0] != 500 and rp[1].get("content-type") != rn[1].get("content-type") and ct_p == ct_n:
                charset_only.append(desc)
            ct_ok = rp[0] == 500 or ct_p == ct_n
            ok = body_ok and ct_ok and seq_ok and not nch
            passed += ok; failed += (not ok)
            rows.append((ok, desc, rp, rn, sp, sn))

        py_prof = await d["system.profile"].find({"appName": PY_APP}).to_list(None)
        late = [p for p in py_prof if p.get("op") in ("update", "insert")]
        print(f"[gate9b] python profiler writes total={len(late)} "
              f"colls={sorted({(p.get('ns') or '.').split('.', 1)[1] for p in late})}")
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        h_end = (await d.command("dbHash", collections=TRACKED))["collections"]

        print("\n" + "=" * 100 + "\nPHASE 4 · GATE 9b · LOGIN IDENTITY PARITY (production-shaped sessions)\n" + "=" * 100)
        for ok, desc, rp, rn, sp, sn in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {desc:52} py={rp[0]} node={rn[0]} {rp[2][:70]!r}")
            if not ok:
                print(f"        node body: {rn[2][:160]!r}\n        auth py={sp}\n        auth nd={sn}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} writes={len(node_writes)} "
              f"collections={node_colls} node-attributed changes={node_changes or 'none'}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in APP_COLLS)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged (companies excluded: Python repair): {APP_COLLS}")
        print(f"  auth read commands compared per request: {auth_pairs}")
        print(f"  python-side writes (rolling refresh / company repair — Python-only): {len(py_writes)} requests; "
              f"{sorted({c for _, cs in py_writes for c in cs})}")
        print(f"  KNOWN framework (Gate 9d, not hiding status/body): charset-only content-type diffs={len(charset_only)}; "
              f"500 body-format diffs={len(body500)}")
        print("-" * 100 + f"\n  cases: {len(rows) + 2}   passed: {passed}   failed: {failed}\n" + "=" * 100)
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate9b] dropped {DB}; leftover gate9b DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate9b_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
